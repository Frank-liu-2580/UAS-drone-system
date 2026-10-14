# -*- coding: utf-8 -*-
"""
阈值集中配置（thresholds.py）
==============================
影子 AI 决策引擎 (decision_engine.py) 里所有"数值型判定"的阈值，全部集中在这里。
好处：以后要调参数（换电池、换电机、调抗风包线）只改这一个文件，不动引擎逻辑。

约定：
  - 每项标注 [已确认] 或 [TODO 待你确认]
  - [TODO] 项用的是行业保守默认值，上机前必须按你的无人机实际规格替换
  - 单位写在注释里
"""

# ============ 1. 电池 ============
# TODO 待你确认: 你的电池是几 S？下面按 4S 保守占位
BATTERY_S = 4
# TODO 待你确认: 单节容量 mAh（影响续航，不影响阈值判定，仅记录）
BATTERY_CELL_MAH = 1500
# TODO 待你确认: 起飞最低安全电压(全包, V)。4S 通用保守 15.4V(3.85/cell)
BATTERY_MIN_TAKEOFF_V = 15.4
# TODO 待你确认: 低电量告警电压(全包, V)。4S 约 15.0V(3.75/cell)
BATTERY_WARN_V = 15.0
# TODO 待你确认: 紧急返航/降落电压(全包, V)。4S 约 14.4V(3.6/cell)
BATTERY_CRIT_V = 14.4
# TODO 待你确认: 电池过温阈值(°C)。通用 65°C
BATTERY_TEMP_CRIT_C = 65
# TODO 待你确认: 电池低温下限(°C)，低于此电池内阻大掉压快。通用 0°C
BATTERY_TEMP_LOW_C = 0

# ============ 2. 电机/电调/桨 ============
# TODO 待你确认: 电机型号/KV、桨叶尺寸（记录用）
MOTOR_MODEL = "unknown"
MOTOR_KV = None
PROPELLER_SIZE = "unknown"
# TODO 待你确认: 推重比 (thrust:weight)。决定单电机失效后能否维持悬停
#   >=1.5  单电机失效仍可矢量补偿悬停
#   <1.3   单电机失效基本无法维持，应立即软降
MOTOR_REDUNDANCY_TR = 1.3
# TODO 待你确认: 单电机失效后仍可维持悬停的推重比下限
TR_SUSTAIN_HOVER = 1.5
# TODO 待你确认: 电调正常工作温度上限(°C)。通用 80°C
ESC_TEMP_CRIT_C = 80
# 单电机失效时电机电流归零的判定(默认 <=0.0A)
MOTOR_FAIL_CURRENT_A = 0.0

# ============ 3. 机臂抗风包线 ============
# TODO 待你确认: 标称抗风等级(级风) 与对应 m/s
WIND_RATED_BOFORUS = 6          # 示例 6 级风
WIND_RATED_MS = 14.0           # 6级≈14m/s
# TODO 待你确认: 告警风速(m/s)，达到降高度/限机动
WIND_WARN_MS = 10.0
# TODO 待你确认: 强制禁止起飞/强制降落风速(m/s)，通常=标称抗风
WIND_CRIT_MS = 14.0

# ============ 4. 通信链路 ============
# TODO 待你确认: 正常 RSSI 范围 / 丢链判定(dBm)
RSSI_NORMAL_DBM = -60
RSSI_WARN_DBM = -75           # 低于此=即将丢链
RSSI_LOST_DBM = -85          # 低于此=已丢链触发 Failsafe
# TODO 待你确认: GPS HDOP 上限（>此=定位漂移）
GPS_HDOP_MAX = 2.0
# TODO 待你确认: 最少可用卫星数
GPS_SAT_MIN = 6
# TODO 待你确认: 丢链后 Failsafe 动作参数
FAILSAFE_HOLD_SECONDS = 10    # 悬停等待信号恢复时长
FAILSAFE_RTB_HEIGHT_M = 40    # 返航点高度
FAILSAFE_RTB_SPEED_MPS = 8    # 返航速度
FAILSAFE_LAND_TIMEOUT_S = 30  # 超过此未恢复自动降落

# ============ 5. 任务与载荷 ============
# TODO 待你确认: 典型任务续航(分钟)
MISSION_DURATION_MIN = 20
# TODO 待你确认: 是否有云台相机
HAS_GIMBAL = True
# TODO 待你确认: 最大载荷(kg)
PAYLOAD_MAX_KG = 0.5
# TODO 待你确认: MISSION 模式下允许"继续任务"的最低剩余电量百分比
MISSION_MIN_BATTERY_PCT = 15   # 低于 15% 即使任务模式也强制返航
# TODO 待你确认: 降雨时 MISSION 模式允许继续的最大降雨强度(0-3)
RAIN_MISSION_MAX_INTENSITY = 2

# ============ 6. 其它传感器 ============
# TODO 待你确认: 障碍近距离预警(米)
OBSTACLE_CLOSE_M = 5.0
# TODO 待你确认: 视距/能见度下限(米)，低于=沙尘/雾
VISIBILITY_MIN_M = 50
# TODO 待你确认: 气温极端上下限(°C)
TEMP_LOW_C = -10
TEMP_HIGH_C = 45
# 振动标志、鸟类检出、雷击预警为布尔触发，无数值阈值
