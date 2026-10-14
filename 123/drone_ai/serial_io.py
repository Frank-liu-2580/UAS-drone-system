# -*- coding: utf-8 -*-
"""
serial_io.py — 机载 5 路 UART 的 I/O 抽象
==========================================
两实现：
  - SerialIO(sim=True)   仿真口：桌面开发/单元测试直接跑通，生成规范 JSON 帧
  - SerialIO(sim=False)  真实口：接 pyserial 走 /dev/tty* 或 COMx

统一帧格式（AI 只消费这个，不面对裸字节）
  {
    "ts": 1730000000123, "source": "flight_ctrl-01",
    "channel": "uart1", "metric": "battery_v",
    "value": 15.0, "unit": "V",
    "quality": "ok", "seq": 88123, "raw": "01 03 04 00 01 ..."
  }

通道定义（与前端串口建议一一对应）
  uart1  飞控 MAVLink         115200
  uart2  气象站 + 数字雨滴    9600 (RS485 半双工 Modbus RTU)
  uart3  GNSS / RTK          115200
  uart4  云台 + 避障雷达      115200
  uart5  4G / 数传 -> AGH    115200
"""
import time
import threading
from collections import deque

CHANNELS = {
    "uart1": {"name": "flight_ctrl", "baud": 115200,
               "metrics": ["attitude", "position", "speed", "battery_v",
                            "battery_pct", "yaw", "esc_current",
                            "flight_ctrl_alive", "vib_high"],
               "hz": 20},
    "uart2": {"name": "weather", "baud": 9600,
               "metrics": ["wind_speed", "wind_dir", "temp_c",
                            "humidity", "pressure", "rain", "thunder",
                            "battery_temp", "esc_temp", "visibility"],
               "hz": 2},
    "uart3": {"name": "gnss", "baud": 115200,
               "metrics": ["lat", "lon", "fix", "hdop", "sat_count"],
               "hz": 5},
    "uart4": {"name": "gimbal_obstacle", "baud": 115200,
               "metrics": ["gimbal_pitch", "obstacle_dist",
                            "obstacle_bearing_deg", "obstacle_pos", "bird_detect",
                            "payload_fault_flag"],
               "hz": 15},
    "uart5": {"name": "uplink", "baud": 115200,
               "metrics": ["link_rssi", "link_ok"],
               "hz": 1},
}

# 模拟默认值（桌面开发用；上机替换为 pyserial 实际读值）
DEFAULTS = {
    "attitude": [0.0, 0.0, 0.0], "position": [30.0, 120.0, 20.0],
    "speed": 5.0, "battery_v": 15.0, "battery_pct": 88, "yaw": 12.0,
    "esc_current": 2.5, "flight_ctrl_alive": 1, "vib_high": 0,
    "wind_speed": 3.2, "wind_dir": 90, "temp_c": 22.5,
    "humidity": 60, "pressure": 1013, "rain": 0,
    "battery_temp": 45, "esc_temp": 55, "visibility": 800, "thunder": 0,
    "lat": 30.0, "lon": 120.0, "fix": 3, "hdop": 0.8, "sat_count": 12,
    "gimbal_pitch": -10.0, "obstacle_dist": 45.0,
    "obstacle_bearing_deg": 0.0, "obstacle_pos": None, "bird_detect": 0,
    "payload_fault_flag": 0, "link_rssi": -65, "link_ok": 1,
}

UNITS = {
    "wind_speed": "m/s", "temp_c": "C", "humidity": "%",
    "pressure": "hPa", "battery_pct": "%", "battery_v": "V",
    "obstacle_dist": "m", "rain": "bool", "link_rssi": "dBm",
    "hdop": "-", "sat_count": "-", "fix": "-", "yaw": "deg",
    "battery_temp": "C", "esc_temp": "C", "visibility": "m", "thunder": "bool",
    "gimbal_pitch": "deg", "payload_fault_flag": "bool",
}


def _norm_frame(channel, metric, value):
    return {
        "ts": int(time.time() * 1000),
        "source": CHANNELS[channel]["name"] + "-01",
        "channel": channel,
        "metric": metric,
        "value": value,
        "unit": UNITS.get(metric, "-"),
        "quality": "ok",
        "seq": 0,
        "raw": "",
    }


class SerialIO:
    """5 路 UART 统一读入口。
    对外暴露：
      - read(channel)    最新一帧（含 quality）
      - read_all()       全部 5 路最新帧
      - cmd(channel, payload)  下发控制命令（真实实现写裸帧 + 校验）
      - start()/stop()   启动/停止后台收帧线程
      - latest_value(channel, metric, default)  在缓存里找该 metric 最新值
    """

    LOSE_FRAMES = 3
    LOST_SEC = 10.0
    CACHE_SEC = 600      # 本地 ring buffer 至少 10 分钟

    def __init__(self, sim=True, device_map=None):
        self.sim = sim
        self.device_map = device_map or {}   # channel -> pyserial.Serial
        self._ports = {}
        self._latest = {}
        self._last_seen = {}
        self._miss = {}
        self._quality = {}
        self._cache = {c: deque(maxlen=self.CACHE_SEC) for c in CHANNELS}
        self._pending_tx = {c: [] for c in CHANNELS}
        self._lock = threading.Lock()
        self._threads = []
        self._stop_evt = threading.Event()

    def start(self, demo_mode=False):
        self._demo_mode = demo_mode
        for key in CHANNELS:
            if self.sim:
                self._ports[key] = _SimPort(key)
            else:
                self._ports[key] = self.device_map.get(key)
            self._latest[key] = None
            self._last_seen[key] = time.time()
            self._miss[key] = 0
            self._quality[key] = "ok"
            t = threading.Thread(target=self._pump, args=(key,), daemon=True)
            t.start()
            self._threads.append(t)
        return self

    def stop(self):
        self._stop_evt.set()
        for t in self._threads:
            t.join(timeout=1.0)

    def _pump(self, key):
        hz = CHANNELS[key]["hz"]
        interval = 1.0 / max(1, hz)
        while not self._stop_evt.is_set():
            # demo 模式下由 _inject_metrics 控制帧内容，pump 只更新质量状态，
            # 不再生成默认帧，避免与注入值竞争
            if getattr(self, "_demo_mode", False):
                frame = None
                with self._lock:
                    self._quality[key] = "ok"
                self._stop_evt.wait(interval)
                continue
            frame = self._ports[key].read_frame() if self._ports[key] else None
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
            self._stop_evt.wait(interval)

    def read(self, channel):
        with self._lock:
            f = dict(self._latest.get(channel) or {})
            f["quality"] = self._quality.get(channel, "unknown")
            return f

    def read_all(self):
        return {k: self.read(k) for k in CHANNELS}

    def latest_value(self, channel, metric, default=None):
        with self._lock:
            cache = list(self._cache[channel])[-60:]
        val = default
        for fr in cache:
            if fr and fr.get("metric") == metric:
                val = fr.get("value", default)
        return val

    def cmd(self, channel, payload):
        with self._lock:
            if self._quality.get(channel) == "lost":
                self._pending_tx[channel].append(payload)
                return {"channel": channel, "cmd": payload, "ok": False,
                        "reason": "link_lost_queued"}
        if self._ports.get(channel):
            return self._ports[channel].write_cmd(payload)
        return {"channel": channel, "cmd": payload, "ok": True}

    def flush_pending(self, channel):
        with self._lock:
            items = list(self._pending_tx[channel])
            self._pending_tx[channel].clear()
        for it in items:
            self.cmd(channel, it)
        return len(items)


class _SimPort:
    """模拟一路串口：按 metric 轮转生成规范帧，供桌面开发/单测。"""

    def __init__(self, key):
        self.key = key
        self._seq = 0
        self._idx = 0
        self._metrics = CHANNELS[key]["metrics"]

    def read_frame(self):
        m = self._metrics[self._idx % len(self._metrics)]
        self._idx += 1
        self._seq += 1
        return {
            **_norm_frame(self.key, m, DEFAULTS.get(m, 0)),
            "seq": self._seq,
            "raw": "%04x %02x" % (self._seq & 0xFFFF, self._seq & 0xFF),
        }

    def write_cmd(self, payload):
        return {"channel": self.key, "cmd": payload, "ok": True, "sim": True}


def open_serial(channel, device_path, baud):
    """真实机载：用 pyserial 打开一路串口。示例：
        io = SerialIO(sim=False, device_map={"uart1": open_serial("uart1", "/dev/ttyS0", 115200)})
    真实实现读帧时把 _pump 里的 read_frame 换成 serial.readline + 解析。
    """
    import serial
    s = serial.Serial(device_path, baud, timeout=0.5)
    return s

