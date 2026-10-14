# -*- coding: utf-8 -*-
"""
视频应对做法提取器（纯整理，不涉及 AI）
=========================================
从一条视频的 标题 + 描述 + 热门评论 文本中，用关键词规则初步提取：
  - accident_type   事故/故障类别（内部 / 自然 / 通信 / 未明）
  - environment     当时环境（雨 / 大风 / 低温 / 沙尘 / 未知）
  - action_taken    视频里提到的应对动作（悬停 / 返航 / 迫降 / 矢量补偿 / 人工接管...）
  - outcome         结果（成功 / 坠毁 / 未知）
目的：把"视频里做了什么"整理成可人工审阅的结构化行。
说明：全部是可解释的关键词匹配，离线可跑，不调用任何模型。
"""
import re

# 事故类别：复用 classifier.classify 的 anomaly 命名（与 P/T 权重体系一致）
# 旧的 ACCIDENT_TYPES 词库已废弃：分类逻辑全部收敛在 classifier.py，
# 本文件只做 outcome / actions / environment 的关键词提取
ANOMALY_NAMES = [
    "motor_failure", "prop_break", "esc_fault", "battery_issue",
    "flight_ctrl", "gimbal_fault", "payload_fault", "signal_loss",
    "gps_drift", "wind_gust", "rain", "cold_hot", "dust_fog",
    "bird", "lightning", "obstacle", "crash_general", "unknown",
]


ACTIONS = {
    "hover_hold":  ["悬停", "原地", "hold", "hover", "保持位置"],
    "rtb":         ["返航", "回家", "rtb", "return", "回场"],
    "force_land":  ["迫降", "软降", "落地", "land", "着陆", "降落"],
    "vector_comp": ["矢量", "补偿", "倾斜", "倾斜补偿", "vector"],
    "manual_take": ["手动", "接管", "人工", "手飞", "manual", "takeover"],
    "slowdown":    ["减速", "降速", "降速", "slow", "减速"],
    "climb_up":    ["上升", "爬升", "climb", "升"],
    "descend":     ["下降", "降低", "descend", "低飞"],
    "abort":       ["中止", "取消任务", "abort", "放弃"],
    "search":       ["搜索", "搜寻", "search", "找"],
}

# 结果 -> 关键词（先查"坠毁"，再查"成功"，避免误判）
OUTCOME_CRASH = ["坠机", "坠毁", "炸机", "crash", "lose", "loss", "down", "failed", "事故"]
OUTCOME_OK    = ["成功", "安全", "完好", "救回", "回收", "成功返航", "success", "safe", "recover", "salvage"]

def _text(rec):
    parts = [rec.get("title",""), rec.get("description","")]
    tc = rec.get("top_comments")
    if isinstance(tc, list):
        parts.extend(tc)
    elif tc:
        parts.append(str(tc))
    return " ".join(parts).lower()

def _has(text, kws):
    return any(k.lower() in text for k in kws)

def extract(rec):
    """返回 {accident_type, environment, actions(list), outcome}
    accident_type 复用 classifier.classify（anomaly 命名，与 P/T 权重体系一致），
    environment / actions / outcome 用关键词规则独立提取。"""
    import sys, os as _os
    _here = _os.path.dirname(_os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    from classifier import classify
    t = _text(rec)
    # 事故类别：交给统一分类器（消除分叉词库）
    atype = classify(rec)["anomaly_type"]
    # 环境：命中的自然因素（可多个）
    ENV_KW = {"wind":  ["风", "wind", "gust"],
               "rain":  ["雨", "rain", "water", "wet"],
               "cold":  ["低温", "cold", "ice", "凝露"],
               "bird":  ["鸟", "bird"],
               "lightning": ["雷", "lightning", "thunder"]}
    env = [k for k, kws in ENV_KW.items() if _has(t, kws)]
    # 应对动作：可多个
    acts = [k for k,kws in ACTIONS.items() if _has(t, kws)]
    # 结果：坠毁优先（避免"安全返航...但坠毁"误判）
    if _has(t, OUTCOME_CRASH):
        outcome = "crash"
    elif _has(t, OUTCOME_OK):
        outcome = "success"
    else:
        outcome = "unknown"
    return {"accident_type":atype, "environment":env,
            "actions":acts, "outcome":outcome}

if __name__ == "__main__":
    import json, os
    from collections import Counter
    _here = os.path.dirname(os.path.abspath(__file__))
    _crawler = os.path.join(_here, "..", "..", "drone_crawler")  # P1-1: HERE abs path
    _fixed = os.path.join(_crawler, "data", "raw", "multi_raw_fixed.jsonl")
    _orig  = os.path.join(_crawler, "data", "raw", "multi_raw.jsonl")
    _path  = _fixed if os.path.exists(_fixed) else _orig
    if os.path.exists(_path):
        at=Counter(); ac=Counter(); oc=Counter()
        for line in open(_path, encoding="utf-8"):
            line=line.strip()
            if not line: continue
            r=json.loads(line); res=extract(r)
            at[res["accident_type"]]+=1
            oc[res["outcome"]]+=1
            for a in res["actions"]: ac[a]+=1
        print("accident:", dict(at.most_common()))
        print("outcome: ", dict(oc.most_common()))
        print("actions: ", dict(ac.most_common()))
