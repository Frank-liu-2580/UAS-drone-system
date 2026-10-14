# drone_ai — 机载内置 AI 主程序

无人机机载侧 AI：从 5 路串口读入传感器信号 → 判定异常 → 按当前模式
（保护无人机 / 完成任务）智能选择避险方式 → 写回串口对应指令，并支持
自动避障 + 定点 / 定速巡航。

## 文件结构

| 文件 | 作用 |
|---|---|
| `serial_io.py`  | 5 路 UART 抽象：仿真口 / 真实 pyserial 双实现，统一 JSON 帧 |
| `thresholds.py` | 数值阈值集中配置（换电池/电机/抗风包线只改这里） |
| `trigger.py`    | 传感器读数 → 命中哪些异常（电机/电池/雨/风/障碍/鸟…） |
| `decision.py`   | 模式选择器：算 P/T 双值 → PROTECT / MISSION / CRUISE / RTB |
| `cruise.py`     | 定点 / 定速 巡航控制器（PID + 偏航限幅） |
| obstacle.py   | 自动避障（雷达距离 + 方位角 bearing → 绕行 / 急停 / 正前方 hold） |
| `ai_main.py`    | 主程序入口：把上面串起来，读串口 → 决策 → 写串口 |

## 快速自检（桌面仿真）

```
cd 123/drone_ai（项目根下的 123/drone_ai）
python -c "import sys; sys.path.insert(0,'drone_ai'); import ai_main; ai_main.main()"
```

会依次打印：5 路串口最新帧、兜底判定、8 个场景演示（含自动选模式 +
指令叠加 + 避障 / 巡航效果）。

## 机载接入（真实串口）

```python
from drone_ai.ai_main import DroneAI
from drone_ai.serial_io import open_serial

ai = DroneAI(
    transport=None,
    device_map={
        "uart1": open_serial("uart1", "/dev/ttyS0", 115200),  # 飞控
        "uart2": open_serial("uart2", "/dev/ttyS1", 9600),    # 气象+雨滴
        "uart3": open_serial("uart3", "/dev/ttyS2", 115200),  # GNSS
        "uart4": open_serial("uart4", "/dev/ttyS3", 115200),  # 云台+避障
        "uart5": open_serial("uart5", "/dev/ttyS4", 115200),  # 4G->AGH
    },
    cruise_target=(30.0, 120.0, 20.0),   # 定点目标
    cruise_speed_mps=5.0,                # 定速目标
)
ai.start()
while not ai._stop_evt.is_set():
    ai.tick()       # 每个控制周期一次
    time.sleep(0.05)
ai.stop()
```

前端模式按钮：

```python
ai.set_forced_mode("PROTECT")   # 保护无人机
ai.set_forced_mode("MISSION")   # 完成任务
ai.set_forced_mode(None)        # 自动（按 P/T 差）
```

## 数据流

```
5路UART -> 归一化JSON帧 -> trigger命中异常
        -> decision算P/T选模式(PROTECT/MISSION/CRUISE/RTB)
        -> cruise(定点/定速) + obstacle(避障) 叠加
        -> 指令写回 uart1(飞控) + uart5(上报AGH)
```

## 三条底线（保持安全）

1. **AI 不可达仍有兜底**：`ai_main.safety_fallback()` 内置最小规则
   （飞控失联 / 低电 / 雨 / 超风），不依赖决策库。
2. **安全动作不走 AI**：致命类（电机/桨/飞控/雷击）执行目标恒为
   `FlightController`，硬约束留在飞控。
3. **串口只是物理层**：AI 只消费归一化 JSON 帧，不解析裸字节。
