# -*- coding: utf-8 -*-
"""
smooth.py — 指令平滑 / 斜率限制器（补强：避免指令突变导致机臂抖）
====================================================================
decision/cruise/obstacle 合成的飞控指令（dx/dy/dz/dvyaw/throttle_delta）
若逐周期突变，会令机臂抖动、能耗上升、甚至诱发振荡。
本模块对指令做"一阶斜率限制 + 低通"：

  - RateLimiter   单轴：限制每周期变化量不超过 max_step
  - CmdSmoother   对 5 个控制量统一做斜率限制 + 可选一阶低通
  - 致命模式（PROTECT）下放宽斜率限制（允许快速动作），普通模式收紧

零依赖、O(1)，机载可跑。
"""


class _AxisSmoother:
    def __init__(self, max_step, lp=0.0):
        self.max_step = max_step
        self.lp = max(0.0, min(1.0, lp))   # 低通系数 0=纯斜率限制
        self.last = None

    def apply(self, target):
        if self.last is None:
            self.last = target
            return target
        step = target - self.last
        if abs(step) > self.max_step:
            step = self.max_step if step > 0 else -self.max_step
        out = self.last + step
        if self.lp > 0:
            out = self.last + self.lp * (out - self.last)
        self.last = out
        return out

    def reset(self):
        self.last = None


class CmdSmoother:
    """对飞控指令 dict 做平滑。
    参数：
      max_step_hv   水平速度单周期最大变化 (m/s)
      max_step_dz   升降单周期最大变化 (m/s)
      max_step_yaw  偏航角速度单周期最大变化 (deg/s)
      max_step_thr  油门增量单周期最大变化
      lp            额外一阶低通系数（0~1，0 关闭）
      fast_mode     True=致命模式（放宽 3 倍斜率，允许快速保机动作）
    """

    def __init__(self,
                 max_step_hv=1.5, max_step_dz=0.5,
                 max_step_yaw=10.0, max_step_thr=0.15,
                 lp=0.3):
        self.fast_mult = 3.0
        self.max_step_hv = max_step_hv
        self.max_step_dz = max_step_dz
        self.max_step_yaw = max_step_yaw
        self.max_step_thr = max_step_thr
        self.lp = lp
        self._ax = {}

    def _get(self, key, step):
        a = self._ax.get(key)
        if a is None:
            a = _AxisSmoother(step, self.lp)
            self._ax[key] = a
        return a

    def apply(self, cmd, fast_mode=False):
        """cmd: {dx,dy,dz,dvyaw,throttle_delta,...} -> 平滑后的 dict（不改动原 dict）"""
        mult = self.fast_mult if fast_mode else 1.0
        out = dict(cmd)
        for k, step in (
            ("dx", self.max_step_hv * mult),
            ("dy", self.max_step_hv * mult),
            ("dz", self.max_step_dz * mult),
            ("dvyaw", self.max_step_yaw * mult),
            ("throttle_delta", self.max_step_thr * mult),
        ):
            v = cmd.get(k, 0.0)
            if not isinstance(v, (int, float)):
                continue
            out[k] = self._get(k, step).apply(v)
        return out

    def reset(self):
        for a in self._ax.values():
            a.reset()
