# -*- coding: utf-8 -*-
"""
trigger.py — 传感器读数 -> 命中哪些异常
=======================================
把 5 路串口上的 metric 值映射到 anomaly_type。
规则与 archive_ai 的影子 AI 一致，阈值全部来自 thresholds.py。

返回 [(anomaly_type, metric, reason), ...]
按严重度降序 + 内部因素优先（调用方排序）。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import thresholds as T

# (metric, anomaly_type, 判定函数(value, unit) -> bool, 说明)
TRIGGER_RULES = [
    # ---- 内部致命（飞控兜底，权重最高）----
    ("esc_current", "motor_failure",
        lambda v,u: isinstance(v,(int,float)) and float(v) <= T.MOTOR_FAIL_CURRENT_A,
        "某电机通道电流<=0A => 电机停转/失效"),
    ("vib_high", "prop_break",
        lambda v,u: bool(v),
        "高频振动标志 => 桨叶断裂/不平衡"),
    ("flight_ctrl_alive", "flight_ctrl",
        lambda v,u: not bool(v),
        "飞控心跳丢失 => 飞控死机/复位"),
    ("battery_v", "battery_issue",
        lambda v,u: isinstance(v,(int,float)) and float(v) < T.BATTERY_CRIT_V,
        f"全包电压<{T.BATTERY_CRIT_V}V => 低电量紧急"),
    ("battery_temp", "battery_issue",
        lambda v,u: isinstance(v,(int,float)) and float(v) > T.BATTERY_TEMP_CRIT_C,
        f"电池温度>{T.BATTERY_TEMP_CRIT_C}°C => 过温"),
    ("esc_temp", "esc_fault",
        lambda v,u: isinstance(v,(int,float)) and float(v) > T.ESC_TEMP_CRIT_C,
        f"电调温度>{T.ESC_TEMP_CRIT_C}°C => 过热"),
    # ---- 通信/定位 ----
    ("link_ok", "signal_loss",
        lambda v,u: (v in (0, False)),
        "通信链路丢失 => Failsafe"),
    ("link_rssi", "signal_loss",
        lambda v,u: isinstance(v,(int,float)) and float(v) < T.RSSI_LOST_DBM,
        f"RSSI<{T.RSSI_LOST_DBM}dBm => 已丢链"),
    ("hdop", "gps_drift",
        lambda v,u: isinstance(v,(int,float)) and float(v) > T.GPS_HDOP_MAX,
        f"HDOP>{T.GPS_HDOP_MAX} => GPS 漂移"),
    ("sat_count", "gps_drift",
        lambda v,u: isinstance(v,(int,float)) and float(v) < T.GPS_SAT_MIN,
        f"卫星数<{T.GPS_SAT_MIN} => 定位降级"),
    # ---- 自然因素 ----
    ("rain", "rain",
        lambda v,u: bool(v),
        "雨滴传感器触发 => 降雨"),
    ("wind_speed", "wind_gust",
        lambda v,u: isinstance(v,(int,float)) and float(v) > T.WIND_WARN_MS,
        f"风速>{T.WIND_WARN_MS}m/s => 强风告警"),
    ("temp_c", "cold_hot",
        lambda v,u: isinstance(v,(int,float)) and
                    (float(v) < T.TEMP_LOW_C or float(v) > T.TEMP_HIGH_C),
        "气温超包线 => 极端温度"),
    ("visibility", "dust_fog",
        lambda v,u: isinstance(v,(int,float)) and float(v) < T.VISIBILITY_MIN_M,
        f"视距<{T.VISIBILITY_MIN_M}m => 沙尘/雾霾"),
    ("bird_detect", "bird",
        lambda v,u: bool(v),
        "视觉/雷达检出鸟类 => 鸟撞风险"),
    ("obstacle_dist", "obstacle",
        lambda v,u: isinstance(v,(int,float)) and float(v) < T.OBSTACLE_CLOSE_M,
        f"障碍距离<{T.OBSTACLE_CLOSE_M}m => 接近预警"),
    # ---- 天气学：打雷（事件库 lightning 类 279 条）----
    ("thunder", "lightning",
        lambda v,u: bool(v),
        "打雷/雷曲线风检测 => 离开雷曲"),
    # P0-2: gimbal_fault / payload_fault trigger rules
    # (previously simulator injected these metrics but AI could never detect them)
    ("gimbal_pitch", "gimbal_fault",
        lambda v,u: isinstance(v,(int,float)) and abs(float(v)) > T.GIMBAL_PITCH_MAX_DEG,
        f"gimbal pitch out of +/-{T.GIMBAL_PITCH_MAX_DEG} deg => gimbal fault"),
    ("payload_fault_flag", "payload_fault",
        lambda v,u: bool(v),
        "payload fault flag => stop task action / assess payload"),
]



def detect(metric_values):
    """
    入参: {metric: value, ...}  数值或布尔
    返回: [(anomaly_type, metric, reason), ...]
    """
    hits = []
    for metric, atype, fn, desc in TRIGGER_RULES:
        if metric not in metric_values:
            continue
        val = metric_values[metric]
        try:
            if fn(val, ""):
                hits.append((atype, metric, desc))
        except Exception:
            pass
    return hits


def read_metrics_from_io(io, stale_sec=3.0):
    """从 SerialIO 的 5 路缓存里挑出所有能用的 metric 值。
    修复：时效闸门 —— 帧 ts 超过 stale_sec 或通道 quality=lost 的不进决策，
    避免断链后用陈旧坐标开飞机（场景C）。"""
    import time as _t
    now_ms = int(_t.time() * 1000)
    stale_ms = stale_sec * 1000
    out = {}
    for ch in ("uart1","uart2","uart3","uart4","uart5"):
        # 通道级丢链 -> 该通道全部 metric 都不可信
        if io._quality.get(ch) == "lost":
            continue
        for fr in io._cache[ch]:
            if not fr:
                continue
            # 帧级时效：ts 太旧就丢弃
            ts = fr.get("ts", 0)
            if ts and (now_ms - ts) > stale_ms:
                continue
            out[fr["metric"]] = fr["value"]
    return out


def is_fresh(io, stale_sec=3.0):
    """返回 {channel: bool}，该通道是否在 stale_sec 内有新帧且未丢链。"""
    import time as _t
    now_ms = int(_t.time() * 1000)
    stale_ms = stale_sec * 1000
    res = {}
    for ch in ("uart1","uart2","uart3","uart4","uart5"):
        if io._quality.get(ch) == "lost":
            res[ch] = False
            continue
        fresh = False
        for fr in io._cache[ch]:
            if fr and fr.get("ts",0) and (now_ms - fr["ts"]) <= stale_ms:
                fresh = True
                break
        res[ch] = fresh
    return res
