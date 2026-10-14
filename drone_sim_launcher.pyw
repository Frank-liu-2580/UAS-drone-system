# -*- coding: utf-8 -*-
"""
drone_sim_launcher.pyw — 无人机影子 AI 决策系统 · 统一外壳
=============================================================
双击 launch_sim.bat（或直接双击本 .pyw）即可弹出一个图形菜单，
快捷打开系统核心内容：
  - 飞行模拟（控制台报告 / 写 xlsx）
  - 机载 AI 自检
  - 3D 离线演示（pywebview 小窗口）
  - 3D Web 后端（Flask + 浏览器）
  - 项目日志 / 爬虫数据目录
  - 目录结构说明

设计说明：
  - 放在 12/ 根目录（与 123/ 和 drone_frontend/ 同级），
    作为整个系统的统一入口。
  - 纯 tkinter（Python 内置，无需额外依赖）。
  - 子进程调用用 sys.executable 保证用同一个 Python 解释器。
  - 每个"跑 Python"类动作都在子窗口里显示输出，不阻塞菜单。
"""
import os
import sys
import subprocess
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, scrolledtext

# ============================================================
# 路径定位（始终定位到本文件所在目录 = 12/）
# ============================================================
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT_123 = os.path.join(_HERE, "123")
_CORE = _ROOT_123                      # 核心代码目录（drone_ai / drone_sim / drone_crawler）
_FRONTEND = os.path.join(_HERE, "drone_frontend")
_SIM_DIR = os.path.join(_CORE, "drone_sim")
_AI_DIR = os.path.join(_CORE, "drone_ai")
_CRAWLER_DIR = os.path.join(_CORE, "drone_crawler")
_SIM_PY = os.path.join(_SIM_DIR, "simulate.py")
_AI_MAIN_PY = os.path.join(_AI_DIR, "ai_main.py")
_LOG_TXT = os.path.join(_CORE, "项目日志.txt")
_CRAWLER_DATA = os.path.join(_CRAWLER_DIR, "data")
_FRONT_DEMO_PYW = os.path.join(_FRONTEND, "launch_app.pyw")
_FRONT_SERVER_PY = os.path.join(_FRONTEND, "start_server.py")
_PY = sys.executable                    # 用当前解释器跑子进程


def _ensure_path(p, label):
    """启动时校验关键路径存在，缺了给出提示但不阻断。"""
    missing = []
    for path, name in [
        (_SIM_PY, "飞行模拟器 simulate.py"),
        (_AI_MAIN_PY, "机载 AI ai_main.py"),
        (_FRONT_DEMO_PYW, "3D 离线演示 launch_app.pyw"),
        (_FRONT_SERVER_PY, "3D Web 后端 start_server.py"),
        (_LOG_TXT, "项目日志.txt"),
    ]:
        if not os.path.exists(path):
            missing.append(f"{name}\n  ({path})")
    return missing


# ============================================================
# 主窗口
# ============================================================
class LauncherApp:
    def __init__(self, root):
        self.root = root
        root.title("无人机影子 AI 决策系统 · 启动器")
        root.resizable(False, False)
        # 居中
        root.update_idletasks()
        w, h = 460, 300
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 2
        root.geometry(f"{w}x{h}+{x}+{y}")

        # 顶部标题
        tk.Label(
            root, text="无人机影子 AI 决策系统",
            font=("Microsoft YaHei", 14, "bold"),
        ).pack(pady=(12, 2))
        tk.Label(
            root, text=f"工作目录：{_HERE}",
            font=("Consolas", 9), fg="#666",
        ).pack(pady=(0, 10))

        # 按钮网格
        frame = tk.Frame(root)
        frame.pack(padx=18, pady=(0, 10))

        self._buttons = [
            ("① 飞行模拟（控制台报告）", self.run_sim_stdout, False),
            ("② 飞行模拟（写 xlsx）", self.run_sim_xlsx, False),
            ("③ 机载 AI 自检", self.run_ai_selftest, False),
            ("④ 3D 离线演示（小窗口）", self.open_3d_demo, True),
            ("⑤ 3D Web 后端 + 浏览器", self.open_3d_web, True),
            ("⑥ 项目日志", self.open_log, True),
            ("⑦ 爬虫数据目录", self.open_crawler_data, True),
            ("⑧ 目录结构说明", self.show_about, True),
        ]
        for i, (label, cmd, is_ext) in enumerate(self._buttons):
            col = i % 2
            row = i // 2
            bg = "#eef6ff" if not is_ext else "#fff8ee"
            b = tk.Button(
                frame, text=label, command=cmd,
                font=("Microsoft YaHei", 10),
                bg=bg, activebackground="#d0e8ff",
                relief="flat", bd=0, padx=14, pady=8,
                anchor="w", cursor="hand2",
            )
            b.grid(row=row, column=col, padx=6, pady=4, sticky="ew")
        # 让两列等宽
        for c in range(2):
            frame.columnconfigure(c, weight=1)

        # 底部提示
        self.status_var = tk.StringVar(value="就绪")
        tk.Label(root, textvariable=self.status_var,
                 font=("Microsoft YaHei", 9), fg="#888",
                 anchor="w").pack(padx=18, pady=(0, 8), side="bottom")

        # 启动校验
        missing = _ensure_path(_HERE, "core")
        if missing:
            self.status_var.set("部分文件缺失")
            tk.Label(root, text="以下核心文件缺失，对应功能可能不可用：\n"
                                + "\n".join(missing[:3]) + "…",
                     font=("Microsoft YaHei", 8), fg="#c00",
                     anchor="w").pack(padx=18, pady=(0, 4), side="bottom")

    # ---------------- 子进程通用 ----------------
    def _run_subprocess(self, args, title, show_window=True):
        """在子线程里跑 subprocess，结束后在输出窗口显示结果。"""
        def _job():
            self.status_var.set(f"运行中：{title} ...")
            self.root.update()
            try:
                r = subprocess.run(
                    args, capture_output=True, text=True,
                    cwd=_CORE, timeout=300,
                )
                out = (r.stdout or "") + (r.stderr or "")
                self._show_output(title, out, r.returncode)
            except Exception as e:
                self._show_output(title, f"[ERROR] {e}", 1)
            self.status_var.set("完成")
        if show_window:
            threading.Thread(target=_job, daemon=True).start()
        else:
            _job()

    def _show_output(self, title, text, rc):
        """弹出一个只读文本窗口显示子进程输出。"""
        win = tk.Toplevel(self.root)
        win.title(f"输出 · {title}")
        win.geometry("760x480")
        win.resizable(True, True)
        txt = scrolledtext.ScrolledText(win, wrap="word", font=("Consolas", 9))
        txt.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        txt.insert("end", text if text.strip() else "(无输出)")
        txt.configure(state="disabled")
        # 底部状态 + 关闭
        bar = tk.Frame(win); bar.pack(fill="x", padx=8, pady=(0, 8))
        color = "green" if rc == 0 else "red"
        tk.Label(bar, text=f"退出码 {rc}", fg=color,
                 font=("Microsoft YaHei", 9)).pack(side="left")
        tk.Button(bar, text="关闭", command=win.destroy,
                  font=("Microsoft YaHei", 9)).pack(side="right")
        self.root.update()

    # ---------------- ① 飞行模拟 · 控制台报告 ----------------
    def run_sim_stdout(self):
        mins = simpledialog.askstring(
            "模拟时长", "模拟分钟数（默认 8）：",
            initialvalue="8", parent=self.root)
        mins = mins.strip() if mins else "8"
        seed = simpledialog.askstring(
            "随机种子（留空=每次不同）", "seed（可留空）：", parent=self.root)
        args = [_PY, _SIM_PY, "--minutes", mins, "--stdout"]
        if seed and seed.strip():
            args += ["--seed", seed.strip()]
        self._run_subprocess(args, f"飞行模拟 {mins}min")

    # ---------------- ② 飞行模拟 · 写 xlsx ----------------
    def run_sim_xlsx(self):
        mins = simpledialog.askstring(
            "模拟时长", "模拟分钟数（默认 8）：",
            initialvalue="8", parent=self.root)
        mins = mins.strip() if mins else "8"
        seed = simpledialog.askstring(
            "随机种子（留空=每次不同）", "seed（可留空）：", parent=self.root)
        out = os.path.join(_CORE, "sim_output.xlsx")
        args = [_PY, _SIM_PY, "--minutes", mins, "--out", out]
        if seed and seed.strip():
            args += ["--seed", seed.strip()]
        self._run_subprocess(args, f"飞行模拟写盘 {mins}min")

    # ---------------- ③ 机载 AI 自检 ----------------
    def run_ai_selftest(self):
        self._run_subprocess([_PY, _AI_MAIN_PY], "机载 AI 自检")

    # ---------------- ④ 3D 离线演示 ----------------
    def open_3d_demo(self):
        if not os.path.exists(_FRONT_DEMO_PYW):
            messagebox.showwarning("缺少文件", f"找不到：\n{_FRONT_DEMO_PYW}")
            return
        # 用 pythonw 避免黑窗口
        pyw = os.path.join(os.path.dirname(_PY), "pythonw.exe")
        exe = pyw if os.path.exists(pyw) else _PY
        subprocess.Popen([exe, _FRONT_DEMO_PYW], cwd=_FRONTEND)
        self.status_var.set("已启动 3D 离线演示（小窗口）")

    # ---------------- ⑤ 3D Web 后端 + 浏览器 ----------------
    def open_3d_web(self):
        if not os.path.exists(_FRONT_SERVER_PY):
            messagebox.showwarning("缺少文件", f"找不到：\n{_FRONT_SERVER_PY}")
            return
        # 直接起 server.py（start_server.py 会阻塞挂住子进程，导致浏览器永不开）
        server_py = os.path.join(_FRONTEND, "server.py")
        if os.path.exists(server_py):
            proc = subprocess.Popen([_PY, server_py, "5000"], cwd=_FRONTEND)
        else:
            proc = subprocess.Popen([_PY, _FRONT_SERVER_PY], cwd=_FRONTEND)
        self.status_var.set("已启动 Flask 后端，3 秒后打开浏览器 ...")
        def _open_browser():
            webbrowser.open("http://127.0.0.1:5000/")
            self.status_var.set("浏览器已打开（后端运行中）")
        threading.Timer(3.0, _open_browser).start()

    # ---------------- ⑥ 项目日志 ----------------
    def open_log(self):
        if not os.path.exists(_LOG_TXT):
            messagebox.showwarning("缺少文件", f"找不到：\n{_LOG_TXT}")
            return
        os.startfile(_LOG_TXT)
        self.status_var.set("已打开项目日志")

    # ---------------- ⑦ 爬虫数据目录 ----------------
    def open_crawler_data(self):
        if not os.path.isdir(_CRAWLER_DATA):
            messagebox.showwarning("缺少目录", f"找不到：\n{_CRAWLER_DATA}")
            return
        os.startfile(_CRAWLER_DATA)
        self.status_var.set("已打开爬虫数据目录")

    # ---------------- ⑧ 目录结构说明 ----------------
    def show_about(self):
        text = f"""目录结构
==========
{_HERE}
├─ 123/                  # 核心代码
│   ├─ drone_ai/         #   机载 AI（ai_main / trigger / decision /
│   │                    #   cruise / obstacle / route / sensing / smooth /
│   │                    #   serial_io / thresholds）
│   ├─ drone_sim/        #   飞行模拟器（simulate.py / run_sim.py / .bat）
│   ├─ drone_crawler/    #   爬虫 + 数据（data/raw/）
│   ├─ sim_output.xlsx   #   模拟器 xlsx 输出
│   └─ 项目日志.txt       #   整合日志
└─ drone_frontend/       # 3D Web 前端
    ├─ server.py         #   Flask 后端
    ├─ demo.html         #   离线演示（含演示数据 + three.min.js）
    ├─ launch_app.pyw    #   pywebview 小窗口启动器
    └─ start_server.py   #   Flask + 浏览器启动器

依赖
====
核心：openpyxl（写 xlsx）
前端：flask（Web）/ pywebview（离线演示窗口）
爬虫：requests / beautifulsoup4 / lxml / yt-dlp
真实串口：pyserial（上机才需要）
统一清单见 123/requirements.txt
"""
        win = tk.Toplevel(self.root)
        win.title("目录结构 · 关于")
        win.geometry("680x520")
        t = scrolledtext.ScrolledText(win, wrap="word", font=("Consolas", 9))
        t.pack(fill="both", expand=True, padx=8, pady=8)
        t.insert("end", text)
        t.configure(state="disabled")


# ============================================================
# 入口
# ============================================================
def main():
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
