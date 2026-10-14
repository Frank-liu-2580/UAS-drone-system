# -*- coding: utf-8 -*-
"""
sensing.py — 传感器数据滤波层（补强：现实传感器有噪声/跳变/丢帧）
====================================================================
机载 5 路串口的原始 metric 直接进决策会被噪声/单帧跳变误导。
本模块提供轻量、零依赖（纯 Python）、机载可跑的滤波：

  - ExponentialFilter   指数滑动（一阶低通），适合慢变量（电池/温度/RSSI）
  - MedianGate          中值门控，抑制单帧尖峰（脉冲噪声）
  - Kalman1D            一维标量卡尔曼，适合匀速/匀加速量（位置/速度）
  - SensorBank          按 metric 类型自动选滤波器，暴露统一的 read()

设计原则：
  - 全部 O(1) 内存 / 常数次运算，可放在 RPi/Jetson 跑
  - 首帧/复位时直接透传最新值（不引入稳态误差积累）
  - 陈旧/丢链帧由调用方 trigger.read_metrics_from_io 的时效闸门处理，
    本模块只负责"新鲜值里的噪声整形"
"""
from collections import deque
import math


class ExponentialFilter:
    """一阶低通：y += alpha*(x-y)。alpha=1/(N) 约对应 N 秒时间常数。"""

    def __init__(self, alpha=0.2):
        self.alpha = max(0.01, min(1.0, alpha))
        self.y = None

    def update(self, x):
        if self.y is None:
            self.y = x
        else:
            self.y = self.y + self.alpha * (x - self.y)
        return self.y

    def reset(self):
        self.y = None


class MedianGate:
    """中值门控：取最近 W 帧中值作粗滤，再与最新帧比对，
    若最新帧偏离中值超过 k*MAD 倍则判定为尖峰，输出中值。"""

    def __init__(self, window=5, k=3.0):
        self.win = deque(maxlen=max(3, window))
        self.k = k

    def _median(self):
        s = sorted(self.win)
        return s[len(s) // 2]

    def _mad(self):
        med = self._median()
        devs = [abs(v - med) for v in self.win]
        devs.sort()
        return devs[len(devs) // 2]

    def update(self, x):
        self.win.append(x)
        med = self._median()
        mad = self._mad()
        if mad > 1e-9 and abs(x - med) > self.k * mad:
            return med          # 尖峰 -> 用中值兜
        return x

    def reset(self):
        self.win.clear()


class Kalman1D:
    """一维恒定速度模型的标量卡尔曼（状态 [x, v]，观测 x）。
    对位置/速度这类匀速量比纯低通响应更快且稳。
    参数简化为固定 Q/R（机载够用，不做完整 EKF）。"""

    def __init__(self, q=0.5, r=1.0):
        self.q, self.r = q, r
        self.x = None
        self.v = 0.0
        self.p = 1.0

    def update(self, z):
        if self.x is None:
            self.x = z
            return z
        # predict
        self.p += self.q
        # update
        s = self.p + self.r
        k = self.p / s
        # 观测残差隐含在当前 z 与预测 x 之间（一维简化）
        self.x = self.x + k * (z - self.x)
        self.p = (1 - k) * self.p
        self.v = 0.5 * (z - self.x)
        return self.x

    def reset(self):
        self.x = None
        self.v = 0.0
        self.p = 1.0


# metric -> 滤波器类型 的配置（按物理特性）
#   slow  = 慢变量，用指数低通
#   gate  = 易出尖峰的布尔/脉冲量，中值门控
#   kalman= 匀速连续量（位置/速度）
_METRIC_FILTER = {
    "battery_v": ("slow", 0.15),
    "battery_pct": ("slow", 0.15),
    "battery_temp": ("slow", 0.2),
    "esc_temp": ("slow", 0.2),
    "esc_current": ("gate", None),
    "link_rssi": ("slow", 0.2),
    "wind_speed": ("slow", 0.25),
    "temp_c": ("slow", 0.1),
    "humidity": ("slow", 0.1),
    "pressure": ("slow", 0.05),
    "visibility": ("slow", 0.25),
    "position": ("kalman", None),
    "speed": ("kalman", None),
    "obstacle_dist": ("gate", None),
    "hdop": ("slow", 0.3),
}


class SensorBank:
    """对 trigger 读出的 metric 字典做一层滤波整形。
    用法：
        bank = SensorBank()
        raw = trigger.read_metrics_from_io(io, stale_sec=...)
        clean = bank.update(raw)   # 返回同结构 dict，值已整形
    未配置的 metric 原样透传（安全）。"""

    def __init__(self):
        self._filters = {}

    def _filter_for(self, metric, kind, param):
        f = self._filters.get(metric)
        if f is None:
            if kind == "slow":
                f = ExponentialFilter(alpha=param)
            elif kind == "gate":
                f = MedianGate(window=5, k=3.0)
            elif kind == "kalman":
                f = Kalman1D()
            else:
                f = None
            self._filters[metric] = f
        return f

    @staticmethod
    def _is_num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    def update(self, raw):
        out = dict(raw)
        for m, v in raw.items():
            cfg = _METRIC_FILTER.get(m)
            if not cfg or not self._is_num(v):
                continue          # 未配置 / 非数值（如 position 列表、bool）-> 透传
            kind, param = cfg
            f = self._filter_for(m, kind, param)
            if f is not None:
                out[m] = f.update(v)
        return out

    def reset(self):
        for f in self._filters.values():
            if f:
                f.reset()


def make_bank():
    return SensorBank()
