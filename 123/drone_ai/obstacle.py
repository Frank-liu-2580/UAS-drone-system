# -*- coding: utf-8 -*-
"""
obstacle.py — 自动避障（修复版）
================================
输入：
  - obstacle_dist        障碍距离 (m)
  - obstacle_bearing_deg 障碍方位角 (deg, 0=正前方, 正=偏右, 负=偏左)
  - gimbal_pitch         云台俯仰（仅用于判断障碍上下位置，不再决定左右）

输出：{"action": "none|turn|evasive|abort|hold",
       "dvyaw": float, "throttle_delta": float, "dz": float, "reason": str}

修复要点：
  - 转向方向由 obstacle_bearing_deg 决定（方位角为负=障碍偏左 -> 右转绕开，
    方位角为正=障碍偏右 -> 左转绕开）。
  - 若无方位角数据（bearing 缺失），只做"急停 + 悬停"（action="hold"），
    不再盲猜左右。
  - gimbal_pitch 不再参与转向决策。
"""
import thresholds as T

# 方位角缺失时只做悬停，不盲转
def avoid_obstacle(dist_m, bearing_deg, gimbal_pitch_deg=0.0):
    """返回指令 dict。bearing_deg=None 表示雷达未提供方位角。"""
    if dist_m is None:
        return {"action": "none", "dvyaw": 0.0, "throttle_delta": 0.0,
                "dz": 0.0, "reason": "no_obstacle_data"}

    if dist_m >= T.OBSTACLE_CLOSE_M:
        return {"action": "none", "dvyaw": 0.0, "throttle_delta": 0.0,
                "dz": 0.0, "reason": f"obstacle_far({dist_m:.1f}m>={T.OBSTACLE_CLOSE_M}m)"}

    # 方位角缺失 -> 安全策略：悬停 + 减速，不盲转
    if bearing_deg is None:
        if dist_m < 1.0:
            return {"action": "abort", "dvyaw": 0.0, "throttle_delta": -1.0,
                    "dz": 0.0, "reason": f"obstacle_crit_no_bearing({dist_m:.1f}m)"}
        return {"action": "hold", "dvyaw": 0.0, "throttle_delta": -0.5,
                "dz": 0.0, "reason": f"obstacle_hold_no_bearing({dist_m:.1f}m)"}

    # 有方位角：根据 bearing 决定绕向
    # bearing > 0: 障碍在机头右方 -> 左转 (dvyaw < 0)
    # bearing < 0: 障碍在机头左方 -> 右转 (dvyaw > 0)
    # |bearing| < FRONT_CONE（正前方锥角）：正面迎头障碍无法靠偏航绕过，
    # 显式采用"悬停 + 减速"策略（不再让 bearing==0 落到右转分支）。
    FRONT_CONE_DEG = T.OBSTACLE_FRONT_CONE_DEG
    if dist_m >= 3.0:
        # 中等距离：缓绕
        if abs(bearing_deg) < FRONT_CONE_DEG:
            return {"action": "hold", "dvyaw": 0.0, "throttle_delta": -0.6,
                    "dz": 0.0, "reason": f"obstacle_front_hold(dist={dist_m:.1f}m)"}
        dvyaw = -15.0 if bearing_deg > 0 else 15.0
        return {"action": "turn", "dvyaw": dvyaw, "throttle_delta": 0.1,
                "dz": 0.0, "reason": f"obstacle_turn(bearing={bearing_deg:.0f}°,dist={dist_m:.1f}m)"}

    if dist_m >= 1.0:
        # 近距离：急绕 + 减速
        if abs(bearing_deg) < FRONT_CONE_DEG:
            return {"action": "hold", "dvyaw": 0.0, "throttle_delta": -0.6,
                    "dz": 0.0, "reason": f"obstacle_front_hold(dist={dist_m:.1f}m)"}
        dvyaw = -30.0 if bearing_deg > 0 else 30.0
        return {"action": "evasive", "dvyaw": dvyaw, "throttle_delta": -0.5,
                "dz": 0.0, "reason": f"obstacle_evasive(bearing={bearing_deg:.0f}°,dist={dist_m:.1f}m)"}

    # < 1m：急停
    return {"action": "abort", "dvyaw": 0.0, "throttle_delta": -1.0,
            "dz": 0.0, "reason": f"obstacle_abort(bearing={bearing_deg:.0f}°,dist={dist_m:.1f}m)"}
