# -*- coding: utf-8 -*-
"""
route.py — 路线判断 + 避障几何（路线/避障/行为动作 用 drone_ai 算法）
=====================================================================
把无人机"往哪飞"从模拟器写死线性漂移，升级为算法驱动的路线判断：

  1) 多 waypoint 航线：RoutePlanner 持有 [home, wp1..wpN, home]，
     next_waypoint() 判断该飞向哪个点（路线判断 = 选下一航点）。
  2) 路线速度向量：route_velocity(cur, tgt, speed) 产出 NED 水平速度
     （m/s），交给 cruise.CruiseController / DroneAI 闭环积分。
  3) 避障几何：obstacle_bearing(cur, yaw_deg, obstacle) 把"障碍在哪"
     算成相对机头朝向的方位角（deg，0=正前方，正=偏右），喂给
     obstacle.avoid_obstacle 做绕行/急停（行为动作选定）。

零依赖、纯 Python、机载可跑。坐标系 NED（x=北, y=东, z=下为正）。
"""
import math

import thresholds as T


def _norm_yaw(a):
    """归一化到 (-180, 180]。"""
    return ((a + 180) % 360) - 180


class RoutePlanner:
    """多 waypoint 航线规划器：决定"接下来该飞向哪个点"（路线判断）。

    waypoints: [x, y, z] 列表（NED，米），不含 home。
    """

    def __init__(self, waypoints, home=(0.0, 0.0, 0.0)):
        self.home = home
        self.waypoints = [tuple(w) for w in waypoints]
        self.wp_index = 0        # 当前飞向的 waypoint 在 self.waypoints 的下标
        self.wp_reached = []     # 已到达 waypoint 记录（日志用）
        self.total_wp = len(self.waypoints)
        self._home_reached_at = None

    @property
    def in_return_phase(self):
        return self.wp_index >= self.total_wp

    @property
    def current_target(self):
        """当前要飞向的点（NED 列表）。未走完 waypoint -> wp[i]；走完 -> home。"""
        if self.wp_index < self.total_wp:
            return list(self.waypoints[self.wp_index])
        return list(self.home)

    def next_waypoint(self, cur, arrive_tol_m=None):
        """路线判断：若到当前目标点（NED 2D 距离 < tol）则推进 wp_index。
        cur: [x, y, z] NED。返回 (reached: bool, target, return_phase: bool)。"""
        if arrive_tol_m is None:
            arrive_tol_m = T.CRUISE_POS_HOLD_TOL_M * 5.0   # 航线用比定点宽松的到达门限
        target = self.current_target
        cx, cy = cur[0], cur[1]
        tx, ty = target[0], target[1]
        dist = math.hypot(cx - tx, cy - ty)
        if dist < arrive_tol_m:
            if self.wp_index < self.total_wp:
                self.wp_reached.append(self.waypoints[self.wp_index])
                self.wp_index += 1
            else:
                # 已回到家：记录（收尾）
                self._home_reached_at = cur
            target = self.current_target
            return (True, target, self.in_return_phase)
        return (False, target, self.in_return_phase)


def route_velocity(cur, target, speed_mps):
    """路线速度向量：从 cur 指向 target 的 NED 水平速度（m/s）。
    到达（<0.5m）返回 0 向量（悬停/切换下一点由 RoutePlanner 推进）。"""
    cx, cy = cur[0], cur[1]
    tx, ty = target[0], target[1]
    dx, dy = tx - cx, ty - cy
    d = math.hypot(dx, dy)
    dz = target[2] - cur[2]
    if d < 0.5:
        return [0.0, 0.0, 0.0 if abs(dz) < 0.5 else (1.0 if dz > 0 else -1.0)]
    scale = speed_mps / d
    return [dx * scale, dy * scale, max(-1.5, min(1.5, dz * 0.5))]


def obstacle_bearing(cur, yaw_deg, obstacle):
    """把"障碍在哪"算成相对机头朝向的方位角（deg）。
    cur/obstacle: [x, y, z] NED。yaw_deg: 机头朝向（0=北, 顺时针）。
    返回：0=障碍正前方，正=偏右，负=偏左；距离 < 0.5m 返回 (0.0, 0.0)（很近）。"""
    cx, cy = cur[0], cur[1]
    ox, oy = obstacle[0], obstacle[1]
    # NED 坐标：dx = ox-cx (北分量), dy = oy-cy (东分量)。
    # 目标约定：方位角 0°=正北，90°=正东，顺时针为正（与 yaw_deg 同口径）。
    # 在 (北,东) 平面上，北分量 x_n=dx、东分量 x_e=dy：
    #   atan2(x_e, x_n) 直接得到以 x_n 轴(北)为 0°、x_e 轴(东)为 90° 的角度，
    #   即约定方位角本身（正东=+90°、正北=0°、正西=-90°、正南=±180°）。
    bearing_to_obs = math.degrees(math.atan2(oy - cy, ox - cx))  # 北为 0, 东为 90, 顺时针
    rel = _norm_yaw(bearing_to_obs - yaw_deg)
    dist = math.hypot(ox - cx, oy - cy)
    return (rel, dist)


def default_waypoints(home=(0.0, 0.0, 0.0)):
    """默认 4 点矩形巡检航线（home 中心，边长 40m，巡航高度 20m）。
    NED 坐标（z 向下为正）：相对 home 上方 20m 的巡航点取 z = home_z - 20
    （z 更小 = 离地更高），起飞 home 点本身为 home。
    这样无人机从 home 爬到航线高度（dz 负 = 上升），飞完航线再回 home 着陆（dz 正 = 下降）。"""
    hx, hy, hz = home
    alt = 20.0
    span = 20.0
    cz = hz - alt   # NED: z 向下为正，巡航在 home 上方 20m = hz - 20（更小 z）
    return [
        [hx + span, hy + span, cz],
        [hx + span, hy - span, cz],
        [hx - span, hy - span, cz],
        [hx - span, hy + span, cz],
    ]
