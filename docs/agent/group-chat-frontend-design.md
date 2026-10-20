# 群聊前端设计：入口与样式（方案附篇）

> 状态：设计草案。与主文档 `group-chat-multi-agent-design.md`（数据/编排/通信）配套，只覆盖前端入口、路由、组件与样式。
> 遵循：`frontend/CLAUDE.md`（view/component/store 分层、抗压缩布局规范）、Neutral Minimal 设计语言（token 唯一权威 `base.css`）。

## 1. 入口与信息架构

### 1.1 入口位置：侧栏「我的智能体」分区下的第二个分区

工作台侧栏（WorkspaceLayout）现有「我的智能体」分区承载单聊 agent。群聊作为**同级分区**插入其下：

```
侧栏（展开态）              侧栏（折叠态 rail）
┌──────────────────┐      ┌──────┐
│ 我的智能体 (3)    ▾ │      │  [+] │  ← 创建智能体（现有）
│  ◻ 创建智能体      │      │  A   │
│  ⬡ 市场分析师      │      │  B   │
│  ⬡ 技术评审        │      ├──────┤  ← 分隔（视觉：留白，无分割线）
│  ⬡ 产品经理        │      │  ⧉  │  ← 群聊分组图标（点击=展开侧栏+滚到群分区）
│ 群聊 (2)          ▾ │      │  ⧉  │
│  ◻ 创建群聊        │      │  ⧉  │
│  ▣ 产品评审团      │      ├──────┤
│  ▣ 头脑风暴组      │      │  ›  │  ← 展开按钮（现有）
└──────────────────┘      └──────┘
```

- 分区结构完全复用现有 `list-section` 模式（`section-new-btn` + 可折叠 `list-area`），`sectionCollapsed` 增加 `group: boolean`。
- 群条目视觉与 agent 条目区分：agent 用首字方头像（现有 `.agent-avatar-sm`），群用**多圆点组头像**（2×2 迷你成员点阵，见 3.2）。
- 折叠态 rail 下方新增「群聊」图标组（NavIcon 新增 `group` 图形，双人气泡）。
- 点群条目 → `router.push({ name: 'WorkspaceGroupChat', params: { groupId } })`。

### 1.2 路由

```ts
// router/index.ts → /home/workspace children 追加
{
  path: 'groups/:groupId(\\d+)',
  name: 'WorkspaceGroupChat',
  component: () => import('@/views/agent/GroupChatView.vue'),
  meta: { title: '群聊', requiresApp: 'agent' },
},
{
  path: 'groups',
  name: 'WorkspaceGroups',
  component: () => import('@/views/agent/GroupWorkspaceView.vue'),
  meta: { title: '群聊', requiresApp: 'agent' },
},
```

- `WorkspaceGroups` 为空态占位页（结构照抄 AgentWorkspaceView：图标 + 标题 + 描述 + 「创建群聊」按钮，经 inject 调布局层的 `openGroupDialog`）。
- 旧路径无需 redirect（群聊是新域，无历史路径）。

### 1.3 入口门控

- `requiresApp: 'agent'` 与单聊对齐（群聊是 agent 能力的延伸，不设独立 app 门禁）。
- 建群上限提示：成员 ≥2 才可建群（前端表单校验 + 后端兜底）。

## 2. 组件与文件布局

```
frontend/src/
├─ api/
│  ├─ agentGroup.ts               # 群聊 API 客户端（CRUD + WS 流）
│  └─ types.ts                    # AgentGroup/AgentGroupMember/AgentGroupRun 及事件类型
├─ stores/
│  └─ agentGroup.ts               # 群聊 Pinia store（群列表/当前群/时间线/run 状态）
├─ components/agent/group/        # 群聊领域组件（不进通用 components）
│  ├─ GroupTimeline.vue           # 时间线消息流（用户+成员气泡+notice）
│  ├─ GroupMemberBubble.vue       # 成员发言气泡（头像/名字/内容/consult 徽标）
│  ├─ GroupComposer.vue           # 输入区（复用单聊输入行为，去附件/深研开关）
│  ├─ GroupMemberPicker.vue       # 建群弹窗的成员多选 + 主持人指定
│  └─ GroupRunStatus.vue          # run 进行中状态条（当前发言人/波次/取消按钮）
└─ views/agent/
   ├─ GroupChatView.vue           # 群聊主视图（view 层，编排数据加载与 WS）
   └─ GroupWorkspaceView.vue      # 空态占位页
```

- 建群/编辑群弹窗**收编在 WorkspaceLayout**（与单聊创建弹窗同模式：布局层持有弹窗 + `provide('openGroupDialog')`），不另建 view 内弹窗——这是项目已验证的收编决策，不破例。
- store 职责：群列表拉取/CRUD、当前群时间线、WS 连接生命周期、run 进行态；与 `agent` store 并列不合并（领域边界）。

## 3. 样式设计

### 3.1 设计原则

- **Neutral Minimal 延续**：全部走 base.css token，零新色值硬编码；中性首字头像风格（accent 不浸染）与单聊一致。
- **气泡制度 = 用户右、成员左**：与单聊工作台一致（用户右对齐浅底气泡，agent 内容左对齐通栏）。群聊的特殊性只在**成员侧需要署名与分组**。
- **成员身份用「首字头像 + 名字头」区分，不用颜色编码成员**。理由：成员数量不定（2~8），色板承载不了稳定映射，且深浅两套主题下任意色都需成对维护——违背「改中性色只动 base.css 成对」的维护纪律。cc 用 color 字段区分成员的前提是它只服务单一终端渲染；Web 端宁可保守。

### 3.2 群组头像（双处复用：侧栏条目 + 聊天头部）

```html
<!-- GroupAvatar.vue：2×2 迷你点阵，前 4 成员首字，超出显示 +N -->
<div class="group-avatar" :style="{ '--ga-count': displayMembers.length }">
  <span v-for="m in displayMembers" :key="m.id" class="ga-cell">{{ m.name.charAt(0) }}</span>
  <span v-if="overflow > 0" class="ga-cell ga-more">+{{ overflow }}</span>
</div>
```

```css
.group-avatar {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  width: 28px; height: 28px;
  padding: 2px;
  border-radius: var(--radius-md);
  background: var(--color-bg-hover);
  flex-shrink: 0;
}
.ga-cell {
  display: flex; align-items: center; justify-content: center;
  border-radius: 2px;
  font-size: 9px; font-weight: var(--weight-semibold);
  color: var(--color-text-secondary);
  background: var(--color-bg-card);
  overflow: hidden;
}
.ga-more { background: transparent; color: var(--color-text-muted); }
```

### 3.3 时间线气泡（GroupMemberBubble）

```
──────────────────────────────────────────────
 (用户消息：右对齐，现有 .message-row.user 样式原样复用)
                    ┌────────────────────────┐
                    │ 这两个方案大家怎么看？    │
                    └────────────────────────┘

 ⬡ 市场分析师                                    ← 名字头：12px muted，气泡上方
 ┌──────────────────────────────────────────┐
 │ 从需求侧看……                             │  ← 通栏内容（markdown 渲染同单聊）
 │                                          │
 │ ▸ 调用了知识检索（3 条来源）               │  ← 工作过程折叠条，同单聊 TrajectoryList 折叠交互
 └──────────────────────────────────────────┘

 ⬡ 技术评审
 ┌──────────────────────────────────────────┐
 │ 补充一点实现侧的风险……                    │
 └──────────────────────────────────────────┘

 ◦ 主持人已请 产品经理 分析竞品                    ← consult 徽标：居中细字 notice 行
──────────────────────────────────────────────
```

关键样式决策：

- **名字头**：成员气泡上方一行 `名字`（12px、`--color-text-muted`、semibold），首个字用 22px 迷你首字头像（`.turn-avatar` 同款缩小）。同一成员**连续发言不重复名字头**（中间无其他发言者时）， Discord 式分组降噪。
- **发言中态**：名字头右侧 spinner + 「正在发言…」（`--color-text-faint`），气泡骨架随流式内容生长——复用单聊流式渲染管线（content 事件直拼）。
- **consult 徽标（专家咨询模式）**：居中 notice 行（`--color-text-faint` 12px，前后 8px 留白），格式「主持人已请 X 分析竞品」。这是时间线上的弱信息，绝不做成彩色 chip 抢视觉。
- **notice 行（错误/系统提示）**：同 consult 徽标制度，错误用 `--color-danger` 文字，无底色块。
- **波次分隔**（头脑风暴 R>1）：波与波之间一条极浅分隔线 + `第 2 轮讨论` 小标（可选渲染，配置关闭）。

### 3.4 输入区（GroupComposer）

- 单行输入 + 发送按钮，视觉与单聊一致（圆角容器、focus 边框 `--color-border-focus`）。
- **去掉**：附件上传、深度研究开关、steering 插话（P1 群聊 run 进行中输入框禁用+占位文案「成员讨论中…」，run 结束解锁）。这是功能裁剪不是偷懒——群 run 是编排器串行事务，运行中插话语义复杂（投给谁？），P1 明确不做。
- 模式徽标：输入区右上角静态显示群模式（「头脑风暴」/「专家咨询」小 pill，`--color-bg-hover` 底）——只读提示，不可点击切换（模式是建群时定的）。

### 3.5 run 进行中状态条（GroupRunStatus）

时间线顶部（或输入区上方）吸底细条：

```
⬡ 技术评审 正在发言 · 第 1/2 轮 · 已用 3.2k tokens        [停止]
```

- 左侧当前发言人迷你头像+名字，中间波次进度，右侧停止按钮（调 WS 取消 → run=cancelled）。
- 样式：`--color-bg-card` 底 + 上边框 `--color-border-light`，高度 36px；token 计数事件（复用 done 前 usage）没有就不显示该段。

### 3.6 建群/编辑群弹窗（WorkspaceLayout 内，与单聊弹窗同 width=880px 双列）

```
┌──────────────────────────────────────────────────────┐
│ 创建群聊                                              │
├──────────────────────────────────────────────────────┤
│ ┌─ 左列：基本信息 ──────────┐ ┌─ 右列：成员与模式 ──────┐ │
│ │ 名称*                     │ │ 模式（radio 卡片二选一） │ │
│ │ [产品评审团_________]      │ │ ┌────────┐ ┌────────┐ │ │
│ │ 描述                      │ │ │头脑风暴 │ │专家咨询 │ │ │
│ │ [___________]             │ │ │全员依次 │ │主持人   │ │ │
│ │                           │ │ │发言讨论 │ │按需问成员│ │ │
│ │                           │ │ └────────┘ └────────┘ │ │
│ │                           │ │ 成员（多选，≥2）        │ │
│ │                           │ │ ☑市场分析师 ☑技术评审  │ │
│ │                           │ │ ☐产品经理  ☐数据分析   │ │
│ │                           │ │ （consult 模式下）      │ │
│ │                           │ │ 主持人：[市场分析师 ▾]  │ │
│ │                           │ │ 讨论轮数 [1] (≤3)      │ │
│ └───────────────────────────┘ └───────────────────────┘ │
├──────────────────────────────────────────────────────┤
│                                    [取消]  [确定]      │
└──────────────────────────────────────────────────────┘
```

- 双列 grid 沿用 `.agent-form-columns` 的 `11fr 9fr` 模式与 `.form-section h4` 分组标签制度；≤920px 降单列（同一断点）。
- 模式选择用**radio 卡片**（两枚可选卡，图标+标题+一句话说明，选中态 `--color-primary-muted` 底 + `--color-primary` 边）——模式是群的核心语义，值得占视觉权重；不是普通表单项。
- 成员多选直接列现有 agents（复用 agentStore.agents），checkbox 网格；选中 ≥2 才允许提交（表单 rule）；consult 模式追加「主持人」下拉（选项=已选成员）与「讨论轮数」仅 brainstorm 模式显示。
- 提交 payload 对齐后端 `CreateAgentGroupRequest`（name/description/mode/member_ids/host_agent_id/extra_config.rounds_per_turn）。

### 3.7 空态

- `GroupChatView` 未选群（经 WorkspaceGroups 进入）→ 照抄 AgentWorkspaceView 占位结构：`group` NavIcon 72px 底盘 + 「群聊」标题 + 「从左侧列表选择群聊，或创建一个新的群聊」+ 创建按钮。
- 群时间线无消息 → 时间线中央弱提示「发送第一条消息，开始群聊讨论」。

## 4. 事件流与 store 设计（view 层消费口径）

```ts
// api/types.ts 追加（对齐后端契约）
interface AgentGroup {
  id: number; name: string; description: string | null
  mode: 'brainstorm' | 'consult'
  host_agent_id: number | null
  member_count: number
  created_at: string
}
interface AgentGroupDetail extends AgentGroup {
  members: { id: number; agent_id: number; role_hint: string | null; speak_order: number
             agent_name: string }[]
  extra_config: { rounds_per_turn?: number } | null
}
// WS 事件（在单聊事件集上扩展；content/tool_call 等照旧，data 增 member_agent_id）
type GroupEvent =
  | { type: 'group.speaker'; data: { member_agent_id: number; name: string } }
  | { type: 'group.run_done'; data: { run_id: number; status: string; rounds: number } }
  | { type: 'notice'; data: { content: string; level: 'info' | 'error' } }
```

- `agentGroup` store states：`groups / currentGroup / timeline / running / currentSpeaker`。时间线条目 `{ kind: 'user' | 'member' | 'notice', member_agent_id?, content, steps?, streaming? }`。
- WS 复用 `createWebSocketStream`（`/agent/groups/{id}/ws`）；`group.speaker` 切换 `currentSpeaker`（GroupRunStatus 与气泡名字头 spinner 共用此状态）。
- 消息历史：进页拉 `GET /agent/sessions/{group_session_id}/messages`（群会话即 AgentSession，渲染映射按 `extra.member_agent_id` 分派气泡）。会话列表（群的多会话）P1 简化为**每群单会话**（`POST /agent/groups/{id}/sessions` get_or_create 语义），侧栏群条目不展开二级会话列表——降低三层嵌套（分区→群→会话）的导航成本，多会话留 P2。

## 5. 与单聊渲染管线的复用边界

| 单聊已有 | 群聊复用方式 |
|---|---|
| markdown 渲染、代码高亮 | 直接复用渲染组件/工具函数 |
| 消息按轮分组（turns） | 时间线不复用轮分组——群按**消息流**平铺（成员发言之间天然有名字头分隔，再套轮分组视觉过重）；仅波次分隔线可选 |
| TrajectoryList 工作过程折叠 | GroupMemberBubble 内复用同交互（成员自己的工具步骤折叠在名字头气泡内） |
| WorkbenchDrawer 引用面板 | P1 不接（群消息 sources 聚合语义待定，P2 评估） |
| `createWebSocketStream` | 直接复用，仅事件分发 switch 增 group.* 分支 |

## 6. 实施清单（前端 P1）

1. `api/agentGroup.ts` + types（对齐后端 group_routes 契约）
2. `stores/agentGroup.ts`
3. NavIcon 增 `group` 图形（双人气泡）
4. WorkspaceLayout：侧栏群聊分区 + 建群/编辑群弹窗（双列）+ `openGroupDialog` provide
5. 路由两条 + GroupWorkspaceView 空态页
6. `GroupChatView` + `components/agent/group/` 五组件
7. `npm run type-check` / `lint` / 抗压缩三档视口自查（DevTools 拖到 ~320px）
8. 后端联调前可用 MSW/mock 档位自测渲染（时间线/状态条/弹窗校验）
