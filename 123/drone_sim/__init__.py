# -*- coding: utf-8 -*-
"""
drone_sim 包：机载 AI 飞行模拟
================================
新建一个文件夹里的模拟脚本，按下运行即可：
  1. 模拟一次完整飞行（起飞 -> 定点/定速巡航 -> 途中随机事件 -> 降落）
  2. 随机注入事件：下雨、大风、低电量、障碍、丢链、鸟类、GPS 漂移
  3. 每个事件触发时调用 drone_ai.DroneAI.tick() 真实决策
  4. 把整条时间轴以文本形式写到 项目根\\123\\飞行模拟时间轴.txt

运行（在 123\\drone_sim 目录，或用相对路径，不再硬编码盘符）
  python drone_sim\\simulate.py              # 默认 8 分钟模拟
  python drone_sim\\simulate.py --minutes 12 # 指定时长
  python drone_sim\\simulate.py --seed 42    # 固定随机种子（可复现）

依赖：123\\drone_ai 包（同目录上层）
"""
