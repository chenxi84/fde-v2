#!/bin/bash
# FDE v2 自动部署脚本
# 用法：bash scripts/deploy.sh <服务器IP> [用户名]
# 前提：已配置 SSH 免密登录

SERVER="${1:?请提供服务器IP}"
USER="${2:-root}"
REMOTE_DIR="/opt/fde-v2.2"

set -e

echo "=== 1. 推送本地代码到 Gitee ==="
git push origin master

echo "=== 2. 服务器拉取 + 重建 ==="
ssh "${USER}@${SERVER}" << 'ENDSSH'
set -e
cd /opt/fde-v2
echo ">>> git pull..."
git pull
echo ">>> docker-compose down..."
docker-compose down
echo ">>> docker-compose build..."
docker-compose build --no-cache 2>&1 | tail -3
echo ">>> docker-compose up..."
docker-compose up -d
echo ">>> 等待启动..."
sleep 8
echo ">>> 健康检查..."
curl -sk -o /dev/null -w "HTTPS: %{http_code}\n" https://127.0.0.1/ 2>/dev/null || echo "HTTPS 未就绪"
curl -s -o /dev/null -w "HTTP: %{http_code}\n" http://127.0.0.1:4000/ 2>/dev/null || echo "HTTP 未就绪"
echo "=== 部署完成 ==="
ENDSSH

echo ""
echo "=== 3. 运行冒烟测试 ==="
python scripts/smoke_test.py "${SERVER}"
