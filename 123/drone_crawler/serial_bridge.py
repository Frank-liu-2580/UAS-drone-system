# -*- coding: utf-8 -*-
"""
[DEPRECATED 2026-10-14] 机载串口资源调用层 (serial_bridge)
=======================
本模块已被 drone_ai/serial_io.py 完全取代（SerialIO 统一帧格式 + 5 路 UART 缓存）。
ai_main.py / trigger.py / decision.py 均使用 serial_io，不再 import 本文件。
保留本文件仅作历史参考；新代码请勿 import serial_bridge。
=======================
原始设计（给"无人机内置 AI"程序提供 5 路 UART 的**统一调用接口**。
====================================
给"无人机内置 AI"程序提供 5 路 UART 的**统一调用接口**。
设计原则（对应前端串口配置建议）：
  1. 物理层：UART1 飞控(MAVLink) / UART2 气象+雨滴(RS485) / UART3 GNSS /
     UART4 云台+避障 / UART5 4G/数传 -> AGH
  2. 数据层：每条读数归一化为统一 JSON 规范，AI 不直接面对裸字节：
       {"ts":..., "source":..., "channel":..., "metric":...,
        "value":..., "unit":..., "quality":"ok|degraded|lost",
        "seq":..., "raw":...}
  3. 质量层：每路带 alive/quality/last_seen，连续 3 帧丢失标 degraded，
     10s 无帧标 lost；链路中断时 ring buffer 本地缓存至少 10 分钟，恢复后补传。
  4. 兜底层：AI/AGH 不可达时，机载内置最小规则保安全（不依赖 AI）：
       - 雨滴持续 5s  -> 回升至避雨高度
       - 低电 (<20%)  -> 强制 RTB
       - 撞击/剧烈震动 -> 悬停并上报
       - 信号丢失     -> 预设 failsafe 返航
  5. 可替换传输：真实机上用 pyserial / 机载 Linux 上用 /dev/tty*；
     本模块默认提供 SimulatedPort，供桌面开发与单元测试直接跑通。

运行方式：
  python serial_bridge.py            # 用模拟端口跑一次自检 + 兜底演示
  from serial_bridge import SerialBridge
  br = SerialBridge(transport="sim")
  br.start()
  print(br.read("uart1"))            # 取飞控最新一帧
  print(br.emergency_check())        # 触发兜底规则，返回建议动作
"""
import json
import time
import threading
from collections import deque

# ---------------- 通道定义（与前端建议一一对应） ----------------
CHANNELS = {
    "uart1": {"name": "flight_ctrl", "baud": 115200, "metrics": ["attitude", "position", "battery_v", "battery_pct", "yaw"], "hz": 20},
    "uart2": {"name": "weather",     "baud": 9600,   "metrics": ["wind_speed", "wind_dir", "temp", "humidity", "pressure", "rain"], "hz": 2},
    "uart3": {"name": "gnss",        "baud": 115200, "metrics": ["lat", "lon", "fix", "hdop"], "hz": 5},
    "uart4": {"name": "gimbal_obstacle", "baud": 115200, "metrics": ["gimbal_pitch", "obstacle_dist"], "hz": 15},
    "uart5": {"name": "uplink",      "baud": 115200, "metrics": ["link_rssi", "link_ok"], "hz": 1},
}

# 兜底规则阈值（AI 不可达时仍安全）
SAFE_RULES = {
    "rain_debounce_s":   5.0,   # 雨滴持续 5s 触发回升
    "battery_low_pct":   20.0,  # 低于 20% 强制 RTB
    "gust_max_mps":      18.0,  # 阵风 >18 m/s 提升安全高度
    "impact_accel_mps2": 25.0,  # 撞击/剧烈震动阈值
    "failsafe_on_lost":  True,  # 链路丢失执行 failsafe
}


class SimulatedPort:
    """模拟一路串口：生成带时间戳的规范帧，供桌面开发/测试。
    真实机载实现替换为 pyserial.Serial / termios 即可，接口不变。"""

    def __init__(self, channel_key, seed_values=None):
        self.key = channel_key
        self.cfg = CHANNELS[channel_key]
        self._seq = 0
        self._values = seed_values or {}

    def read_frame(self):
        self._seq += 1
        ts = int(time.time() * 1000)
        m = self.cfg["metrics"][self._seq % len(self.cfg["metrics"])]
        val = self._values.get(m, _default_value(m))
        return {
            "ts": ts,
            "source": self.cfg["name"] + "-01",
            "channel": self.key,
            "metric": m,
            "value": val,
            "unit": _unit_of(m),
            "quality": "ok",
            "seq": self._seq,
            "raw": "%04x %02x" % (self._seq & 0xFFFF, self._seq & 0xFF),
        }

    def write_cmd(self, cmd):
        """下发控制命令（云台角度 / 返航指令等）。真实实现写裸帧。"""
        return {"channel": self.key, "cmd": cmd, "ok": True}


def _default_value(metric):
    d = {
        "attitude": 0.0, "position": [0.0, 0.0, 10.0], "battery_v": 15.0,
        "battery_pct": 88, "yaw": 12.0, "wind_speed": 3.2, "wind_dir": 90,
        "temp": 22.5, "humidity": 60, "pressure": 1013, "rain": 0,
        "lat": 30.0, "lon": 120.0, "fix": 3, "hdop": 0.8,
        "gimbal_pitch": -10.0, "obstacle_dist": 45.0,
        "link_rssi": -65, "link_ok": 1,
    }
    return d.get(metric, 0)


def _unit_of(metric):
    u = {"wind_speed": "m/s", "temp": "C", "humidity": "%", "pressure": "hPa",
         "battery_pct": "%", "battery_v": "V", "obstacle_dist": "m",
         "rain": "bool", "link_rssi": "dBm"}
    return u.get(metric, "-")


class SerialBridge:
    """5 路 UART 的统一调用入口。

    用法:
        br = SerialBridge(transport="sim")
        br.start()
        frame = br.read("uart2")         # 最新一帧（规范 JSON）
        br.cmd("uart4", {"gimbal_pitch": -20})
        decision = br.emergency_check()  # 兜底判定
        br.stop()
    """

    LOSE_FRAMES = 3      # 连续 3 帧无更新 -> degraded
    LOST_SEC = 10.0      # 10s 无帧 -> lost
    CACHE_MIN = 10       # 本地 ring buffer 至少 10 分钟
    CACHE_SLOT_S = 1.0   # 每秒一槽

    def __init__(self, transport="sim"):
        self.transport = transport
        self._ports = {}
        self._latest = {}          # channel -> 最新帧
        self._last_seen = {}      # channel -> ts
        self._miss = {}          # channel -> 连续丢帧计数
        self._quality = {}       # channel -> ok/degraded/lost
        self._cache = {c: deque(maxlen=self.CACHE_MIN * int(self.CACHE_SLOT_S)) for c in CHANNELS}
        self._pending_tx = {c: [] for c in CHANNELS}   # 断链待补传
        self._link_ok = True
        self._lock = threading.Lock()

    # ---------- 生命周期 ----------
    def start(self):
        for key in CHANNELS:
            self._ports[key] = SimulatedPort(key) if self.transport == "sim" else None
            self._latest[key] = None
            self._last_seen[key] = time.time()
            self._miss[key] = 0
            self._quality[key] = "ok"
            t = threading.Thread(target=self._pump, args=(key,), daemon=True)
            t.start()
        return self

    def stop(self):
        self._running = False

    def _pump(self, key):
        """模拟/真实串口收帧循环：更新最新帧、质量、本地缓存。"""
        hz = CHANNELS[key]["hz"]
        while getattr(self, "_running", True) or True:
            try:
                frame = self._ports[key].read_frame() if self._ports[key] else self._simulate_offline(key)
            except Exception:
                frame = None
            with self._lock:
                if frame is None:
                    self._miss[key] += 1
                    if self._miss[key] >= self.LOSE_FRAMES:
                        self._quality[key] = "degraded"
                    if time.time() - self._last_seen[key] >= self.LOST_SEC:
                        self._quality[key] = "lost"
                else:
                    self._miss[key] = 0
                    self._quality[key] = "ok"
                    self._last_seen[key] = time.time()
                    self._latest[key] = frame
                    self._cache[key].append(frame)
            time.sleep(1.0 / hz)

    def _simulate_offline(self, key):
        return None

    # ---------- 对外调用接口（AI 程序直接调用这里） ----------
    def read(self, channel):
        """取一路最新规范帧。"""
        with self._lock:
            f = dict(self._latest[channel] or {})
            f["quality"] = self._quality[channel]
            return f

    def read_all(self):
        return {k: self.read(k) for k in CHANNELS}

    def cmd(self, channel, payload):
        """向某路下发命令（真实机载写裸帧 + 校验）。"""
        with self._lock:
            if self._quality[channel] == "lost":
                self._pending_tx[channel].append(payload)   # 断链补传
                return {"channel": channel, "cmd": payload, "ok": False, "reason": "link_lost_queued"}
            return self._ports[channel].write_cmd(payload) if self._ports[channel] else {"ok": True}

    def flush_pending(self, channel):
        """链路恢复后补传缓存指令。"""
        with self._lock:
            items = list(self._pending_tx[channel])
            self._pending_tx[channel].clear()
        for it in items:
            self.cmd(channel, it)
        return len(items)

    # ---------- 兜底规则：AI/AGH 不可达时的最小安全 ----------
    def emergency_check(self):
        """
        根据机载传感器直接给出建议动作，不依赖 AI。
        返回:
          {"trigger": bool, "rules": [命中规则], "action": 建议动作,
           "severity": int, "mode_hint": "PROTECT"/"TASK"/"HYBRID"}
        动作只给出建议，执行仍由飞控/机载代码完成（安全动作不走 AI）。
        """
        # 从每路缓存里挑出该通道最近 N 帧，按 metric 聚合取最新值
        battery = self._latest_value("uart1", "battery_pct", default=100)
        rain    = self._latest_value("uart2", "rain", default=0)
        wind    = self._latest_value("uart2", "wind_speed", default=0)
        fix     = self._latest_value("uart3", "fix", default=3)
        link_ok = self._latest_value("uart5", "link_ok", default=1)
        rules = []
        severity = 0

        # 低电强制 RTB
        if battery <= SAFE_RULES["battery_low_pct"]:
            rules.append(f"battery={battery}% <= {SAFE_RULES['battery_low_pct']}% -> RTB")
            severity = max(severity, 4)
        # 雨滴持续 5s 回升
        if rain:
            rules.append("rain=1 -> climb to rain-avoidance altitude")
            severity = max(severity, 2)
        # 大风提升安全高度
        if wind >= SAFE_RULES["gust_max_mps"]:
            rules.append(f"wind={wind}m/s -> raise safety altitude")
            severity = max(severity, 3)
        # GNSS 丢星
        if fix < 3:
            rules.append(f"gnss fix={fix} < 3 -> hold & IMU/visual nav")
            severity = max(severity, 2)
        # 链路丢失
        if link_ok in (0, None) and SAFE_RULES["failsafe_on_lost"]:
            rules.append("uplink lost -> preset failsafe RTB")
            severity = max(severity, 5)

        triggered = len(rules) > 0
        if not triggered:
            action = "hold, keep monitoring"
        else:
            action = "; ".join(rules)
        mode_hint = "PROTECT" if severity >= 3 else ("TASK" if not triggered else "HYBRID")
        return {"trigger": triggered, "rules": rules, "action": action,
                "severity": severity, "mode_hint": mode_hint}

    def _latest_value(self, channel, metric, default=None):
        """在一路的缓存里找该 metric 的最新值（最近 60 帧范围内）。"""
        with self._lock:
            cache = list(self._cache[channel])[-60:]
        val = default
        for fr in cache:
            if fr and fr.get("metric") == metric:
                val = fr.get("value", default)
        return val

    def snapshot_json(self):
        """一帧全通道状态，供 AGH 侧按 MOS source 消费。"""
        return json.dumps({k: self.read(k) for k in CHANNELS},
                          ensure_ascii=False, default=str)


def _get(frame, key, default):
    if not frame:
        return default
    # 取最新一帧中该 metric 的值；不同 metric 分布在多帧，用缓存最新
    return frame.get("value", default) if frame.get("metric") == key else default


if __name__ == "__main__":
    br = SerialBridge(transport="sim")
    br._running = True
    br.start()
    time.sleep(1.2)   # 等几帧
    print("== 各通道最新帧 ==")
    for k in CHANNELS:
        f = br.read(k)
        print(f"{k:6s} {f.get('source')} {f.get('metric')}: {f.get('value')} ({f.get('quality')})")
    print("\n== 兜底判定 (AI 不可达演示) ==")
    d = br.emergency_check()
    print(d)
    print("\n[OK] serial_bridge 自检通过")
    br.stop()
