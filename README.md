# 无人机失控分析系统

> 从「多站视频数据采集」到「机载 AI 失控判定」，再到「3D 飞行可视化」的完整链路。
> 机载侧纯 Python，无外部 AI 服务依赖；3D 前端全离线可跑（无 CDN）。

## 这是什么

本项目研究无人机在电机、电池、风、雨、障碍等异常下的**失控判定与自主避险**，
并把分析结论落成可运行的机载决策程序 + 可看的 3D 演示。

## 模块导航

| 模块 | 路径 | 作用 |
|---|---|---|
| 机载 AI | [`123/drone_ai/`](123/drone_ai/) | 5 路 UART 传感器 → 异常判定 → 模式选择 → 指令回写 |
| 数据爬虫 | [`123/drone_crawler/`](123/drone_crawler/) | B站 API + YouTube yt-dlp + 10 国际站探针 |
| 飞行仿真 | [`123/drone_sim/`](123/drone_sim/) | 随机事件 + 时间轴输出的桌面仿真 |
| 3D 前端 | [`drone_frontend/`](drone_frontend/) | Three.js 可视化 · Flask Web 版 + pywebview 离线版 |

## 快速开始

需要 **Python 3.9+**，且 `python` 在 PATH 中。

```powershell
pip install -r 123/requirements.txt
```

**方式一：统一 GUI 启动器（推荐）**

双击根目录的 `启动模拟系统.bat` —— 菜单含「飞行仿真 / AI 自检 / 3D 演示 / 项目日志」。

**方式二：3D Web 版**

```powershell
cd drone_frontend
python server.py 5000      # 浏览器打开 http://localhost:5000
```

**方式三：3D 离线版**（pywebview 小窗口，全程无网络）

```powershell
cd drone_frontend
pythonw launch_app.pyw
```

**方式四：机载 AI 自检**（桌面仿真，不需要真实串口）

```powershell
cd 123/drone_ai
python -c "import ai_main; ai_main.main()"
```

会依次打印 5 路串口最新帧、兜底判定与 8 个场景演示（含自动选模式 + 指令叠加 + 避障 / 巡航）。

## 架构

```
5 路 UART → 归一化 JSON 帧 → trigger 命中异常
          → decision 算 P/T 选模式（PROTECT / MISSION / CRUISE / RTB）
          → cruise（定点/定速）+ obstacle（避障）+ route（多航点航线）叠加
          → 指令写回 uart1（飞控）+ uart5（上报）

爬虫数据 → analyzer 生成 P/T 校准矩阵 → 上表决策依据
```

## 安全设计（三条底线）

1. **AI 不可达仍有兜底** —— `ai_main.safety_fallback()` 内置最小规则（飞控失联 / 低电 / 雨 / 超风），不依赖决策库。
2. **安全动作不走 AI** —— 致命类（电机 / 桨 / 飞控 / 雷击）执行目标恒为 `FlightController`，硬约束留在飞控。
3. **串口只是物理层** —— AI 只消费归一化 JSON 帧，不解析裸字节。

另有一条硬限制：命中 7 类**自身事件**（电机失效 / 飞控死机 / 电池故障 / 桨叶断裂 / 电调过热 / 云台故障 / 载荷故障）时，
AI 立即就近迫降并终止任务（`FORCE_LAND`），不再返航 home、不继续巡航。

## 依赖

| 用途 | 包 |
|---|---|
| 核心（AI + 仿真 + xlsx） | `openpyxl` |
| 爬虫 | `requests` `beautifulsoup4` `lxml` `yt-dlp` |
| 3D 前端 | `flask` `pywebview` |
| 真实串口上机（桌面开发不需要） | `pyserial` |

完整清单见 [`123/requirements.txt`](123/requirements.txt)。

> 决策层会读取 P/T 校准矩阵。该矩阵不在版本库中（由分析层生成），
> 缺失时 `decision.py` 会打印一条 warning 并回退到内置默认值，功能不受阻断。

## 文档

- 详细变更记录：[`123/项目日志.txt`](123/项目日志.txt)
- 迁移与排障：[`_迁移安装说明.txt`](_迁移安装说明.txt) —— 含「3D 离线演示打不开」排障清单
- 仿真使用说明：[`123/drone_sim/使用说明.md`](123/drone_sim/使用说明.md)
- 各模块 README：见上方模块导航表
