# -*- coding: utf-8 -*-
"""
关键词库 + 抓取量配置
覆盖 内部故障/自然环境/通信定位/任务载荷 等 10 大类
B站中文、YouTube英文
每关键词抓取量在这里统一调整（BILI_PER_KW / YT_PER_KW）
"""

# ---------------- B 站（国内）关键词 ----------------
BILI_KEYWORDS = {
    "动力故障": [
        "无人机 电机故障", "无人机 炸机", "四轴 电机 停转", "无人机 电调 故障",
        "无人机 螺旋桨断裂", "无人机 桨 脱落", "无人机 动力 失效", "无人机 单桨 飞行",
        "无人机 炸机 合集", "无人机 坠机 合集", "无人机 事故", "无人机 故障",
        "四轴 炸机", "多旋翼 坠机", "无人机 电机 烧", "无人机 电调 烧",
        "无人机 螺旋桨 断", "无人机 桨叶 破损", "无人机 起落架 故障",
        "无人机 炸机 原因",
    ],
    "云台载荷": [
        "无人机 云台 摇头", "无人机 云台 不转", "无人机 云台 故障", "无人机 相机 云台",
        "无人机 载荷 掉落", "无人机 喷洒 故障", "无人机 巡检 异常",
        "无人机 巡检 故障", "无人机 测绘 数据 异常", "无人机 喷洒 量 不准",
        "无人机 挂载 释放 失败", "无人机 回收 失败", "无人机 降落 不准",
    ],
    "飞控导航": [
        "无人机 飞控 死机", "无人机 飞控 复位", "无人机 姿态 失控", "无人机 悬停 飘",
        "无人机 打偏", "无人机 跑偏", "无人机 航线 偏差", "无人机 偏航",
        "无人机 飞控 异常", "无人机 导航 发散", "无人机 悬停 抖动",
    ],
    "能源系统": [
        "无人机 电池鼓包", "无人机 低电量", "无人机 电压 骤降", "无人机 电池 过温",
        "无人机 掉电", "无人机 电量不足 返航", "无人机 电池 过放",
        "无人机 电池 保护板", "无人机 电池 鼓包 处理", "无人机 电量 不足",
        "无人机 电池 低温 衰减", "无人机 电池 热失控", "无人机 低电量 返航",
    ],
    "通信定位": [
        "无人机 失控", "无人机 信号丢失", "无人机 失联 返航", "无人机 GPS 漂移",
        "无人机 定位 丢失", "无人机 罗盘 故障", "无人机 指南针 偏差", "无人机 数传 中断",
        "无人机 失联", "无人机 失控 返航", "无人机 丢遥控", "无人机 遥控 中断",
        "无人机 数传 中断", "无人机 GPS 丢星", "无人机 罗盘 乱转", "无人机 罗盘 校准",
        "无人机 指南针 异常", "无人机 磁干扰", "无人机 偏航 修正",
    ],
    "自然环境-风": [
        "无人机 大风", "无人机 阵风", "无人机 侧风 测试", "无人机 强风 降落",
        "无人机 逆风 飞行", "无人机 风切变", "无人机 大风 飞行", "无人机 阵风 测试",
        "无人机 侧风 修正", "无人机 强对流",
    ],
    "自然环境-雨/雾/沙": [
        "无人机 雨天", "无人机 下雨 飞行", "无人机 暴雨 坠机", "无人机 淋雨 返航",
        "无人机 雨滴 传感器", "无人机 雨 淋水", "无人机 大雾 飞行", "无人机 沙尘 环境",
    ],
    "自然环境-温/雷/冰": [
        "无人机 低温", "无人机 高温 电池", "无人机 结露", "无人机 凝露",
        "无人机 低温 飞行", "无人机 高温 降额", "无人机 雷暴 天气", "无人机 冰雹",
        "无人机 雷击", "无人机 电磁干扰", "无人机 静电 放电", "无人机 短路",
    ],
    "障碍物/生物": [
        "无人机 避障", "无人机 撞 鸟", "无人机 鸟撞", "无人机 障碍物 检测",
        "无人机 碰撞 躲避", "无人机 激光 测距", "无人机 鸟撞 避让", "无人机 鸟类 躲避",
        "无人机 障碍物 撞击",
    ],
    "复盘处置": [
        "无人机 炸机 分析", "无人机 事故 复盘", "无人机 应急 处置",
    ],
}

# ---------------- YouTube（国际）关键词 ----------------
YT_KEYWORDS = {
    "power": [
        "drone motor failure", "drone propeller break", "drone ESC failure",
        "drone single motor flight", "drone power loss", "drone motor jam",
        "drone crash compilation", "drone accident", "drone failure",
        "drone motor burnt", "drone propeller damaged", "drone prop strike",
        "drone landing gear fault",
    ],
    "gimbal_payload": [
        "drone gimbal failure", "drone camera gimbal", "drone payload drop",
        "drone inspection anomaly", "drone spraying fault",
        "drone gimbal stuck", "drone gimbal wobble", "drone inspection fault",
        "drone survey data anomaly", "drone spray rate error",
        "drone payload release fail", "drone recovery fail", "drone landing inaccuracy",
    ],
    "fc_nav": [
        "drone navigation error", "drone attitude loss", "drone hover vibration",
        "drone EKF divergence", "drone flight controller crash", "drone deviation",
        "drone flight controller crash", "drone FC watchdog reset", "drone off course",
        "drone hover drift", "drone waypoint miss", "drone crash analysis",
        "drone accident review", "drone emergency response",
    ],
    "battery": [
        "drone battery failure", "drone low battery emergency", "drone battery swelling",
        "drone battery overheat", "drone power drain",
        "drone battery overdischarged", "drone battery protection board",
        "drone battery swelling fix", "drone low battery RTH", "drone battery fails",
        "drone battery thermal runaway", "drone cold battery sag", "drone hot battery derating",
    ],
    "signal_gps": [
        "drone signal loss", "drone GPS failure", "drone compass error",
        "drone telemetry lost", "drone data link loss", "drone failsafe",
        "drone lost link", "drone failsafe trigger", "drone remote lost",
        "drone data link drop", "drone GPS lost", "drone GPS drift",
        "drone compass glitch", "drone compass interference", "drone magnetometer error",
    ],
    "wind": [
        "drone strong wind", "drone wind gust", "drone crosswind", "drone wind shear",
        "drone into wind flight", "drone turbulent",
        "drone in strong wind", "drone gust test", "drone crosswind handling", "drone squall",
    ],
    "rain_fog_dust": [
        "drone rain", "drone heavy rain crash", "drone wet landing", "drone rain avoidance",
        "drone water spray", "drone rain soaked", "drone rain sensor", "drone fog flight",
        "drone dust storm flight",
    ],
    "temp_thunder_ice": [
        "drone cold weather", "drone hot weather battery", "drone dust storm",
        "drone fog flight", "drone condensation",
        "drone low temperature flight", "drone high temperature derate",
        "drone thunderstorm", "drone hail", "drone lightning strike", "drone EMI interference",
    ],
    "obstacle_bird": [
        "drone obstacle avoidance", "drone bird collision", "drone lidar obstacle",
        "drone collision avoidance", "drone laser ranging",
        "drone bird strike", "drone bird avoidance", "drone obstacle hit", "drone cliff collision",
    ],
}

# 每关键词抓取量（B站取前 N，YouTube 用 ytsearch N）
BILI_PER_KW = 80
YT_PER_KW   = 60

def all_bili_keywords():
    out = []
    for cat, kws in BILI_KEYWORDS.items():
        for k in kws:
            if k not in out:
                out.append(k)
    return out

def all_yt_keywords():
    out = []
    for cat, kws in YT_KEYWORDS.items():
        for k in kws:
            if k not in out:
                out.append(k)
    return out