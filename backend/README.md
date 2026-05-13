# 智能知识库后端系统

企业级智能知识库平台后端，集成知识管理、混合检索、AI 对话与深度研究能力。支持团队协作，私有化部署。

**适用场景**：企业内部知识库、教育培训平台。

---

## 系统能做什么

### 知识空间 — 团队级知识管理

- **多空间隔离**: 每个团队/项目创建独立空间，数据互不干扰
- **灵活可见性**: 支持私有、团队、公开三种可见性
- **成员协作**: 邀请制加入，VIEWER / EDITOR / ADMIN 三级角色
- **公开发现**: 公开空间可被任何人浏览和检索
- **统一 Embedding**: 空间级别统一管理 Embedding 模型，知识库运行时自动读取，确保向量兼容

### 知识库 & 文档 — 从文件到可检索的知识

- **多格式支持**: PDF、Word、Excel、PPT、TXT、Markdown、CSV、HTML、JSON
- **智能分块**: 4 种切分策略（递归 / 固定大小 / Markdown 结构 / 语义切分），按需选择
- **自动解析**: 上传后自动执行 解析 → 切分 → 向量化 → 索引，无需手动操作
- **批量处理**: 支持单篇和批量触发解析，支持重新解析
- **假设问题生成**: AI 为每个分块自动生成相关问题，建立问题到内容的反向索引，提升检索命中率

### 混合检索 — 9 种模式精准定位

- **3×3 组合**: 内容/问题/全字段 × BM25/向量/混合，共 9 种检索模式
- **RRF 融合排序**: 多路检索结果自动融合，取长补短
- **Rerank 重排序**: 可选二次精排
- **查询改写**: 支持 HyDE 假设文档和子查询分解两种策略
- **AI 回答**: 可选开启 LLM，基于检索结果直接生成回答
- **智能降级**: 向量服务不可用时自动回退到纯 BM25

### AI 聊天 — 实时智能对话

- **流式输出**: SSE 实时推送 AI 回复
- **会话管理**: 自动维护聊天历史，支持清除
- **模型可选**: 支持切换不同 LLM 模型

### 智能问答 — 知识库增强对话

- **绑定知识库**: 指定知识空间和知识库，基于自有数据回答
- **会话记忆**: 多轮对话自动维护上下文
- **上下文压缩**: 4 种压缩策略（摘要 / 滑动窗口 / 保留最近 / 截断），避免 Token 超限

### 深度研究 — 自动化研究报告

- **多源聚合**: 同时检索内部知识库 + 外部搜索引擎（DuckDuckGo / Tavily / SerpAPI）
- **三种深度**: 快速、标准、深度
- **流式进度**: SSE 实时推送研究进度和报告内容

### 模型配置 — 用户级模型管理

- **私有配置**: 每个用户可配置自己的 LLM / Embedding / Rerank 模型
- **连接测试**: 配置前可先测试模型连接是否正常
- **密钥脱敏**: API Key 在响应中自动脱敏，仅显示后 4 位

### 知识库测评 — RAG 效果量化评估

- **测试集管理**: 上传 JSON/CSV 格式测试集，支持复用
- **自动化评估**: 检索评估（Precision、MRR）、生成评估（Faithfulness、Correctness）、端到端评估
- **异步执行**: 任务创建后自动异步运行，支持进度查询和取消
- **人工评分**: 对自动评估结果补充人工打分
- **结果导出**: JSON / CSV 双格式导出

### Agent 智能体 — 可扩展 AI 助手

- **多轮对话**: 支持上下文连续的多轮工具调用
- **MCP Server**: 通过 MCP 协议接入外部工具和数据源
- **代码沙箱**: 安全执行 Agent 生成的代码
- **自定义 Agent**: 创建、配置专属智能体，绑定不同的工具集

### 技能广场 — Agent 能力扩展

- **技能上传**: 开发者上传技能包（YAML 定义 + Python 实现）
- **审核管理**: 管理员审核、批准/拒绝技能发布
- **市场发现**: 用户浏览、搜索、安装可用技能
- **版本管理**: 支持技能版本更新，自动升级

### 应用中心 — 场景化 AI 工具

- **简历挖掘**: 上传简历 PDF/Word，AI 自动结构化提取，智能分析候选人画像
- **统一入口**: 应用中心作为各类 AI 应用的入口，后续持续扩展

---

## 技术架构

| 类别 | 技术选型 |
|------|---------|
| 框架 | FastAPI + Python 3.12 |
| 数据库 | MySQL / MariaDB |
| 缓存 | Redis（支持哨兵/集群） |
| 搜索引擎 | Elasticsearch 8.15+（含 IK 分词、HNSW 向量索引） |
| 对象存储 | MinIO |
| LLM | OpenAI 兼容接口（智谱 AI / 通义千问等） |
| 认证 | JWT + Argon2 密码哈希 |
| 架构 | 领域驱动设计（DDD）分层 |

---

## 快速开始

### 环境依赖

- Python 3.12+
- MySQL 8.0+ 或 MariaDB 10.5+
- Redis 6.0+（可选，未配置时自动降级为内存存储）
- Elasticsearch 8.0+（需安装 IK 分词器插件）
- MinIO

### 安装

```bash
git clone git@github.com:SpaceshiptoMoon/NovaMind.git
cd backend

# 安装依赖
uv sync

# 或使用 pip
pip install -e .
```

### 配置

配置文件位于 `src/setting/yaml_config/yaml/`，按环境分层：

| 文件 | 用途 |
|------|------|
| `default.yaml` | 所有环境共享的基础配置 |
| `development.yaml` | 开发环境覆盖 |
| `testing.yaml` | 测试环境 |
| `production.yaml` | 生产环境（支持环境变量替换） |
| `local.yaml` | 本地个人覆盖（可选，不提交 Git） |

加载顺序: `default.yaml` → `{env}.yaml` → `local.yaml`，后者深度覆盖前者。

### 启动

```bash
# 开发模式（热重载）
python main.py --reload

# 指定环境
python main.py --config development

# 完整参数
python main.py --config development --host 0.0.0.0 --port 8100 --reload

# 生产模式（多进程）
python main.py --config production --workers 4
```

启动成功后：
- **Swagger UI**: http://localhost:8100/docs
- **ReDoc**: http://localhost:8100/redoc
- **健康检查**: http://localhost:8100/health

### 基本使用流程

1. **创建知识空间** → `POST /api/v1/spaces`，创建者自动成为管理员
2. **配置 Embedding 模型** → `PATCH /api/v1/spaces/{space_id}/config` 设置空间的 Embedding 模型
3. **创建知识库** → `POST /api/v1/spaces/{space_id}/knowledge-bases`，Embedding 自动从空间继承
4. **上传文档** → `POST .../documents`，支持 12 种文件格式
5. **触发解析** → `POST .../documents/{id}/process`，自动完成 切分 → 向量化 → 索引
6. **检索知识** → `POST .../search`，9 种检索模式可选

---

## 接口文档

系统共提供 **140+ 个 API 接口**，详细接口文档请参阅：

- **在线文档**: 启动后访问 http://localhost:8100/docs (Swagger UI)
- **知识空间模块**: [docs/api/knowledge_space_api.md](docs/api/knowledge_space_api.md)

---

## 安全

| 特性 | 说明 |
|------|------|
| 密码安全 | Argon2 哈希，抗 GPU 暴力破解 |
| Token 体系 | JWT 双 Token（Access + Refresh），Redis 黑名单 |
| 速率限制 | 登录 5/min、注册 3/min、AI 操作 10-30/min |
| 文件安全 | 魔数检测防伪装，危险扩展名拦截，100MB 大小限制 |
| 链路追踪 | X-Trace-ID 全链路追踪 |
| 启动审计 | 生产环境自动检查配置安全性，不通过则阻止启动 |

---

## 许可证

MIT License
