#!/usr/bin/env bash
# 启动 Flask 服务（保持运行），然后测试 API
set -e

cd "$(dirname "$0")"

PORT="${1:-5000}"
echo "启动 Flask 服务 (端口 $PORT)..."
python server.py "$PORT" &
SERVER_PID=$!

# 等待服务就绪
sleep 2

echo "健康检查..."
curl -s "http://localhost:$PORT/health" && echo

echo "测试 /api/sim?minutes=4&seed=42 ..."
curl -s "http://localhost:$PORT/api/sim?minutes=4&seed=42" | python -c "
import sys, json
data = json.load(sys.stdin)
print(f'  events: {len(data[\"events\"])}')
print(f'  ticks:  {len(data[\"ticks\"])}')
print(f'  pos_seq:{len(data[\"position_seq\"])}')
print(f'  raining frames: {sum(1 for p in data[\"position_seq\"] if p[\"raining\"])}')
print('API 测试通过 ✓')
"

echo ""
echo "服务运行中 (PID: $SERVER_PID)，按 Ctrl+C 停止..."
wait $SERVER_PID
