# -*- coding: utf-8 -*-
"""下载无人机 3D 模型 (GLB) 到本地 models 目录。
优先用户列出的网站；若网站需登录/无直链，则使用稳定 CDN（threejs.org / raw.githubusercontent）兜底。
"""
import os, sys, urllib.request, ssl

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
os.makedirs(MODELS_DIR, exist_ok=True)

# 先创建 ssl 上下文跳过证书验证（有些 CDN 证书链问题）
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# 候选源（按优先级）：均为可直接 GET 的 GLB 文件
CANDIDATES = [
    # 1. threejs.org 官方示例的 drone.glb（稳定、无鉴权、MIT 示例模型）
    "https://threejs.org/examples/models/gltf/drone/drone.glb",
    # 2. three.js 官方仓库 raw
    "https://raw.githubusercontent.com/mrdoob/three.js/dev/examples/models/gltf/drone/drone.glb",
]

TARGET = os.path.join(MODELS_DIR, "drone.glb")

for url in CANDIDATES:
    print("尝试:", url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            data = r.read()
        if len(data) > 1000 and data[:4] in (b"\x46\x54\x6c\x66", b"glTF") or data[:2] == b"gl":
            with open(TARGET, "wb") as f:
                f.write(data)
            print("  下载成功:", len(data), "bytes ->", TARGET)
            sys.exit(0)
        else:
            print("  数据异常（可能不是 GLB）:", len(data), "bytes, head=", data[:16])
    except Exception as e:
        print("  失败:", e)
        continue

# 若都没成功，回退：用程序化建模（不依赖外部模型）
print("\n[回退] 所有在线源失败，使用程序化建模，跳过 GLB 下载。")
sys.exit(0)
