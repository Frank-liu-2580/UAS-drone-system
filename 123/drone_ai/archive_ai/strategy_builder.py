# -*- coding: utf-8 -*-
"""
决策策略库 + 模式动态评分
输入 Anomaly_Events（来自 event_builder），为每个异常事件在 4 种模式下
计算 Reward/Penalty，输出 Decision_Strategies.xlsx
模式：CRUISE(常规) / PROTECT(保飞机) / MISSION(保任务) / RTB(紧急返航)
评分规则（0-100，越高越好；负值=惩罚）：
  按 异常严重度 + 模式偏好 决定。核心：
   - 内部致命类(motor/prop/flight_ctrl/battery)：任何模式都必须强制保飞机
   - 自然类(rain/wind/cold)：MISSION 模式奖励"继续/避雨"，PROTECT 奖励"立即返航"
   - 通信类(signal/gps)：所有模式执行 failsafe
"""
import json, os
from openpyxl import Workbook

EVENTS_IN  = "analyzer/output/Anomaly_Events.xlsx"
OUT = "analyzer/output/Decision_Strategies.xlsx"

MODES = ["CRUISE","PROTECT","MISSION","RTB"]
MODE_CN = {"CRUISE":"常规巡航","PROTECT":"保护无人机","MISSION":"任务优先","RTB":"紧急返航"}

# 每个异常类型在 4 模式下 (动作, 该动作本身的风险risk 1-10, 对任务价值mission_value)
# 然后由 score() 折算成 Reward/Penalty
Policies = {
 "motor_failure":  ("切换三轴冗余/极速软降",9,"CRITICAL"),
 "prop_break":     ("极速降油门软着陆",8,"CRITICAL"),
 "esc_fault":      ("限油门/就近降落",6,"HIGH"),
 "battery_issue":  ("关载荷+计算续航→返航或就近降",5,"MEDIUM"),
 "flight_ctrl":     ("硬件备份接管/迫降",10,"CRITICAL"),
 "gimbal_fault":    ("保持机身水平禁机动",2,"LOW"),
 "payload_fault":   ("停任务动作/评估载荷",2,"MEDIUM"),
 "signal_loss":     ("执行预设Failsafe返航/悬停",5,"HIGH"),
 "gps_drift":       ("切视觉/IMU导航, 限时悬停",4,"MEDIUM"),
 "wind_gust":       ("降高度/顺风提速穿过",3,"LOW"),
 "rain":            ("避雨点悬停 或 直接返航",3,"LOW"),
 "cold_hot":        ("缩短任务/提前返航",2,"LOW"),
 "dust_fog":        ("降高度增视距/取消任务",3,"MEDIUM"),
 "bird":            ("避让保持距离/密集则急降",4,"MEDIUM"),
 "lightning":       ("立即接地断电",10,"CRITICAL"),
 "obstacle":        ("动态避障绕飞/急停",4,"LOW"),
 "unknown":         ("保守悬停待命, 请求接管",3,"LOW"),
}

def score(anomaly, mode, risk, mission_value):
    """返回 0-100 的净得分（可负）"""
    # 致命内部类：PROTECT/RTB 下强保飞机=高分；MISSION 下也必须在安全底线内
    fatal = anomaly in ("motor_failure","prop_break","flight_ctrl","lightning")
    if fatal:
        base = 95 if mode in ("PROTECT","RTB") else 60
        return base
    # 自然类：模式分化（你强调的核心规则）
    natural = anomaly in ("rain","wind_gust","cold_hot","dust_fog","bird","obstacle")
    if natural:
        if mode == "MISSION":
            # 任务模式：鼓励继续任务/避雨而非立即返航
            return 85 if risk<=4 else 70
        elif mode == "PROTECT":
            # 保护模式：立即保守处置（返航/悬停）
            return 90
        elif mode == "RTB":
            return 92
        else:  # CRUISE
            return 75
    # 通信类：所有模式执行 failsafe
    if anomaly in ("signal_loss","gps_drift"):
        return 88 if mode in ("PROTECT","RTB") else 78
    # 低影响类
    if risk <= 2:
        return 70 if mode=="MISSION" else 85
    return 75

def build():
    from openpyxl import load_workbook
    wb_ev = load_workbook(EVENTS_IN); ws = wb_ev["异常事件库"]
    events = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        events.append({"type":row[0],"factor":row[1],"priority":row[2],
                       "severity":row[3],"count":row[4]})
    rows = []
    for ev in events:
        atype = ev["type"]
        action, risk, mval = Policies.get(atype, ("保守悬停待命",3,"LOW"))
        for m in MODES:
            sc = score(atype, m, risk, mval)
            reward = max(0, sc-50)
            penalty = max(0, 50-sc)
            # 执行目标：致命/紧急=飞控硬约束，其余=影子AI策略
            target = "FlightController" if (atype in ("motor_failure","prop_break","flight_ctrl","lightning")) or m=="RTB" else "Shadow_AI"
            rows.append([f"D_{atype}_{m}", atype, MODE_CN[m], m,
                        action, f"risk={risk}/mission={mval}", target,
                        reward, penalty, sc, ev["severity"]])
    os.makedirs("analyzer/output", exist_ok=True)
    wb = Workbook(); ws2 = wb.active; ws2.title = "决策策略库"
    ws2.append(["Strategy_ID","Anomaly_Type","Mode_CN","Mode","Action",
               "RiskInfo","Execution_Target","Reward","Penalty","NetScore","Severity"])
    for r in rows: ws2.append(r)
    widths=[20,16,12,8,40,22,18,8,8,10,10]
    for i,w in enumerate(widths,1): ws2.column_dimensions[chr(64+i)].width=w
    wb.save(OUT)
    print(f"[完成] {len(events)} 个异常 × {len(MODES)} 模式 = {len(rows)} 条策略 -> {OUT}")
    return len(rows)

if __name__ == "__main__":
    build()