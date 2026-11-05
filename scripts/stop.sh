#!/bin/bash
# 停止所有 ClinAtlas 服务

set -e

echo "正在停止 ClinAtlas 服务..."

# 检测可用的 compose 命令
if docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    COMPOSE_CMD=""
fi

# 停止 Celery Worker
echo "停止 Celery Worker..."
pkill -f "celery -A src.pipeline.tasks worker" || echo "Celery Worker 未运行"

# 停止 Uvicorn
echo "停止 Uvicorn..."
pkill -f "uvicorn src.api.main:app" || echo "Uvicorn 未运行"

# 停止 Docker 依赖服务
cd "$(dirname "$0")/.."
if [ -n "$COMPOSE_CMD" ]; then
    echo "停止 Docker 服务..."
    $COMPOSE_CMD -f config/docker-compose.yml down
else
    echo "⚠️  未找到 compose 命令，跳过 Docker 服务停止"
fi

echo "✓ 所有服务已停止"
