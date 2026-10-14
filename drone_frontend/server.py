# -*- coding: utf-8 -*-
"""
Drone Sim Frontend - Flask 后端
================================
运行飞行模拟并解析成结构化 JSON，供前端 3D 动画消费。

运行方式:
  开发:  python server.py [port]
  打包:  双击 DroneSim.exe（自动起服务 + 打开浏览器）
"""
import os, sys, json, logging, re, time, traceback
from datetime import datetime

from flask import Flask, jsonify, request, send_file

# 路径：静态/模型 资源目录
_FROZEN = getattr(sys, "frozen", False)

if _FROZEN:
    # frozen 模式：server.py 被 PyInstaller 打包，_MEIPASS 是解压目录。
    # onefile 模式下 _MEIPASS 在 exe 运行期间对当前进程全程可读，
    # 直接从中 send_file，不再复制到 exe 同级（复制会因残留只读文件失败）。
    _EXE_DIR   = os.path.dirname(os.path.abspath(sys.executable))
    _MEIPASS   = getattr(sys, "_MEIPASS", _EXE_DIR)
    _LOG_DIR   = os.path.join(_EXE_DIR, "logs")
    _STATIC_DIR = os.path.join(_MEIPASS, "static")
    _MODELS_DIR = os.path.join(_MEIPASS, "models")

    # 核心代码（drone_ai / drone_sim / ai_main）由 spec 打进 _MEIPASS（PYZ 可导入）。
    # 可写状态文件（sim_last_fp.txt）放到 exe 同级，经环境变量交给 simulate.py。
    _PROJECT_ROOT = _MEIPASS
    _SIM_DIR = os.path.join(_MEIPASS, "drone_sim")
    _SIM_WRITABLE_DIR = os.path.join(_EXE_DIR, "drone_sim_writable")
    os.makedirs(_SIM_WRITABLE_DIR, exist_ok=True)
    os.environ["DRONE_SIM_STATE_DIR"] = _SIM_WRITABLE_DIR
else:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _STATIC_DIR = os.path.join(_HERE, "static")
    _MODELS_DIR = os.path.join(_HERE, "models")
    _ROOT = os.path.dirname(_HERE)
    _SIM_DIR = os.path.join(_ROOT, "123", "drone_sim")
    _PROJECT_ROOT = os.path.join(_ROOT, "123")
    _LOG_DIR = os.path.join(_HERE, "logs")

_LOG_FILE = os.path.join(_LOG_DIR, "drone_sim.log")
os.makedirs(_LOG_DIR, exist_ok=True)

# 让 drone_sim / drone_ai / ai_main 可被 import
# 开发模式：_PROJECT_ROOT = 12/123/（含 drone_ai/ drone_sim/ 子目录 + ai_main.py 在 drone_ai/ 内）
# 打包模式：_PROJECT_ROOT = _MEIPASS（spec 把 123/ 核心代码打进去了，结构同上）
for _p in (
    _PROJECT_ROOT,
    os.path.join(_PROJECT_ROOT, "drone_ai"),
    os.path.join(_PROJECT_ROOT, "drone_sim"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------- 日志 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("drone_frontend")

# 前端操作日志
_FRONT_LOG_FILE = os.path.join(_LOG_DIR, "frontend.log")
frontend_log = logging.getLogger("drone_frontend_fe")
frontend_log.setLevel(logging.INFO)
_fe_handler = logging.FileHandler(_FRONT_LOG_FILE, encoding="utf-8")
_fe_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
frontend_log.addHandler(_fe_handler)

app = Flask(__name__, static_folder=_STATIC_DIR, static_url_path="/static")

# ---------- 中文映射 ----------
ANOMALY_CN = {
    "none": "正常", "rain": "下雨", "wind_gust": "大风",
    "gps_drift": "GPS漂移", "obstacle": "障碍",
    "bird_detect": "鸟群", "signal_loss": "链路丢失",
    "battery_issue": "低电量", "flight_ctrl": "飞控故障",
    "lightning": "打雷", "dust_fog": "沙尘雾",
    "cold_hot": "极端温度", "esc_fault": "电调过热",
    "prop_break": "桨叶断裂", "motor_failure": "电机失效",
    "payload_fault": "载荷故障", "gimbal_fault": "云台故障",
}
MODE_CN = {"CRUISE": "巡航", "PROTECT": "保护", "MISSION": "任务", "RTB": "返航"}


def _run_sim(minutes: float, seed):
    """同进程 import 并运行 FlightSimulator，获取结构化数据。"""
    import drone_sim.simulate as simulate_mod
    log.info("运行模拟: FlightSimulator(minutes=%s, seed=%s)", minutes, seed)
    t0 = time.time()

    sim = simulate_mod.FlightSimulator(total_minutes=minutes, seed=seed)

    import io as _io
    from contextlib import redirect_stdout
    buf = _io.StringIO()
    with redirect_stdout(buf):
        sim.run_stdout()
    raw = buf.getvalue()

    # P1-4: 捕获真实位置轨迹（替代旧版 t*0.01 线性漂移）
    pos_history = getattr(sim, "_pos_history", [])
    home = sim._home if hasattr(sim, "_home") else (30.0, 120.0, 15.0)

    elapsed = time.time() - t0
    log.info("模拟完成，耗时 %.2fs，输出 %d 字符，轨迹点 %d",
             elapsed, len(raw), len(pos_history))
    return _parse_report(raw, minutes, seed, pos_history=pos_history, home=home)


def _parse_report(raw: str, minutes: float, seed, pos_history=None, home=None):
    """把 simulate.py 的 stdout 解析成结构化 dict。"""
    events = []
    for m in re.finditer(
            r'#(\d+)\s+t=(\d+)m(\d+)s\s+(\S+)\s+\(持续(\d+)s\)', raw):
        start_s = int(m.group(2)) * 60 + int(m.group(3))
        dur = int(m.group(5))
        events.append({
            "id": int(m.group(1)),
            "start_s": start_s,
            "dur_s": dur,
            "name_cn": m.group(4),
        })

    fp_m = re.search(r'events\[([^\]]+)\]\s+modes\[([^\]]+)\]\s+changes=(\d+)', raw)
    fingerprint = ""
    mode_summary = {}
    if fp_m:
        fingerprint = f"events[{fp_m.group(1)}] modes[{fp_m.group(2)}] changes={fp_m.group(3)}"
        for mm in re.finditer(r'(\w+)=(\d+)s', fp_m.group(2)):
            mode_summary[mm.group(1)] = int(mm.group(2))

    timeline = []
    ticks = []
    for line in raw.splitlines():
        line_s = line.strip()
        m = re.match(
            r'(\d{2}):(\d{2}):(\d{2})\s+\[([A-Z ]{1,4})\]\s+(.*)',
            line_s)
        if not m:
            continue
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        ts = h * 3600 + mi * 60 + s
        level = m.group(4).strip()
        content = m.group(5)
        timeline.append({
            "ts": ts, "time_str": f"{h:02d}:{mi:02d}:{s:02d}",
            "level": level, "content": content,
        })

        cm = re.match(r'(\w+)\s+\|\s+(\w+)\s+\|\s+(.*)', content)
        if cm:
            mode, anomaly, rest = cm.group(1), cm.group(2), cm.group(3)
            cmd_data = {}
            for kv in re.finditer(r'(\w+)=([-\d.]+)', rest):
                cmd_data[kv.group(1)] = float(kv.group(2))
            sm = re.search(r'\(([^)]+)\)', rest)
            sensor_note = sm.group(1) if sm else ""
            tail = rest.split(")")[-1].strip() if ")" in rest else rest.strip()
            em = re.search(r'(\w+)$', tail)
            extra = em.group(1) if em else ""
            ticks.append({
                "ts": ts, "time_str": f"{h:02d}:{mi:02d}:{s:02d}",
                "mode": mode, "mode_cn": MODE_CN.get(mode, mode),
                "anomaly": anomaly, "anomaly_cn": ANOMALY_CN.get(anomaly, anomaly),
                "cmd": cmd_data, "sensor_note": sensor_note, "extra": extra,
            })

    total_s = int(minutes * 60)
    # P1-4: 使用模拟器真实轨迹（_pos_history），不再用 t*0.01 线性漂移
    if pos_history is None:
        pos_history = []
    if home is None:
        home_m = re.search(r'home=([\-0-9.]+),([\-0-9.]+),([\-0-9.]+)', raw)
        home = (float(home_m.group(1)) if home_m else 30.0,
                float(home_m.group(2)) if home_m else 120.0,
                float(home_m.group(3)) if home_m else 15.0)
    home_lat, home_lon, home_alt = home

    rain_ranges = []
    for ev in events:
        if any(k in ev["name_cn"] for k in ["雨", "打雷", "雷", "lightning", "rain"]):
            rain_ranges.append((ev["start_s"], ev["start_s"] + ev["dur_s"]))

    if pos_history:
        # 从模拟器真实轨迹构建 pos_seq（NED 绝对坐标 -> 相对 home 的经纬高偏移）
        # NED: x=北, y=东, z=下（米）。模拟器 _pos 起点为绝对 NED home 坐标，
        # 故须减去 home 的 NED 原点，取相对位移后再换算经纬高：
        #   Δlat = Δn/111000, Δlon = Δe/(111000·coslat), Δalt = home_alt - Δd（z 向下）
        import math
        cos_lat = max(0.01, math.cos(math.radians(home_lat)))
        hx, hy, hz = home
        pos_seq = []
        for pt in pos_history:
            t_val = pt["t"]
            nx, ny, nz = pt["pos"]
            frac = t_val / total_s if total_s > 0 else 0
            battery_pct = int(100 * (1 - frac * 0.45))  # 与模拟器一致
            raining = any(s <= t_val < e for s, e in rain_ranges)
            pos_seq.append({
                "t": t_val,
                "lat": round(home_lat + (nx - hx) / 111000.0, 6),
                "lon": round(home_lon + (ny - hy) / (111000.0 * cos_lat), 6),
                "alt": round(home_alt - (nz - hz), 4),
                "yaw": pt.get("yaw", 0.0),
                "battery_pct": battery_pct,
                "raining": raining,
            })
    else:
        # 回退：旧版线性漂移（兼容 pos_history 未提供时）
        pos_seq = []
        t = 0.0
        while t <= total_s:
            frac = t / total_s if total_s > 0 else 0
            battery_pct = int(100 * (1 - frac * 0.45))
            raining = any(s <= t < e for s, e in rain_ranges)
            pos_seq.append({
                "t": round(t, 1),
                "lat": round(home_lat + t * 0.01, 4),
                "lon": round(home_lon + t * 0.01, 4),
                "alt": home_alt,
                "battery_pct": battery_pct,
                "raining": raining,
            })
            t += 0.5

    return {
        "seed": seed, "minutes": minutes, "total_s": total_s,
        "fingerprint": fingerprint, "mode_summary": mode_summary,
        "events": events, "timeline": timeline, "ticks": ticks,
        "position_seq": pos_seq,
        "home": {"lat": home_lat, "lon": home_lon, "alt": home_alt},
    }


# ---------- 路由 ----------
@app.route("/")
def index():
    fp = os.path.join(_STATIC_DIR, "index.html")
    if not os.path.exists(fp):
        log.error("index.html 不存在: %s", fp)
        return "index.html not found: " + fp, 404
    return send_file(fp)


@app.route("/static/<path:filename>")
def static_files(filename):
    fp = os.path.join(_STATIC_DIR, filename)
    if not os.path.exists(fp):
        log.warning("静态文件缺失: %s", fp)
        return "not found: " + filename, 404
    return send_file(fp)


@app.route("/static/models/<path:filename>")
def static_models(filename):
    fp = os.path.join(_MODELS_DIR, filename)
    if not os.path.exists(fp):
        log.warning("模型文件缺失: %s", fp)
        return "not found: " + filename, 404
    return send_file(fp)


# P1-2：GLTFLoader.js / three.min.js 本地路由（断网时仍可用）
@app.route("/GLTFLoader.js")
def _gltfloader():
    fp = os.path.join(_HERE, "GLTFLoader.js")
    if not os.path.exists(fp):
        return "GLTFLoader.js not found", 404
    return send_file(fp)


@app.route("/three.min.js")
def _threemin():
    fp = os.path.join(_HERE, "three.min.js")
    if not os.path.exists(fp):
        return "three.min.js not found", 404
    return send_file(fp)


@app.route("/api/sim")
def api_sim():
    log.info("=== API /api/sim 请求 ===")
    t0 = time.time()
    try:
        minutes = float(request.args.get("minutes", 8))
        seed_raw = request.args.get("seed")
        seed = int(seed_raw) if seed_raw else None

        data = _run_sim(minutes, seed)
        log.info("=== API 完成, 耗时 %.2fs, events=%d, ticks=%d, pos=%d ===",
                 time.time() - t0, len(data["events"]),
                 len(data["ticks"]), len(data["position_seq"]))
        return jsonify(data)
    except Exception as e:
        log.error("API /api/sim 异常: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/log")
def api_log():
    if not os.path.exists(_LOG_FILE):
        return jsonify({"lines": []})
    with open(_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()[-500:]
    return jsonify({"lines": [l.rstrip() for l in lines]})


@app.route("/api/frontend-log", methods=["POST"])
def api_frontend_log():
    try:
        data = request.get_json(force=True)
        entry = data.get("entry", "")
        level = data.get("level", "INFO")
        frontend_log.log(getattr(logging, level, logging.INFO), entry)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


def _get_port():
    if len(sys.argv) > 1:
        try:
            return int(sys.argv[1])
        except ValueError:
            pass
    return 5000


# ---------- 打包后行为：自动开浏览器 + 保持进程存活 ----------
_FROZEN = getattr(sys, "frozen", False)

if _FROZEN:
    import threading as _th
    import webbrowser as _wb

    def _auto_open_browser(port):
        def _open():
            import time as _t
            _t.sleep(2.0)   # 等 Flask 起来
            _wb.open(f"http://127.0.0.1:{port}/")
            log.info("auto-opened browser -> http://127.0.0.1:%d/", port)
        _th.Thread(target=_open, daemon=True).start()

    def _keep_alive(port):
        """frozen 模式：app.run() 返回后保持进程存活，
        等用户手动关窗口（任务管理器结束 DroneSim.exe）。"""
        import time as _t
        log.info("frozen mode: app.run() returned, keeping process alive")
        try:
            while True:
                _t.sleep(1.0)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    port = _get_port()
    log.info("Drone Sim Frontend 启动，端口 %d，日志: %s", port, _LOG_FILE)
    log.info("资源: static=%s models=%s core=%s", _STATIC_DIR, _MODELS_DIR, _PROJECT_ROOT)

    if _FROZEN:
        _auto_open_browser(port)

    # 非 frozen 模式：服务在控制台运行，直接打印访问地址
    print()
    print("=" * 50)
    print(f"  Drone Sim Frontend 正在运行")
    print(f"  访问: http://localhost:{port}")
    print(f"  日志: {_LOG_FILE}")
    print(f"  按 Ctrl+C 停止，或关闭此窗口")
    print("=" * 50)
    print()
    try:
        app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
    finally:
        if _FROZEN:
            _keep_alive(port)
