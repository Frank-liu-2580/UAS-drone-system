# -*- coding: utf-8 -*-
"""
ai_main.py — 机载内置 AI 主程序（可被无人机/机载 SoC 导入运行）
==============================================================
数据流：
  串口(5路UART) -> 归一化JSON帧 -> trigger 命中异常 -> decision 选模式(P/T)
              -> cruise(定点/定速) + obstacle(避障) -> 指令 -> 写回串口

两模式
  PROTECT  保护无人机
  MISSION  完成任务
模式由 P/T 双值差自动选择，也可前端按钮强制。

用法
  from drone_ai.ai_main import DroneAI
  ai = DroneAI(transport="sim")
  ai.start()
  # 机载侧: 持续循环
  while not ai.stop_requested:
      ai.tick()
  # 或一次性演示
  ai.run_demo()
"""
import time
import threading
import os, sys

import serial_io, trigger, decision, cruise, obstacle as obstacle_mod
import sensing, smooth
import route as route_mod
import thresholds as T

# 让 drone_ai 包内的绝对导入在两种运行方式下都可用：
#   python drone_ai/ai_main.py      （把 drone_ai 目录加进 sys.path）
#   python -m drone_ai.ai_main      （作为包模块运行）
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


class DroneAI:
    # 无人机"自身事件"（内部机体/动力/飞控/电池/电调/桨/云台/载荷故障）。
    # 命中任一自身事件 -> 立即就近迫降 + 终止任务（不走返航 home、不停任务巡航）。
    # 区别于外部因素（雨/风/GPS/障碍/鸟/链路/打雷——那些走 RTB 返航，不终止任务）。
    # 白名单以 decision.SELF_ABORT_TYPES 为唯一来源（与决策层一致，2026-10-13）
    SELF_FAULT_TYPES = decision.SELF_ABORT_TYPES

    def __init__(self, transport="sim", device_map=None,
                 cruise_target=None, cruise_speed_mps=5.0,
                 route_waypoints=None, home=(0.0, 0.0, 0.0)):
        """
        transport: "sim" 仿真 / 传 device_map 走真实 pyserial
        cruise_target: 定点巡航目标 (lat, lon, alt) 或 (x, y, z)，None=不定点
        cruise_speed_mps: 定速巡航目标速度
        route_waypoints: 多 waypoint 航线 [[x,y,z],...]（NED）。传入后用
            route.RoutePlanner 做路线判断（飞向当前航点），替代单点定点；
            None 时退回 cruise_target 单点定点（向后兼容）。
        home: 起飞 home 点（NED），航线走完后 RTB 飞向此处。
        """
        self.io = serial_io.SerialIO(sim=(transport == "sim"),
                                     device_map=device_map)
        self.sel = decision.ModeSelector()
        self.cruise = cruise.CruiseController()
        # 补强：传感器滞波杠 + 指令平滑
        self.sens = sensing.make_bank()
        self.smoother = smooth.CmdSmoother(
            max_step_hv=T.CMD_MAX_HV_MPS * 0.15,
            max_step_dz=T.CMD_MAX_DZ_MPS * 0.4,
            max_step_yaw=T.CMD_MAX_DVYAW_DEG_S * 0.4,
            max_step_thr=0.15, lp=0.3)
        self.cruise_target = cruise_target
        self.cruise_speed_mps = cruise_speed_mps
        # 路线判断：多 waypoint 航线（用 drone_ai/route.py 算法，替代单点定点）
        self.route_waypoints = route_waypoints
        self._home_default = home
        self.route_planner = None
        if route_waypoints:
            self.route_planner = route_mod.RoutePlanner(
                route_waypoints, home=home)

        self.forced_mode = None          # 前端可强制 PROTECT/MISSION/None
        self.log = []                    # 本地决策日志
        self._stop_evt = threading.Event()
        self._running = False
        # P1-5: 链路/导航失效悬停等待计时（now_ms），链路恢复时清 0
        self._failsafe_hover_ts = None
        # ---- 自身事件 -> 任务终止状态（命中即 True，模拟器据此停止）----
        self.task_aborted = False        # 一旦 True，模拟器应停止任务
        self.task_abort_reason = None    # 触发终止的自身事件类型
        self.task_abort_ts = None        # 终止发生的模拟时刻（ms）

    # ---------- 生命周期 ----------
    def start(self, home=None, yaw=0.0):
        """home: 起飞时传入 (lat, lon, alt)，RTB 用它算水平速度向量。
        yaw: 机头朝向（deg，0=北顺时针），避障几何算方位角用；默认 0。
        若传 home 且 route_planner 在构造时用了默认 home，这里同步航线 home。"""
        self.io.start(demo_mode=True)
        self.home = home if home is not None else self._home_default
        if self.route_planner is not None and home is not None:
            self.route_planner.home = tuple(home)
        self.yaw = yaw
        self._last_tick_ts = None   # 用于算真实 dt
        self._rtb_active = False
        self._running = True
        # 每次新任务重置自身事件终止标志
        self.task_aborted = False
        self.task_abort_reason = None
        self.task_abort_ts = None
        return self

    def stop(self):
        self._stop_evt.set()
        self._running = False
        self.io.stop()

    # ---------- 前端可调用 ----------
    def set_forced_mode(self, mode):
        """前端模式按钮：PROTECT / MISSION / None(自动)。"""
        if mode in (None, "PROTECT", "MISSION"):
            self.forced_mode = mode

    def record_home(self, home):
        """起飞成功后调用：记录 home 点，RTB 时用它算水平速度向量。"""
        self.home = home

    # ---------- 核心：读串口 -> 决策 -> 写串口 ----------
    def tick(self):
        """单次决策循环。机载主程序每控制周期调用一次。
        返回指令 dict，同时已通过 io.cmd 写到对应串口。"""
        now_ms = int(time.time() * 1000)
        # 真实 dt（修复：不再硬编码 0.05，避免调度抖动导致积分项突变）
        if self._last_tick_ts is None:
            dt = 0.05
        else:
            dt = max(0.001, (now_ms - self._last_tick_ts) / 1000.0)
        self._last_tick_ts = now_ms

        # 1) 归一化 metric 值（含时效闸门：陈旧/丢链帧不进决策）
        raw_metrics = trigger.read_metrics_from_io(self.io, stale_sec=T.STALE_FRAME_SEC)
        metrics = self.sens.update(raw_metrics)   # 补强：噪声形整
        fresh = trigger.is_fresh(self.io, stale_sec=T.STALE_FRAME_SEC)
        # 关键通道丢链 -> 不信任位置/速度，切到安全悬停，不用陈旧坐标纠偏
        nav_lost = not fresh.get("uart1", False)

        # 2) 命中异常
        hits = trigger.detect(metrics)

        # 3) 选模式（多异常叠加：所有命中异常参与定模式，保机取严）
        if self.forced_mode:
            mode = self.forced_mode
        elif not hits:
            mode = "CRUISE"
        else:
            pt_map = {a: self.sel.pt_for(a) for a in {h[0] for h in hits}}
            mode = decision.combined_mode(list(pt_map.keys()), pt_map)

        # 4) 出动作
        if hits:
            atype = decision.worst_anomaly(hits, decision._SEV)
            action, target = self.sel.action_for(atype, mode)
        else:
            atype, action, target = "none", "维持常规巡航", "Shadow_AI"
        # 异常类型切换（含恢复）时重置指令滑平器：
        # 新妃况情的指令是全新意图，不应被上一异常的残留压住
        if atype != getattr(self, "_last_atype", None):
            self.smoother.reset()
            self._last_atype = atype

        # 致命异常进入时清 PID 积分（修复：避免上一状态残留）
        fatal_now = atype in ("motor_failure","prop_break","flight_ctrl",
                              "lightning","battery_issue")
        if fatal_now and not self._rtb_active:
            self.cruise.reset()
            self._rtb_active = True
        elif not fatal_now:
            self._rtb_active = False
        # 注：battery_issue 属致命异常（低电），此处仍清 PID 积分；
        # 但它已移出 SELF_ABORT_TYPES，不会走 5.5 的强制迫降终止分支（P0-4）

        # 5) 叠加巡航 + 避障 + RTB
        cmd = self._build_command(mode, metrics, atype, dt, nav_lost, fatal_now)
        cmd.update({"mode": mode, "anomaly": atype, "action": action,
                    "target": target, "reasons": [r[2] for r in hits],
                    "dt": round(dt,4), "nav_lost": nav_lost})

        # 5.5) 无人机自身事件 -> 立即就近迫降 + 终止任务
        # 内部机体/动力/飞控/桨/云台/载荷故障：
        #   不走返航 home、不做任务巡航，直接强下降迫降并标记任务终止。
        # P0-4：battery_issue 已移出 SELF_ABORT_TYPES，低电不再命中本分支，
        #   改走 _apply_rtb 的 enroute_home 返航、电量到线才 force_land。
        # 触发：决策层已判 mode=FORCE_LAND，或 atype 命中自身事件白名单（双保险）
        if (mode == "FORCE_LAND" or atype in self.SELF_FAULT_TYPES) \
                and not self.task_aborted:
            self._force_land_abort(cmd, metrics, atype, now_ms)
            mode = "FORCE_LAND"   # 上报/记账统一为终止模式

        # 6) 指令平滑（补强：斜率限制 + 一阶低通，防机腰抖）
        #    致命模式放宽 3 倍斜率，允许快速保机动作
        cmd = self.smoother.apply(
            cmd, fast_mode=(mode in ("PROTECT", "RTB", "FORCE_LAND")))
        # 7) 指令白名单限幅（修复：量纲钳位，超限记录）
        cmd = self._clamp_cmd(cmd)

        # 7) 写回对应串口
        self._emit(cmd)

        # 8) 记日志
        self.log.append({"ts": now_ms, "mode": mode,
                         "anomaly": atype, "cmd": cmd})
        return cmd

    def _force_land_abort(self, cmd, metrics, atype, now_ms):
        """无人机自身事件（内部故障）：立即就近迫降 + 终止任务。
        覆盖 _build_command 已合成的指令：
          - 水平速度收敛（不冲 home，就近稳着落）
          - 强下降（RTB_DESCENT_MPS × 1.5，比低电迫降更快）
          - 油门收敛（防动力故障后油门拉高恶化）
          - task_aborted=True + 记录原因/时刻，供模拟器终止飞行
        """
        cur = metrics.get("position")
        # 1) 水平：有定位就缓慢减速归零（避免侧翻），无定位就近
        if cur:
            # 就近慢速降落：水平速度压到 0.5 m/s（稳着落）
            cmd["dx"] = 0.0
            cmd["dy"] = 0.0
        else:
            cmd["dx"] = 0.0
            cmd["dy"] = 0.0
        # 2) 垂直：强下降迫降
        cmd["dz"] = T.RTB_DESCENT_MPS * 1.5
        # 3) 偏航：收敛
        cmd["dvyaw"] = 0.0
        # 清掉 _build_command 可能先写下的 RTB/模式残留字段，避免误导
        for _stale in ("rtb", "mode_action", "obstacle_action", "obstacle_reason"):
            cmd.pop(_stale, None)
        # 4) 油门：收敛（动力/电调故障时避免拉高油门）
        cmd["throttle_delta"] = -0.3
        # 5) 标记（终止模式写回 cmd，覆盖 _build_command 先前写下的常规 mode）
        cmd["mode"] = "FORCE_LAND"
        cmd["force_land"] = "self_fault_force_land"
        cmd["task_aborted"] = True
        self.task_aborted = True
        self.task_abort_reason = atype
        self.task_abort_ts = now_ms

    def _build_command(self, mode, metrics, atype, dt, nav_lost, fatal_now):
        """把巡航控制器 + 避障器 + RTB + 模式动作合成一组飞控指令。
        坐标系：NED（x=北, y=东, z=下为正），速度 m/s，偏航角速度 deg/s，
        油门增量归一化 [-1,1]。所有指令最终经 _clamp_cmd 限幅。"""
        cmd = {"dx": 0.0, "dy": 0.0, "dz": 0.0, "dvyaw": 0.0,
               "throttle_delta": 0.0}

        # --- 链路/导航失效 failsafe（P1-5：独立于 P/T 竞争）---
        # 通信/导航失效命中且 mode==CRUISE：悬停等待链路恢复，绝不放行零指令
        if decision.is_failsafe_hover(atype, mode):
            # 悬停：水平/偏航收敛，轻微降低油门保持悬停稳定
            cmd["dx"] = 0.0
            cmd["dy"] = 0.0
            cmd["dvyaw"] = 0.0
            cmd["throttle_delta"] = -0.2
            cmd["failsafe"] = "hover_wait"
            # 超时后转 RTB：悬停累计超过 FAILSAFE_HOVER_MAX_S 仍未恢复
            now_ms = int(time.time() * 1000)
            hover_ts = getattr(self, "_failsafe_hover_ts", None)
            if hover_ts is None:
                self._failsafe_hover_ts = now_ms
                hover_ts = now_ms
            if (now_ms - hover_ts) / 1000.0 > decision.FAILSAFE_HOVER_MAX_S:
                self._failsafe_hover_ts = None
                cmd["failsafe"] = "rtb_timeout"
                P, _T, _src, _wp, _wd, _neff = self.sel.pt_for(atype)
                self._apply_rtb(cmd, metrics, atype, protect_strength=P)
                return cmd
            return cmd
        # 链路恢复（非 failsafe 类型或异常消失）时清掉悬停计时
        if getattr(self, "_failsafe_hover_ts", None) is not None and \
                not decision.is_failsafe_hover(atype, mode):
            self._failsafe_hover_ts = None

        # --- RTB（真实水平速度向量 + 下降率 + 定高降落，不是字符串）---
        # 白名单驱动（decision.RTB_TYPES，含 rain/wind_gust/battery_issue/signal_loss/
        # gps_drift...），单一真值来源 should_rtb，P0-3 修复后与矩阵口径一致
        if decision.should_rtb(atype, mode):
            P, _T, _src, _wp, _wd, _neff = self.sel.pt_for(atype)
            self._apply_rtb(cmd, metrics, atype, protect_strength=P)
            return cmd

        # --- 路线判断 / 定点 / 定速 巡航（致命异常或导航丢失时停用）---
        # 路线判断优先级：route_planner（多 waypoint 航线，route.py 算法）>
        #   cruise_target（单点定点）> 无目标（纯定速巡航）。
        if not fatal_now and not nav_lost and (
                self.route_planner is not None or self.cruise_target is not None):
            cur = metrics.get("position", [0, 0, 0])
            if self.route_planner is not None:
                # 路线判断：选当前该飞的航点（路线判断 = 选下一航点，route.py 算法）
                _reached, target, _ret = self.route_planner.next_waypoint(cur)
                # 用 route.py 的航线速度向量作为巡航目标速度（替代单点定点纠偏）
                v = route_mod.route_velocity(cur, target, self.cruise_speed_mps)
                # 把航线速度叠加到水平指令；到达航点由 next_waypoint 推进 wp_index
                cmd["dx"] = v[0]
                cmd["dy"] = v[1]
                cmd["dz"] = v[2]
                cmd["route_wp"] = (self.route_planner.wp_index - 1
                                   if _reached else self.route_planner.wp_index)
                cmd["route_return"] = _ret
                if _reached:
                    cmd["route_event"] = (
                        "wp_%d_reached" % self.route_planner.wp_index
                        if self.route_planner.wp_index < self.route_planner.total_wp
                        else "home_reached")
            else:
                hold = self.cruise.position_hold(self.cruise_target, cur, dt)
                cmd["dx"], cmd["dy"], cmd["dz"] = hold["dx"], hold["dy"], hold["dz"]
            spd = self.cruise.speed_track(self.cruise_speed_mps,
                                          metrics.get("speed", 0.0), dt)
            cmd["throttle_delta"] = spd["throttle_delta"]

        # --- 自动避障（修复：用方位角 bearing，不用云台俯仰猜左右）---
        # 避障几何：若 metric 未直接提供方位角（obstacle_bearing_deg=None）但
        # 提供了障碍位置 obstacle_pos（NED [x,y,z]），用 route.obstacle_bearing
        # 从无人机当前位置 + 机头朝向算出方位角，再交给 obstacle.avoid_obstacle。
        ob_dist = metrics.get("obstacle_dist")
        ob_bearing = metrics.get("obstacle_bearing_deg")
        ob_pos = metrics.get("obstacle_pos")
        if ob_bearing is None and ob_pos is not None:
            cur_nav = metrics.get("position", [0, 0, 0])
            ob_bearing, geo_dist = route_mod.obstacle_bearing(
                cur_nav, getattr(self, "yaw", 0.0), ob_pos)
            if ob_dist is None:
                ob_dist = geo_dist
        obs = obstacle_mod.avoid_obstacle(
            ob_dist,
            ob_bearing,
            metrics.get("gimbal_pitch", 0.0))
        if obs["action"] in ("turn", "evasive", "abort", "hold"):
            cmd["dvyaw"] = obs["dvyaw"]
            cmd["throttle_delta"] = obs["throttle_delta"]
            cmd["dz"] = obs.get("dz", 0.0)
            cmd["obstacle_action"] = obs["action"]
            cmd["obstacle_reason"] = obs["reason"]
        # 避障产生的偏航更新机头朝向（机载闭环：转向后下次算方位角用新机头向）
        self.yaw = (getattr(self, "yaw", 0.0) + obs["dvyaw"] * dt) % 360

        # --- 模式级动作叠加（雨/打雷降级；wind_gust 已由 RTB 白名单覆盖，见 P0-3）---
        # P0-3 说明：rain / wind_gust 现已在 decision.RTB_TYPES，上面 should_rtb 分支
        # 会提前 return，因此这里只保留 lightning 的"升高离雷曲"修饰（lightning 不在
        # RTB_TYPES 白名单，仍走普通模式 + 爬升）；rain 的爬升在 RTB 前已被覆盖，
        # 故删除原 rain/wind_gust 死分支，避免与返航指令冲突。
        if atype == "lightning" and mode in ("PROTECT", "RTB"):
            # 打雷：离开雷曲线 + 升到安全高度 + 限机动
            cmd["dz"] = max(cmd.get("dz", 0.0), 3.0)   # 升高离雷曲（NED z 负=上升）
            cmd["mode_action"] = "avoid_thunderstorm"

        # --- 零指令不变式（P0-3 强烈推荐的防同类复发兜底）---
        # 17 类中除 unknown / crash_general（纯观察类）外，任何异常都应产生
        # 可执行动作；若五指令全零且无动作标签，保守悬停减速，绝不放行零指令。
        _ACT_MUST_TYPES = frozenset({
            "motor_failure", "flight_ctrl", "battery_issue", "prop_break",
            "esc_fault", "gimbal_fault", "payload_fault", "signal_loss",
            "gps_drift", "wind_gust", "rain", "dust_fog", "cold_hot",
            "bird", "obstacle", "lightning",
        })
        five = ("dx", "dy", "dz", "dvyaw", "throttle_delta")
        if atype in _ACT_MUST_TYPES \
                and not any(abs(cmd.get(k, 0.0)) > 1e-6 for k in five) \
                and not any(cmd.get(k) for k in ("rtb", "mode_action",
                                                    "obstacle_action", "failsafe")):
            # 保守兑底：悬停减速，绝不放行零指令
            cmd["conservative_hold"] = True
            cmd["throttle_delta"] = -0.2
            cmd["mode_action"] = cmd.get("mode_action") or "conservative_hold"
        return cmd

    def _apply_rtb(self, cmd, metrics, atype, protect_strength=0.5):
        """RTB 真实指令：算往 home 点的水平速度向量 + 下降率 + 末段定高降落。
        home 未记录或定位丢失时退化为“悬停 + 就近降”，绝不悬停到掉电。"""
        cur = metrics.get("position")          # NED [x=北, y=东, z=下]
        home = self.home
        if not cur or not home:
            # 无 home 或无定位：就近降（安全，但记日志提醒）
            cmd["dz"] = T.RTB_DESCENT_MPS      # 下降
            cmd["throttle_delta"] = -0.2
            cmd["rtb"] = "land_near_no_home" if not home else "land_near_no_gps"
            return
        hx, hy, hz = home
        cx, cy, cz = cur
        dx_home = hx - cx
        dy_home = hy - cy
        dist = (dx_home*dx_home + dy_home*dy_home) ** 0.5
        # P 联动：保机意图强（P高）时降速至 50%，更稳
        speed_scale = 1.0 - 0.5 * max(0.0, min(1.0, protect_strength - 0.3))
        speed = T.RTB_SPEED_MPS * max(0.5, speed_scale)
        if dist > 1.0:
            # 水平飞向 home（NED 速度指令，m/s）
            cmd["dx"] = dx_home / dist * speed
            cmd["dy"] = dy_home / dist * speed
            cmd["rtb"] = "enroute_home"
            if cz < hz:          # 高于 home，下降
                cmd["dz"] = T.RTB_DESCENT_MPS
        else:
            # 末段：水平 1m 内 -> 定高 + 垂直降落
            cmd["dx"] = cmd["dy"] = 0.0
            cmd["dz"] = T.RTB_DESCENT_MPS
            cmd["rtb"] = "descend_and_land"
        # 若低电且电量已到迫降线，加速下降
        if atype == "battery_issue" and \
                metrics.get("battery_pct", 0) <= T.RTB_FORCE_LAND_PCT:
            cmd["dz"] = T.RTB_DESCENT_MPS * 1.5
            cmd["rtb"] = "force_land"

    def _clamp_cmd(self, cmd):
        """指令白名单限幅：单周期 dz ≤ ±1.5 m/s、dvyaw ≤ 30°/s，超限钳位并记录。
        P0-4：FORCE_LAND 迫降通道用更高限幅（CMD_MAX_DZ_EMERG_MPS=3.0），
        使 _force_land_abort 的 dz=RTB_DESCENT_MPS*1.5=3.0 不被正常限幅截掉一半。"""
        dz_max = T.CMD_MAX_DZ_EMERG_MPS if cmd.get("force_land") else T.CMD_MAX_DZ_MPS
        limits = {"dx": T.CMD_MAX_HV_MPS, "dy": T.CMD_MAX_HV_MPS,
                  "dz": dz_max, "dvyaw": T.CMD_MAX_DVYAW_DEG_S,
                  "throttle_delta": 1.0}
        clamped = []
        for k, lo in limits.items():
            v = cmd.get(k, 0.0)
            if abs(v) > lo:
                clamped.append(f"{k}:{v}->{lo if v>0 else -lo}")
                cmd[k] = lo if v > 0 else -lo
        if clamped:
            cmd["clamped"] = clamped
        return cmd

    def _emit(self, cmd):
        """把指令写到对应串口（uart1 飞控 / uart5 上报 AGH）。"""
        # 飞控指令 -> uart1
        fc = {k: cmd.get(k, 0.0) for k in
              ("dx","dy","dz","dvyaw","throttle_delta")}
        self.io.cmd("uart1", fc)
        # 决策摘要 -> uart5（AGH 侧可消费）
        self.io.cmd("uart5", {"mode": cmd["mode"], "anomaly": cmd["anomaly"],
                               "action": cmd["action"]})

    # ---------- 兜底：AI/AGH 不可达时仍安全 ----------
    def safety_fallback(self):
        """链路/飞控异常时触发内置最小规则，不依赖决策库。"""
        metrics = trigger.read_metrics_from_io(self.io)
        battery = metrics.get("battery_v", 99.0)
        rain = metrics.get("rain", 0)
        wind = metrics.get("wind_speed", 0.0)
        ctrl_alive = metrics.get("flight_ctrl_alive", 1)
        rules = []
        if ctrl_alive == 0:
            rules.append("flight_ctrl_lost -> hard RTB")
        if battery < T.BATTERY_CRIT_V:
            rules.append("low_battery -> RTB")
        if rain:
            rules.append("rain -> climb to rain-avoidance alt")
        if wind >= T.WIND_CRIT_MS:
            rules.append("wind_over_limit -> forced land")
        return {"triggered": bool(rules), "rules": rules}

    # ---------- 演示 ----------
    def run_demo(self, scenarios=None):
        """桌面演示：喂几组典型传感器场景，打印模式选择与指令。"""
        scenarios = scenarios or [
            ("正常巡航(定点)",       {"position": [30.0, 120.0, 20.0],
                                       "obstacle_dist": 45.0,
                                       "obstacle_bearing_deg": 0.0,
                                       "speed": 5.0, "rain": 0},
              "CRUISE"),
            ("降雨(自动)",           {"rain": 1, "obstacle_dist": 40.0}, None),
            ("大风超包线(自动)",     {"wind_speed": 15.0}, None),
            ("低电量 RTB(自动)",     {"battery_v": 14.0, "battery_pct": 12,
                                       "position": [35.0, 118.0, 25.0]}, None),
            ("障碍右前(自动)",       {"obstacle_dist": 2.0,
                                       "obstacle_bearing_deg": 30.0}, None),
            ("障碍左前(自动)",       {"obstacle_dist": 2.0,
                                       "obstacle_bearing_deg": -30.0}, None),
            ("障碍无方位角(自动)",   {"obstacle_dist": 2.0,
                                       "obstacle_bearing_deg": None}, None),
            ("强制PROTECT+雨",       {"rain": 1}, "PROTECT"),
        ]
        base = dict(DEFAULT_METRICS)
        print(f"{'场景':18s} | {'模式':8s} | {'anomaly':12s} | 指令摘要")
        print("-" * 90)
        for label, over, forced in scenarios:
            m = dict(base)
            m.update(over)
            self._inject_metrics(m)
            # 每个场景重置滞波杠/滑平器状态：
            # 单 tick 演示时避免上一场景的指令残留影响本场景（生产多 tick 不受影响）
            self.sens.reset()
            self.smoother.reset()
            self.set_forced_mode(forced)
            cmd = self.tick()
            self.set_forced_mode(None)
            summ = {k: cmd[k] for k in
                    ("dx","dy","dz","dvyaw","throttle_delta")
                    if cmd.get(k)}
            extra = cmd.get("mode_action") or cmd.get("rtb") or \
                    cmd.get("obstacle_action") or "-"
            print(f"{label:18s} | {cmd['mode']:8s} | {cmd['anomaly']:12s} | "
                  f"{summ} [{extra}]")
        self.set_forced_mode(None)

    def _inject_metrics(self, metrics):
        """把一组 metric 值塞进 uart 缓存，供 trigger 读取（仿真用）。"""
        for ch, cfg in serial_io.CHANNELS.items():
            for mk, val in metrics.items():
                if mk in cfg["metrics"]:
                    fr = serial_io._norm_frame(ch, mk, val)
                    fr["seq"] = len(self.io._cache[ch]) + 1
                    self.io._cache[ch].append(fr)


# 默认指标基线（演示/仿真用）
DEFAULT_METRICS = {
    "position": [30.0, 120.0, 20.0], "attitude": [0, 0, 0], "yaw": 12.0,
    "speed": 5.0, "battery_v": 15.0, "battery_pct": 88, "battery_temp": 45,
    "esc_current": 2.5, "flight_ctrl_alive": 1, "vib_high": 0, "esc_temp": 55,
    "wind_speed": 3.2, "wind_dir": 90, "temp_c": 22.5, "humidity": 60,
    "pressure": 1013, "rain": 0, "visibility": 800, "thunder": 0,
    "lat": 30.0, "lon": 120.0, "fix": 3, "hdop": 0.8, "sat_count": 12,
    "link_rssi": -65, "link_ok": 1,
    "gimbal_pitch": -10.0, "obstacle_dist": 45.0,
    "obstacle_bearing_deg": 0.0, "bird_detect": 0,
    "payload_fault_flag": 0,
}


def main():
    import ai_main as ai_main_module
    print("=" * 60)
    print("DroneAI 主程序自检（仿真串口）")
    print("=" * 60)
    ai = DroneAI(transport="sim", cruise_target=(30.0, 120.0, 20.0),
                 cruise_speed_mps=5.0)
    ai.start(home=(30.0, 120.0, 15.0))   # 起飞记录 home 点（NED 北/东/下）
    time.sleep(0.5)
    # 先注入一组默认 metric 帧，让“最新帧”打印有内容
    ai._inject_metrics(ai_main_module.DEFAULT_METRICS)
    print("\n-- 5 路串口最新帧 --")
    for ch in serial_io.CHANNELS:
        # demo 模式下 pump 不生成默认帧，_latest 可能为空，改从 cache 尾读
        cache = ai.io._cache.get(ch)
        if cache:
            f = dict(cache[-1])
        else:
            f = {}
        f["quality"] = ai.io._quality.get(ch, "unknown")
        print(f"  {ch:6s} {f.get('metric')}: {f.get('value')} ({f['quality']})")
    print("\n-- 兜底判定 --")
    print(" ", ai.safety_fallback())
    print("\n-- 场景演示 --")
    ai.run_demo()
    ai.stop()
    print("\n[OK] DroneAI 自检通过")


if __name__ == "__main__":
    main()
