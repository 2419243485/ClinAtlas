# ClinAtlas 医学知识库 — 技术实现文档

**版本**：v1.0  
**日期**：2026-11-03  
**定位**：面向医院本地化部署的通用型国际化 RAG 医学知识库

---

## 目录

1. [系统概览](#1-系统概览)
2. [整体架构](#2-整体架构)
3. [离线侧：文档处理流水线](#3-离线侧文档处理流水线)
4. [在线侧：检索增强生成链路](#4-在线侧检索增强生成链路)
5. [数据模型设计](#5-数据模型设计)
6. [API 接口设计](#6-api-接口设计)
7. [权限与安全](#7-权限与安全)
8. [部署架构](#8-部署架构)
9. [技术栈汇总](#9-技术栈汇总)
10. [非功能性指标](#10-非功能性指标)

---

## 1. 系统概览

### 1.1 产品定位

ClinAtlas 是一个部署在医院内网的 RAG 医学知识库平台，支持医护人员以自然语言检索院内规程、临床指南、药品手册、诊断标准等文档，同时支持客户自主上传和管理文档。

### 1.2 核心场景

| 场景 | 描述 |
|------|------|
| 临床问答 | 医护人员输入临床问题，系统返回精准的知识段落和来源 |
| 文档检索 | 支持模糊语义检索，找到相关指南或规范 |
| 多语言查询 | 支持中文、英文及其他语言混合查询 |
| 文档管理 | 管理员上传、分类、版本管理文档 |

### 1.3 设计原则

- **本地化优先**：所有模型和服务运行在院内，数据不出院
- **多语言**：支持中英文及多语言医学术语查询
- **合规**：完整的审计日志和数据版本管理
- **可观测**：检索成功率、响应时间全链路监控

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端（Vue 3）                         │
│         文档管理  |  知识问答  |  检索历史  |  系统配置       │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP/SSE
┌────────────────────────▼────────────────────────────────────┐
│                    API 网关（FastAPI）                        │
│          鉴权 | 限流 | 路由 | 审计日志 | 链路追踪            │
└──────────┬──────────────────────────┬───────────────────────┘
           │                          │
┌──────────▼──────────┐   ┌───────────▼─────────────────────┐
│    离线处理服务       │   │          在线检索服务             │
│  (Celery Worker)    │   │          (FastAPI)               │
│                     │   │                                  │
│ 1. 文档解析          │   │ 1. Query 改写 & 扩展             │
│ 2. 清洗 & 预处理     │   │ 2. 混合检索（向量 + BM25）       │
│ 3. 结构感知分块      │   │ 3. Rerank 精排                  │
│ 4. Embedding 向量化  │   │ 4. 父子块扩展                   │
│ 5. 写入向量库        │   │ 5. Context 组装 & 生成           │
└──────────┬──────────┘   └───────────┬─────────────────────┘
           │                          │
┌──────────▼──────────────────────────▼───────────────────────┐
│                          存储层                              │
│                                                             │
│  Qdrant（向量 + 元数据）  PostgreSQL（文档管理/权限/审计）    │
│  Redis（缓存/任务队列）   MinIO（原始文件）                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 离线侧：文档处理流水线

### 3.1 支持格式

| 格式 | 解析方案 |
|------|----------|
| PDF（数字版） | PyMuPDF（fitz）|
| PDF（扫描版） | PyMuPDF + PaddleOCR |
| DOCX / DOC | python-docx |
| XLSX / CSV | pandas + openpyxl |
| HTML | BeautifulSoup4 |
| TXT / MD | 直接读取 |
| PPTX | python-pptx |

### 3.2 Step 1：文档解析与清洗

**流程**：

```
原始文件
  │
  ├─ 格式检测
  │
  ├─ 解析引擎选择
  │     ├─ 数字 PDF → PyMuPDF 直接提取
  │     └─ 扫描 PDF → PaddleOCR（中英文双模型）
  │
  ├─ 结构提取
  │     ├─ 标题层级（H1/H2/H3）
  │     ├─ 表格（保留为结构化文本）
  │     ├─ 列表项
  │     └─ 图片标题（ALT 文本和 Caption）
  │
  └─ 文本清洗
        ├─ 去除页眉页脚
        ├─ 去除多余空白/换行
        ├─ 修复编码问题（GBK/UTF-8）
        └─ 医学术语标准化（ICD-10 / SNOMED CT 映射）
```

**医学术语标准化示例**：

```python
TERM_NORMALIZATION = {
    "DM":  "Diabetes Mellitus（糖尿病）",
    "HTN": "Hypertension（高血压）",
    "感冒": "上呼吸道感染",
    "心梗": "急性心肌梗死",
}
```

**元数据提取**：每个文档解析后记录以下字段：

```json
{
  "doc_id":       "uuid-v4",
  "filename":     "临床指南_2026.pdf",
  "upload_by":    "admin_user_id",
  "upload_at":    "2026-11-03T08:00:00Z",
  "department":   "内科",
  "language":     "zh",
  "version":      "1.0",
  "source_type":  "clinical_guideline",
  "checksum":     "sha256:...",
  "page_count":   45
}
```

### 3.3 Step 2：结构感知分块

**分块策略**：采用「结构感知 + 语义辅助」双层策略。

**核心思路**：
1. 优先按文档标题层级切分，保证每个 chunk 语义完整
2. 超长段落二次用滑动窗口切分
3. 表格和列表作为不可拆分的完整块处理
4. 同时生成父块和子块（用于父子块检索）

**参数配置**：

```yaml
chunking:
  # 子块（用于精准检索）
  child_chunk_size: 256        # tokens
  child_chunk_overlap: 50      # tokens，约 20% overlap

  # 父块（传给 LLM 保证上下文完整）
  parent_chunk_size: 1024      # tokens
  parent_chunk_overlap: 100    # tokens

  # 不可拆分类型
  atomic_types:
    - table          # 整张表格作为一个块
    - list           # 完整列表项作为一个块
    - code_block     # 代码/公式块

  # 医学文档专项
  section_boundary_keywords:
    - "适应症"
    - "禁忌症"
    - "用法用量"
    - "注意事项"
    - "Indications"
    - "Contraindications"
    - "Dosage"
```

**父子块关联存储**：

```
[父块 ID: parent_001]
  ├─ [子块 ID: child_001_a]  tokens: 0-256
  ├─ [子块 ID: child_001_b]  tokens: 206-462   (overlap: 50)
  └─ [子块 ID: child_001_c]  tokens: 412-668   (overlap: 50)
```

子块向量化用于检索，命中子块后向上查找父块传给 LLM。

### 3.4 Step 3：Embedding 向量化

**模型选型**：`bge-m3`（BAAI/bge-m3）

| 维度 | 说明 |
|------|------|
| 多语言支持 | 支持 100+ 语言，中英文效果尤佳 |
| 模型大小 | 567M 参数，CPU 可运行，有 GPU 加速效果更好 |
| 向量维度 | 1024 维 |
| 上下文长度 | 最大 8192 tokens |
| 医学场景 | BEIR/MTEB 医学子集排名前列 |
| 授权 | MIT License，可商用 |

**备选方案**：`multilingual-e5-large`（微软，560M 参数，1024 维）

**向量化流程**：

```python
# 批量向量化，充分利用 GPU 显存
def embed_chunks(chunks: list[str], batch_size: int = 64) -> list[list[float]]:
    embeddings = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i+batch_size]
        batch_embeddings = model.encode(
            batch,
            normalize_embeddings=True,   # 余弦相似度归一化
            show_progress_bar=False,
        )
        embeddings.extend(batch_embeddings.tolist())
    return embeddings
```

### 3.5 Step 4：写入向量数据库

**向量数据库选型**：Qdrant

选型理由：
- Rust 实现，单机资源占用远低于 Milvus（无需 etcd/pulsar 依赖）
- 原生支持混合检索（向量 + 关键词过滤）
- 支持 Payload（元数据）字段过滤，方便实现部门级权限过滤
- HTTP/gRPC 双 API，运维友好
- 单节点可支撑千万级向量

**Collection 设计**：

```python
# 子块 Collection（用于检索）
child_collection = {
    "name": "medical_chunks_child",
    "vectors_config": {
        "size": 1024,
        "distance": "Cosine",
    },
    "payload_schema": {
        "doc_id":       "keyword",
        "parent_id":    "keyword",   # 关联父块
        "chunk_index":  "integer",
        "department":   "keyword",   # 科室，用于权限过滤
        "tenant_id":    "keyword",   # 租户隔离
        "language":     "keyword",
        "source_type":  "keyword",
        "version":      "keyword",
        "text":         "text",      # 原始文本，用于 BM25
        "updated_at":   "datetime",
    }
}

# 父块 Collection（存储完整上下文）
parent_collection = {
    "name": "medical_chunks_parent",
    "vectors_config": {
        "size": 1024,
        "distance": "Cosine",
    },
    # payload_schema 同上，额外保存完整文本
}
```

### 3.6 异步任务队列

文档处理采用 Celery + Redis 异步执行，避免 API 阻塞：

```
用户上传文件
     │
     ▼
API 接收 → 文件存 MinIO → 创建 DB 记录（status: pending）
     │
     ▼
推送 Celery 任务
     │
     ▼
Worker 执行：解析 → 分块 → 向量化 → 写 Qdrant
     │
     ▼
更新 DB 记录（status: ready）→ WebSocket 通知前端
```

**任务状态机**：

```
pending → processing → ready
                    ↘ failed（记录错误信息，支持重试）
```

---

## 4. 在线侧：检索增强生成链路

### 4.1 完整链路

```
用户 Query
    │
    ▼
Step 1: Query 预处理
    ├─ 语言检测
    ├─ 医学术语标准化
    ├─ 同义词扩展
    └─ Multi-Query 生成（3-5 个变体）
    │
    ▼
Step 2: 混合检索（并行执行）
    ├─ 向量检索 → Top-50（bge-m3 语义相似）
    └─ BM25 关键词检索 → Top-50
    │
    ▼
Step 3: RRF 融合排序 → Top-20
    │
    ▼
Step 4: Rerank 精排（bge-reranker-v2-m3） → Top-10
    │
    ▼
Step 5: 父子块扩展
    ├─ 命中子块 → 查询对应父块
    └─ 去重 + 排序
    │
    ▼
Step 6: Context 组装
    ├─ 按相关度排序
    ├─ 注入来源元数据
    └─ 控制总 Token 数（不超过 LLM 上下文窗口 80%）
    │
    ▼
Step 7: LLM 生成回答（SSE 流式输出）
```

### 4.2 Step 1：Query 预处理

```python
class QueryPreprocessor:
    def process(self, raw_query: str, tenant_id: str) -> ProcessedQuery:
        # 1. 语言检测
        lang = detect_language(raw_query)          # zh / en / ja / ...

        # 2. 医学术语标准化
        normalized = self.normalize_medical_terms(raw_query)

        # 3. 同义词扩展（中英双语）
        expanded_terms = self.expand_synonyms(normalized)

        # 4. Multi-Query 生成（用小型 LLM 或规则模板）
        queries = self.generate_multi_queries(normalized, n=3)
        # 例："糖尿病用药注意事项"生成：
        #   - "2型糖尿病药物禁忌"
        #   - "胰岛素使用注意事项"
        #   - "Diabetes Mellitus medication precautions"

        return ProcessedQuery(
            original=raw_query,
            normalized=normalized,
            language=lang,
            expanded_terms=expanded_terms,
            multi_queries=queries,
        )
```

### 4.3 Step 2：混合检索

向量检索和 BM25 并行执行，充分利用两种检索方式的互补优势：

- **向量检索**：捕捉语义相似性，应对术语变体、多语言查询
- **BM25 关键词检索**：精确匹配医学术语、药品名称、ICD 编码

```python
async def hybrid_search(
    query: ProcessedQuery,
    tenant_id: str,
    department_filter: list[str] | None,
    top_k: int = 50,
) -> list[RetrievedChunk]:

    # 构建 Qdrant 元数据过滤条件（实现部门级权限隔离）
    filters = build_payload_filter(
        tenant_id=tenant_id,
        departments=department_filter,
    )

    # 对多个 query 变体分别检索，取并集
    all_query_texts = [query.normalized] + query.multi_queries
    vector_results, bm25_results = await asyncio.gather(
        vector_search(all_query_texts, filters, top_k),
        bm25_search(query.normalized, query.expanded_terms, filters, top_k),
    )

    return vector_results, bm25_results
```

### 4.4 Step 3：RRF 融合排序

Reciprocal Rank Fusion（倒数排名融合），无需调参，效果稳定：

```python
def rrf_fusion(
    vector_results: list[RetrievedChunk],
    bm25_results: list[RetrievedChunk],
    k: int = 60,             # RRF 平滑参数，通常取 60
    vector_weight: float = 0.7,
    bm25_weight: float = 0.3,
) -> list[RetrievedChunk]:
    scores: dict[str, float] = {}

    for rank, chunk in enumerate(vector_results):
        scores[chunk.id] = scores.get(chunk.id, 0) + \
            vector_weight * (1 / (k + rank + 1))

    for rank, chunk in enumerate(bm25_results):
        scores[chunk.id] = scores.get(chunk.id, 0) + \
            bm25_weight * (1 / (k + rank + 1))

    # 按融合分数降序，取 Top-20
    sorted_ids = sorted(scores, key=scores.get, reverse=True)[:20]
    chunk_map = {c.id: c for c in vector_results + bm25_results}
    return [chunk_map[cid] for cid in sorted_ids if cid in chunk_map]
```

### 4.5 Step 4：Rerank 精排

使用 `bge-reranker-v2-m3` 对融合结果精排：

| 维度 | 说明 |
|------|------|
| 模型 | BAAI/bge-reranker-v2-m3 |
| 多语言 | 支持，与 bge-m3 同系列 |
| 输入 | query + passage 对 |
| 输出 | 相关性分数 0~1 |
| 推理速度 | Top-20 约 100ms（CPU），约 20ms（GPU）|

```python
def rerank(
    query: str,
    candidates: list[RetrievedChunk],
    top_k: int = 10,
) -> list[RetrievedChunk]:
    pairs = [(query, chunk.text) for chunk in candidates]
    scores = reranker_model.predict(pairs)

    ranked = sorted(
        zip(candidates, scores),
        key=lambda x: x[1],
        reverse=True,
    )
    return [chunk for chunk, score in ranked[:top_k] if score > 0.3]
```

### 4.6 Step 5：父子块扩展

```python
def expand_to_parent_chunks(
    child_chunks: list[RetrievedChunk],
    qdrant_client: QdrantClient,
) -> list[RetrievedChunk]:
    parent_ids = list({chunk.parent_id for chunk in child_chunks})

    # 批量从父块 Collection 获取完整上下文
    parent_chunks = qdrant_client.retrieve(
        collection_name="medical_chunks_parent",
        ids=parent_ids,
        with_payload=True,
    )

    # 保留子块的相关性分数，关联到父块
    parent_map = {p.id: p for p in parent_chunks}
    result = []
    seen_parents = set()

    for child in child_chunks:
        pid = child.parent_id
        if pid not in seen_parents and pid in parent_map:
            parent = parent_map[pid]
            parent.relevance_score = child.relevance_score  # 继承子块分数
            result.append(parent)
            seen_parents.add(pid)

    return sorted(result, key=lambda x: x.relevance_score, reverse=True)
```

### 4.7 Step 6：Context 组装

```python
def assemble_context(
    parent_chunks: list[RetrievedChunk],
    max_tokens: int = 6000,       # LLM 上下文窗口 80%
) -> AssembledContext:
    context_parts = []
    total_tokens = 0

    for i, chunk in enumerate(parent_chunks):
        chunk_tokens = count_tokens(chunk.text)
        if total_tokens + chunk_tokens > max_tokens:
            break

        context_parts.append({
            "index": i + 1,
            "text": chunk.text,
            "source": {
                "doc_name": chunk.metadata["filename"],
                "department": chunk.metadata["department"],
                "version": chunk.metadata["version"],
                "page": chunk.metadata.get("page_number"),
            },
            "relevance_score": round(chunk.relevance_score, 3),
        })
        total_tokens += chunk_tokens

    return AssembledContext(
        parts=context_parts,
        total_tokens=total_tokens,
    )
```

### 4.8 Step 7：LLM 生成

系统支持接入多种 LLM（本地部署优先）：

```
优先级：
1. 本地部署 LLM（Qwen2.5-72B-Instruct / DeepSeek-V3 等）
2. vLLM / Ollama 作为推理服务
3. 私有化 API（如医院已有 GPT 专线）
```

**System Prompt 模板**：

```
你是一位医学知识助手，基于医院内部知识库回答问题。

规则：
1. 只基于提供的参考资料回答，不使用训练数据中的医学知识
2. 每条结论引用对应来源（[来源编号]）
3. 遇到知识库中没有的内容，明确告知"当前知识库中未找到相关信息"
4. 不给出诊断结论，只提供知识参考，并建议咨询主治医生

参考资料：
{context}

用户问题：{query}
```

### 4.9 检索缓存策略

对高频查询的检索结果进行缓存，减少向量库和 Rerank 模型压力：

```python
# 缓存 Key：hash(normalized_query + tenant_id + department_filter)
# TTL：30 分钟（医学内容更新频率较低，缓存可适当延长）
# 缓存内容：parent_chunks 列表（不缓存 LLM 生成结果，保证实时性）
```

---

## 5. 数据模型设计

### 5.1 PostgreSQL 表结构

```sql
-- 租户表
CREATE TABLE tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) NOT NULL,
    code        VARCHAR(64)  UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- 用户表
CREATE TABLE users (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID REFERENCES tenants(id),
    username     VARCHAR(128) NOT NULL,
    role         VARCHAR(32)  NOT NULL,   -- admin / doctor / nurse / readonly
    department   VARCHAR(128),
    created_at   TIMESTAMPTZ  DEFAULT NOW()
);

-- 文档表
CREATE TABLE documents (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID REFERENCES tenants(id),
    filename       VARCHAR(512) NOT NULL,
    file_path      TEXT NOT NULL,          -- MinIO 路径
    checksum       CHAR(64)     NOT NULL,  -- SHA256
    source_type    VARCHAR(64),            -- clinical_guideline / drug_manual / ...
    department     VARCHAR(128),
    language       VARCHAR(16),
    version        VARCHAR(32)  DEFAULT '1.0',
    status         VARCHAR(32)  DEFAULT 'pending',  -- pending / processing / ready / failed
    upload_by      UUID REFERENCES users(id),
    uploaded_at    TIMESTAMPTZ  DEFAULT NOW(),
    indexed_at     TIMESTAMPTZ,
    error_message  TEXT
);

-- 文档版本历史（合规要求，不物理删除）
CREATE TABLE document_versions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  UUID REFERENCES documents(id),
    version      VARCHAR(32),
    file_path    TEXT,
    replaced_at  TIMESTAMPTZ DEFAULT NOW(),
    replaced_by  UUID REFERENCES users(id)
);

-- 审计日志
CREATE TABLE audit_logs (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    UUID REFERENCES tenants(id),
    user_id      UUID REFERENCES users(id),
    action       VARCHAR(64),   -- search / upload / delete / view
    resource_id  TEXT,
    query_text   TEXT,
    ip_address   INET,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 检索反馈（用于后续优化）
CREATE TABLE search_feedback (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID REFERENCES tenants(id),
    user_id      UUID REFERENCES users(id),
    query_text   TEXT,
    result_ids   TEXT[],
    rating       SMALLINT CHECK (rating BETWEEN 1 AND 5),
    comment      TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 6. API 接口设计

### 6.1 文档管理接口

```
POST   /api/v1/documents/upload          上传文档
GET    /api/v1/documents                 文档列表（分页 + 过滤）
GET    /api/v1/documents/{id}            文档详情
DELETE /api/v1/documents/{id}            归档文档（软删除）
GET    /api/v1/documents/{id}/status     处理状态（轮询或 WebSocket）
POST   /api/v1/documents/{id}/reindex    重新索引
```

### 6.2 检索接口

```
POST /api/v1/search                      标准检索（返回段落列表）
POST /api/v1/search/qa                   问答（SSE 流式返回）
GET  /api/v1/search/history              检索历史
POST /api/v1/search/feedback             提交检索反馈
```

**检索请求体**：

```json
{
  "query": "糖尿病患者胰岛素注射部位选择原则",
  "department_filter": ["内分泌科", "ICU"],
  "language_hint": "zh",
  "top_k": 5,
  "source_types": ["clinical_guideline", "drug_manual"]
}
```

**检索响应体**：

```json
{
  "query_id": "uuid",
  "results": [
    {
      "rank": 1,
      "text": "胰岛素注射部位应轮换，推荐腹部、大腿、上臂...",
      "relevance_score": 0.923,
      "source": {
        "doc_id": "uuid",
        "filename": "胰岛素使用规范2026.pdf",
        "department": "内分泌科",
        "version": "2.1",
        "page": 12
      }
    }
  ],
  "latency_ms": 320
}
```

### 6.3 系统管理接口

```
GET  /api/v1/admin/stats                 系统统计（文档数、查询量）
GET  /api/v1/admin/health                健康检查
POST /api/v1/admin/rebuild-index         重建索引（管理员）
GET  /api/v1/admin/audit-logs            审计日志查询
```

---

## 7. 权限与安全

### 7.1 角色权限矩阵

| 功能 | admin | doctor | nurse | readonly |
|------|-------|--------|-------|----------|
| 上传文档 | ✅ | ✅（限本科室） | ❌ | ❌ |
| 删除文档 | ✅ | ❌ | ❌ | ❌ |
| 检索（全库） | ✅ | ✅ | ✅ | ✅ |
| 检索（跨科室） | ✅ | ❌ | ❌ | ❌ |
| 查看审计日志 | ✅ | ❌ | ❌ | ❌ |
| 系统配置 | ✅ | ❌ | ❌ | ❌ |

### 7.2 租户隔离

所有向量检索请求携带 `tenant_id` 作为 Qdrant Payload 过滤条件，从存储层保证数据隔离，不依赖应用层拦截。

### 7.3 认证方案

- **协议**：JWT（RS256 签名）
- **有效期**：Access Token 2 小时，Refresh Token 7 天
- **存储**：Token 不存服务端，无状态
- **接口鉴权**：FastAPI `Depends` 注入统一鉴权中间件

### 7.4 传输安全

- 所有 API 通过 HTTPS（TLS 1.2+）
- MinIO 内部通信走内网，不暴露外网端口
- Qdrant、PostgreSQL、Redis 不对外暴露，只监听内网

---

## 8. 部署架构

### 8.1 目录结构

```
ClinAtlas/
├── docs/                   # 技术文档
│   └── technical-design.md
├── src/
│   ├── api/                # FastAPI 应用
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── documents.py
│   │   │   ├── search.py
│   │   │   └── admin.py
│   │   ├── middleware/
│   │   │   ├── auth.py
│   │   │   └── audit.py
│   │   └── schemas/
│   ├── pipeline/           # 离线处理流水线
│   │   ├── parsers/        # 文档解析器
│   │   │   ├── pdf_parser.py
│   │   │   ├── docx_parser.py
│   │   │   └── ocr_parser.py
│   │   ├── chunker.py      # 结构感知分块
│   │   ├── embedder.py     # bge-m3 向量化
│   │   ├── indexer.py      # 写入 Qdrant
│   │   └── tasks.py        # Celery 任务定义
│   ├── retrieval/          # 在线检索链路
│   │   ├── preprocessor.py # Query 预处理
│   │   ├── searcher.py     # 混合检索
│   │   ├── reranker.py     # Rerank 精排
│   │   ├── expander.py     # 父子块扩展
│   │   └── generator.py    # LLM 生成
│   ├── models/             # ORM 模型
│   └── utils/
├── config/
│   ├── settings.yaml       # 主配置
│   ├── logging.yaml
│   └── docker-compose.yml
├── tests/
└── data/
    ├── uploads/            # 临时上传目录
    └── models/             # 本地模型文件
```

### 8.2 Docker Compose 部署

```yaml
version: "3.9"

services:
  api:
    build: ./src
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://clinatlas:${PG_PASSWORD}@postgres:5432/clinatlas
      - QDRANT_URL=http://qdrant:6333
      - REDIS_URL=redis://redis:6379/0
      - MINIO_ENDPOINT=minio:9000
    depends_on:
      - postgres
      - qdrant
      - redis
      - minio

  worker:
    build: ./src
    command: celery -A pipeline.tasks worker --loglevel=info --concurrency=4
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
      - qdrant
      - postgres

  postgres:
    image: postgres:16-alpine
    volumes:
      - pg_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=clinatlas
      - POSTGRES_PASSWORD=${PG_PASSWORD}

  qdrant:
    image: qdrant/qdrant:v1.9.0
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    ports:
      - "9001:9001"
    volumes:
      - minio_data:/data
    environment:
      - MINIO_ROOT_USER=clinatlas
      - MINIO_ROOT_PASSWORD=${MINIO_PASSWORD}

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./config/nginx.conf:/etc/nginx/conf.d/default.conf
      - ./config/certs:/etc/nginx/certs

volumes:
  pg_data:
  qdrant_data:
  redis_data:
  minio_data:
```

### 8.3 硬件推荐配置

| 规模 | CPU | 内存 | 存储 | GPU |
|------|-----|------|------|-----|
| 小型（< 5万文档） | 8 核 | 32GB | 500GB SSD | 可选，GTX 1080 Ti |
| 中型（5-50万文档）| 16 核 | 64GB | 2TB SSD | 推荐，RTX 3090 |
| 大型（> 50万文档）| 32 核 | 128GB | 10TB NVMe | 必须，A10 / A100 |

---

## 9. 技术栈汇总

| 层级 | 组件 | 版本建议 |
|------|------|----------|
| API 框架 | FastAPI | 0.115.x |
| 任务队列 | Celery + Redis | 5.4.x |
| 向量数据库 | Qdrant | 1.9.x |
| 关系数据库 | PostgreSQL | 16.x |
| 对象存储 | MinIO | RELEASE.2024 |
| 缓存 | Redis | 7.x |
| Embedding | bge-m3 | 最新 |
| Reranker | bge-reranker-v2-m3 | 最新 |
| OCR | PaddleOCR | 2.7.x |
| PDF 解析 | PyMuPDF | 1.24.x |
| ORM | SQLAlchemy | 2.x + asyncpg |
| 容器 | Docker + Compose | 最新稳定版 |
| 反向代理 | Nginx | 1.26.x |
| 前端框架 | Vue 3 + Vite | 3.4.x |
| UI 组件库 | Element Plus | 2.8.x |

---

## 10. 非功能性指标

| 指标 | 目标 |
|------|------|
| 检索端到端延迟（P95） | < 2 秒（含 LLM 流式首字节） |
| 向量检索延迟 | < 200ms |
| Rerank 延迟 | < 300ms（Top-20 → Top-10）|
| 文档处理吞吐量 | 50 页/分钟（单 Worker，有 GPU）|
| 系统可用性 | 99.5%（允许每月 3.6 小时维护）|
| 最大并发检索用户 | 200（单节点）|
| 向量库容量 | 500 万子块（Qdrant 单节点）|
| 审计日志保留期 | 不少于 3 年 |
