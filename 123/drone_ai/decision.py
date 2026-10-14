# -*- coding: utf-8 -*-
"""
decision.py — 模式选择器（保护无人机 vs 完成任务）
=================================================
两个运行模式：
  PROTECT  保护无人机：保机为先
  MISSION  完成任务  ：任务为先

判定流程：
  1) 根据当前命中异常 + 风险档，算 P(保机) / T(任务) 双值
  2) P >= 0.75 或 tier=L3 -> PROTECT ; P < 0.35 且 tier=L0/L1 -> MISSION
     tier=L2/L3 且 0.55<=P<0.75 -> RTB ; 否则 CRUISE
  3) 查策略库（Decision_Matrix_Calibrated.xlsx 校准版）出动作 + 执行目标

P/T 来源：
  - 优先读 analyzer/output/Decision_Matrix_Calibrated.xlsx（数据校准值）
  - 若文件不存在，用 weight_base 理论先验兜底（不再手写常数）

修正（对应 weight_theory.md §5）：
  - 消除 _FALLBACK_PT 写死常数：兜底 P/T 由 weight_base.compute_P 计算
  - 消除 "P-T>0.15" 硬阈值：tier/模式由理论 P 决定（compute_Tier/recommend_mode）
  - 消除 _SEV 写死：severity 从 weight_base.SEV_BY_TYPE 读取
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_MATRIX_XLSX = os.path.join(
    os.path.join(HERE, "analyzer", "output", "Decision_Matrix_Calibrated.xlsx"))

# 尝试导入 weight_base（理论先验源）；不可用时用内置最小兜底表
try:
    import sys
    _analyzer_dir = os.path.join(HERE, "analyzer")
    if _analyzer_dir not in sys.path:
        sys.path.insert(0, _analyzer_dir)
    from weight_base import (
        compute_P as _w_compute_P,
        SEV_BY_TYPE as _SEV_BY_TYPE,
        INTERNAL_TYPES as _INTERNAL_TYPES,
        compute_Tier as _w_compute_Tier,
        recommend_mode as _w_recommend_mode,
    )
    _HAS_WEIGHT_BASE = True
    _WB_IMPORT_ERR = None
except ImportError as e:
    _HAS_WEIGHT_BASE = False
    _WB_IMPORT_ERR = str(e)
    print("[decision] WARNING: weight_base 不可用，用内置兜底表: %s" % _WB_IMPORT_ERR, file=sys.stderr)
    # 兜底最小先验表（与 weight_base.PRIOR_P 的 FMECA 映射一致）
    _FALLBACK_P_PRIOR = {
        "motor_failure": 0.90, "flight_ctrl": 0.90, "battery_issue": 0.70,
        "prop_break": 0.65, "esc_fault": 0.60, "signal_loss": 0.80,
        "gps_drift": 0.50, "gimbal_fault": 0.30, "payload_fault": 0.25,
        "wind_gust": 0.45, "rain": 0.40, "dust_fog": 0.35,
        "cold_hot": 0.35, "bird": 0.30, "lightning": 0.95,
        "obstacle": 0.40, "unknown": 0.50,
    }
    _SEV_BY_TYPE = {
        "lightning": 10, "motor_failure": 9, "flight_ctrl": 9,
        "battery_issue": 8, "esc_fault": 7, "gps_drift": 6,
        "wind_gust": 5, "rain": 5, "obstacle": 5,
        "cold_hot": 4, "dust_fog": 4, "gimbal_fault": 4,
        "bird": 3, "payload_fault": 3, "unknown": 3,
        "signal_loss": 8, "prop_break": 8,
    }
    _INTERNAL_TYPES = frozenset(_FALLBACK_P_PRIOR.keys())

    def _w_compute_P(anom, crash=0, success=0, **kw):
        """纯先验（neff=0）：P = 0.80*P_prior + 0.05*0.5 + 0.15*0
        crash/success 保持与 weight_base.compute_P 签名一致（机载无历史数据传 0）。"""
        p = _FALLBACK_P_PRIOR.get(anom, 0.50)
        P = 0.80 * p + 0.05 * 0.5 + 0.15 * 0.0
        P = max(0.05, min(0.95, P))
        return {"P": round(P, 3), "T": round(1.0 - P, 3), "P_prior": p}

    def _w_compute_Tier(P):
        return "L0" if P < 0.35 else "L1" if P < 0.55 else "L2" if P < 0.75 else "L3"

    def _w_recommend_mode(P, tier):
        if P >= 0.75 or tier == "L3":
            return "PROTECT"
        elif P < 0.35 and tier in ("L0", "L1"):
            return "MISSION"
        elif tier in ("L2", "L3") and 0.55 <= P < 0.75:
            return "RTB"
        else:
            return "CRUISE"


def _load_matrix():
    """从校准版 Decision_Matrix_Calibrated.xlsx 读 P/T + 模式 + 动作。"""
    data = {}
    if not os.path.exists(_MATRIX_XLSX):
        import warnings
        warnings.warn(f"[decision] {_MATRIX_XLSX} not found, P/T matrix empty, using defaults")
        return data
    try:
        from openpyxl import load_workbook
        ws = load_workbook(_MATRIX_XLSX).active
        hdr = [c.value for c in ws[1]]
        idx = {n: i for i, n in enumerate(hdr)}
        # 校准版的列名 accident_type -> 映射到 anomaly 名
        # 注意：crash_general 是矩阵中的真实行名（"炸/坠"宽命中类，降权后 P=0.40），
        # 不得映射成 unknown，否则该类型读不到校准值（P1-3 修复）。
        name_map = {
            "motor_fault": "motor_failure", "battery": "battery_issue",
            "gimbal": "gimbal_fault", "gps": "gps_drift", "wind": "wind_gust",
            "cold": "cold_hot", "prop_break": "prop_break",
        }
        for r in ws.iter_rows(min_row=2, values_only=True):
            t = r[idx["accident_type"]]
            if not t:
                continue
            anon = name_map.get(t, t)
            data[anon] = {
                "P": float(r[idx["P"]] or 0),
                "T": float(r[idx["T"]] or 0),
                "mode": r[idx["recommended_mode"]] or "CRUISE",
                "action": r[idx["action"]],
                "target": r[idx["execution_target"]],
            }
    except Exception as e:
        import warnings
        if isinstance(e, ModuleNotFoundError):
            warnings.warn(f"[decision] openpyxl not installed, cannot load {_MATRIX_XLSX}; "
                          f"P/T matrix empty, using defaults")
        else:
            warnings.warn(f"[decision] failed to load {_MATRIX_XLSX}: {e}; "
                          f"P/T matrix empty, using defaults")
    # 覆盖率日志：17 类中实际加载多少，避免同类静默失配（P1-3）
    _KNOWN_TYPES = frozenset({
        "motor_failure", "flight_ctrl", "battery_issue", "prop_break", "esc_fault",
        "gimbal_fault", "payload_fault", "signal_loss", "gps_drift", "wind_gust",
        "rain", "dust_fog", "cold_hot", "bird", "obstacle", "lightning",
        "crash_general", "unknown",
    })
    covered = _KNOWN_TYPES & set(data.keys())
    print(f"[decision] matrix loaded: {len(covered)}/{len(_KNOWN_TYPES)} types "
          f"(calibrated {len(data)} rows)")
    return data


class ModeSelector:
    def __init__(self):
        self._matrix = _load_matrix()

    def pt_for(self, anomaly):
        """返回 (P, T, source, w_prior, w_data, neff)。
        source ∈ {matrix, theory, fallback}
        w_prior/w_data/neff 来自校准基础（先验兑底时 w_data=0, neff=0）"""
        if anomaly in self._matrix:
            m = self._matrix[anomaly]
            return m["P"], m["T"], "matrix", m.get("w_prior"), m.get("w_data"), m.get("neff", 0)
        # 理论先验（weight_base 或内置兑底）
        # weight_base.compute_P 需要 (an_type, crash, success)；
        # 机载运行时无历史 crash/success 数据，传 0 退化为纯先验 P_prior。
        r = _w_compute_P(anomaly, 0, 0)
        return r["P"], r["T"], ("theory" if _HAS_WEIGHT_BASE else "fallback"), 0.80, 0.0, 0

    def pick_mode(self, anomaly):
        """根据校准 P 决定 PROTECT / MISSION / RTB / CRUISE。
        自身事件（SELF_ABORT_TYPES）直接判 FORCE_LAND（就近迫降+终止任务），
        不再按 P/T 算常规模式——内部故障必须终止。"""
        if is_self_fault(anomaly):
            return "FORCE_LAND"
        P, _T, _src, _wp, _wd, _neff = self.pt_for(anomaly)
        tier = _w_compute_Tier(P)
        # 校准版矩阵自带 mode 时优先采用
        if anomaly in self._matrix:
            return self._matrix[anomaly]["mode"]
        return _w_recommend_mode(P, tier)

    def action_for(self, anomaly, mode):
        """查策略库出动作 + 执行目标。致命类强制 FlightController。
        FORCE_LAND 模式（自身事件）统一动作='立即就近迫降并终止任务'。
        矩阵命中时致命类 target 也过安全覆盖（P1-4：消除脆弱耦合）。"""
        if mode == "FORCE_LAND" or is_self_fault(anomaly):
            return "立即就近迫降并终止任务", "FlightController"
        if anomaly in self._matrix:
            m = self._matrix[anomaly]
            # 致命类（电机/桨/飞控/电调/雷击）target 恒为 FlightController，
            # 即使矩阵里写了别的 target 也要覆盖（P1-4 修复）
            target = "FlightController" if anomaly in _FATAL_TARGET_TYPES else m["target"]
            return m["action"], target
        # 兜底
        # 兑底（与 17 类 anomaly 词表对齐）
        fatal = anomaly in _FATAL_TARGET_TYPES
        _BUILTIN = {
            "motor_failure": ("切换冗余电机/极速软降", "FlightController"),
            "prop_break":    ("极速降油门软着陆", "FlightController"),
            "flight_ctrl":   ("硬件备份接管/迫降", "FlightController"),
            "lightning":     ("立即接地断电", "FlightController"),
            "esc_fault":     ("限油门就近降落", "FlightController"),
            "battery_issue": ("关载荷+计算续航→返航或就近降", "Shadow_AI"),
            "signal_loss":   ("执行预设Failsafe返航/悬停", "FlightController"),
            "gps_drift":     ("切视觉/IMU导航, 限时悬停", "Shadow_AI"),
            "rain":          ("避雨点悬停 或 直接返航", "Shadow_AI"),
            "wind_gust":     ("降高度/顺风提速穿过", "Shadow_AI"),
            "obstacle":      ("动态避障绕飞/急停", "Shadow_AI"),
            "dust_fog":      ("降高度增视距/取消任务", "Shadow_AI"),
            "cold_hot":      ("缩短任务/提前返航", "Shadow_AI"),
            "bird":          ("加速穿过鸟群/避让", "Shadow_AI"),
            "payload_fault": ("停任务动作/评估载荷", "Shadow_AI"),
            "crash_general": ("保守悬停待命, 请求接管", "Shadow_AI"),
        }
        action, target = _BUILTIN.get(anomaly, ("保守悬停待命", "Shadow_AI"))
        if fatal:
            target = "FlightController"
        return action, target

# -*- coding: utf-8 -*-
# 兼容别名：ai_main.py 旧代码引用 decision._SEV / _INTERNAL / tier_of
_SEV = _SEV_BY_TYPE
_INTERNAL = _INTERNAL_TYPES


def tier_of(L):
    """兼容接口：旧代码传 L 数值(0-10)。新代码用 _w_compute_Tier(P)。"""
    if L <= 2.5:
        return "L0"
    elif L <= 5.0:
        return "L1"
    elif L <= 7.5:
        return "L2"
    else:
        return "L3"


# ============ 机载决策增强：多异常叠加 + RTB 白名单 ============

def worst_anomaly(hits, sev_map):
    """多异常命中时按 severity 降序取最严重的一条。
    hits: 列表 [ (anomaly, ...), ...] — 第一位必须是 anomaly 名。"""
    if not hits:
        return None
    return sorted(hits, key=lambda h: -sev_map.get(h[0], 0))[0][0]


def combined_mode(anomalies, pt_map):
    """多异常叠加决策：取 P 最高的异常定模式（保机取严）。
    自身事件优先级最高：命中任一 SELF_ABORT_TYPES -> 直接 FORCE_LAND
    （立即就近迫降+终止任务），不再走常规 P/T 模式。
    pt_map: {anomaly: (P, T, source, w_prior, w_data, neff)} 或 {anomaly: (P, T, source)}"""
    # 自身事件一票否决：只要命中任一内部故障就终止
    for a in anomalies:
        if is_self_fault(a):
            return "FORCE_LAND"
    best = None
    for a in anomalies:
        v = pt_map[a]
        P = v[0]
        w_data = v[4] if len(v) > 4 else None
        if w_data is not None and w_data < 0.30 and P > 0.55:
            shrink = (0.30 - w_data) * 0.5
            P = P - shrink
        if best is None or P > best[0]:
            best = (P, a)
    if best is None:
        return "CRUISE"
    P, a = best
    tier = _w_compute_Tier(P)
    return _w_recommend_mode(P, tier)


# RTB 真实指令白名单（这些异常走 _apply_rtb 的水平速度向量 + 下降率）
# P0-3 修复：校准矩阵把 rain / wind_gust / signal_loss / gps_drift 判为 RTB，
# 补入白名单使"是否返航"与矩阵口径一致（此前 rain 只爬升不返航、wind_gust 全零）。
# P1-5：motor_failure / prop_break 从 SELF_ABORT_TYPES 移出，但仍是致命类，
# 走 RTB 返航（飞控在途中硬保），不是零指令。补入白名单。
RTB_TYPES = frozenset({
    "battery_issue", "flight_ctrl",
    "esc_fault", "gimbal_fault", "payload_fault",
    "lightning", "rain", "wind_gust",
    "motor_failure", "prop_break",   # P1-5：飞控硬保接管，AI 走 RTB 不抢控制权
    "signal_loss", "gps_drift",      # P1-5 failsafe 类型：超时后 RTB
})

# ============ 链路/导航失效 failsafe（P1-5：独立于 P/T 竞争）============
# 通信/导航失效属"外部失效"，不参与 P/T 竞争：命中且 mode==CRUISE 时
# 悬停等待链路恢复，超过 FAILSAFE_HOVER_MAX_S 仍未恢复则转 RTB 返航。
FAILSAFE_HOVER_TYPES = frozenset({"signal_loss", "gps_drift"})
# 悬停等待上限（秒），同源 thresholds.FAILSAFE_LAND_TIMEOUT_S
FAILSAFE_HOVER_MAX_S = 30.0

# ============ 自身事件 -> 立即就近迫降 + 终止任务（2026-10-13 新增）============
# 无人机内部机体/动力/飞控/电池/电调/桨/云台/载荷故障：命中任一即
#  不走返航 home、不做任务巡航，直接就近迫降并终止任务。
# 自身事件（SELF_ABORT_TYPES）：命中即就近迫降 + 终止任务，不再走常规 P/T 模式。
# 约束：SELF_ABORT_TYPES ⊂ RTB_TYPES（任何"立即迫降"成员必须同时是返航成员）。
# P0-4 修复：battery_issue 移出（低电可返航，走 _apply_rtb enroute_home，电量到线才 force_land）。
# P1-5 修复：motor_failure / prop_break 同时移出——动力/控制丧失时飞控层有独立
#   硬保机制接管（飞控自保护），AI 层强降反而可能与飞控抢控制权；这两类
#   改走 RTB 返航，让飞控在返航途中硬保。若飞控方确认 AI 层需直接终止，
#   再移回本集合（见任务单 §P1-5 备注）。
SELF_ABORT_TYPES = frozenset({
    "flight_ctrl", "esc_fault",
    # "battery_issue" 已移出（P0-4）：低电走 _apply_rtb 的 enroute_home
    # "motor_failure" 已移出（P1-5）：飞控硬保接管，AI 走 RTB 不抢控制权
    # "prop_break" 已移出（P1-5）：同上
    "gimbal_fault", "payload_fault",
})

# 致命异常（执行目标必须为 FlightController，硬约束）：电机/桨/飞控/电调/雷击。
# 即使策略矩阵里写了别的 target，这些类型命中矩阵时也要覆盖为 FlightController
# （P1-4：消除"致命类目标恒为 FlightController 只在兑底分支成立"的脆弱耦合）。
_FATAL_TARGET_TYPES = frozenset({
    "motor_failure", "prop_break", "flight_ctrl", "esc_fault", "lightning",
})


def is_self_fault(anomaly):
    """判断该异常是否属于'无人机自身事件'（内部故障，须立即迫降终止任务）。
    P1-5：外部失效类（signal_loss / gps_drift）绝不属于自身事件，
    即使误入 SELF_ABORT_TYPES 也要在此否决（双保险）。"""
    if anomaly in FAILSAFE_HOVER_TYPES:
        return False   # 外部失效，不走 FORCE_LAND
    return anomaly in SELF_ABORT_TYPES


def should_rtb(anomaly, mode):
    """判断该异常是否应走 RTB 指令（真实水平速度向量 + 下降）。
    单一真值来源：是否返航只看 RTB_TYPES 白名单（与安全语义对齐，P0-3 修复）。

    - 自身事件（SELF_ABORT_TYPES，已不含 battery_issue）改走 FORCE_LAND
      就近迫降终止，不走 RTB 返航 home。
    - 链路/导航失效（signal_loss / gps_drift，P1-5 failsafe）：
      mode==CRUISE 时悬停等待链路恢复（由 ai_main 的 failsafe 分支处理，
      返回 False 不走 RTB）；超过 FAILSAFE_HOVER_MAX_S 后 mode 转 RTB，此处返回 True。
    """
    if anomaly in SELF_ABORT_TYPES:
        return False   # 自身故障不返航 home，就近迫降终止
    if anomaly not in RTB_TYPES:
        return False
    # 链路/导航失效在 CRUISE 模式不返航，只悬停等待（P1-5 failsafe）
    if mode == "CRUISE" and anomaly in FAILSAFE_HOVER_TYPES:
        return False
    # PROTECT / RTB / MISSION / FORCE_LAND 等其余模式：RTB_TYPES 成员都返航
    return True


def is_failsafe_hover(anomaly, mode):
    """P1-5：链路/导航失效且当前为 CRUISE -> 应悬停等待（不返航、不巡航）。
    命中则 ai_main 走 failsafe=hover_wait 分支；超时后转 RTB。"""
    return anomaly in FAILSAFE_HOVER_TYPES and mode == "CRUISE"
