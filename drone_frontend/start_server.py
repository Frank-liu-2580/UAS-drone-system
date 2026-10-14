"""启动 Flask 服务（保持运行），然后测试 API。
用法:
  先运行本脚本启动服务（会阻塞）:
    python start_server.py
  或在另一个终端运行:
    python server.py 5000
"""
import subprocess, sys, time, urllib.request, json, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("启动 Flask 服务...")
proc = subprocess.Popen(
    [sys.executable, "server.py", "5000"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)
time.sleep(3)

# 健康检查
try:
    r = urllib.request.urlopen("http://localhost:5000/health", timeout=5)
    print("健康检查:", r.status, r.read().decode())
except Exception as e:
    print("健康检查失败:", e)
    proc.terminate()
    sys.exit(1)

# 测试模拟 API（4分钟，种子42）
print("测试 /api/sim?minutes=4&seed=42 ...")
try:
    r = urllib.request.urlopen("http://localhost:5000/api/sim?minutes=4&seed=42", timeout=90)
    data = json.loads(r.read().decode())
    print(f"  events: {len(data['events'])}")
    print(f"  ticks:  {len(data['ticks'])}")
    print(f"  pos:    {len(data['position_seq'])}")
    print(f"  fingerprint: {data['fingerprint'][:80]}")
    for e in data["events"][:5]:
        print(f"    #{e['id']} t={e['start_s']}s dur={e['dur_s']}s {e['name_cn']}")
    print("  raining frames:", sum(1 for p in data["position_seq"] if p["raining"]))
    print("API 测试通过 ✓")
except Exception as e:
    print("API 测试失败:", e)

print("\n服务运行中 (PID: %d)，按 Ctrl+C 停止..." % proc.pid)
try:
    proc.wait()
except KeyboardInterrupt:
    proc.terminate()
    proc.wait()
    print("\n服务已停止")
