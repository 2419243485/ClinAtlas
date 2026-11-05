# ClinAtlas 医学知识库

企业级医学知识库系统，支持本地化部署，提供文档管理、语义检索和智能问答能力。

## 核心特性

- **多格式文档解析**：支持 PDF、DOCX，自动 OCR 识别扫描件
- **智能分块策略**：结构感知分块 + 父子块检索，兼顾精准度和上下文完整性
- **混合检索**：向量检索（bge-m3）+ BM25 关键词检索 + RRF 融合
- **精排优化**：bge-reranker-v2-m3 二次精排，过滤噪声结果
- **多语言支持**：内置医学术语标准化（中英文互译）和同义词扩展
- **多租户隔离**：科室级权限管理，数据严格隔离
- **流式问答**：SSE 实时推送，边生成边展示
- **完整审计**：操作日志全记录，满足医疗合规要求

## 技术架构

### 后端
- **API 层**：FastAPI + JWT 鉴权 + SSE 流式响应
- **离线处理**：Celery + Redis 异步任务队列
- **向量数据库**：Qdrant（父子双层索引）
- **关系数据库**：PostgreSQL（元数据 + 审计日志）
- **Embedding 模型**：bge-m3（多语言支持）
- **Rerank 模型**：bge-reranker-v2-m3

### 前端
- Vue 3 + Vite 6 + Element Plus + Pinia
- SSE 流式渲染，实时展示生成过程
- 响应式布局，支持多种屏幕尺寸

## 快速开始

### 环境要求
- Python 3.9+
- Docker & Docker Compose
- Node.js 18+（前端）

### 一键启动

```bash
# 1. 克隆项目
git clone <repo-url>
cd ClinAtlas

# 2. 后端启动（自动拉起 Docker 服务）
./scripts/start.sh

# 3. 前端启动（新终端）
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173

### 手动启动

```bash
# 启动依赖服务
docker compose -f config/docker-compose.yml up -d

# 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 初始化数据库（首次部署）
python scripts/init_db.py init

# 启动 Celery Worker
celery -A src.pipeline.tasks worker --loglevel=info &

# 启动 API 服务
uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# 启动前端（新终端）
cd frontend
npm install
npm run dev
```

## 默认账号

### 管理员
- 用户名：`admin`
- 密码：`admin123`
- 权限：全部功能 + 系统管理

### 测试账号（密码均为 `doc123` 或 `nurse123`）
- `doctor_internal` - 内科
- `doctor_surgery` - 外科
- `doctor_endocrine` - 内分泌科
- `doctor_cardio` - 心血管科
- `nurse_icu` - ICU
- `doctor_emergency` - 急诊科
- `pharmacist` - 药剂科
- `nurse_general` - 护理部

## 功能模块

### 1. 文档管理
- 上传 PDF/DOCX 文档（拖拽或点击）
- 按科室、文档类型筛选
- 文档归档（软删除，保留历史版本）
- 重新索引（更新向量库）

### 2. 知识问答
- 自然语言提问
- 按科室/文档类型筛选检索范围
- 流式生成回答（SSE）
- 展示参考来源（文件名、页码、相关度）
- 评分反馈

### 3. 系统管理（仅管理员）
- 统计看板：文档数、查询数、用户数
- 审计日志：操作类型、IP、时间

## 数据库管理

```bash
# 初始化数据库（创建租户和用户）
python scripts/init_db.py init

# 重置数据库（清空所有数据）
python scripts/init_db.py reset

# 创建示例文档
python scripts/init_db.py sample

# 查看迁移状态
python scripts/migrate_db.py status

# 执行数据库迁移
python scripts/migrate_db.py migrate
```

## API 文档

启动服务后访问：
- Swagger UI：http://localhost:8000/docs
- ReDoc：http://localhost:8000/redoc

### 核心接口

**登录**
```bash
POST /api/v1/auth/login
{
  "username": "admin",
  "password": "admin123"
}
```

**上传文档**
```bash
POST /api/v1/documents/upload
Content-Type: multipart/form-data

file: <binary>
department: 内分泌科
source_type: clinical_guideline
version: 1.0
```

**流式问答**
```bash
POST /api/v1/search/qa
Content-Type: application/json
Authorization: Bearer <token>

{
  "query": "胰岛素注射部位轮换原则？",
  "top_k": 5
}

# 响应流（sources 和 answer 的 data 为 JSON，token 中的换行已转义）
event: sources
data: [{"filename": "...", "relevance": 0.89, "text": "...", ...}]

event: answer
data: "胰岛素注射"

event: answer
data: "部位轮换\n"
...
event: done
data: [DONE]
```

## 配置说明

配置文件：`config/settings.yaml`

```yaml
# PostgreSQL
postgres_host: localhost
postgres_port: 5432
postgres_user: clinatlas
postgres_password: changeme
postgres_db: clinatlas

# Redis
redis_host: localhost
redis_port: 6379

# Qdrant
qdrant_host: localhost
qdrant_port: 6333

# Embedding 模型
embedding_model: BAAI/bge-m3
embedding_device: cuda  # 或 cpu
```

LLM 接口地址和密钥通过项目根目录的 `.env` 配置（参考 `.env.example`，`.env` 不提交到 git）：

```
LLM_BASE_URL=https://your-llm-gateway/api/v1
LLM_API_KEY=sk-xxx
```

## 项目结构

```
ClinAtlas/
├── config/
│   ├── settings.yaml           配置文件
│   └── docker-compose.yml      依赖服务编排
├── scripts/
│   ├── init_db.py              数据库初始化
│   ├── migrate_db.py           数据库迁移
│   ├── start.sh                一键启动
│   └── stop.sh                 一键停止
├── src/
│   ├── models/                 数据结构
│   ├── utils/                  工具函数
│   ├── pipeline/               离线处理流水线
│   │   ├── parsers/            文档解析器
│   │   ├── chunker.py          分块器
│   │   ├── embedder.py         向量化
│   │   ├── indexer.py          索引写入
│   │   └── tasks.py            Celery 任务
│   ├── retrieval/              在线检索链路
│   │   ├── preprocessor.py     Query 预处理
│   │   ├── searcher.py         混合检索
│   │   ├── reranker.py         精排
│   │   ├── expander.py         父子块扩展
│   │   ├── generator.py        LLM 生成
│   │   └── orchestrator.py     链路编排
│   └── api/                    API 层
│       ├── main.py             FastAPI 主入口
│       ├── middleware/         鉴权 + 审计
│       ├── routers/            路由
│       └── schemas/            请求/响应 Schema
├── frontend/                   前端
│   ├── src/
│   │   ├── views/              页面组件
│   │   ├── components/         公共组件
│   │   ├── api/                API 封装
│   │   ├── stores/             状态管理
│   │   └── router/             路由配置
│   └── package.json
├── docs/
│   └── technical-design.md     技术设计文档
├── requirements.txt            Python 依赖
└── README.md                   本文件
```

## 部署建议

### 生产环境
1. **修改默认密码**：数据库、Redis、管理员账号
2. **启用 HTTPS**：配置 Nginx 反向代理 + SSL 证书
3. **资源配置**：
   - Qdrant：至少 8GB 内存（百万级向量）
   - Embedding 模型：GPU 推荐 T4/V100（批量向量化）
   - LLM：8B 模型需 16GB 显存，72B 模型需 4×A100
4. **备份策略**：
   - PostgreSQL：每日全量备份
   - Qdrant：定期快照（数据目录挂载持久卷）
   - 文档存储：对象存储（MinIO/S3）
5. **监控告警**：
   - API 响应时间 P99 < 500ms
   - Celery 任务队列长度 < 100
   - GPU 显存利用率 < 90%

### 水平扩展
- **API 层**：多副本部署 + 负载均衡
- **Celery Worker**：按科室拆分队列，独立扩展
- **Qdrant**：分片部署（按租户/科室）

## 常见问题

### 1. Celery Worker 启动失败
检查 Redis 是否正常运行：
```bash
docker compose -f config/docker-compose.yml ps
redis-cli ping  # 应返回 PONG
```

### 2. 文档上传后状态一直是 processing
查看 Celery 日志：
```bash
tail -f logs/celery.log
```
常见原因：OCR 依赖（Tesseract）未安装

### 3. 检索结果为空
检查 Qdrant Collection 是否已创建：
```bash
curl http://localhost:6333/collections
```

### 4. LLM 生成失败
检查 LLM 服务是否可达：
```bash
curl http://localhost:8001/v1/models
```

## 许可证

MIT

## 联系方式

技术支持：请提交 Issue
