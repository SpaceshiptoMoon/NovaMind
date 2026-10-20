# 多智能体群聊设计方案（草案，待评审）

> 状态：设计草案。实现前需用户确认范围与分期。

## 1. 需求

用户创建「群聊」，把自己创建的多个智能体拉为成员。两种模式：

- **头脑风暴模式**：用户发一条消息，成员们**依次**发言讨论（后发言者能看到先发言者的内容）。
- **专家咨询模式**：用户发一条消息，由群**主持人**（从成员中指定）接题——它把合适的成员当作工具调用（成员作答回流），可连问多个、可不问自己答，最后综合答复。

用户提出的通信机制：每个 agent 一个**信箱**（mailbox），agent 可调用工具给其他 agent 发消息；每个 agent 每轮 turn 读取信箱新消息，信箱维护 **offset** 记录已读进度。

## 2. 方案核心决策（对用户原始方案的修正）

### 2.1 信箱 = 投递机制，读取在基础设施层，不是模型调工具读

保留信箱思想，但**读信不改由模型发起**（cc 同款结论，见第 10 节）：

| 用户原方案 | 修订后 | 理由 |
|---|---|---|
| agent 每轮调工具读信箱 | 编排器把信件**投递写入成员私有会话**（见 2.3），成员 turn 自然消费 | 模型调 `read_mailbox` 多花一轮 LLM 且会忘调/漏调 → 信件丢失。与 steering 队列（f890251f）同一思想：**边界消费，不靠模型自觉** |
| 信箱维护 offset 表示已读 | offset 概念消亡：会话历史即消费状态，投递写入会话即已消费 | 会话是 append-only 事实源，水位职责被会话历史吸收，少一份状态 |
| —— | 保留 `send_group_message` / `send_direct_message` 工具，仅用于**发信** | 发信是模型真实意图的表达，适合工具化 |

### 2.2 执行模型：拉起式编排，不建常驻 agent 进程

没有消息驱动的「agent 常驻循环」。用户消息触发一次编排：

```
用户消息 → GroupOrchestrator（编排器）
  ├─ 头脑风暴：确定发言顺序 → 逐个拉起成员 turn（串行）
  └─ 专家咨询：拉起主持人 turn → 主持人经 consult 成员工具按需拉起成员
每个 turn = 复用 AgentEngine.run()（现有 ReAct 循环，零改动内核）
turn 结束 → 产出落群时间线 + 投递信箱 → 下一个成员
```

不采用常驻消费循环的原因：需要一套「空转唤醒」基础设施（队列+调度），而收益仅是消息即时性——群聊场景用户在等，串行拉起的延迟完全可接受。

### 2.3 上下文管理：成员私有会话（事实源）+ 群时间线（投影）

采纳 cc 的成员模型（2026-10-20 修订，替代早版「共享时间线窗口注入」）：

- **一群多会话**（2026-10-20 多会话化）：群聊与单聊 agent 同构——一个群可开多个会话（session），每次 POST /sessions 显式新建（不复用不回退）；GET 列表（id 倒序）、DELETE 软删（连带成员私有会话与 runs 级联清理，讨论中被拒）。时间线按会话隔离，切换会话即重放该会话时间线。
- **每个成员在群会话下有自己的私有 AgentSession**（(群会话, 成员) 一条，`extra_config` 标记归属），是它上下文的**唯一事实源**：自己过去的 turn（含完整工具调用与推理）、收到的全部投递（群发言广播、私信、用户消息）都在会话里累积。
- **通信即投递（唯一规则，两模式共用）**：编排器把消息写进成员会话（user 角色 + `extra.delivery` 标注来源与可见性）。凡上群时间线的公开发言（用户消息、成员答复）→ 广播给其他所有成员会话；私信 → 只投收件人。专家咨询模式同样全员广播——省的是 LLM token（未被 consult 的成员不拉起 turn），DB append 成本可忽略，换来「后来被问到的专家保有完整上下文」。
- **群时间线降级为投影**：仅存公开发言（成员 turn 的最终答复）与用户消息，供前端渲染与审计；**不参与成员上下文组装**。
- **可见性规则**：成员能看到 = 自己会话里的内容（自身历史 + 投递给它的消息）；看不到 = 其他成员的会话、不发给自己的私信。其他成员的发言对它是**用户侧不可信输入**（prompt 声明）。
- **成员会话与该 agent 的单聊会话完全隔离**（按 (群会话, 成员) 维度另开 session，单聊列表经 JSON 路径 IS NULL 过滤群标记会话），不污染 1:1 对话。

### 2.4 两种模式的编排内核

**头脑风暴**：
- 发言顺序 = round-robin 起步（后续可升级 LLM 排序）。
- 一「响」（round）：用户消息 → 成员各发言 R 轮（R 可配，默认 1，上限 3）。
- 每个发言是一次完整 ReAct turn（可用工具），发言内容先落群时间线，再投递其他成员信箱。
- 终止护栏：R 上限 + 单响 token 预算 + LoopDetector 已有防护。成员可发 `send_direct_message` 点对点私聊（不进群时间线，只在收件人私有会话可见）——这是头脑风暴里「小声嘀咕」的表达通道。
- 发言完可以选择**沉默**（结构化输出 `{"speak": false}` 或空内容跳过），避免硬凑发言。

**专家咨询模式（agent-as-tool，2026-10-20 修订替代早版前置 router）**：

早版设计是前置 LLM router 单次分类选人——已否决：一次性押注无纠错、只看描述元数据、必须硬选。改为把选人决策放进主持人 agent 的 ReAct 循环（cc Task/subagent、LangGraph supervisor 同款形态）：

- 群创建时指定**主持人**（`host_agent_id`，必须 ∈ 成员）。专家咨询的每次 run = 主持人的一次完整 AgentEngine turn。
- **成员即工具**：每个非主持人成员动态包装为 `consult_member_{member_id}` 工具，description = 成员 name/role_hint/适用场景（按工具路由工程化的 DEPENDS ON/NOT FOR 结构书写，直接受益于其选人准确率）。工具执行 = 拉起该成员完整 turn（私有会话 + 自有业务工具，与头脑风暴共用同一条 `_run_member_turn` 路径），成员最终答复作为 tool_result 回流主持人；成员发言同时上群时间线（group.speaker 渲染独立气泡）。
- 主持人能力天然覆盖 router 做不到的事：先问 A 不满意再问 B（纠错）、并行问多个再综合、谁都不问自己反问澄清或直接答。
- 主持人 turn 注入工具 = 自有 enabled_tools + consult 成员工具；**成员 turn 不注入 consult**（无递归），头脑风暴模式两样都不涉及。
- 群身份段 prompt 键 `agent_group_identity` 覆盖两模式（主持人职责说明在专家咨询下追加一段）。
- token 护栏：成员答复全文作为 tool_result 进主持人上下文，超长截断（阈值配置化），全文在成员会话与时间线可查。

## 3. 数据模型

新增三张表（features/agent/models/，经 manifest models_loader 建表，遵守 DB 无 Alembic 惯例）：

```python
class AgentGroup(Base):
    id, user_id, name, description
    mode: str            # "brainstorm" | "consult"
    host_agent_id (FK→agent_definitions, nullable)  # 主持人，必须∈成员；brainstorm 可空，consult 必填
    extra_config: JSON   # rounds_per_turn、max_round_tokens 等编排参数
    created_at, updated_at

class AgentGroupMember(Base):
    id, group_id (FK), agent_id (FK→agent_definitions)
    role_hint: str       # 给 consult 工具描述/其他成员看的补充描述（可选）
    speak_order: int     # 头脑风暴默认顺序
    joined_at

class AgentGroupRun(Base):   # 一次用户消息触发的一响编排（隔离单元）
    id, group_id, user_id
    session_id (FK→agent_sessions)   # 群会话（时间线所在）
    status: str          # pending/running/done/failed/cancelled
    mode_snapshot: str   # 触发时的模式
    orchestration_meta: JSON  # 审计：brainstorm 记发言序列；consult 记主持人调用的成员工具与顺序
    error: str | None
    started_at, finished_at
```

**成员私有会话（上下文本源）**：每个 (群会话, 成员) 一条 `AgentSession`，复用现有模型，`extra_config.group_member = {group_id, group_session_id}` 二元组标记归属——消息持久化、任务化压缩（faee58ad）、context-usage 端点全部免费复用。无需新表、无需 offset 列。旧格式（仅 group_id）会话与新查询不匹配即新建（不迁移，失败方向安全：新会话空白优于串入旧上下文）。

**投递即会话消息**：编排器投递 = 直接向成员会话 append 一条 user 角色消息，`extra.delivery = {from, visibility: "group"|"direct", run_id}`。公开发言/用户消息 visibility=group，私信 visibility=direct。无需独立 DM 表。

**群时间线（投影）**：群会话（`extra_config.group` 标记的 `AgentSession`）只存公开发言与用户消息，成员发言 `role="assistant"` + `extra.member_agent_id=<agent_id>`，前端按此渲染头像/名字。仅渲染与审计用。

## 4. 通信与执行链路

### 4.1 send_message 工具（新内置工具 provider，仅头脑风暴）

```
group_messaging provider（BaseTool 子类，features/agent/tool/builtins/group_messaging.py）
  ├─ send_group_message(content)      → 追加群时间线（等价公开发言）
  └─ send_direct_message(to_member, content) → 投递收件人私有会话
```
- 注册：registry_setup.py 元组加实例；**仅头脑风暴模式的成员 turn 注入**（单聊/专家咨询不出现）。
- ToolContext 注入 `group_run_id`/`member_agent_id`，工具侧校验 to_member 必须是同组成员（防注入传播到非成员）。
- 私信不触发被收件人立刻执行（只在被拉起时消费）——防止 A→B→A 死循环。

### 4.1b consult 成员工具（专家咨询模式）

- 成员动态包装：`consult_member_{member_id}` 工具实例在群 run 组装时按成员表动态生成（非注册表静态注册），description 按工具路由工程化的 DEPENDS ON/NOT FOR 结构从成员 name/role_hint 派生；parameter 为 `question: str`。
- 工具执行体 = 编排器的 `_run_member_turn(run, member, question)`（与头脑风暴共用），成员答复全文作 tool_result 回流；成员发言事件照常 WS 转发（前端渲染独立气泡）。
- 成员答复超长截断阈值 `max_consult_result_tokens`（extra_config 配置化）；全文在成员私有会话与群时间线可查。

### 4.2 编排器（GroupOrchestrator，services/group_orchestrator.py）

伪代码（头脑风暴）：

```python
async def run_round(self, run: AgentGroupRun, user_content: str):
    members = await self.load_members(run.group_id)          # 按 speak_order
    for member in members:                                   # wave 0：用户消息投递全员
        await self.deliver(member, from_="user", content=user_content, visibility="group")
    for wave in range(config.rounds_per_turn):               # 默认 1，上限 3
        for member in members:
            if wave > 0 and member_spoke_nothing(member, wave - 1):
                continue                                     # 沉默者跳过
            speech = await self._run_member_turn(run, member)
            # 成员私有会话上下文（已含收到的全部投递）→ AgentEngine.run()；
            # 事件流 WS 转发；最终答复即公开发言
            if not speech:
                mark_silent(member)
                continue
            await self.append_timeline(run, member, speech)  # 群时间线投影
            for other in members:
                if other is not member:
                    await self.deliver(other, from_=member, content=speech, visibility="group")
            if token_budget_exceeded(run):
                return                                       # 预算护栏
```

关键复用点（引擎调研结论）：
- `AgentEngine.run(llm_client, messages, tools, context, ...)`（agent_engine.py:62）吃任意 messages/tools 列表，对「单聊/群聊」无感 → 成员 turn 直接传「成员私有会话 build_context 产出的 messages + 该成员自己的 enabled_tools + group_messaging」。**引擎内核零改动**。
- 每个成员用自己的 `llm_client`（get_llm_client_by_model(member.user_id, member.llm_model)）——不同成员可挂不同模型。
- LoopDetector/max_iterations/压缩都在引擎内，成员 turn 免费继承。
- 成员 turn 的落库与 chat_service 同构（事件 → 成员会话消息），实现为 chat_service 的群变体；用户消息与终态 commit 时机照抄单聊防长事务惯例。
- steering 队列：群场景下成员 turn 期间用户插话 → 注入**当前运行成员**的队列（现有 WS recv 路径），或排队到下一成员的信箱（首版选后者，简单）。

### 4.3 专家咨询模式：主持人 ReAct 循环替代前置路由

```python
async def run_round(self, run: AgentGroupRun, user_content: str):
    host = await self.load_host(run.group_id)                # host_agent_id，创建时校验∈成员
    # ① 用户消息广播全员会话（纯 DB append，无 LLM）
    for member in await self.load_members(run.group_id):
        await self.deliver(member, from_="user", content=user_content, visibility="group")
    # ② 主持人一次完整 AgentEngine turn；consult_member_* 工具在过程中按需拉起成员
    speech = await self._run_member_turn(run, host, user_content, consult_tools=self._build_consult_tools(run))
    #    - 每次 consult 调用 → 成员完整 turn（私有会话+自有工具）→ 答复 tool_result 回流
    #    - 成员发言照常上群时间线 + WS group.speaker
    # ③ 主持人最终答复上时间线，run.orchestration_meta 记 consulted 序列（审计）
    await self.append_timeline(run, host, speech)
```

关键点：

- **选人决策发生在 ReAct 循环内**——主持人可先问 A 不满意再问 B、可并行问多个综合、可谁都不问自己答/反问澄清。前置 router 的一次性押注、只看元数据、必须硬选三个缺陷全部消解。
- consult 工具执行失败（成员 turn 异常）→ tool_result 返回错误文本，主持人自行决定重试换人——失败处理天然交给模型，无需编排器回退逻辑。
- 审计：`orchestration_meta.consulted = [{member_id, question_digest, ok}]`。

## 5. WS/API 设计

### REST（features/agent/api/group_routes.py，RouterSpec 声明进 manifest）

```
POST   /agent/groups                        建群（name/mode/member_ids/配置）
GET    /agent/groups                        我的群列表
GET    /agent/groups/{id}                   群详情（含成员）
PUT    /agent/groups/{id}                   改配置/成员增删
DELETE /agent/groups/{id}                   解散
POST   /agent/groups/{id}/sessions          显式新建群会话（一群多会话，不复用不回退）
GET    /agent/groups/{id}/sessions          群会话列表（id 倒序）
DELETE /agent/groups/{id}/sessions/{sid}    删群会话（连带成员私有会话与 runs 级联清理；讨论中被拒）
GET    /agent/groups/{id}/sessions/{sid}/messages  时间线消息（该会话投影）
GET    /agent/groups/{id}/runs              运行历史
GET    /agent/groups/{id}/members/{mid}/session  调试用：查看某成员私有会话消息（owner）
```

### WS 群对话

`/agent/groups/{group_id}/ws`，协议与单聊一致（action=chat），事件流**兼容现有前端分发器**：

现有事件照发（session/content/tool_call/done...），新增：

```
group.speaker     {member_agent_id, name}   # 发言开始，前端切换头像/流式渲染目标
group.run_done    {run_id, status, rounds}  # 一响结束
```

content 事件带 `member_agent_id` 字段（data 内加键，向后兼容）。前端渲染：群时间线按消息流渲染，每条发言一个气泡（头像=成员 agent）。

## 6. 上下文管理细则

成员 turn 的上下文 = **其私有会话**经现有 MemoryManager.build_context 组装（编排器只负责投递与拉起，不做定制拼装）：

```
system: 成员自己的 system_prompt
        + 群身份段（你是「X」，群成员还有：A（简介）、B（简介）…；模式与 send_* 工具使用指引）
历史（原生消息结构，非拼接文本）：
  - 自己过去的 assistant turn（完整 tool_use/tool_result——上一波查了什么、怎么推理的，这波原样记得）
  - 收到的投递（user 角色）：
    <delivery from="市场分析师" visibility="group">……发言内容……</delivery>
    <delivery from="产品经理" visibility="direct">……私信……</delivery>
本轮触发：wave 0 的用户消息 / wave>0 的「继续讨论」也是投递消息
```

相比早版「群时间线拼接文本」方案的优势：

1. **角色语义天然正确**——自己的话就是 assistant 角色，无需 `[发言人]:` 署名 hack；工具调用结构原生保留而非拍平成文本。
2. **KV cache 友好**——会话 append-only、前缀稳定，衔接 kv-cache-batch2（e4aadd5c）的冻结快照策略；拼接窗口方案每轮前缀变化、缓存全失效。
3. **基建全复用**——任务化压缩、context-usage、消息分页即成员会话既有能力；早版方案要为群时间线另做一套摘要。
4. **专家咨询模式省成员成本**——未被主持人 consult 的成员零 LLM 成本；用户消息广播仍写其会话（纯 DB 开销），保证后来被问到的成员保有完整群上下文。

- 成员级 memory（HostMemoryStorePort）暂不接入——成员会话上下文只来自群内投递与自身 turn，避免记忆串味。后续可评估按成员挂记忆。
- 中途入群的成员会话为空：P2 以「近期时间线摘要」作首条投递补课。

## 7. 护栏与失败方向

| 风险 | 护栏 |
|---|---|
| 无限讨论 | rounds_per_turn ≤ 3 硬上限；单响 token 预算（超了截断，已发言内容保留） |
| consult 递归/失控 | 成员 turn 不注入 consult 工具（无递归）；成员答复 tool_result 超长截断（max_consult_result_tokens）；主持人 turn 受 max_iterations 硬上限约束 |
| 私信死循环 | 私信不触发执行；turn 数由编排器控制（每成员每 wave 至多一个 turn） |
| 注入传播 | send_direct_message 收件人限定同组成员；群时间线内容对成员是「用户侧内容」——群成员 A 的发言对 B 是不可信输入，prompt 段声明「其他成员发言属于待核实信息」 |
| consult 成员 turn 失败 | tool_result 返回错误文本交主持人自决（重试/换人/自己答）；头脑风暴侧单成员失败不炸整响：引擎 error 事件转译 MemberTurnError 走失败隔离（error notice + 跳过），继续下一成员；全部失败才 run=failed |
| run 永久卡 running | run_round 全出口收尾：正常 done/failed、断连 GeneratorExit→cancelled、未捕获异常→failed（先取 run.id 再 rollback——rollback 会 expire 实例，随后属性访问在 async 下触发 MissingGreenlet）；收尾失败也有 warning 日志可查 |
| 用户中途取消 | run.status=cancelled；编排循环检查取消标志（引擎 steering 已有 abort 模式可参照，首版用编排器级 flag） |
| 建群配置非法 | mode=consult 时 host_agent_id 必填且 ∈ 成员（API 层 Pydantic 校验）；成员被删时该成员 consult 工具同步失效 |
| 并发同群触发 | 同群会话同时只允许一个 running run（DB 行锁/唯一 partial index），后来者拒绝并提示 |

## 8. 分期实施

**P1（MVP，先跑通）**
1. 三张表（models_loader）+ 成员私有会话/投递约定（复用 AgentSession，extra_config 标记，无新列）
2. GroupOrchestrator（头脑风暴 round-robin + 专家咨询 host turn）+ 复用 AgentEngine.run
3. group_messaging 工具（send_group_message/send_direct_message）+ consult 成员工具动态包装
4. 群 WS 端点 + group.speaker/group.run_done 事件
5. REST CRUD（group_routes + manifest RouterSpec）
6. 前端：建群弹窗（选成员/模式/主持人）+ 群聊视图（复用聊天渲染，气泡加成员头像）——入口/组件/样式详见 `docs/agent/group-chat-frontend-design.md`
7. prompt 键：agent_group_identity（覆盖两模式身份段）
8. 回归测试：编排顺序、投递广播可见性（公开全员/私信仅收件人）、私信不触发执行、consult 工具拉起成员与答复截断、头脑风暴预算截断、单成员失败隔离

**P2（打磨）**
- LLM 发言顺序排序；沉默判定优化（结构化 speak:false）
- 群时间线任务化摘要接 P1 窗口
- 成员级记忆接入（隔离评估后）
- 成员会话调试面板（前端查看成员私有会话上下文与投递）

## 9. 明确不做（边界）

- 不建常驻 agent 进程/守护消费循环（拉起式足够）
- 不做 agent 间自由组局（发起对话必须由用户消息驱动）
- 不做跨群消息路由
- 不改 AgentEngine 内核（单聊行为不动，引擎对群无感知）

## 10. 业界对照：Claude Code agent teams（2026-10-20 从本机 cc 2.1.27 cli.js bundle 逆向核实）

cc 的 agent teams 就是「信箱模式」的工业级实现，与用户原始提案同构。以下为核实到的实现事实：

### 10.1 cc 的架构事实

- **存储**：`~/.claude/teams/{team}/config.json`（成员名单：agentId/name/agentType/model/color/subscriptions/backendType）+ `~/.claude/teams/{team}/inboxes/{agent}.json`（每人一个信箱文件，消息数组，每条 `{from, text, timestamp, color, read}`）
- **并发**：读写均经 proper-lockfile 文件锁（`{path}.lock`），写后重读校验
- **已读语义**：**逐消息 `read` 布尔位，不是 offset 水位**。`readUnreadMessages` 过滤 `!read`，消费后 `markMessageAsReadByIndex` 单条标记已读
- **消费者是基础设施，模型从不读信箱**：teammate runner 在每轮 prompt 结束后进入轮询循环（首次立即、空转 500ms 间隔）：查未读信 → 标记已读 → 包装注入；无信时顺带从共享任务列表认领无主任务。官方 prompt 明示「Messages from teammates are automatically delivered to you. You do NOT need to manually check your inbox.」
- **注入格式**：信件包装为 `<teammate_message teammate_id="X" color="Y">text</teammate_message>` 后作为 user 消息进入该成员的会话
- **发送**：`SendMessage` 工具，schema `{type: message|broadcast|request|response, recipient, content, subtype, request_id, approve}`，按成员名寻址。broadcast 是逐成员写 N 个信箱，官方 prompt 明确警告开销线性（N teammates = N deliveries）并要求默认单发
- **一切皆信件**：初始任务指派（spawn 后把 prompt 写进成员信箱）、shutdown 请求/批准/拒绝、权限请求/响应、加群请求/批准、计划审批、任务分配通知——全部走同一信箱通道，用 JSON-in-text 的 `type` 字段区分，requestId 做请求-响应配对
- **空闲通知**：teammate 停止时自动向 team-lead 信箱投 `idle_notification`（含完成的 taskId），lead 据此知道谁空闲
- **上下文模型**：每个 teammate 是常驻进程 + **私有持久 transcript**——信件唤醒不重建上下文，自己的历史跨轮保留、超阈值自行 compact；跨成员共享状态放共享任务列表（TaskCreate/TaskUpdate），不放共享对话
- **显示后端**：tmux 分屏（每成员一个 pane）/ in-process runner 两栖，`--teammate-mode` 切换

### 10.2 对照结论

| # | 结论 | 对本设计的影响 |
|---|---|---|
| 1 | ✅ cc 的信箱读取也在基础设施层（runner 轮询），模型只写不读 | **验证 2.1 修正**（边界消费不靠模型自觉）。我们用编排器拉起前注入，cc 用常驻轮询注入，思想一致 |
| 2 | ✅ cc 用 XML tag + 颜色署名注入信件 | 验证第 6 节投递格式；我们用 `<delivery from visibility>` 包裹，同为「结构化标签信封 + 原文」方案 |
| 3 | ✅ cc 警告 broadcast 成本线性 | 头脑风暴每条公开发言由编排器逐成员写入 N-1 个私有会话，零额外 LLM 成本；P2 若开放成员主动 broadcast 需同样限频 |
| 4 | ✅ 已读语义收敛为「会话历史即消费状态」（2026-10-20 修订） | cc 用逐消息 read 位，初版用水位 offset；私有会话模型下两者都不需要——投递 = 事务性 append 到成员会话，写入即已消费，崩溃恢复由 DB 事务保证，无独立状态可漂移 |
| 5 | ⚠️ cc teammate 常驻空闲轮询 vs 我们拉起式 | cc 需要常驻是因它支撑「成员自主领任务」的工作流；群聊场景用户在等，拉起式足够。P2 若做「成员互发私信触发被收件人回应」，在编排器层补「信箱非空→补拉一轮」的唤醒判定（仍是拉起，非守护进程） |
| 6 | ✅ 已采纳 cc 每成员私有持久 transcript（2026-10-20 修订，初版判断有误） | 初版以 token 成本否了私有 transcript；复核后改为采纳：私有会话才能复用 per-agent 基建（压缩/context-usage）、保住 KV cache 前缀与成员自身工具过程记忆（详见 2.3/6 节修订记录）。idle_notification 在拉起式下仍不需要（编排器天然知道 turn 边界） |
| 7 | 📦 借鉴：一切皆信件 + 协议信件类型 | 未来成员管理（加群/退群审批）、任务分配、「成员请求人工审批」都走 DM 通道加 `type` 字段 + requestId 配对，不另造通道 |
| 8 | 📦 借鉴：cc 告诉成员「你的纯文本输出别人看不见，必须 SendMessage」 | 头脑风暴里发言即交付物（turn 产出自动落时间线），不需要此规则；但 P2 成员做长工具链工作时，过程性发现须 prompt 指引其主动 send_direct_message 分享，最终答复之外不要指望编排器转述 |
