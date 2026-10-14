# -*- coding: utf-8 -*-
"""
C. 事件 × 动作 推荐矩阵
========================
基于 Anomaly_Events.xlsx 中 16 类 anomaly_type，为 4 种操作模式
生成"事件 → 推荐动作 + P(保机) / T(完成任务) 双值评分"矩阵，
输出 Decision_Matrix_Static.xlsx（静态矩阵，无样本数据）。

修正（对应 weight_theory.md §5）：
  - 不再写死 RISK_L / severity 常数，全部从 Anomaly_Events.xlsx 读取
  - P/T 由 weight_base.compute_P 计算（先验 + Laplace 数据 + 动作偏置 + 残差）
  - tier / 推荐模式 由理论 P 决定（compute_Tier / recommend_mode），
    取代原 P-T>0.15 硬阈值，消除自相矛盾

注意：输出文件名为 Decision_Matrix_Static.xlsx，
与 calibrate_pt.py 生成的 Decision_Matrix.xlsx（含数据校准）区分。
"""
import os
from openpyxl import Workbook, load_workbook

from weight_base import (
    PRIOR_P, SEV_BY_TYPE, INTERNAL_TYPES,
    compute_P, compute_Tier, recommend_mode,
)

HERE = os.path.dirname(os.path.abspath(__file__))

# 每种 anomaly_type 的推荐动作（来自 Decision_Strategies.xlsx 既有策略 + 补充）
# 键: anomaly_type -> (action_text, execution_target)
ACTIONS = {
    "motor_failure":  ("切换三轴冗余 / 极速软降 / 手动接管", "FlightController"),
    "flight_ctrl":    ("硬件备份接管 / 迫降",                "FlightController"),
    "battery_issue":  ("关载荷 + 计算续航 → 返航或就近降",     "Shadow_AI"),
    "prop_break":     ("极速降油门软着陆",                   "FlightController"),
    "esc_fault":      ("限油门 / 就近降落",                  "Shadow_AI"),
    "gimbal_fault":   ("保持机身水平禁机动",                 "Shadow_AI"),
    "payload_fault":  ("停任务动作 / 评估载荷",               "Shadow_AI"),
    "signal_loss":    ("执行预设 Failsafe 返航 / 悬停",       "FlightController"),
    "gps_drift":      ("切视觉/IMU 导航, 限时悬停",           "Shadow_AI"),
    "wind_gust":      ("降高度 / 顺风提速穿过",              "Shadow_AI"),
    "rain":           ("避雨点悬停 或 直接返航",              "Shadow_AI"),
    "dust_fog":       ("降高度增视距 / 取消任务",             "Shadow_AI"),
    "cold_hot":       ("缩短任务 / 提前返航",                 "Shadow_AI"),
    "bird":           ("加速穿越鸟群 / 避让 / 手动接管",       "Shadow_AI"),
    "lightning":      ("立即接地断电",                      "FlightController"),
    "obstacle":       ("动态避障绕飞 / 急停",                "Shadow_AI"),
    "unknown":        ("保守悬停待命, 请求接管",              "Shadow_AI"),
}

# 4 种操作模式 (来自 Decision_Strategies.xlsx)
MODES = ["CRUISE", "PROTECT", "MISSION", "RTB"]
MODE_CN = {"CRUISE": "常规巡航", "PROTECT": "保护无人机", "MISSION": "任务优先", "RTB": "紧急返航"}


def load_sev_and_factor():
    """
    §5 修正：从 Anomaly_Events.xlsx 读取 severity 和 factor，
    取代原写死的 RISK_L 表。若文件缺失则回落到 weight_base.SEV_BY_TYPE。
    返回 {anomaly_type: (severity, factor)}
    """
    ae_path = os.path.join(HERE, "output", "Anomaly_Events.xlsx")
    if not os.path.exists(ae_path):
        return {t: (SEV_BY_TYPE.get(t, 3), "unknown") for t in ACTIONS}
    ae = load_workbook(ae_path).active
    ae_hdr = [c.value for c in ae[1]]
    ae_idx = {n: i for i, n in enumerate(ae_hdr)}
    out = {}
    for row in ae.iter_rows(min_row=2, values_only=True):
        atype = row[ae_idx.get("Anomaly_Type", 0)]
        sev = row[ae_idx.get("Severity", 2)] or SEV_BY_TYPE.get(atype, 3)
        factor = row[ae_idx.get("Factor", 3)] or "unknown"
        if atype:
            out[atype] = (int(sev), factor)
    for t in ACTIONS:
        if t not in out:
            out[t] = (SEV_BY_TYPE.get(t, 3), "unknown")
    return out


def compute_PT_theory(anom, sev):
    """
    §4/§5 理论 P/T：
    无样本数据时 neff=0，P 纯由 FMECA 先验主导（weight_base.compute_P）。
    sev 仅用于展示，不参与 P 计算（消除原"sev 顶 P"自相矛盾）。
    """
    r = compute_P(anom, crash=0, success=0, action_bias=0.0)
    P, T = r["P"], r["T"]
    tier = compute_Tier(P)
    return P, T, tier, r


def build():
    wb = Workbook()
    ws = wb.active
    ws.title = "Decision_Matrix"

    sev_factor = load_sev_and_factor()

    headers = [
        "anomaly_type", "factor", "severity", "P_prior",
        "tier", "action", "execution_target",
        "P", "T", "recommended_mode", "default_action_hint",
    ]
    ws.append(headers)

    rows = []
    for anom in ACTIONS:
        sev, factor = sev_factor.get(anom, (3, "unknown"))
        P, T, tier, r = compute_PT_theory(anom, sev)
        mode = recommend_mode(P, tier)
        action, target = ACTIONS[anom]

        if mode == "PROTECT":
            hint = "立即切换保护模式，执行保机动作"
        elif mode == "MISSION":
            hint = "继续推进任务，保持监控"
        elif mode == "RTB":
            hint = "启动紧急返航流程"
        else:
            hint = "保持常规巡航，持续监测"

        rows.append([
            anom, factor, sev, r["P_prior"],
            tier, action, target,
            P, T, mode, hint,
        ])

    for r in rows:
        ws.append(r)

    for i, w in enumerate([16, 10, 9, 9, 6, 36, 18, 8, 8, 16, 40], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"

    # Sheet 2: 模式对照表
    ws2 = wb.create_sheet("Mode_Reference")
    ws2.append(["mode", "mode_cn", "P_range", "T_range", "trigger_condition"])
    mode_refs = [
        ("CRUISE",  "常规巡航", "0.05-0.35", "0.65-0.95", "P<0.35 且 tier=L0/L1"),
        ("PROTECT", "保护无人机", ">=0.75",    "<=0.25",   "P>=0.75 或 tier=L3"),
        ("MISSION", "任务优先", "<0.35",     ">0.65",     "P<0.35 且 tier=L0/L1"),
        ("RTB",     "紧急返航", "0.55-0.75", "0.25-0.45",  "tier=L2/L3 且 0.55<=P<0.75"),
    ]
    for m in mode_refs:
        ws2.append(list(m))
    for i, w in enumerate([12, 12, 14, 14, 30], 1):
        ws2.column_dimensions[chr(64 + i)].width = w

    out = os.path.join(HERE, "output", "Decision_Matrix_Static.xlsx")
    wb.save(out)
    print(f"[C] 事件×动作矩阵(理论加权,静态) -> {out}  ({len(rows)} 类事件)")
    return out


if __name__ == "__main__":
    build()
