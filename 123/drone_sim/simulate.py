# -*- coding: utf-8 -*-
"""
飞行模拟器：驱动 drone_ai.DroneAI 跑一次完整飞行，注入随机事件，
输出时间轴报告。

设计
  - 虚拟时钟：从 0s 到 total_minutes*60s，每 dt=0.5s 推进一次
  - 事件：按"时刻 + 持续时长"注入到传感器值，触发后 DroneAI 自动决策
  - 位置：闭环积分（当前位置 = 上次位置 + AI指令速度*dt），模拟飞机真的在动
  - 电量：随时间线性下降，低电事件拉低到紧急线才真正触发 battery_issue
  - 时间轴：每个关键事件 / 模式切换 / 指令变化 都记一行，最终写 xlsx 或 stdout
"""
import os, sys, time, random, argparse, math
from datetime import datetime, timedelta

# 让 drone_ai 包可被找到（drone_sim 与 drone_ai 同级，用相对路径，使用相对路径）
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from drone_ai import serial_io, trigger, decision, thresholds as T

# DroneAI 在包根，单独 import
sys.path.insert(0, os.path.join(_ROOT, "drone_ai"))
import ai_main


class FlightSimulator:
    """
    一次完整飞行模拟：
      起飞 -> 巡航 -> [随机事件 x N] -> 降落
    每个 tick 把当前 sensor 状态喂给 DroneAI，收集决策，记时间轴。
    输出：xlsx（RunSummary/Timeline/Events 三表），每次运行覆盖重写。
    """

    def __init__(self, total_minutes=8.0, seed=None, dt=0.5):
        self.total_s = int(total_minutes * 60)
        self.dt = dt
        self.seed = seed
        self.rng = random.Random(seed)
        self._event_log = []       # 时间轴行
        self._mode_log = []        # 模式切换
        self._ai = None
        self._cur = None           # 当前注入的 sensor dict
        self._mode_acc_s = {}      # 模式累计时长（秒），用于尾部指纹
        self._cmd_changes = 0      # 指令变化次数（指纹）
        self._events_started = 0
        self._events_done = 0
        self._task_terminated = False
        self._task_terminate_ts = None
        self._dedup_key = None     # 相邻 INFO 事件去重键
        # ---- 路线判断/避障/行为动作 用 drone_ai 算法（闭环状态）----
        # 无人机真实 NED 位置（米），由 AI 指令积分驱动（替代旧版写死 ts*0.01 漂移）
        self._pos = [30.0, 120.0, 15.0]   # 起飞 home
        # 机头朝向（deg，0=北 顺时针），由 dvyaw 积分（避障转向 / 航线航向）
        self._yaw = 0.0
        # 航线 waypoint（用 drone_ai/route.py 默认 4 点巡检航线，相对 home 中心）
        self._home = (30.0, 120.0, 15.0)
        self._waypoints = None     # 延迟到 run() 里用 route.default_waypoints(home) 生成
        self._obstacle_pos = None  # 当前障碍物 NED 位置（避障几何算方位角用）
        self._obstacle_pos_active = False
        self._log_route_done = False   # 航线完成日志去重
        # P1-4: 位置轨迹历史（server.py 消费，用于 3D 动画）
        self._pos_history = []   # list of {"t": float, "pos": [x,y,z], "yaw": float}

    def _init_route(self):
        """用 drone_ai/route.py 生成默认 4 点巡检航线（home 中心）。"""
        import route as _route
        self._waypoints = _route.default_waypoints(home=self._home)

    def _geometry_obstacle_bearing(self):
        """用 drone_ai/route.py 几何算出相对机头朝向的障碍方位角 + 距离。
        仅在障碍物处于激活期时返回 (bearing, dist)，否则返回 (None, None)。"""
        import route as _route
        if not self._obstacle_pos_active or self._obstacle_pos is None:
            return (None, None)
        bearing, dist = _route.obstacle_bearing(self._pos, self._yaw, self._obstacle_pos)
        return (bearing, dist)

    # ---------- 时间轴工具 ----------
    def _log(self, ts, level, msg):
        """ts: 模拟秒, level: INFO/WARN/CRIT/OK"""
        t = datetime.fromtimestamp(0) + timedelta(seconds=ts)
        self._event_log.append(
            f"{t.strftime('%H:%M:%S')}  [{level:4s}]  {msg}")

    # 触发指令的传感器指标（anomaly -> 该看的 metric 名），用于在时间轴
    # 上标出"这次是什么读数触发的"，不同种子下数值不同，便于辨识运行差异
    _ANOMALY_SENSORS = {
        "rain": ("rain", "temp_c"),
        "wind_gust": ("wind_speed",),
        "gps_drift": ("hdop", "sat_count"),
        "obstacle": ("obstacle_dist", "obstacle_bearing_deg"),
        "bird_detect": ("bird_detect",),
        "signal_loss": ("link_ok", "link_rssi"),
        "battery_issue": ("battery_pct", "battery_v"),
        "flight_ctrl": ("flight_ctrl_alive",),
        # 事件库扩充新增
        "lightning": ("thunder", "wind_speed"),
        "dust_fog": ("visibility",),
        "cold_hot": ("temp_c",),
        "esc_fault": ("esc_temp",),
        "prop_break": ("vib_high", "esc_current"),
        "motor_failure": ("esc_current",),
        "payload_fault": ("obstacle_dist",),
        "gimbal_fault": ("gimbal_pitch",),
        "crash_general": ("flight_ctrl_alive", "esc_current"),
    }

    def _sensor_note(self, anomaly, cur):
        """返回触发该 anomaly 的传感器读数摘要（无则空串）。"""
        names = self._ANOMALY_SENSORS.get(anomaly)
        if not names:
            return ""
        parts = []
        for n in names:
            v = cur.get(n)
            if v is None:
                continue
            if isinstance(v, float):
                v = round(v, 1)
            parts.append(f"{n}={v}")
        return " ".join(parts)

    def _log_cmd(self, ts, cmd, anomaly, mode, cur=None):
        """只在"状态变化"时记一行：异常类型变、模式变、指令从无到有/归零。
        用 self._last_sig 记录上一个 tick 的指纹，避免每个 tick 都刷一行。
        cur: 当前 sensor dict，用于标注触发该指令的传感器读数。"""
        five = {k: cmd.get(k, 0.0) for k in ("dx","dy","dz","dvyaw","throttle_delta")}
        nonzero = any(abs(v) > 1e-6 for v in five.values())
        sig = (anomaly, mode, nonzero, cmd.get("rtb") or cmd.get("obstacle_action") or
               cmd.get("mode_action") or "")
        if sig == self._last_sig:
            return
        self._last_sig = sig
        self._cmd_changes += 1
        extra = cmd.get("rtb") or cmd.get("obstacle_action") or cmd.get("mode_action") or ""
        summary = " ".join(f"{k}={v:.2f}" for k,v in five.items() if abs(v)>1e-6)
        note = self._sensor_note(anomaly, cur or {})
        level = "CMD" if anomaly == "none" else "W   "[:3]
        line = f"{mode:8s} | {anomaly:12s} | {summary or '(hold)'}"
        if note:
            line += f"  ({note})"
        if extra:
            line += f" {extra}"
        self._log(ts, level, line.rstrip())

    # ---------- 随机事件生成 ----------
    # 事件类型池（事件库扩充：新增 8 类天气学+动力+云台）
    EVENT_TYPES = [
        "rain", "wind", "low_battery", "obstacle", "link_loss", "bird", "gps",
        "lightning", "dust_fog", "cold_hot", "esc_fault",
        "prop_break", "motor_failure", "payload_fault", "gimbal_fault",
    ]

    def _gen_events(self):
        """
        在飞行中随机生成 5~10 个事件（事件库扩充后更密集）。
        每个事件 = (start_s, dur_s, type)
        """
        n = self.rng.randint(5, 10)
        margin = min(30, max(5, self.total_s // 4))   # P2-7：短模拟时缩小安全区，避免 randint(margin,margin) 退化
        events = []
        for _ in range(n):
            start = self.rng.randint(margin, self.total_s - margin)
            dur   = self.rng.randint(8, 60)
            etype = self.rng.choice(self.EVENT_TYPES)
            events.append((start, min(dur, self.total_s - start), etype))
        events.sort(key=lambda e: e[0])
        return events

    def _event_payload(self, etype, ts):
        """返回该事件要叠加到 sensor 上的 metric 值。
        事件库扩充：新增 lightning/dust_fog/cold_hot/esc_fault/
        prop_break/motor_failure/payload_fault/gimbal_fault 8 类。"""
        p = {}
        if etype == "rain":
            p["rain"] = 1
        elif etype == "wind":
            p["wind_speed"] = self.rng.uniform(
                T.WIND_WARN_MS + 1, T.WIND_CRIT_MS + 2)
        elif etype == "low_battery":
            p["battery_v"] = T.BATTERY_CRIT_V - 0.5
            p["battery_pct"] = self.rng.randint(8, 14)
        elif etype == "obstacle":
            # 避障几何：障碍物放在无人机机头前方 2~5m（模拟器据此算 obstacle_pos 注入）
            # bearing 置 None -> ai_main 用 route.obstacle_bearing 从当前位置+机头朝向算方位角
            p["obstacle_dist"] = self.rng.uniform(1.5, 4.0)
            p["obstacle_bearing_deg"] = None   # 交给几何计算（不再随机注入）
            p["_obstacle_geom"] = True        # 标记：模拟器据此算出 obstacle_pos 注入
        elif etype == "link_loss":
            p["link_ok"] = 0
            p["link_rssi"] = -100
        elif etype == "bird":
            p["bird_detect"] = 1
        elif etype == "gps":
            p["hdop"] = T.GPS_HDOP_MAX + 1.5
            p["sat_count"] = 3
        # ---- 事件库扩充新增 8 类 ----
        elif etype == "lightning":
            p["thunder"] = 1
            p["wind_speed"] = self.rng.uniform(18.0, 25.0)
            p["rain"] = 1
        elif etype == "dust_fog":
            p["visibility"] = self.rng.randint(5, T.VISIBILITY_MIN_M - 10)
        elif etype == "cold_hot":
            # 随机冷/热
            if self.rng.random() < 0.5:
                p["temp_c"] = self.rng.uniform(T.TEMP_LOW_C - 10, T.TEMP_LOW_C - 2)
            else:
                p["temp_c"] = self.rng.uniform(T.TEMP_HIGH_C + 2, T.TEMP_HIGH_C + 10)
        elif etype == "esc_fault":
            p["esc_temp"] = T.ESC_TEMP_CRIT_C + self.rng.uniform(5, 20)
        elif etype == "prop_break":
            p["vib_high"] = 1
            p["esc_current"] = self.rng.uniform(0.0, 1.5)
        elif etype == "motor_failure":
            p["esc_current"] = 0.0
        elif etype == "payload_fault":
            p["payload_fault_flag"] = 1
            p["gimbal_pitch"] = self.rng.uniform(60, 80)
        elif etype == "gimbal_fault":
            p["gimbal_pitch"] = self.rng.uniform(85, 95)
        p["_event_type"] = etype
        return p

    def _event_name_cn(self, etype):
        return {
            "rain": "下雨", "wind": "大风", "low_battery": "低电量",
            "obstacle": "障碍接近", "link_loss": "通信链路丢失",
            "bird": "鸟群接近", "gps": "GPS漂移",
            # 事件库扩充
            "lightning": "打雷/雷曲线", "dust_fog": "沙尘雾霾",
            "cold_hot": "极端温度", "esc_fault": "电调过热",
            "prop_break": "桨叶断裂", "motor_failure": "电机失效",
            "payload_fault": "载荷故障", "gimbal_fault": "云台故障",
        }.get(etype, etype)

    # ---------- 公共模拟循环（run / run_stdout 共用，消除重复）----------
    def _build_sim_loop(self, events):
        """公共模拟循环：事件生成→注入→AI.tick→闭环积分→记录。
        run() 和 run_stdout() 共享此方法，只在输出方式上有差异。"""
        # 路线判断：用 drone_ai/route.py 的 4 点巡检航线（相对 home 中心）
        import route as _route_mod
        _wps = _route_mod.default_waypoints(home=self._home)
        self._waypoints = _wps
        self._ai = ai_main.DroneAI(
            transport="sim",
            cruise_target=(30.0, 120.0, 20.0),
            cruise_speed_mps=5.0,
            route_waypoints=_wps,
            home=self._home)
        self._ai.start(home=self._home, yaw=0.0)
        self._last_sig = None
        self._dedup_key = None
        self._events_started = 0
        self._events_done = 0

        base = dict(ai_main.DEFAULT_METRICS)
        active = []   # (end_s, etype, payload, started_logged)

        self._log(0, "OK",  f"起飞 | home=(30.0,120.0,15.0) | "
                            f"总时长 {self.total_s//60}min | "
                            f"随机事件 {len(events)} 个")

        # 预记事件开始行（去重：同一时刻同类型合并为一行，避免刷屏/误读）
        for i,(s,d,et) in enumerate(events,1):
            key = (s, et)
            if key == self._dedup_key:
                continue
            self._dedup_key = key
            self._log(s, "INFO", f"事件#{i} 开始: {self._event_name_cn(et)} "
                                 f"(持续 {d}s)")

        ts = 0.0
        self._init_route()
        while ts <= self.total_s:
            # 检查是否有事件在此时刻开始
            for (s_, d, et) in events:
                if abs(ts - s_) < self.dt / 2:
                    payload = self._event_payload(et, ts)
                    # 避障几何：若标记 _obstacle_geom，把障碍物放到机头前方，算 NED 位置
                    if payload.get("_obstacle_geom"):
                        front_dist = payload.get("_obstacle_front_dist",
                                                 payload.get("obstacle_dist", 3.0))
                        # 机头朝向 self._yaw：0=北, 顺时针。NED: x=北, y=东
                        yw = math.radians(self._yaw)
                        off_x = front_dist * math.cos(yw)   # 北分量
                        off_y = front_dist * math.sin(yw)   # 东分量
                        self._obstacle_pos = [
                            self._pos[0] + off_x,
                            self._pos[1] + off_y,
                            self._pos[2],
                        ]
                        self._obstacle_pos_active = True
                    active.append((s_ + d, et, payload, False))

            # 构建当前 sensor（基线 + 活跃事件叠加）
            cur = dict(base)
            # 电量随时间线性下降（修正 P0-1：终点设为 BATTERY_WARN_V，
            # 正常飞完到达告警线仍高于紧急线 14.4V，不会误触发 battery_issue 自身事件；
            # 低电量事件会把 battery_v 拉到 CRIT_V-0.5 才真正触发）
            flight_frac = ts / self.total_s
            cur["battery_v"] = T.BATTERY_MIN_TAKEOFF_V - \
                flight_frac * (T.BATTERY_MIN_TAKEOFF_V - T.BATTERY_WARN_V)
            cur["battery_pct"] = int(100 * (1 - flight_frac * 0.45))
            # 位置/航向/高度：闭环积分（用当前 self._pos / self._yaw，不再是 ts*0.01）
            cur["position"] = list(self._pos)
            cur["yaw"] = self._yaw
            cur["obstacle_pos"] = self._obstacle_pos if self._obstacle_pos_active else None

            # 叠加活跃（未结束）事件
            for (_end, _et, payload, _logged) in active:
                if _end > ts:        # 只叠加还没结束的事件
                    cur.update(payload)

            # 注入到 ai 的 uart 缓存
            self._ai._inject_metrics(cur)

            # 决策（drone_ai：trigger -> P/T -> combined_mode -> cruise/route/obstacle -> smooth）
            cmd = self._ai.tick()
            anomaly = cmd["anomaly"]
            mode = cmd["mode"]
            self._mode_acc_s[mode] = self._mode_acc_s.get(mode, 0.0) + self.dt

            # 闭环积分：用 AI 的 dx/dy/dz/dvyaw 更新 self._pos / self._yaw
            # （NED: x 北, y 东, z 下为正；速度 m/s；dvyaw deg/s）
            dvx = cmd.get("dx", 0.0)
            dvy = cmd.get("dy", 0.0)
            dvz = cmd.get("dz", 0.0)
            dv_yaw = cmd.get("dvyaw", 0.0)
            self._pos[0] += dvx * self.dt
            self._pos[1] += dvy * self.dt
            self._pos[2] += dvz * self.dt
            self._yaw = (self._yaw + dv_yaw * self.dt) % 360
            self._ai.yaw = self._yaw   # 反馈给 AI，下次避障几何用新机头朝向

            # P1-4: 记录位置轨迹
            self._pos_history.append({
                "t": round(ts, 2),
                "pos": [round(self._pos[0], 3), round(self._pos[1], 3),
                        round(self._pos[2], 3)],
                "yaw": round(self._yaw, 2),
            })

            # 路线判断完成日志（首次到 home 时记一次）
            if cmd.get("route_return") and not self._log_route_done:
                self._log_route_done = True
                self._log(ts, "OK", "航线完成 | 已飞完 %d 个 waypoint，返航 home"
                           % len(self._waypoints))

            # 记时间轴（只在状态变化时，带当前 sensor 读数）
            self._log_cmd(ts, cmd, anomaly, mode, cur)

            # 无人机自身事件 -> 立即迫降 + 终止任务（底层已置 task_aborted）
            if self._ai.task_aborted:
                self._log(ts, "CRIT",
                    "任务终止 | 自身事件[%s] 立即就近迫降 | 后续事件不再处理"
                    % self._ai.task_abort_reason)
                self._task_terminated = True
                self._task_terminate_ts = ts   # 模拟秒（0 起算），供结尾日志用
                break

            # 事件结束检查
            for (end_s, et, _p, _l) in active:
                if ts >= end_s:
                    self._log(end_s, "OK", f"事件结束: {self._event_name_cn(et)}")
                    if et == "obstacle":
                        self._obstacle_pos_active = False
                        self._obstacle_pos = None
                    self._events_done += 1
            active = [(e, et, p, l) for (e, et, p, l) in active if e > ts]

            ts += self.dt

        self._events_started = len(events)
        # 降落 / 或任务被自身事件终止
        if getattr(self, "_task_terminated", False):
            self._log(getattr(self, "_task_terminate_ts", self.total_s), "CRIT",
                "飞行提前终止 | 自身事件[%s] 迫降 | 已处理事件 %d/%d | 任务未正常完成"
                % (self._ai.task_abort_reason, self._events_done, len(events)))
        else:
            self._log(self.total_s, "OK", "任务完成 | 安全降落 | "
                                         f"共处理事件 {self._events_done}/{len(events)} 个")
        self._ai.stop()

    # ---------- 主循环入口 ----------
    def run(self, out_path):
        """跑完整模拟并写 xlsx。"""
        # 每次运行先清理上一次成果（xlsx），本次覆盖重写，避免残留混杂
        self._cleanup(out_path)
        events = self._gen_events()
        self._build_sim_loop(events)
        self._write_out(out_path, events)
        print(f"[模拟完成] 时间轴 -> {out_path}")
        if getattr(self, "_task_terminated", False):
            _tt = int(getattr(self, "_task_terminate_ts", 0))
            print(f"  飞行提前终止 @ {_tt//60}m{_tt%60:02d}s | "
                  f"自身事件[{self._ai.task_abort_reason}] 迫降 | 任务未正常完成")
        else:
            print(f"  飞行 {self.total_s//60} 分钟, 注入 {len(events)} 个事件, 全部完成")
        return out_path

    def _cleanup(self, out_path):
        """运行前先删除上一次成果文件（xlsx），本次覆盖重写，避免残留混杂。"""
        if os.path.exists(out_path):
            os.remove(out_path)

    def _build_report_lines(self, events):
        """构造完整报告行（指纹/事件/时间轴），供 xlsx 与 stdout 两种输出复用。"""
        fp = _run_fingerprint(events, self._mode_acc_s, self._cmd_changes)
        lines = [
            "=" * 70,
            "  无人机飞行模拟 · 事件时间轴",
            "=" * 70,
            f"  本次指纹: {fp}",
            f"  模拟 {self.total_s//60} 分钟 | 事件 {len(events)} 个 | "
                  f"指令变化 {self._cmd_changes} 次",
            f"  模式时长: " + ", ".join(
                f"{k}={int(v)}s" for k, v in sorted(self._mode_acc_s.items())),
            "=" * 70,
            f"  随机种子: {self.seed}  (同种子重跑结果一致, 换种子则不同)",
            f"  起飞时间: {datetime.fromtimestamp(0).strftime('%H:%M:%S')}",
            f"  home:     (lat=30.0, lon=120.0, alt=15.0) NED",
            "",
            "  事件列表:",
        ]
        for i, (s, d, et) in enumerate(events, 1):
            lines.append(f"    #{i}  t={s//60}m{s%60:02d}s  "
                         f"{self._event_name_cn(et)} (持续{d}s)")
        lines += [
            "",
            "-" * 70,
            "  逐 tick 时间轴（只记指令变化 / 异常触发行；括号内为触发读数）:",
            "-" * 70,
        ]
        lines.extend(self._event_log)
        lines += ["", "=" * 70, "  [END]", "=" * 70]
        return fp, lines

    def _write_out(self, out_path, events):
        """写 xlsx 三表（需 openpyxl，仅在 --out 写盘时导入，--stdout 模式不需要）。"""
        import openpyxl
        fp, _ = self._build_report_lines(events)

        wb = openpyxl.Workbook()

        # --- 表 1: RunSummary ---
        ws = wb.active
        ws.title = "RunSummary"
        ws.append(["指标", "值"])
        ws.append(["本次指纹", fp])
        ws.append(["随机种子", self.seed])
        ws.append(["模拟时长(分钟)", self.total_s // 60])
        ws.append(["事件数", len(events)])
        ws.append(["指令变化次数", self._cmd_changes])
        for k, v in sorted(self._mode_acc_s.items()):
            ws.append([f"模式时长_{k}", int(v)])
        ws.append(["起飞时间", datetime.fromtimestamp(0).strftime('%H:%M:%S')])
        ws.append(["home(NED)", "(30.0,120.0,15.0)"])

        # --- 表 2: Events ---
        we = wb.create_sheet("Events")
        we.append(["#", "开始时刻", "事件", "持续(s)"])
        for i, (s, d, et) in enumerate(events, 1):
            we.append([i, f"{s//60:02d}:{s%60:02d}", self._event_name_cn(et), d])

        # --- 表 3: Timeline ---
        wt = wb.create_sheet("Timeline")
        wt.append(["时刻(HH:MM:SS)", "级别", "内容"])
        for line in self._event_log:
            parts = line.split(None, 2)
            ts = parts[0]
            level = parts[1].strip() if len(parts) > 1 else ""
            level = level.strip("[] ")
            content = parts[2] if len(parts) > 2 else ""
            wt.append([ts, level, content])

        wb.save(out_path)
        print(f"  本次指纹: {fp}")

    def run_stdout(self):
        """跑完整模拟循环（sensor+决策），但不写任何文件，把完整报告直接打印到
        stdout，供 bat 窗口内展示。返回本次指纹。"""
        events = self._gen_events()
        self._build_sim_loop(events)

        fp, lines = self._build_report_lines(events)
        print("\n".join(lines))

        # 把本次指纹存盘（唯一状态文件），并打印上次/本次对比供 bat 窗口展示
        # 状态文件目录：默认模块同级（开发模式），frozen 模式（PyInstaller exe）
        # 由 server.py 设置环境变量 DRONE_SIM_STATE_DIR 指向可写目录，
        # 因为 _MEIPASS 解压目录只读、每次重建，写进去下次也读不到。
        state_dir = os.environ.get("DRONE_SIM_STATE_DIR")
        if not state_dir:
            state_dir = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(state_dir, exist_ok=True)
        last_fp_path = os.path.join(state_dir, "sim_last_fp.txt")
        last = ""
        if os.path.exists(last_fp_path):
            with open(last_fp_path, encoding="utf-8") as f:
                last = f.read().strip()
        print()
        if last:
            print("  [last] " + last)
            print("  [this] " + fp)
            print("  [SAME] same as last run" if last == fp
                  else "  [DIFF] different from last run  = output really changed")
        else:
            print("  [this] " + fp + "  (first run, nothing to compare)")
        with open(last_fp_path, "w", encoding="utf-8") as f:
            f.write(fp)
        return fp


def _run_fingerprint(events, mode_acc_s, cmd_changes):
    """运行指纹：事件分布 + 模式累计时长 + 指令变化次数的简写。
    不同 seed 的指纹必然不同，直接证明两次运行结果不一样。"""
    from collections import Counter
    c = Counter(et for (_s, _d, et) in events)
    ev = "/".join(f"{et.replace('_','')}×{n}" for et,n in sorted(c.items()))
    md = "/".join(f"{k}={int(v)}s" for k,v in sorted(mode_acc_s.items()))
    return f"events[{ev}] modes[{md}] changes={cmd_changes}"


def main():
    ap = argparse.ArgumentParser(description="无人机飞行模拟")
    ap.add_argument("--minutes", type=float, default=8.0,
                    help="模拟总时长（分钟），默认 8")
    ap.add_argument("--seed", type=int, default=None,
                    help="随机种子（留空=每次不同）")
    ap.add_argument("--out", default=None,
                    help="输出 xlsx 路径，默认为项目根目录下的 sim_output.xlsx（相对路径）")
    ap.add_argument("--stdout", action="store_true",
                    help="结果直接打印到 stdout，不写任何文件")
    args = ap.parse_args()

    if args.stdout:
        sim = FlightSimulator(total_minutes=args.minutes, seed=args.seed)
        sim.run_stdout()
        return

    # 默认输出路径：项目根目录（drone_sim 的上一级）下的 sim_output.xlsx
    out = args.out or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "sim_output.xlsx")

    sim = FlightSimulator(total_minutes=args.minutes, seed=args.seed)
    sim.run(out)


if __name__ == "__main__":
    main()
