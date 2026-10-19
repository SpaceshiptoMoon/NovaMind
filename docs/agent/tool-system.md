# Agent 工具体系

> 适用于 2026-10-19 主线（commit `cc97c5ef`，工具路由工程化三件套）。
> 核心代码：`backend/src/engines/agent/tool/`（引擎层：基类/注册表/执行器/校验）、
> `backend/src/features/agent/tool/registry_setup.py`（装配清单）、
> `backend/src/features/agent/services/chat_service.py`（条件注入接线）。

---

## 一、四层架构

```
① 代码声明层   engines/agent/tool/builtins（7 个通用）
               features/agent/tool/builtins（4 个业务）
               → BaseTool 子类，get_tools() 声明 OpenAI function schema
② 装配语义层   registry_setup.build_tool_registry()（唯一装配清单）
               + chat_service 条件注入（恒注入/门控端口）
③ HTTP 契约层  GET /agent/tools（前端下拉源）
               GET /agent/tools-runtime（管理员诊断）
               GET /agent/agents（各 agent 的 enabled_tools 实况）
④ 前端消费层   WorkspaceLayout.vue 工具下拉（PRIORITY_TOOLS 置顶知识库/联网）
```

任何一层口径漂移都会造成「前端能勾/后端不认」或「后端注册/前端看不到」的
静默失配。对账脚本 `backend/scripts/audit_agent_tools.py`（8 组检查 A–H）
对这四层做交叉验证，见第五节。

---

## 二、工具清单（10 提供者 / 21 function）

| 提供者 | function 名 | 门控 | 依赖前置 |
|--------|------------|------|---------|
| `knowledge_search` | list_spaces / list_knowledge_bases / list_all_knowledge_bases / knowledge_search / document_list | — | space_id 来自 list_spaces |
| `web_search` | web_search | 勾选才下发 `web_search_port` | 无 |
| `memory` | memory | — | memory_store_port 恒注入 |
| `todo` | todo | — | TodoStore 装配期注入 |
| `read_tool_result` | read_tool_result | **恒注入** | 之前有被截断的工具调用（tool_call_id 来自截断通知） |
| `task` | task | 勾选才注入 `subagent_runner` | 无（prompt 即子 agent 全部上下文） |
| `plan_output` | plan_output | **plan_mode 才注入** | 计划模式 + 至少一个已完成步骤 |
| `wiki` | wiki_read_page / wiki_search / wiki_write_page / wiki_flag_issue / wiki_replace_text / wiki_rename_page / wiki_read_issue / wiki_update_issue | — | kb_id + slug 来自 wiki_search |
| `research` | research | 勾选才注入 `research_service_factory` | 无（query 即研究简报，数分钟长任务） |
| `read_attachment` | read_attachment | **恒注入** | 用户上传过附件（attachment_id 来自 `<system-uploaded-files>` 清单） |

**条件注册**：`code_execution`（run_code）仅在 Docker 沙箱启动成功时注册——
能力缺失优于半可用，缺席不算故障。

### 描述规范（DEPENDS ON / WHEN TO USE / NOT FOR）

全部 21 个 function 的 description 统一三段结构：

- **DEPENDS ON**：只写「没有 X 就别调」级别的事实（依赖前置的 ID 来源、
  不继承哪些上下文）。
- **WHEN TO USE**：明确应用场景。
- **NOT FOR**：互斥边界，**指名替代工具**（如 web_search 的 NOT FOR 指向
  knowledge_search / research / read_attachment）。

四路检索分工：`knowledge_search`（用户 KB 文档）↔ `web_search`（公网单轮）
↔ `research`（复杂课题多轮综合，分钟级）↔ `read_attachment`（本会话上传
附件）；wiki 家族另有独立链 wiki_search → wiki_read_page →
write/replace/rename → flag_issue → update_issue。

改描述时同步检查 `tests/features/agent/test_plan_output_tool.py` 的描述断言。

---

## 三、注册与执行链路

### 注册期（startup，fail-fast）

`registry_setup.build_tool_registry(todo_store, sandbox)` 装配；`ToolRegistry.register()`
逐个验证：

1. function 名必填；
2. function 名跨 provider 不重复（二级索引 `_tool_name_to_provider` 不被抢占）；
3. parameters schema 经 `jsonschema.Draft202012Validator.check_schema` 元验证。

非法定义直接抛 `ValueError`，启动期暴露（坏 schema 注册成功后要到执行期才炸，
且模型看到的 tools 契约是坏的）。

### 模型可见 schema（保真透传）

`ToolParameter` 声明工具 schema 实际用到的 JSON Schema 子集：`type /
description / enum / default / items / minimum / maximum / minLength /
maxLength / minItems / maxItems`。`executor._raw_to_definition` 逐键防御性
吸收（MCP 外部 schema 的畸形值丢弃该键而非注册失败）；`to_openai_format()`
原样回写给模型；`validation.py::_param_to_schema` 用同一投影构造校验
schema——**模型可见口径与校验口径同源**。

> 历史坑：扩展前 ToolParameter 只有 4 个字段，`wiki_read_page` 的
> `maxItems: 5`、`todo` 的嵌套 items 结构被 pydantic 静默丢弃，模型看到的
> schema 是削减过的。新增约束字段时三处同步：ToolParameter 定义、
> `_SCHEMA_CONSTRAINT_KEYS`、`_param_to_schema` 投影。

### 执行期（纠错反馈）

`executor.execute()` 流程：

```
参数 schema 校验（畸形参数不进执行，错误带修正指引回喂）
  → before hooks（日志/审批/消毒）
  → asyncio.wait_for 超时保护
  → 路由（builtin 二级索引 / mcp__ 前缀拆解）
  → 失败/超时 → 附加纠错指引
  → after hooks（消毒→token 预算截断→预览标记）
```

**失败纠错指引**（2026-10-19 起）：

- 执行失败/超时的错误自动附加「该工具的用途：{function description 首行}
  请对照检查参数，修正后可重试」——模型可对照用途自查参数。
- 同一 `(session_id, tool_name)` **连败 3 次**升级为「请勿以相同方式重试：
  换工具、换思路或告知用户」——阻断同参数无限重试循环。
- 计数在 executor 实例上（应用生命周期），成功即清零，不跨会话泄漏。
- 参数校验失败（validation.py）不走此计数——那是「畸形参数不执行」，
  天然带修正指引。

### 超时

每个工具的 `default_timeout_ms` 类属性（默认 30s；`research` 15 分钟），
经 `_provider_timeout_ms` 反推进 ToolDefinition。

---

## 四、条件注入（chat_service）

| context 键 | 门控 | 说明 |
|-----------|------|------|
| `read_tool_result` / `read_attachment` 工具本体 | 恒注入 | 不受 enabled_tools 门控 |
| `plan_output` 工具本体 | extra_config.plan_mode | 计划模式专用 |
| `web_search_port` | `"web_search" in enabled_tools` | 未勾选不下发端口 |
| `subagent_runner` | `"task" in enabled_tools` | 预剔除 task/todo 防递归 |
| `research_service_factory` | `"research" in enabled_tools` | — |
| `knowledge_search_port` / `knowledge_pipeline` / `attachment_read_port` / `memory_store_port` / `memory_search_port` / `embedding_client_resolver` / `approval_registry` / `event_sink` | 恒注入 | 工具执行上下文基础端口 |

默认助手基线：`agent_service._DEFAULT_AGENT_TOOLS`（knowledge_search、
web_search、memory、todo、task、read_attachment、research），ensure 时对
存量默认行做并集补齐。

---

## 五、对账脚本（工具体系门禁）

```bash
cd backend && .venv/Scripts/python -X utf8 scripts/audit_agent_tools.py
# 可选 --base-url / --username / --password；退出码 0=全过 1=有 FAIL 2=仅 WARN
```

静态 AST 提取（registry_setup 装配类、_DEFAULT_AGENT_TOOLS、工具 context
依赖键）× 真实 HTTP 端点交叉验证，8 组检查：

| 组 | 内容 |
|----|------|
| A | 运行时注册表 vs 代码装配清单（条件注册缺席=WARN，其余缺席=FAIL） |
| B | function 名全局唯一（重名=路由抢占） |
| C | /tools 与 /tools-runtime 出口一致 |
| D | _DEFAULT_AGENT_TOOLS 基线无死引用（对照运行时 ∪ 条件注册） |
| E | 门控端口接线完整 + 工具 context 依赖键不悬空 |
| F | 存量 agent enabled_tools 无死引用 |
| G | 恒注入/条件注入工具不暴露在前端可勾选集合（噪音检测） |
| H | system_prompt_fragment 覆盖面（description-only 工具列出人工判断） |

---

## 六、HTTP 端点

| 端点 | 权限 | 用途 |
|------|------|------|
| `GET /agent/tools` | 登录用户 | 前端工具下拉数据源（provider + function + parameters schema + system_prompt_fragment） |
| `GET /agent/tools/{name}` | 登录用户 | 单工具详情 |
| `GET /agent/tools-runtime` | AGENT_MANAGE_SYSTEM | 运行时诊断：builtin_tools（含 default_timeout_ms）+ MCP 服务器连接与解析结果 |

前端 `WorkspaceLayout.vue` 的 `PRIORITY_TOOLS = ['knowledge_search', 'web_search']`
控制下拉置顶。

已知遗留（audit 脚本 G 组 WARN）：`plan_output` / `read_attachment` /
`read_tool_result` 三个注入工具仍出现在 /tools 可勾选集合——勾选无增量
效果，待端点过滤或 UI 置灰。

---

## 七、相关测试

- `tests/engines/agent/test_tool_description_engineering.py`：三件套回归
  （schema 保真往返 / 注册期 fail-fast / 失败指引与连败升级）
- `tests/engines/agent/test_tool_argument_validation.py`：参数校验器
- `tests/features/agent/test_tools_runtime_endpoint.py`：诊断端点
- `tests/features/agent/test_wiki_tools.py` 等：各工具行为测试
