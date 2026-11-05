#!/bin/bash
# ClinAtlas 一键启动脚本

set -e

echo "========================================="
echo "  ClinAtlas 医学知识库 - 启动脚本"
echo "========================================="

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 未检测到 Python 3，请先安装"
    exit 1
fi
echo "✓ Python 版本: $(python3 --version | awk '{print $2}')"

# 检测可用的 docker compose 命令
detect_compose() {
    if docker compose version &> /dev/null 2>&1; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
    else
        echo "❌ 未检测到 docker compose，请安装 Docker Compose"
        echo "  安装方式：brew install docker-compose"
        exit 1
    fi
    echo "✓ Compose 命令: $COMPOSE_CMD"
}

detect_compose

# 确保 Docker 守护进程在运行（Colima / Docker Desktop 均支持）
ensure_docker_running() {
    if ! docker info &> /dev/null 2>&1; then
        echo "⚠️  Docker 守护进程未运行，尝试启动..."
        # 优先尝试 Colima（macOS 常见）
        if command -v colima &> /dev/null; then
            echo "  启动 Colima..."
            colima start
            # 再次检查
            if ! docker info &> /dev/null 2>&1; then
                echo "❌ Colima 启动后仍无法连接 Docker"
                exit 1
            fi
            echo "✓ Colima 已启动"
        else
            echo "❌ Docker 守护进程未运行，且未检测到 Colima"
            echo "  请手动启动 Docker Desktop 或执行：colima start"
            exit 1
        fi
    fi
}

ensure_docker_running

# 切换到项目根目录
cd "$(dirname "$0")/.."
PROJECT_DIR=$(pwd)
echo "✓ 项目目录: $PROJECT_DIR"

# 检查 docker-compose.yml 是否存在
if [ ! -f "config/docker-compose.yml" ]; then
    echo "❌ config/docker-compose.yml 不存在"
    exit 1
fi

# 启动依赖服务
echo ""
echo "启动依赖服务（PostgreSQL / Redis / Qdrant / MinIO）..."
$COMPOSE_CMD -f config/docker-compose.yml up -d

echo "等待服务就绪..."
# 轮询等待 PostgreSQL 就绪
for i in $(seq 1 30); do
    if $COMPOSE_CMD -f config/docker-compose.yml ps postgres 2>/dev/null | grep -q "healthy"; then
        echo "✓ PostgreSQL 已就绪"
        break
    fi
    sleep 2
    if [ $i -eq 30 ]; then
        echo "⚠️  PostgreSQL 启动超时，继续执行..."
    fi
done

# 创建虚拟环境
if [ ! -d "venv" ]; then
    echo ""
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "安装 Python 依赖..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# 初始化数据库
echo ""
read -p "是否需要初始化数据库（创建租户和管理员账号）？首次部署选 y [y/N]: " init_db
if [[ "$init_db" =~ ^[Yy]$ ]]; then
    python scripts/init_db.py init
fi

# 启动 Celery Worker（后台）
echo ""
echo "启动 Celery Worker..."
mkdir -p logs
celery -A src.pipeline.tasks worker --loglevel=info --logfile=logs/celery.log &
CELERY_PID=$!
echo "✓ Celery Worker PID: $CELERY_PID"

# 启动 API 服务
echo ""
echo "启动 FastAPI 服务..."
echo "  API 地址: http://localhost:8000"
echo "  API 文档: http://localhost:8000/docs"
echo ""

# Ctrl+C 退出时自动停止 Celery 和依赖服务
trap "echo ''; echo '正在停止服务...'; kill $CELERY_PID 2>/dev/null; $COMPOSE_CMD -f config/docker-compose.yml stop; exit" INT TERM

uvicorn src.api.main:app --host 0.0.0.0 --port 8000
