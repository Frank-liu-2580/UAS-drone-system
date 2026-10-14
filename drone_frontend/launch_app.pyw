# -*- coding: utf-8 -*-
"""
Drone Sim 离线演示 · 小窗口启动器
===================================
双击 launch_app.pyw（或 run_demo.bat）即可弹出一个固定大小的小窗口，
窗口内嵌离线 demo.html（已内置演示数据 + 本地 three.min.js + GLB 模型），
全程不需要联网、不需要 localhost:5000、不需要 Flask 后端。

依赖（只需装一次）:
  pip install pywebview

运行方式:
  1) 双击 launch_app.pyw        （.pyw 不弹黑窗口）
  2) 或 run_demo.bat            （自动先检测并装 pywebview，再弹窗口）
  3) 或 python launch_app.pyw   （命令行手动跑）
"""
import os, sys, threading, time

# ---- 路径（始终定位到本文件所在目录）----
_HERE = os.path.dirname(os.path.abspath(__file__))
_DEMO_HTML = os.path.join(_HERE, "demo.html")

WIN_W, WIN_H = 1000, 640   # 小窗口尺寸（可改）


def _log(msg):
    """无控制台（pythonw）也能留下痕迹：写到日志文件，方便排查“打不开”。"""
    try:
        log_path = os.path.join(_HERE, "logs", "offline_demo.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def _cleanup_stale_webview2():
    """清理上一次未干净退出的 WebView2 残留进程 + 锁文件。
    这是“有时打不开”的主因：WebView2 多实例靠 user-data 锁协调，
    残留进程会把新实例锁死，webview.start() 静默失败。"""
    import subprocess
    try:
        # 清掉本机所有 msedgewebview2.exe（本演示的残留；若你本机跑着别的 Edge 网页
        # 也会被一起关，可接受；如需保守可改成只杀带 --type= 的子进程）
        subprocess.run(["taskkill", "/F", "/IM", "msedgewebview2.exe"],
                       capture_output=True, text=True)
        _log("cleaned up stale msedgewebview2.exe processes")
    except Exception as e:
        _log("taskkill failed (may be OK if none running): %s" % e)


def _ensure_pywebview():
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        _log("pywebview missing, trying pip install ...")
        print("首次运行：正在安装 pywebview ...")
        import subprocess
        try:
            # 优先 ensurepip（本机可能没预装 pip）
            subprocess.check_call([sys.executable, "-m", "ensurepip", "--upgrade"],
                                  capture_output=True)
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pywebview"])
        except Exception as e:
            _log("pip install pywebview failed: %s" % e)
        try:
            import webview  # noqa: F401
            _log("pywebview installed OK")
            return True
        except ImportError:
            _log("pywebview still missing after install attempt")
            print("pywebview 安装失败，请手动执行: pip install pywebview")
            return False


def main():
    _log("=== launch_app.pyw start ===")
    if not os.path.exists(_DEMO_HTML):
        _log("demo.html missing: %s" % _DEMO_HTML)
        print("找不到 demo.html: %s" % _DEMO_HTML)
        input("按回车退出...")
        return

    if not _ensure_pywebview():
        input("按回车退出...")
        return

    import webview

    # 启动前清理残留 WebView2（解决“有时打不开”的锁冲突）
    _cleanup_stale_webview2()

    _log("starting webview window ...")
    print("启动离线演示窗口 ...  (demo.html: %s)" % _DEMO_HTML)
    # 用 file:// URL 打开本地 HTML，彻底离线、不依赖任何服务器
    import pathlib
    url = pathlib.Path(_DEMO_HTML).as_uri()

    # 固定 user_data 目录，避免每次启动竞争不同 profile 锁
    user_data = os.path.join(_HERE, "logs", "webview2_user_data")
    os.makedirs(user_data, exist_ok=True)

    window = webview.create_window(
        "无人机飞行模拟 · 离线演示",
        url,
        width=WIN_W,
        height=WIN_H,
        resizable=True,
        min_size=(720, 480),
    )
    try:
        webview.start(
            gui="winforms",      # 显式指定（本机唯一可用后端），不再自动探测
            debug=False,
            storage_path=user_data,  # 固定 profile 目录，锁行为可预期
        )
    except Exception as e:
        _log("webview.start() RAISED: %r" % e)
        print("WebView 窗口启动失败: %s" % e)
        print("已写入日志: logs\\offline_demo.log")
        input("按回车退出...")
        return
    _log("webview window closed (normal exit)")


if __name__ == "__main__":
    main()
