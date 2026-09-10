# 深度研究模块：与 deer-flow 全流程对齐说明（2026-09）

> 考证基线：bytedance/deer-flow `main-1.x` 分支（经典 Planner/Researcher/Reporter
> LangGraph 架构，2025-09 快照 commit `79ab7365`）。deer-flow 2.0 已重写为
> super-agent harness，不在对齐范围。

## 流程映射表

| deer-flow 1.x | NovaMind | 说明 |
|---|---|---|
| coordinator（任务路由判定） | **不做** | NovaMind 深度研究是用户显式发起的功能，不存在"是不是研究任务"的路由问题 |
| background_investigator | `engine.background_investigation` | 规划前单轮检索（尊重 search_source 路由，非固定 Tavily）；结果注入 planner prompt；`enable_background_investigation` 默认开；失败降级空列表 |
| planner（Plan JSON） | `engine.analyze_plan` | 输出 `{has_enough_context, thought, title, steps[{step_type, need_search, ...}]}`；`research_plan` prompt 替代旧 `research_decompose_tasks`；解析失败降级默认计划 |
| Context Assessment | `has_enough_context` | planner 看到背景调查后判足够 → 空步骤 → 管线跳过检索直接 reporter（严格判定语义写入 prompt） |
| human_feedback（interrupt） | `PlanFeedbackRegistry` + WS `plan_generated`/`plan_feedback` | 计划卡确认/修订；`[EDIT_PLAN]` = edit_plan 携 feedback 重规划；**超时 auto-accept 300s**（与 agent 审批 fail-closed deny 相反：计划非危险产物）；非流式 POST 强制 auto-accept |
| max_plan_iterations（默认 1） | `DEFAULT_MAX_PLAN_ITERATIONS=1` | 首轮计划可被修订一次；再编辑按现计划继续（熔断）；完成后不做二次规划评估 LLM 调用（deer-flow 默认配置同样直通 reporter），管线留 while 骨架 |
| researcher（ReAct agent） | `engine.search` 观察驱动模式 | 每轮检索后反思 `{sufficient, next_query, reason}`；query 演化；机械阈值兜底；跨步骤 finding 注入（见下） |
| observations / `<finding>` | `TaskFinding` 事件 + prior_findings | 前序步骤 finding 注入后续步骤反思 prompt；累积进 `SearchComplete.task_findings` 喂 reporter |
| coder（代码执行步骤） | **不做** | 无沙箱；processing 步骤用纯 LLM 实现近似语义 |
| processing/analyst 步骤 | `_run_processing_step` | step_type=processing（或 need_search=false）走纯 LLM 分析：综合前序发现产出结论，产出 finding 并入信息流；未注入 LLM 时静默跳过；全 processing 计划守卫强制首步转 research |
| reporter（五段结构） | `research_synthesize_report[_stream]` | Key Points → Overview → Detailed Analysis → Survey Note → Key Citations；markdown 表格优先；正文 [n] 编号引用 + 文末链接；语言跟随 query（不引入 locale 字段） |
| report_style（四种） | `report_style` 请求字段 | academic/popular_science/news/default；feature 侧 `_STYLE_INSTRUCTIONS` 预格式化指令块注入（str.format 无法条件分支） |
| citations | `result.citations` | 引擎纯函数 `extract_citations`（全量去重 {title,url,source_type}）；`result.sources`（≤5 字符串）保留兼容 |
| State.plan_iterations / observations / current_plan | `ResearchContext` / plan JSON v2 | plan 列存 `{"version":2, title, thought, has_enough_context, iteration, background_investigation_results, steps[{execution_res}]}`；v1 旧形状兼容读 |

## WS 协议增量（向后兼容）

- 下行新事件：`plan_generated`
  `{"type":"plan_generated","data":{session_id, plan:{title,thought,has_enough_context,iteration,steps[]}, wait_feedback, feedback_timeout_seconds}}`
- 上行新消息：`{"action":"plan_feedback","decision":"accepted"|"edit_plan","feedback":"..."}`
- done 事件 data 增 `citations`
- progress/content/done/error 既有语义不变

## 关键文件

- `backend/src/engines/deep_research/engine.py` — 引擎（analyze_plan/background_investigation/search 路由/synthesize）
- `backend/src/engines/deep_research/types.py` — StepType/PlanStep/ResearchPlan/TaskFinding/事件
- `backend/src/features/deep_research/services/deep_research_service.py` — 管线编排（_plan_phase/_plan_phase_stream）
- `backend/src/features/deep_research/services/plan_feedback_registry.py` — 计划确认挂起
- `backend/src/features/deep_research/api/routes.py` — WS 双 task 接线
- `frontend/src/components/research/ResearchPlanCard.vue` — 计划卡组件

## 手动验证清单（WS 双向流程）

1. 前端设置面板关闭「自动确认计划」→ 发起研究
2. 出现计划卡，研究挂起（plan_generated）
3a. 「确认执行」→ 检索进度继续 → 报告完成
3b. 输入意见「修订计划」→ 新计划卡（iteration=1）→ 再确认；再修订 → 提示达上限按现计划继续
3c. 不操作等 300s → 日志「计划确认超时，自动接受」→ 继续
3d. 等待期间关闭页面 → 详情接口 status=cancelled
