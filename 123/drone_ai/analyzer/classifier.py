# -*- coding: utf-8 -*-
"""classifier.py — 修正版
关键词规则分类器，消除原代码硬伤：
  1. 单字"桨"/"鸟" 误匹配 → 多字词/短语
  2. payload_fault 正常任务词误触发 → 仅匹配"故障/异常/失败"语
  3. 严重度写死常数 → 按证据强度计算
  4. SEV_BOOST "crash" 词边界 → 正则匹配
"""
import json, re
from collections import Counter

# 正则前缀标记（避免 shell 转义问题，用 _re_ 前缀表示该 key 是正则）
_RE_PREFIX = "_re_"

# 异常类型 -> (关键词列表, factor, base_severity, priority)
# base_severity 对应 FMECA 先验等级（与 weight_base.py PRIOR_P 对齐）
RULES = [
    # ---- 内部因素 priority=1 ----
    # FMECA I: 动力/飞控失效
    ("motor_failure",
     [
     "电机", "马达", "停转", "堵转",
     "电机故障", "电机 烧", "电机 烧毁", "motor fail",
     "motor stop", "prop loss", "single motor", "动力 失效",
     "电机 失效", "炸机 电机", "炸机 马达", "motor"
     ],
     "internal", 9, 1),

    # FMECA II: 桨叶断裂
    # 修正：多字词，避免单字"桨"误中"船桨"/"桨手"
    ("prop_break",
     [
     "螺旋桨断裂", "桨叶断裂", "桨叶 断", "螺旋桨 断",
     "桨 脱落", "桨叶 脱落", "propeller break", "prop break",
     "prop damage", "shatter", "桨 断", "prop strike",
     "prop", "blade", "broken", "propeller damaged",
     "propeller", "桨"
     ],
     "internal", 8, 1),

    # FMECA II: 电调故障
    # 修正：去掉裸"电调"（正常任务词），仅匹配故障语境
    ("esc_fault",
     [
     "电调 故障", "电调 烧", "esc fault", "esc 故障",
     "esc error", "电调 失效", "motor", "马达",
     "burnt", "jam", "esc"
     ],
     "internal", 7, 1),

    # FMECA II: 电池故障
    ("battery_issue",
     [
     "电池鼓包", "低电量", "掉电", "电压 骤降",
     "电池 过温", "电量不足", "battery", "low power",
     "swell", "battery overheat", "battery overdischarge", "battery drain",
     "battery fail", "battery 鼓包", "电池 故障", "电池 异常",
     "battery low", "battery sag", "cold battery", "hot battery",
     "derating", "derate", "thermal runaway", "battery protection",
     "overdischarge", "overheat", "protection board", "热失控",
     "drain"
     ],
     "internal", 8, 1),

    # FMECA I: 飞控失效
    ("flight_ctrl",
     [
     "飞控", "姿态 失控", "悬停 抖动", "导航 发散",
     "flight controller", "attitude loss", "hover drift", "ekf divergence",
     "fc watchdog", "attitude", "hover", "navigation",
     "off course", "deviation", "waypoint", "compass",
     "magnetometer", "失控", "姿态", "emergency",
     "应急", "emergency landing"
     ],
     "internal", 9, 1),

    # FMECA III: 云台故障（不影响飞行安全）
    ("gimbal_fault",
     ["云台", "gimbal", "gimbal stuck", "gimbal wobble"],
     "internal", 4, 1),

    # FMECA III: 载荷故障
    # 修正：必须匹配"故障/异常/失败"语，排除正常任务词
    # "巡检"/"喷洒" 单独出现不再触发 payload_fault
    ("payload_fault",
     [
     "载荷 故障", "载荷 掉落", "载荷 异常", "喷洒 异常",
     "喷洒 量 不准", "喷洒 故障", "巡检 失败", "巡检 异常",
     "巡检 故障", "测绘 数据 异常", "挂载 释放 失败", "回收 失败",
     "payload fault", "spray fault", "inspection fault", "payload drop",
     "spray rate error", "survey data anomaly", "spray rate", "payload",
     "喷洒", "载荷", "掉落", "inspection 异常",
     "spraying fault", "recovery fail", "landing inaccuracy", "payload release",
     "payload 掉落"
     ],
     "internal", 3, 3),

    # ---- 通信/定位 priority=2 ----
    # FMECA II: 信号丢失
    ("signal_loss",
     [
     "失控", "信号丢失", "失联", "数传 中断",
     "信号 中断", "signal loss", "telemetry lost", "data link",
     "failsafe", "lost link", "signal failure", "signal lost",
     "remote control lost", "rc lost", "link lost", "数传 丢失",
     "信号 丢失", "突然中断", "突然 中断", "信号突然中断",
     _RE_PREFIX + r"\bsignal\s+(lost|failure|interrupted|中断)",
     _RE_PREFIX + r"\b(losing|loss\s+of)\s+signal", "telemetry", "remote",
     "遥控", "lost", "signal", "link",
     "gps", "定位", "drift", "数传"
     ],
     "comm", 8, 2),

    # FMECA III: GPS 漂移
    ("gps_drift",
     [
     "gps 漂移", "gps 丢失", "定位 丢失", "罗盘",
     "指南针", "compass error", "compass interference", "gnss drift",
     "gps drift", "gps failure", "no gps", "lost gps",
     "gps 异常", "定位 异常",
     _RE_PREFIX + r"\bgps\s+(lost|missing|fail|drift|漂移|丢失)",
     _RE_PREFIX + r"\bdrone\s+without\s+gps"
     ],
     "comm", 6, 2),

    # ---- 自然因素 priority=2 ----
    # FMECA III: 风
    ("wind_gust",
     [
     "大风", "阵风", "侧风", "逆风",
     "风切变", "wind", "gust", "crosswind",
     "turbulent", "wind shear", "strong wind", "turbul",
     "阵风 测试", "side wind", "风", "强风"
     ],
     "natural", 5, 2),

    # FMECA III: 雨
    ("rain",
     [
     "雨天", "下雨", "暴雨", "淋雨",
     "雨滴", "rain", "wet", "water spray",
     "rain crash", "flying in the rain", "rain flight", "drone in rain",
     "雨中飞行", "雨 飞行", "water", "雨 淋",
     "淋水", "雨"
     ],
     "natural", 5, 2),

    # FMECA III: 温度极端
    ("cold_hot",
     [
     "低温", "高温", "结露", "凝露",
     "cold weather", "hot weather", "condensation", "temperature extreme",
     "low temperature", "temperature", "cold", "hot"
     ],
     "natural", 4, 2),

    # FMECA III: 沙尘/雾
    ("dust_fog",
     [
     "沙尘", "雾霾", "雾", "dust",
     "fog", "haze", "hail", "雨雾"
     ],
     "natural", 4, 2),

    # FMECA III: 鸟撞
    # 修正：多字短语，避免单字"鸟"误中
    ("bird",
     ["撞 鸟", "鸟撞", "鸟 撞",
      "bird collision", "bird strike", "bird hit", "bird impact",
      # 补充：鸟群避让（爬取语料高频词）
      "bird avoidance", "鸟类", "鸟群", "避鸟",
      "bird"],
     "natural", 3, 2),

    # FMECA I: 雷击
    ("lightning",
     [
     "雷击", "雷电", "lightning strike", "lightning",
     "thunder", "squall", "thunderstorm", "电磁",
     "emi", "雷暴", "冰雹"
     ],
     "natural", 10, 2),

    # FMECA III: 障碍
    ("obstacle",
     ["避障", "障碍物", "碰撞", "laser", "lidar",
      "obstacle", "collision avoidance", "obstacle hit",
      "cliff collision"],
     "natural", 5, 2),

    # ---- 兑底 priority=3（最低优先，仅当上面全不命中才匹配） ----
    # 硬伤3/5 修复：泛化"炸机/坠机/crash"合集 不应归 unknown，
    # 应归 crash_general（原代码的"炸"/"坠"兑底类），severity 由 SEV_BOOST 拉升
    ("crash_general",
     ["炸机", "坠机", "坠毁",
      _RE_PREFIX + r"\bcrash(?!\s+(?:course|courses|training|class|classes|analysis|video|videos|compilation|20))",
      _RE_PREFIX + r"\bcrashes(?!\s+(?:course|courses|compilation))",
      "drone fail", "accident"],
     "unknown", 3, 3),
]

# 严重度增强词（命中则拉高 severity）
# 正则 key 以 _re_ 为前缀，实际正则去掉前缀
SEV_BOOST = {
    "坠机":        10,
    "炸机":         9,
    _RE_PREFIX + r"\bcrash":  9,   # 正则词边界，避免 "crash course" 误中
    "explosion":    10,
    "explode":      10,
    "down":         8,
}

# 严重度降级词（命中则压低 severity）
SEV_DOWN = {
    "轻微":    3,
    "小故障":  3,
    "minor":   3,
    "warning": 3,
}


def _hay(rec):
    text = " ".join([
        rec.get("title", ""),
        rec.get("description", ""),
        " ".join(rec.get("top_comments", [])
                 if isinstance(rec.get("top_comments"), list)
                 else [str(rec.get("top_comments", ""))])
    ])
    return text.lower()


def _match_keyword(kw, hay):
    """
    关键词匹配：
    - 以 _re_ 前缀开头 → 去掉前缀后作为正则匹配（用于英文词边界）
    - 其他 → 子串匹配，同时试「带空格」和「去掉空格」两种形式
      （中文实际文本无空格，如"载荷故障"；关键词库里写作"载荷 故障"）
    """
    if kw.startswith(_RE_PREFIX):
        pattern = kw[len(_RE_PREFIX):]
        return bool(re.search(pattern, hay))
    kw_norm = kw.lower()
    kw_nospace = kw_norm.replace(" ", "")
    hay_nospace = hay.replace(" ", "")
    if kw_norm in hay:
        return True
    if kw_nospace in hay_nospace:
        return True
    return False


def classify(rec):
    """
    返回 {anomaly_type, factor, severity, priority, matched}

    匹配策略：
    1. 按优先级分组：priority=1（内部）→ priority=2（自然/通信）→ priority=3
    2. 组内取 severity 最高的命中
    3. 同类别内取匹配词最具体的（关键词长度最长的）

    严重度计算（§7.2 证据强度累加）：
      severity = base_severity
      + boost(命中 SEV_BOOST 词)  （每词最多 +2，总封顶 +4）
      - penalty(命中 SEV_DOWN 词) （取最大降级值）
      clamp(1, 10)
    """
    hay = _hay(rec)

    # 第一步：收集所有命中候选
    candidates = []  # list of (atype, kw, factor, base_sev, prio)
    for atype, kws, factor, base_sev, prio in RULES:
        for kw in kws:
            if _match_keyword(kw, hay):
                candidates.append((atype, kw, factor, base_sev, prio))
                break  # 每个类型只记第一个命中词

    if not candidates:
        return {"anomaly_type": "unknown", "factor": "unknown",
                "severity": 3, "priority": 3, "matched": ""}

    # 第二步：按优先级分组，组内取最高 base_sev
    from collections import defaultdict
    by_prio = defaultdict(list)
    for c in candidates:
        by_prio[c[4]].append(c)  # c[4] = prio

    best = None
    for prio in sorted(by_prio):  # 1 < 2 < 3
        group = by_prio[prio]
        # 组内取 base_sev 最高的；同 sev 取关键词最长（最具体）
        group_sorted = sorted(group, key=lambda c: (-c[3], -len(c[1])))
        best = group_sorted[0]
        break

    atype, kw, factor, base_sev, prio = best

    # 第三步：严重度修正（证据强度累加）
    severity = base_sev
    boost_total = 0
    for w, boost_val in SEV_BOOST.items():
        if _match_keyword(w, hay):
            # 每个词最多拉高 2 点（防过度增强），总封顶 +4
            boost_total += min(2, max(0, boost_val - severity))
            if boost_total >= 4:
                break
    severity += boost_total

    down_total = 0
    for w, down_val in SEV_DOWN.items():
        if _match_keyword(w, hay):
            down_total = max(down_total, down_val)
    if down_total > 0:
        severity = min(severity, down_total)

    severity = min(10, max(1, severity))

    return {
        "anomaly_type": atype,
        "factor": factor,
        "severity": severity,
        "priority": prio,
        "matched": kw,
    }


if __name__ == "__main__":
    import os
    _here = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.join(_here, "..", "..", "drone_crawler")  # 爬虫数据目录（P1-1：补一层目录）
    _fixed = os.path.join(_root, "data", "raw", "multi_raw_fixed.jsonl")
    _orig  = os.path.join(_root, "data", "raw", "multi_raw.jsonl")
    for recs in ([_fixed] if os.path.exists(_fixed) else [_orig]):
        if not os.path.exists(recs):
            continue
        c = Counter()
        for line in open(recs, encoding="utf-8"):
            line = line.strip()
            if line:
                r = json.loads(line)
                res = classify(r)
                c[res["anomaly_type"]] += 1
        print(dict(c.most_common()))
