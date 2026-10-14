# -*- coding: utf-8 -*-
"""
thresholds.py — 数值阈值集中配置（机载 AI 专用副本）
======================================================
从 archive_ai/thresholds.py 复制并裁剪，只保留 AI 主程序实际用到的量。
换电池/电机/抗风包线只改这一个文件。所有 [TODO] 项上机前必须按实参替换。
P/T 权重体系（analyzer/weight_base.py）与本文件解耦，本文件占位符不影响 P/T 计算。
"""

# ============================================================
# 上机替换清单（PRE-FLIGHT CHECKLIST）
# ============================================================
# 以下各项当前值均为"行业保守占位"，上机前必须逐项替换为你的无人机实参。
# 替换依据与风险等级标注在每项注释里，格式：[风险H/M/L] [来源] 当前值。
#
# 风险分级：
#   H = 不改则可能造成安全事故（动力/电池/抗风/通信）
#   M = 不改则动作次优或误触发（任务/载荷/传感器）
#   L = 记录值/调参项（控制器系数、RTB 指令）
#
# 机载实际引用：
#   ai_main.py  -> BATTERY_CRIT_V, CMD_MAX_DVYAW_DEG_S, CMD_MAX_DZ_MPS,
#                  CMD_MAX_HV_MPS, RTB_DESCENT_MPS, RTB_FORCE_LAND_PCT,
#                  RTB_SPEED_MPS, STALE_FRAME_SEC, WIND_CRIT_MS
#   trigger.py  -> BATTERY_CRIT_V, BATTERY_TEMP_CRIT_C, ESC_TEMP_CRIT_C,
#                  GPS_HDOP_MAX, GPS_SAT_MIN, MOTOR_FAIL_CURRENT_A,
#                  OBSTACLE_CLOSE_M, RSSI_LOST_DBM, TEMP_HIGH_C, TEMP_LOW_C,
#                  VISIBILITY_MIN_M, WIND_WARN_MS
#   cruise.py   -> CRUISE_POS_HOLD_TOL_M, CRUISE_POS_KP/KI/KD,
#                  CRUISE_SPEED_TOL_MPS, CRUISE_SPEED_KP/KI/KD,
#                  CRUISE_YAW_RATE_MAX
#   obstacle.py -> OBSTACLE_CLOSE_M

# ============ 1. 电池 ============
# [风险H] 你的电池是几 S？当前按 4S 占位，全包电压 = 单节数 × 单节电压。
#   替换方法：电池标签上的 S 数（如 6S/22.2V）× 单节截止电压
#   单节参考：LiPo 3.7V/节(警告) 3.5V/节(紧急) 3.8V/节(起飞)
BATTERY_S = 4
# [风险H] 起飞最低全包电压(V)。4S: 15.4V(3.85/cell)。6S: 23.1V。
#   替换方法：BATTERY_S × 3.85
BATTERY_MIN_TAKEOFF_V = 15.4
# [风险H] 低电量告警全包电压(V)。4S: 15.0V(3.75/cell)。
#   替换方法：BATTERY_S × 3.75
BATTERY_WARN_V = 15.0
# [风险H] 紧急返航/降落全包电压(V)。4S: 14.4V(3.6/cell)。
#   替换方法：BATTERY_S × 3.6
BATTERY_CRIT_V = 14.4
# [风险H] 电池过温阈值(°C)。通用 65°C；Li-Po 热失控起点 ~60°C，可保守到 60。
#   来源：电池厂商规格书 thermal limit
BATTERY_TEMP_CRIT_C = 65
# [风险M] 电池低温下限(°C)。低于此内阻大、掉压快。LiPo 充电下限 0°C，飞行 0°C。
#   来源：电池厂商低温放电曲线
BATTERY_TEMP_LOW_C = 0

# ============ 2. 电机/电调/桨 ============
# [风险H] 推重比 (thrust:weight)。决定单电机失效后能否维持悬停。
#   替换方法：电机标称推力总和 / 整机全重。
#   判据：>=1.5 单电机失效仍可矢量补偿悬停；<1.3 基本无法维持，应立即软降
MOTOR_REDUNDANCY_TR = 1.3
# [风险H] 单电机失效后仍可维持悬停的推重比下限。
#   替换方法：四旋翼单电机失效后剩余推力 / 全重，需 >= 1.0（含 20% 余量 = 1.2）
TR_SUSTAIN_HOVER = 1.5
# [风险M] 电调正常工作温度上限(°C)。通用 80°C；SiC MOSFET 电调可达 100°C。
#   来源：电调厂商规格书
ESC_TEMP_CRIT_C = 80
# [风险L] 单电机失效时电机电流归零判定(A)。默认 0.0；若电调有底流可设 0.5。
MOTOR_FAIL_CURRENT_A = 0.0

# ============ 3. 机臂抗风包线 ============
# [风险H] 标称抗风等级(级风) 与对应 m/s。
#   替换方法：飞行器抗风试验报告或厂商标称。
#   参考：4级=7-10.7m/s, 5级=10.8-13.8m/s, 6级=13.9-17.1m/s, 7级=17.2-20.7m/s
WIND_RATED_BOFORUS = 6
# [风险H] 标称抗风风速(m/s)。替换为飞行器实际最大抗风。
WIND_RATED_MS = 14.0
# [风险H] 告警风速(m/s)，达到降高度/限机动。通常为 WIND_RATED_MS × 0.7。
WIND_WARN_MS = 10.0
# [风险H] 强制禁止起飞/强制降落风速(m/s)。通常 = WIND_RATED_MS。
WIND_CRIT_MS = 14.0

# ============ 4. 通信链路 ============
# [风险M] 正常 RSSI 范围(dBm)。替换为实测 10m 距离 RSSI。
RSSI_NORMAL_DBM = -60
# [风险M] 即将丢链 RSSI(dBm)。替换为实测 failsafe 触发前 1-2 秒的 RSSI。
RSSI_WARN_DBM = -75
# [风险H] 已丢链 RSSI(dBm)，触发 Failsafe。替换为实测丢链 RSSI。
RSSI_LOST_DBM = -85
# [风险M] GPS HDOP 上限（>此=定位漂移）。通用 2.0；要求高精度可 1.5。
GPS_HDOP_MAX = 2.0
# [风险M] 最少可用卫星数。通用 6；要求 3D 定位至少 4 颗。
GPS_SAT_MIN = 6
# [风险L] 丢链后悬停等待信号恢复时长(秒)。
FAILSAFE_HOLD_SECONDS = 10
# [风险L] 返航点高度(m)。
FAILSAFE_RTB_HEIGHT_M = 40
# [风险L] 返航速度(m/s)。
FAILSAFE_RTB_SPEED_MPS = 8
# [风险L] 超过此未恢复自动降落(秒)。
FAILSAFE_LAND_TIMEOUT_S = 30

# ============ 5. 任务/载荷 ============
# [风险M] 典型任务续航(分钟)。替换为实测。
MISSION_DURATION_MIN = 20
# [风险M] 是否有云台相机。替换为实际配置。
HAS_GIMBAL = True
# [风险M] 最大载荷(kg)。替换为实际最大起飞重量 - 空重。
PAYLOAD_MAX_KG = 0.5
# [风险M] MISSION 模式下允许"继续任务"的最低剩余电量百分比。
#   替换方法：返航点距离 × 电池容量估算，通常为 20-30%。
MISSION_MIN_BATTERY_PCT = 15
# [风险M] 降雨时 MISSION 模式允许继续的最大降雨强度(0-3)。
#   替换为飞行器防水等级（IP 等级）对应的最大降雨。
RAIN_MISSION_MAX_INTENSITY = 2

# ============ 6. 其它传感器 ============
# [风险M] 障碍近距离预警(m)。替换为避障传感器实际探测距离的 50%。
OBSTACLE_CLOSE_M = 5.0
# [风险M] 视距/能见度下限(m)，低于=沙尘/雾。替换为任务空域实际要求。
VISIBILITY_MIN_M = 50
# [风险M] 气温极端上下限(°C)。替换为电池+电机+电调综合温度包线。
TEMP_LOW_C = -10
TEMP_HIGH_C = 45

# ============ 7. 巡航控制器（定点 / 定速） ============
# [风险L] 以下控制器系数上机前需 PID 整定，占位值为保守初值。
# 位置保持（定点）：偏离 > 该值触发纠偏
CRUISE_POS_HOLD_TOL_M = 1.0
CRUISE_POS_KP, CRUISE_POS_KI, CRUISE_POS_KD = 0.8, 0.05, 0.3
# 定速（速度跟踪）：偏差 > 该值触发调速
CRUISE_SPEED_TOL_MPS = 0.5
CRUISE_SPEED_KP, CRUISE_SPEED_KI, CRUISE_SPEED_KD = 1.2, 0.02, 0.4
# 偏航角限幅（deg/s），避免机臂甩尾
CRUISE_YAW_RATE_MAX = 30.0
# 最大机动角加速度（deg/s^2）
CRUISE_MANEUVER_MAX = 5.0

# ============ 8. 数据时效闸门（修复场景C） ============
# [风险M] 帧 ts 超过此时长 / 通道 quality=lost 则不进决策。
#   替换方法：传感器实际刷新率 × 3（如 100Hz -> 0.03s，保守 3s）
STALE_FRAME_SEC = 3.0

# ============ 9. RTB 真实指令参数（修复场景A） ============
# [风险L] 水平返航速度(m/s)。替换为飞行器最大水平速度 × 0.7。
RTB_SPEED_MPS = 8.0
# [风险L] 末段下降率(m/s)。替换为飞行器最大下降率 × 0.5。
RTB_DESCENT_MPS = 2.0
# [风险L] 定高降落目标高度(m)。
RTB_LAND_ALT_M = 0.0
# [风险H] 电量低于此值强制迫降(%)。替换为返航点距离对应电量下限 + 5% 余量。
RTB_FORCE_LAND_PCT = 10

# ============ 10. 指令白名单限幅（修复量纲混用） ============
# [风险L] 单周期水平速度指令上限(m/s)。替换为飞行器最大水平速度。
CMD_MAX_HV_MPS = 10.0
# [风险L] 单周期升降指令上限(m/s)。替换为飞行器最大升降速度。
CMD_MAX_DZ_MPS = 1.5
# [风险L] 单周期偏航角速度上限(°/s)。替换为飞行器最大偏航速率。
CMD_MAX_DVYAW_DEG_S = 30.0

# ============ 11. 打雷 / 雷曲线（新增：事件库事件扩充）============
# [FengXian M] 雷曲线风半径（千米），超过则判打雷
THUNDER_RADIUS_KM = 2.0
# [FengXian M] 闸值判打雷的雷曲线风速（m/s），弱于风包线的专属指标
LIGHTNING_CRIT_MS = 20.0

# ============ 12. 云台/载荷 传感器阈值（P0-2 补全）============
# [风险M] 云台俯仰角最大允许值(°)。正常三轴云台俯仰范围约 -90°~+45°，
#   超过 80° 视为异常（卡死/损坏/超范围）。替换为实际云台包线。
GIMBAL_PITCH_MAX_DEG = 80
# [风险M] 载荷故障标志（bool）：机载侧由载荷自检逻辑置 1，
#   AI 侧只消费该标志；模拟器注入 payload_fault_flag=1 触发 payload_fault。
PAYLOAD_FAULT_FLAG_DEFAULT = 0

# ============ 13. 避障几何参数（P0-1 补全）============
# [风险M] 正前方锥角（deg）：|相对机头方位角| 小于此值视为障碍在正前方，
#   不左转不右转，只做"悬停 + 减速"（正面迎头障碍无法靠偏航绕过）。
OBSTACLE_FRONT_CONE_DEG = 15.0
# [风险L] 紧急通道升降指令上限(m/s)，仅 FORCE_LAND 迫降模式使用（正常限幅 1.5 m/s）。
CMD_MAX_DZ_EMERG_MPS = 3.0
