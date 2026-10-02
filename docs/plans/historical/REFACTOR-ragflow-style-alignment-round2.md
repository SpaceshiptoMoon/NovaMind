# REFACTOR-ragflow-style-alignment-round2

> 状态：已完成（2026-09-21 全部批次执行完毕；批次 6 决策为方案 A——
> 4 个单消费方引擎保持现状，折回改为按需触发）
> 前置：`REFACTOR-ragflow-style-migration.md`（批次 0-6 已完成，R1-R6 已生效）

## 背景

三路全项目审计（仪式层盘点 / 门禁白名单与死码 / 引擎层与重复实现）发现的第二轮对齐项：
3 个真 bug（其中 1 个断链依赖挂 3 条活路由）、7 个 adapters 目录的仪式残留、
11 条门禁白名单、四强厚路由、ASR 集群重复实现。

## 批次 0：P0 修 bug（已完成，4139837 + 69cffbe）

1. `features/user/api/dependencies.py:44-47` 懒 import 已删除的 `knowledge_space_info_adapter`
   + 传 `ModelConfigService` 已不接受的 kwarg（ks search_routes:210 / qa ai_chat_routes:275 /
   agent routes:157 请求即 ImportError）→ 删死分支按现签名重写
2. `features/agent/sandbox/config.py:46` import 不存在的 `config_manager` 被 except 吞
   （sandbox YAML 配置从未生效）→ 改 `from novamind.setting.yaml_config import get_config`
3. `features/qa/services/ai_chat_service.py:25` TYPE_CHECKING import 已删除的
   `shared.retrieval_port` → 删除
4. `test_describe_grouped_degrades_on_multi_image_error`（ea5f8e7 并发化后断言按串行序写死）
   → 响应脚本按消息形状（图片数）匹配而非调用顺序；引擎降级行为本身正确，修测试不修引擎

## 批次 1：死码清扫 + 白名单清零（已完成，b83e583）

删除：6 个零引用 `api/exceptions.py` shim（deep_research/evaluation/qa/skill/user/agent；
ks 的仅测试引用一并迁移）+ `core/compat/` 空目录 + `agent/adapters/web_search_adapter.py` 死 shim
+ `wiki_routes._finalize_links` 死函数（真身在 wiki_retract_service）
+ 6 个死 `as_*_port` 工厂（memory×3/knowledge_search/attachment_read/user_status_resolver）
+ `is_document_ingestion_port` + `test_batch5b` 孤儿变量（`_DEEP_RESEARCH_ENGINE_MODULES` 等 4 个）

白名单 11 条重命名转公共（目标清零）：retry 3（`_is_retryable_error`/`_is_non_retryable`/
`_is_context_overflow`）、video 5（`_compute_gray_histogram`/`_histogram_chi_square`/
`_read_video_metadata`/`_read_frame_at`，frame_dedup→frame_extraction）、路由 4
（`_build_agent_chat_service`/`_get_model_config_service`/`_plan_to_event_data`/`_build_trace_context`）。

Stale docstring 清理：`engines/rag/__init__.py:4`、`model_config_service.py:40`、
`search_config_service.py:46`、`engines/deep_research/__init__.py:10`、
`test_grade_retrier_seam.py:10`、`test_resume_engine_seam.py:20`、`test_batch5_skill_seam.py:14`。

## 批次 2：deep_research adapters 拆除（已完成，6b89c73）

`git mv` 保字节：`adapters/internal_search_port_adapter.py` → `services/internal_search_source.py`、
`web_search_port_adapter.py` → `services/web_search_source.py`、`source_registry.py` →
`services/source_registry.py`；删 adapters/ 目录。类/函数名不变，最小 diff。

`build_web_search_source` 委托 `shared/search/web_search_factory.build_web_search_port_from_provider`
+ 异常镜像（中立异常 → feature 异常，本函数完成）；YAML 凭据提取 + 请求级 search_depth
合并留调用侧；删本地 80 行 provider 构造。

删 `HostWebSearchPort`/`as_web_search_port`；`agent/adapters/__init__.py` 与
`agent/services/chat_service.py` 注解改 `WebSearchPort`（运行时实例本就是 ProviderWebSearchPort）。

保形：可插拔四接入点（register_source_factory / SourcesConfig.extra / /sources 端点 /
cleanup close 链）、SearchSourceContext.deps 间接层、per-source top_k。

测试重指向：`test_source_registry.py` external 四测改测委托与镜像（patch 消费方命名空间
`services/web_search_source.build_web_search_port_from_provider`）；seam 三处换路径/重写。

## 批次 3：agent/ks/user adapters 收编（已完成，1bf711d）

- agent：`adapters/__init__.py` 删 `HostPromptProvider` 无消费别名 + 批 2 后不再 import deep_research；
  `knowledge_search_adapter` 的 knowledge_space repository 内部 import 收敛到对方 services 公共面
  （新增 1-2 个公共查询方法，R2 防环细则：按需 models 直查）；
  `engines/agent/ports.py`（8 个纯 dataclass，名实不符）→ `context_types.py`
- ks：`document_ingestion_adapter` 单方法透传仪式 → 评估直接让 qa 消费
  `engines.document.pipeline.DocumentProcessor`，删 `shared/document/ports.py` 的
  `DocumentIngestionPort`；`cache_adapter.py` 保留（CachePort 合法豁免）
- user：删 `as_user_status_resolver` 死工厂；`adapters/__init__.py` docstring 修
- `features/skill/ports.py`（只剩 ReviewStatus 枚举）改名归位（如 `review_status.py`）
- Protocol 处置结论：`Logger`/`PathStrategy`/`IndexSchema`/`NotificationPort`/`CachePort`/
  `WebSearchPort`/`SearchSourcePort` 保留（typing 或真扩展点）；`DocumentIngestionPort` 删

## 批次 4：厚路由减薄（四强）（已完成，623199b/02c93e5/b141784/0fcfb6e）

标准：路由层只留"参数解析 + Depends 鉴权 + 调 service"。

1. `wiki_routes.py` 读侧（579 行）：11 处 repo 直构下沉（WikiPageService 或新建读服务）；
   `get_page_sources` N+1 批量化；`get_index` 组装下沉；`auto_fix_wiki` 路由层 db.commit() 归 service
2. `document_routes.py`（852 行）：`_build_chunk_response` MinIO presign 下沉；
   upload 批量循环/审计组装下沉 document_upload_service；tasks overview 组装下沉；
   delete RBAC 决策树走 access_service
3. `user_routes.py`（689 行）：register auto-login 下沉 AuthService；`_ensure_user_exists`
   裸 ORM 下沉；app access Redis helper 下沉
4. `skill/routes.py`（554 行）：`_batch_get_usernames` 裸 SQL 改走 user 公共面
   （user service 加批量用户名查询），enrichment 循环下沉

每文件独立 commit；openapi 快照必须全绿（纯内部搬移不改契约）。
WS 编排（agent/deep_research 各约 90 行）与次要路由明确不做。

## 批次 5：重复实现收敛（已完成，e9d0be3）

- ASR 集群：三协议实现从 `engines/document/media/audio/audio_utils.py`（796 行）迁
  `shared/ai_models/asr/`（R3 中心），R5 工厂自注册（local/dashscope/openai-whisper）；
  与 `connection_testers/asr.py` DashScope 提交/轮询去重；
  **保住 ASR 专用单线程 executor 隔离（d01f219 教训，不可丢）**
- 3 处 elif 协议分派链查表化：`media_processing.py:489`、`model_config_service.py:617`、tester
- 小项：`_extract_json_block` 改用 `shared/utils/llm_response`；wiki-link regex 归一
  `wiki_linkify._extract_wiki_slug`；4 个 sanitize 变体**先审语义差异再合**（不许盲合）；
  MCP transport elif 链可选

## 验证与纪律

- 每批次：定向测试 + 三门禁（无环/禁私有/禁 HTTPException）+ openapi 快照；批 4、5 后补 integration
- 收尾全量 pytest：基线 1552 通过、零已知失败
- rg 零命中断言：`deep_research.adapters`、`HostWebSearchPort|as_web_search_port`、
  白名单条目、`retrieval_port`、`config_manager`
- main 直接改、小步原子 commit（中文动机）、backend/.venv 解释器、
  混合行尾文件字节级操作、patch 目标按调用链执行位置定

## 明确不做

vendored deepdoc；frontend；DB 迁移；可观测性/coverage；巨石服务层拆分
（ai_chat_service 1494 等，消重复后独立轨道）；引擎折回（方案 A，按需触发）。
