# -*- coding: utf-8 -*-
"""
cruise.py — 定点 / 定速 巡航控制器
==================================
两种巡航模式：
  1) 定点 (position hold)：偏离 > CRUISE_POS_HOLD_TOL_M 触发纠偏
  2) 定速 (speed track)  ：速度偏差 > CRUISE_SPEED_TOL_MPS 触发调速

实现：PID 控制器 + 偏航角限幅（CRUISE_YAW_RATE_MAX deg/s）。
输出：给飞控的增量指令 {dx, dy, dz, dvyaw, throttle_delta}
"""
import math

import thresholds as T


class CruiseController:
    def __init__(self):
        self._pos_err_int = 0.0
        self._pos_err_last = 0.0
        self._spd_err_int = 0.0
        self._spd_err_last = 0.0

    def reset(self):
        self._pos_err_int = 0.0
        self._pos_err_last = 0.0
        self._spd_err_int = 0.0
        self._spd_err_last = 0.0

    def position_hold(self, target_xyz, current_xyz, dt):
        """定点：返回 {dx, dy, dz} 的纠偏位移指令。"""
        ex = target_xyz[0] - current_xyz[0]
        ey = target_xyz[1] - current_xyz[1]
        ez = target_xyz[2] - current_xyz[2]
        err = math.hypot(ex, ey, ez)
        if err < T.CRUISE_POS_HOLD_TOL_M:
            return {"dx": 0.0, "dy": 0.0, "dz": 0.0, "hold": True}

        self._pos_err_int += err * dt
        self._pos_err_int = min(self._pos_err_int, 5.0)
        de = err - self._pos_err_last
        self._pos_err_last = err

        kp, ki, kd = T.CRUISE_POS_KP, T.CRUISE_POS_KI, T.CRUISE_POS_KD
        cmd = kp * err + ki * self._pos_err_int + kd * de
        cmd = min(cmd, 2.0)   # 限幅：单次最大 2m 纠偏
        k = cmd / max(err, 1e-6)
        return {"dx": ex * k, "dy": ey * k, "dz": ez * k, "hold": False}

    def speed_track(self, target_mps, current_mps, dt):
        """定速：返回 throttle_delta（-1.0 ~ 1.0 的增量油门归一化）。"""
        err = target_mps - current_mps
        if abs(err) < T.CRUISE_SPEED_TOL_MPS:
            return {"throttle_delta": 0.0, "cruise": True}
        self._spd_err_int += err * dt
        self._spd_err_int = min(self._spd_err_int, 1.0)
        de = err - self._spd_err_last
        self._spd_err_last = err
        kp, ki, kd = T.CRUISE_SPEED_KP, T.CRUISE_SPEED_KI, T.CRUISE_SPEED_KD
        out = kp * err + ki * self._spd_err_int + kd * de
        out = max(-1.0, min(1.0, out))
        return {"throttle_delta": out, "cruise": False}

    def yaw_step(self, target_yaw_deg, current_yaw_deg, dt):
        """偏航角限幅：单次不超过 CRUISE_YAW_RATE_MAX * dt。"""
        err = ((target_yaw_deg - current_yaw_deg + 540) % 360) - 180
        max_step = T.CRUISE_YAW_RATE_MAX * dt
        step = max(-max_step, min(max_step, err))
        return {"dvyaw": step, "yaw_err": err}
