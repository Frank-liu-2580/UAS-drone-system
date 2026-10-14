# [EXPERIMENT ABANDONED 2026-10-14] 此 spec 因 PyInstaller 6.22.3 + 项目路径含空格
# 导致 datas 解包后全 0 字节（详 123/项目日志.txt 二十二节），打包方案已暂缓。
# 保留本文件仅为排查参考，当前双击 12/启动模拟系统.bat 或 demo.html 即可。
# 若重启 exe 打包：先试 PyInstaller 其他版本或 onedir 模式验证 datas 是否正常。
import os

# PyInstaller 注入 SPEC 变量（spec 文件路径）
_spec_dir  = os.path.dirname(os.path.abspath(SPEC))
_frontend  = _spec_dir
# 核心代码在 12/123/（drone_frontend 的同级父目录下的 123）
_12_root   = os.path.dirname(_spec_dir)        # 12/
_core_123  = os.path.join(_12_root, "123")     # 12/123/
_drone_ai  = os.path.join(_core_123, "drone_ai")
_drone_sim = os.path.join(_core_123, "drone_sim")

import shutil as _shutil

# ---------- 打包前 staging：把源文件复制到无空格目录，规避 0 字节 bug ----------
# PyInstaller 6.22.3 + Windows 实测：datas 源路径含空格（ai test）时生成 0 字节条目。
# 解决：先 copy2 到 drone_frontend/_dist_staging/（与 spec 同目录，无空格），
# 再指向 staging 副本作为 datas 源。
_staging_root = os.path.join(_frontend, "_dist_staging")
if os.path.isdir(_staging_root):
    _shutil.rmtree(_staging_root, ignore_errors=True)

def _stage(src_file, target_rel):
    t = target_rel.replace("/", os.sep)
    dst_dir = os.path.join(_staging_root, os.path.dirname(t))
    if dst_dir and not os.path.isdir(dst_dir):
        os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(_staging_root, t)
    _shutil.copy2(src_file, dst)
    datas.append((dst, target_rel))

# ---------- 核心代码 data 文件（staging 后打包）----------
datas = []
for src_root in [_drone_ai, _drone_sim]:
    if not os.path.isdir(src_root):
        continue
    for root, _dirs, files in os.walk(src_root):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith((".py", ".xlsx", ".md", ".txt")):
                src = os.path.join(root, f)
                rel = os.path.relpath(src, _core_123)
                _stage(src, rel)

# ---------- static 资源（staging）----------
static_dir = os.path.join(_frontend, "static")
for f in ["index.html", "app.js", "style.css"]:
    p = os.path.join(static_dir, f)
    if os.path.exists(p):
        _stage(p, os.path.join("static", f))

for f in ["three.min.js", "GLTFLoader.js"]:
    p = os.path.join(_frontend, f)
    if os.path.exists(p):
        _stage(p, f)

# ---------- models（staging）----------
models_dir = os.path.join(_frontend, "models")
if os.path.isdir(models_dir):
    for f in os.listdir(models_dir):
        if f.endswith((".glb", ".gltf", ".bin")):
            _stage(os.path.join(models_dir, f), os.path.join("models", f))

# ---------- demo.html（staging）----------
_demo_html = os.path.join(_frontend, "demo.html")
if os.path.exists(_demo_html):
    _stage(_demo_html, "demo.html")

# ---------- 验证：staging 文件必须非 0 字节 ----------
for src_path, rel in datas:
    sz = os.path.getsize(src_path)
    if sz == 0:
        raise RuntimeError("staging 源文件 0 字节，打包必失败: %s -> %s" % (src_path, rel))

a = Analysis(
    [os.path.join(_frontend, "server.py")],
    # pathex：让 server.py import drone_ai / drone_sim / ai_main 能找到
    # 额外把 drone_ai/analyzer 加进 pathex，让 weight_base.py 能作为顶层模块被 PyInstaller 打包
    pathex=[_frontend, _core_123, os.path.join(_core_123, "drone_ai"),
            os.path.join(_core_123, "drone_ai", "analyzer")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # 机载 AI 全部模块（含新增 route.py / smooth.py / sensing.py）
        "drone_ai", "drone_ai.serial_io", "drone_ai.trigger",
        "drone_ai.decision", "drone_ai.thresholds",
        "drone_ai.cruise", "drone_ai.obstacle",
        "drone_ai.sensing", "drone_ai.smooth",
        "drone_ai.route",
        "drone_ai.ai_main",
        # 飞行模拟器
        "drone_sim", "drone_sim.simulate",
        # ai_main 在包根单独 import
        "ai_main",
        # analyzer 子目录下的 weight_base.py：decision.py 通过 sys.path.insert 引入后
        # 执行 `from weight_base import ...`，PyInstaller 必须把它打包成可导入模块
        "weight_base",
        # 依赖
        "openpyxl",
        "flask", "werkzeug", "jinja2", "itsdangerous", "click", "markupsafe",
        # 标准库兜底
        "pathlib", "json", "re",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy", "pandas", "scipy",
        "PIL", "Pillow", "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="DroneSim",
    debug=False,
    strip=False,
    upx=False,
    console=False,      # 无黑窗口（server.py 内部有 logs/ 日志兜底）
    icon=None,
)
