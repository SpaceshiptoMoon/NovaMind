# 工作台对话前端架构（会话中心 + 共享聊天组件）

> 状态：**当前有效**（2026-11-11 核对源码）。描述 2026-11 工作台 UI 两轮收敛与「单聊 / 协作对话」入口统一之后的前端结构，以及配套的后端会话端点。
> 取代：[`group-chat-frontend-design.md`](./group-chat-frontend-design.md) 中的入口、路由、组件布局三节（该文保留为历史方案）。
> 配套：群聊数据模型与编排见 [`group-chat-multi-agent-design.md`](./group-chat-multi-agent-design.md)；本地工作区见 [`local-workspace-runner-design.md`](./local-workspace-runner-design.md)。
> 设计语言：Neutral Minimal，token 唯一权威是 `frontend/src/style/base.css`，改色须 light / dark 成对改。

## 1. 一句话架构

**入口统一、引擎分治**：侧栏是混排单聊与协作会话的「会话中心」，创建走同一个弹窗；进入会话后，单聊（`AgentChatView`）与协作对话（`GroupChatView`）仍是两个 view，但共用同一套聊天渲染组件。后端单聊走 SSE / WS 的 ReAct 循环，协作走群编排器，二者没有合并。

用户可见文案里「群聊」已统一改称**协作对话**；代码标识符与后端路径仍沿用 `group`。

## 2. 路由

定义在 `frontend/src/router/index.ts` 的 `/home/workspace` 节点下（`WorkspaceLayout` 挂在 `/home` 顶层）。

| 路径 | 路由名 | 组件 | 说明 |
| --- | --- | --- | --- |
| `chat` | `WorkspaceChat` | `views/chat/ChatEntryView.vue` | 对话入口：解析默认助手后落到对话页 |
| `chat/:sessionId` | `WorkspaceSessionChat` | `views/chat/SessionEntryView.vue` | **会话直达**：侧栏会话中心条目统一走此路由 |
| `agents/:agentId/chat` | `WorkspaceAgentChat` | `views/agent/AgentChatView.vue` | 单聊对话页 |
| `groups/:groupId(\d+)` | `WorkspaceGroupChat` | `views/agent/GroupChatView.vue` | 协作对话页（`requiresApp: 'agent'`） |
| `agents`、`groups` | — | redirect → `chat` | 占位页已清退，旧链接兼容 |
| `chat/archive`、`research/*` | — | redirect → `chat` | 历史路径兼容 |

`SessionEntryView` 是一个只显示加载态的薄 view：拉 `GET /agent/sessions/{sessionId}`，按 `extra_config.group` 是否存在判断会话类型后立即转跳。

- 群会话 → `WorkspaceGroupChat`，`query.sessionId` 带目标会话供群页定位。
- 单聊 → 补齐 `agentStore.currentAgent` 与会话列表 → `WorkspaceAgentChat` → 拉历史消息。
- 会话不存在、非本人或已删除 → 退回 `chat` 入口（错误提示由 request 拦截器统一 toast）。

两条约束写在该文件注释里，改动时不要破坏：`fetchMessages` 必须在 `router.push` **之后**（`AgentChatView` 挂载时的 `initForAgent` 会清空消息）；转跳前若有流式进行中须先 `cancelStream`（SSE 回调写全局 `messages`，不中止会串台）。

## 3. 侧栏：会话中心

实现在 `frontend/src/layouts/WorkspaceLayout.vue`，数据源是 `agentApi.listRecentSessions()`（`GET /agent/sessions/recent`）。

### 3.1 固定三分类

| 分类 key | 文案 | 判定 |
| --- | --- | --- |
| `agent` | 助手对话 | `kind=agent` 且 `workspace_bound=false` |
| `workspace` | 本地项目 | `kind=agent` 且 `workspace_bound=true`（绑定了本地工作目录的单聊） |
| `group` | 协作对话 | `kind=group` |

- 分类是**用途类别**，不是按所属助手分组；空分类不占位。
- 类头为 chevron + 类名 + 会话数，点击切换折叠（`collapsedCategories`，会话内存态，默认全展开，刷新后复位）。
- 条目两行：标题 + 归属副标题（单聊 = 助手名，协作 = 成员名）。未命名时单聊回退显示「新对话」，协作回退显示更新时间。
- 条目 hover 动作：协作条目是编辑 / 解散 / 删除会话三个，单聊条目只有删除会话。
- 会话的打开、删除动作全部收编在布局层，页内不再有第二个会话栏。
- 侧栏折叠成 rail 时，对话页只留展开键；其它页面显示创建按钮与助手、协作群的快捷图标。

### 3.2 创建入口

三个分类头各有一个 + 号，按类预置创建形态（`openUnifiedCreate(preset, autoBind)`）：

| 分类头 | 行为 |
| --- | --- |
| 助手对话 | 打开 `UnifiedCreateDialog` 默认形态 |
| 本地项目 | 打开 `UnifiedCreateDialog`（`autoBind`）→ 选助手后显式建会话 → 直达路由带 `bind=1` → `AgentChatView` 自动弹出目录绑定 |
| 协作对话 | 打开 `UnifiedCreateDialog`（`preset='group'`） |

### 3.3 助手管理抽屉

侧栏标题行右侧的「助手」按钮打开助手管理抽屉（`WorkspaceLayout` 内联的 `el-drawer`）。抽屉头部有「创建助手」主按钮，列表首位常驻一个创建条目，其下每个助手有配置 / 编辑 / 删除三个动作。「配置」打开只读的 `AgentConfigDrawer`，「编辑」打开 `AgentFormDialog`。

## 4. 统一创建弹窗

`components/agent/manage/UnifiedCreateDialog.vue`，props 为 `preset?: 'agent' | 'group'` 与 `autoBind?: boolean`，建成后 emit `created`。

- **助手形态**（`preset='agent'`，默认）：助手卡片直达层，点卡片即进入对话，无确认按钮。
- **协作形态**（`preset='group'`）：只保留成员多选与模式卡（头脑风暴 / 专家咨询）。群名自动生成：取前 3 位成员名以「×」连接，超出追加「等 N 人」。专家咨询的主持人默认取首位成员，头脑风暴的讨论轮数默认 1。
- 完整配置（改名、主持人、轮数、成员增删）后置到协作对话页头部的「协作设置」按钮，复用 `GroupFormDialog`。

创建时少问、进入后可改，是这一版的取舍：对话类产品的创建流程应尽量零配置。

## 5. 共享聊天组件

单聊与协作对话共用 `components/agent/chat/` 下五个组件，两个 view 只负责数据加载与事件编排。

| 组件 | 职责 |
| --- | --- |
| `ChatHeader.vue` | 页头：agent 徽标 +「对话 / 轨迹」互斥切换（纯展示件） |
| `UserMessage.vue` | 用户消息行：右侧气泡 + 附件卡（图片缩略走带 token 的 Blob 预览） |
| `AssistantTurn.vue` | assistant 一轮：折叠条 → 标记卡 → 工作轨迹 → 最终回复，展开态组件内自持 |
| `WorkTrail.vue` | 一轮内的 ReAct 轨迹（AI 步骤摘要 / 工具执行卡 / 思考段），工具详情跳右面板 |
| `InputCard.vue` | 输入卡，能力开关 props 化 |

`InputCard` 通过 `enableAttachments` / `enableModes` / `enableResearch` / `enableWorkspace` / `enableModel` / `enableContext` 六个 props 让宿主按需裁剪——协作对话把不适用的能力关掉即可，不需要第二个输入组件（原 `GroupComposer.vue` 已删除）。

输入行的当前形态：

- **+ 弹出菜单**收纳上传、深度研究、工作目录三项；深度研究开启后才显示对应 chip。
- **回答模式是单选档位**：极速（直接作答）/ 深度思考（先推理再作答）。后端 `enable_thinking` 是布尔值，所以只有两档。**流式开关已删除，恒走流式。**
- 上下文用量计（ContextMeter）只在超过 70% 警戒线时显示。
- 每轮回答结束后，输入卡上方浮现追问建议 pills（`POST /agent/sessions/{session_id}/suggestions` 生成）；发送新消息即收起上一轮建议。

共享逻辑放在组件之外：

| 位置 | 内容 |
| --- | --- |
| `utils/chatRender.ts` | 消息按轮分组（`groupTurns`）与渲染解析纯函数；`formatToolArgs` 同时接受字符串与已解析对象（协作对话的工具参数是对象） |
| `utils/attachmentPreview.ts` | 附件 Blob 预览，模块级缓存 |
| `composables/useWorkspaceBinding.ts` | 工作目录绑定逻辑 |
| `components/agent/WorkspaceBindDialog.vue`、`WorkspaceBrowser.vue` | 目录绑定弹窗与目录浏览器，**绑定的唯一实现** |

`WorkspaceBrowser` 在 `onMounted` 时自行列出根目录。原因是 `el-dialog` 惰性渲染：宿主在弹窗打开时调用的重置方法会早于浏览器挂载而被静默跳过，导致首次打开列表为空。

## 6. 管理弹窗

`components/agent/manage/` 下的组件由 `WorkspaceLayout` 挂载（都用 `append-to-body`，所以必须挂在布局层）：

| 文件 | 职责 |
| --- | --- |
| `UnifiedCreateDialog.vue` | 新建对话（见第 4 节） |
| `AgentFormDialog.vue` | 助手创建 / 编辑全量表单；工具下拉在此，`PRIORITY_TOOLS` 置顶知识库与联网搜索 |
| `GroupFormDialog.vue` | 协作对话全量编辑表单 |
| `AgentConfigDrawer.vue` | 助手只读配置抽屉 |
| `formDialog.css` | 两个表单弹窗共享的样式 |

## 7. 右侧面板

`components/workbench/WorkbenchDrawer.vue`，**仅在 `WorkspaceAgentChat` 路由挂载**（协作对话页没有右面板）。

- 三个视图：引用 / 工具 / 目录，默认引用。
- 常驻入口是对话页右上角的浮动展开按钮；点击消息里的工具调用会直接打开面板的工具详情视图。
- 「对话」与「轨迹」是全屏互斥的两个视图（轨迹用 `TrajectoryList`，内嵌 `TrajectoryInspector` 详情栏），轨迹不在右面板里。

## 8. 配套后端端点

均在 `backend/src/features/agent/api/routes.py`，群相关在同目录 `group_routes.py`。

| 端点 | 说明 |
| --- | --- |
| `GET /agent/sessions/recent` | 会话中心聚合列表，`updated_at` 倒序，`limit` 默认 50、钳制到 1–100。按用户过滤，排除群成员私有会话；批量取名避免 N+1；所属群已解散或助手已删除的悬空会话跳过。**必须先于 `/sessions/{session_id}` 注册**，否则 `recent` 被动态段吞掉 |
| `POST /agent/agents/{agent_id}/sessions` | 显式新建单聊会话（201），**幂等**：存在「无消息且无群标记」的 active 空会话时复用它 |
| `POST /agent/sessions/{session_id}/suggestions` | 基于最近消息生成追问建议 |
| `POST /agent/groups` | 建群，**同事务原子创建首条时间线会话** |

响应条目 `SessionCenterItem`（`schemas/agent_schema.py`）：

```python
session_id: str            # 会话 UUID
kind: str                  # agent=单聊 / group=群会话
workspace_bound: bool      # 单聊是否绑定本地工作目录；群会话恒为 false
title: str | None          # 未生成时为 null
ref_id: int                # 单聊=Agent ID，群会话=群 ID
name: str                  # 单聊=助手名，群会话=群名
member_count: int | None   # 仅群会话有值
members: list[str] | None  # 群成员名，最多 3 个
updated_at: datetime | None
```

三个实现要点：

1. **空会话判据是消息表计数，不是 `title IS NULL`。** 首轮对话被中断会留下「有消息但没有标题」的会话，按标题判会把它误当空会话复用。
2. **发消息时的缺省建会话分支同样幂等**，会复用显式创建留下的空会话，避免产生孤儿会话。
3. **建群原子建会话**消除了一个时序缺口：此前首条会话由前端进群后 get-or-create，晚于会话中心列表刷新，新群不会立刻出现在侧栏。get-or-create 仍保留作兜底。

已删除的端点：`POST /agent/workspace/validate`（无调用方）。

## 9. 文件规模基线（2026-11-11）

| 文件 | 当前行数 | 拆分前行数 |
| --- | --- | --- |
| `views/agent/AgentChatView.vue` | 449 | 3270 |
| `views/agent/GroupChatView.vue` | 268 | 435 |
| `layouts/WorkspaceLayout.vue` | 1442 | 2173 |
| `components/workbench/WorkbenchDrawer.vue` | 832 | 1128 |
| `components/agent/chat/InputCard.vue` | 1092 | 新增 |
| `utils/chatRender.ts` | 445 | 新增 |

「拆分前行数」取各文件对应拆分提交的父提交实测值。`WorkspaceLayout` 在拆出弹窗后一度降到约 1000 行，会话中心与助手管理抽屉落地后回升到 1442 行；`InputCard` 是目前最大的单组件。两者是下一步拆分的候选。

## 10. 已知遗留

以下均为已评估、暂未实施的项，不是缺陷：

- **断连转后台续跑**：WS 断连即取消当前运行，是工作台最痛的问题，优先级最高。
- **会话重命名 / 搜索 / 置顶**：后端尚无对应端点。
- **长会话虚拟化、会话导出**：未做。
- **审批卡协议化、`@` 引用选择器、`/goal` 命令**：明确排除在本轮之外。
- **空会话过滤或降权**：会话中心目前会列出尚无消息的空会话，可选优化。
- **折叠态不持久化**：分类折叠状态只在内存里，刷新后全部展开。
