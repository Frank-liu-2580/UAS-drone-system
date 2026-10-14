# -*- coding: utf-8 -*-
"""
drone_ai 包
==========
机载内置 AI 主程序（可被无人机/机载 SoC 直接导入调用）。

目录结构
  drone_ai/
    __init__.py
    serial_io.py     # 串口 I/O 抽象：真实 pyserial / 仿真 SimulatedPort 双实现
    thresholds.py    # 数值阈值集中配置（换电池/电机/抗风包线只改这里）
    trigger.py       # 传感器读数 -> 触发哪些异常（复用影子AI规则）
    cruise.py        # 定点 / 定速 巡航控制器（PID + 偏航限幅）
    route.py         # 路线判断：多 waypoint 航线 + 航线速度向量 + 避障方位角几何
    obstacle.py      # 自动避障：雷达距离 + 机头朝向 -> 转向/绕行/急停
    decision.py      # 模式选择器：保护无人机 vs 完成任务，查策略库出动作
    ai_main.py       # 主程序入口：把上面串起来，读串口 -> 决策 -> 写串口

主入口用法
  from drone_ai.ai_main import DroneAI
  ai = DroneAI(transport="sim")
  ai.start()
  ai.run_loop()           # 持续读串口/出指令，直到 stop()
  ai.stop()

设计原则（三条底线，与 README 保持一致）
  - 致命/紧急类动作 Execution_Target=FlightController（飞控硬约束兜底）
  - 其它=Shadow_AI（策略级决策）
  - AI 不可达时，机载内置最小规则（rain/battery/gust）保证安全
"""
