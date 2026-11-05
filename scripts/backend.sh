#!/bin/bash
# ClinAtlas 后端一键启动脚本
# 职责：启动依赖服务 → 激活 venv → 初始化数据库（首次）→ 启动 Celery → 启动 uvicorn

set -e
cd "$(dirname "$0")/.."
PROJECT_DIR=$(pwd)

echo "==========================================="
echo "  ClinAtlas 后端启动"
echo "  目录: $PROJECT_DIR"
echo "==========================================="

# ── 1. 检测 compose 命令 ────────────────────────────────
if docker compose version &>/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE="docker-compose"
else
    echo "❌ 未找到 docker compose，请先执行: brew install docker-compose"
    exit 1
fi
echo "✓ compose: $COMPOSE"

# ── 2. 确保 Docker 守护进程在运行 ───────────────────────
if ! docker info &>/dev/null 2>&1; then
    echo "⚠️  Docker 未运行，尝试启动 Colima..."
    if command -v colima &>/dev/null; then
        colima start
    else
        echo "❌ Docker 未运行且未找到 Colima，请手动启动 Docker"
        exit 1
    fi
fi
echo "✓ Docker 已运行"

# ── 3. 启动依赖服务 ─────────────────────────────────────
echo ""
echo "启动依赖服务..."
$COMPOSE -f config/docker-compose.yml up -d postgres redis qdrant

# 等待 postgres 健康（最多 30 秒）
echo -n "等待 PostgreSQL 就绪"
for i in $(seq 1 15); do
    if $COMPOSE -f config/docker-compose.yml ps postgres 2>/dev/null | grep -q "healthy"; then
        echo "  ✓"
        break
    fi
    echo -n "."
    sleep 2
    if [ $i -eq 15 ]; then
        echo "  ⚠️  超时，继续执行（pg 可能仍在初始化）"
    fi
done

# ── 4. 激活虚拟环境 ─────────────────────────────────────
if [ ! -f "venv/bin/activate" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
    source venv/bin/activate
    echo "安装依赖..."
    pip install -q --upgrade pip
    pip install -q -r requirements.txt
else
    source venv/bin/activate
fi
echo "✓ 虚拟环境已激活: $(python --version)"

# ── 5. 首次运行时初始化数据库 ───────────────────────────
mkdir -p data logs
if [ ! -f "data/.db_initialized" ]; then
    echo ""
    echo "首次运行，初始化数据库..."
    # init_db.py 自包含建表和插数据逻辑
    python scripts/init_db.py init
    touch data/.db_initialized
    echo "✓ 数据库初始化完成"
else
    echo "✓ 数据库已初始化（跳过）"
fi

# ── 6. 启动 Celery Worker（后台）───────────────────────
echo ""
echo "启动 Celery Worker..."
celery -A src.pipeline.tasks worker \
    --loglevel=info \
    --logfile=logs/celery.log \
    --pidfile=logs/celery.pid &
CELERY_PID=$!
echo "✓ Celery Worker PID: $CELERY_PID（日志: logs/celery.log）"

# ── 7. 清理函数 ─────────────────────────────────────────
cleanup() {
    echo ""
    echo "正在停止服务..."
    kill "$CELERY_PID" 2>/dev/null && echo "  Celery 已停止" || true
    $COMPOSE -f config/docker-compose.yml stop 2>/dev/null && echo "  Docker 服务已停止" || true
    exit 0
}
trap cleanup INT TERM

# ── 8. 启动 uvicorn（前台）─────────────────────────────
echo ""
echo "启动 API 服务..."
echo "  地址:   http://localhost:8000"
echo "  文档:   http://localhost:8000/docs"
echo "  Ctrl+C 停止所有服务"
echo ""

uvicorn src.api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level info
