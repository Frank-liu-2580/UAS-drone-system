# 无人机飞行模拟 · 3D 前端

> 2026-10-14：核心代码统一在 `../123/drone_ai` + `../123/drone_sim`；本目录 `backend/` 为已弃用旧快照。
> 统一入口：双击 `../启动模拟系统.bat`；离线 3D 双击 `demo.html` 或 `run_demo.bat`。
> 详细变更记录见 `../123/项目日志.txt` 二十二节。

基于 `../123/drone_sim` 后端脚本的 Web 3D 飞行模拟前端项目。

## 项目结构

```
drone_frontend\
├── server.py          # Flask 后端（API 服务）
├── start.bat          # 一键启动脚本（双击即可）
├── start_server.py    # Python 启动器
├── test_api.py        # API 测试脚本
├── static\
│   ├── index.html     # 主页面
│   ├── app.js         # Three.js 动画逻辑
│   └── style.css      # 样式
├── logs\
│   └── drone_sim.log  # 服务运行日志
└── README.md
```

## 快速启动

### 方式一：双击 start.bat（推荐）

```
双击 drone_frontend\start.bat
```

然后浏览器打开：

```
http://localhost:5000
```

### 方式二：命令行

```powershell
cd drone_frontend
pip install flask
python server.py 5000
```

## 使用流程

1. **打开浏览器** → `http://localhost:5000`
2. **初始菜单界面**：
   - 设置模拟时长（默认 8 分钟）
   - 设置随机种子（留空=每次随机，填数字=可复现）
   - 点击"▶ 开始飞行模拟"
3. **3D 飞行动画界面**：
   - 无人机从 home 点起飞，沿轨迹飞行
   - 事件发生时（如下雨）自动切换对应视觉特效
   - **左上角 HUD**：时间戳、经纬度、高度、电量、模式、当前事件
   - **底部进度条**：播放进度
   - **控制栏**：暂停/继续、1x/4x/8x 速度、返回菜单
4. **飞行结束后**：
   - 显示"✓ 任务完成"
   - 出现"← 返回菜单"按钮，点击返回重新模拟

## 后端 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 主页面 |
| `/api/sim` | GET | 运行模拟（参数：`minutes`, `seed`），返回结构化 JSON |
| `/api/log` | GET | 返回最近 500 行日志 |
| `/health` | GET | 健康检查 |

### /api/sim 返回格式

```json
{
  "seed": 42,
  "minutes": 8,
  "total_s": 480,
  "fingerprint": "events[rain×1/wind×1/...] modes[CRUISE=300s/RTB=60s] changes=12",
  "mode_summary": {"CRUISE": 300, "RTB": 60},
  "events": [
    {"id": 1, "start_s": 65, "dur_s": 30, "name_cn": "下雨"}
  ],
  "timeline": [
    {"ts": 28800, "time_str": "08:00:00", "level": "OK", "content": "起飞..."}
  ],
  "ticks": [
    {"ts": 28865, "mode": "CRUISE", "anomaly": "none", "cmd": {"dx": -0.5, ...}, ...}
  ],
  "position_seq": [
    {"t": 0.0, "lat": 30.0, "lon": 120.0, "alt": 15.0, "battery_pct": 100, "raining": false}
  ],
  "home": {"lat": 30.0, "lon": 120.0, "alt": 15.0}
}
```

## 日志

服务日志写入：

```
drone_frontend\logs\drone_sim.log
```

记录内容：
- 服务启动/停止时间
- 每次 API 请求的参数和耗时
- 模拟运行结果摘要
- 错误信息（含完整 traceback）

可通过 `/api/log` 端点或浏览器访问查看。

## 依赖

- Python 3.8+
- Flask（`pip install flask`）
- Three.js：本目录已有本地 `three.min.js` + `GLTFLoader.js`（离线可用）；index.html 已改引本地资源（去 CDN）

后端依赖（drone_sim 原有）：
- openpyxl（`pip install openpyxl`）

统一依赖清单：`../123/requirements.txt`

## 3D 无人机模型

默认尝试加载本地 GLB：`models/drone_nologo.glb`（约 200KB，app.js `loadGLBDrone` 异步拉取，
失败自动回退到程序化建模）：
- 4 轴 X 形机臂 + 电机 + 旋转螺旋桨（程序化兜底）
- 机身 + GPS 天线 + 底部摄像头
- 状态指示灯（外桨红/内桨绿）
- 2000 粒子雨系统（下雨事件期间激活）
- 飞行轨迹线（蓝色，最多 400 个点）
- 地面网格 + home 标记（绿色）

## 3D 离线演示打不开（WebView2 锁冲突）

3D 离线演示（`demo.html` / `run_demo.bat` / `launch_app.pyw`）基于 pywebview（Edge WebView2）弹出小窗口，**全程离线**（three.min.js / GLTFLoader.js 已在本地；`models/scenery/` 下 6 个 .glb 缺失时自动降级为程序化树木，不影响画面）。

**偶发“打不开”是 WebView2 profile 锁冲突**：上一次窗口没关干净 → 残留 `msedgewebview2.exe` 占着 `logs\webview2_user_data\` 的锁 → 新窗口静默失败。`launch_app.pyw` 内置了 `_cleanup_stale_webview2()` 自动清理，但残留进程仍可能抢先占锁。

**应急处理（在 drone_frontend 目录执行）：**

```powershell
Stop-Process -Name msedgewebview2 -Force -ErrorAction SilentlyContinue
Remove-Item .\logs\webview2_user_data\* -Force -Recurse -ErrorAction SilentlyContinue
pythonw launch_app.pyw
```

先杀掉残留 WebView2 进程、清掉固定 profile 目录，再启动窗口，基本可解决。

## 启动方式

1. 推荐：双击 `../启动模拟系统.bat`（统一 GUI，含 3D 离线 / 3D Web / 模拟 / AI 自检）
2. 3D Web：`start.bat`（本目录，Flask + 浏览器）或 `start_server.py`
3. 3D 离线：`run_demo.bat` / 双击 `launch_app.pyw` / 直接双击 `demo.html`
4. API 测试：`test_api.py`（需先 `python server.py 5000`）
