# 本地工作区（Local Workspace）设计文档：伴生 Runner 模式

> 状态：草案，待评审
> 日期：2026-10-21
> 关联：`group-chat-multi-agent-design.md`（群聊编排与信件模型）、`tool-system.md`（工具体系）

## 0. 问题定义与产品定位

NovaMind 工作台此前的能力边界是 **web 内**：知识库检索（RAG）、联网搜索、附件读取。本设计**不动知识库**——RAG/检索/解析仍在云端照常工作，二者是两条独立通道。

本设计做的事：**agent 页面获得一组本地工具，可以直接操作用户电脑**——用户在 web 端选定自己电脑上的一个文件夹，agent 以该文件夹为工作目录（cwd），`bash` 跑命令、`read`/`write`/`edit` 文件、`glob`/`grep` 检索，像 Claude Code 一样"在选定的文件夹里开发项目"。

**功能基准：Claude Code web 端**（claude.ai/code 的 remote agent 模式——云端会话 + 本地执行器）。对齐它的工具面与会话体验：

| Claude Code web 端 | 本设计对应 |
|---|---|
| Bash（完整 shell、持久会话） | `bash` 工具（ runner 侧真 shell） |
| Read/Write/Edit（分页读、旧串唯一替换） | `read`/`write`/`edit`，语义逐条对齐 |
| Glob/Grep | `glob`/`grep` |
| TodoWrite（任务清单进度） | 复用现有 `todo` 工具（已有） |
| 工作目录（用户选文件夹） | 工作区绑定（WorkspaceBinding） |
| diff 验收 / git 能力 | 变更视图 + 经 bash 的 git（P2 worktree） |

**两种部署形态，一套设计同时覆盖：**

| 形态 | 后端位置 | 工具执行方式 |
|---|---|---|
| 本地部署 | 后端跑在用户机器上（当前开发形态） | 进程内直读（InProcessExecutor） |
| 云端部署 | 后端在服务器 | 伴生 runner（出站 WSS 长连接）转发执行 |

两种形态共享同一套工具定义、白名单校验、审批流——**唯一差异是工具执行器**（进程内 vs 转发到 runner）。本文以云端形态（runner 模式）为主线展开，本地形态作为执行器的退化特例在后文说明。

## 1. 总体架构

```
用户浏览器(Vue)          云端 FastAPI                     用户电脑 runner
     │                      │                                │
     │  HTTPS/WS 业务会话    │                                │
     ├─────────────────────>│                                │
     │                      │<═══════ 出站 WSS 长连接 ════════┤ runner 启动时拨出
     │                      │     （不开入站端口，NAT 免穿透）  │
     │                      │──工具调用 {call_id, tool, args}─>│ 白名单根目录内：
     │                      │<─结果 {call_id, result}─────────┤  bash/read/write/edit
     │                      │                                │  glob/grep/notebook_edit
```

核心决策：

1. **runner 主动出站**。用户电脑在 NAT/防火墙后，云端永远连不进来；runner 拨出的 WSS 连接天然双向，云端借它回发请求。零端口暴露、免穿透。
2. **runner 是执行器不是 agent**。所有智能在云端（引擎/编排器/工具注册表），runner 只做四件事：收调用 → 校验安全边界 → 本机执行 → 回结果。这样升级 agent 能力不需要用户升级 runner。
3. **安全边界在 runner 侧强制执行**。云端声明的授权只是建议；路径白名单、敏感目录拦截、审批拦截全部在 runner 落地——即使云端被攻破，也无法越过 runner 读白名单外的文件。
4. **审批即信件**。复用群聊设计"一切皆信件"原则：审批请求是一种投递（进会话时间线，聊天气泡出「批准/拒绝」卡片），用户点了，云端才向 runner 放行该调用。

## 2. 配对与设备管理

### 2.1 配对流程（状态机）

```
[Web 设置页] --生成 pairing_token--> [云端]          token: 一次性、10 分钟有效、可吊销
     │                                    │
     │  用户在本机执行：                     │
     │  novamind-runner join \             │
     │    --server wss://xxx \             │
     │    --token <pairing_token>          │
     │                                    │
     └--[展示]  <──设备上线通知──[云端]<──hello(token)──[runner]
                                              │
                                     token 换绑定：runner ↔ (user_id, device_id)
                                              │
                                     设备表落库：名称/OS/版本/在线状态
```

- 设备管理页：设备列表（在线徽标/最后活跃/版本），支持重命名与吊销；吊销后云端拒收该 runner 的一切报文并主动断开
- 一个用户可绑多台设备（公司电脑+笔记本）；会话绑工作区时选择「哪台设备的哪个文件夹」

### 2.2 数据模型（`features/agent/models/runner.py`，manifest models_loader 建表）

```python
class RunnerDevice(Base):
    id, user_id
    name: str               # 用户可改的设备别名
    device_key_hash: str    # runner 持久化密钥的哈希（重连凭证，替代一次性 token）
    os_type: str            # windows/darwin/linux
    version: str
    status: str             # online/offline/revoked
    last_seen_at: datetime
    created_at

class WorkspaceBinding(Base):    # 会话/群 ↔ 工作区绑定
    id, user_id
    scope_type: str         # "agent_session" | "group_session"
    scope_id: str           # session_id
    device_id (FK→runner_devices)
    root_path: str          # runner 侧授权根目录（runner 侧也持久化一份，双端比对）
    status: str             # active/revoked
    created_at
```

> 替代方案考虑过把绑定塞 `AgentSession.extra_config`——不采用：设备吊销/工作区权限审计需要独立生命周期与外键完整性，JSON 字段表达不了约束。

## 3. Runner ↔ 云端 WS 协议

端点 `/api/v1/agent/runner/ws`（云端监听，runner 拨出）。认证沿用 bearer subprotocol 惯例：首次 `bearer.<pairing_token>`，后续重连 `bearer.<device_key>`。

### 3.1 报文格式

```jsonc
// → 云端
{"type": "hello", "data": {"os": "windows", "version": "0.1.0", "roots": ["D:/projects"]}}
//    roots: runner 侧当前授权根目录清单（云端记录用于展示与双端比对）
{"type": "pong", "data": {}}
{"type": "result", "data": {"call_id": "c1", "ok": true, "result": "...", "truncated": false}}
{"type": "result_chunk", "data": {"call_id": "c1", "seq": 3, "text": "..."}}   // bash 流式 stdout
{"type": "result", "data": {"call_id": "c1", "ok": false, "error": "路径越界: ...", "error_code": "PATH_ESCAPED"}}
{"type": "approval_required", "data": {"call_id": "c1", "risk": "bash", "summary": "python -m pytest", "detail": {...}}}
//    高风险操作 runner 不执行，先请示；云端转发成审批信件，用户批准后云端回 approve

// ← runner（云端下发）
{"type": "hello_ack", "data": {"heartbeat": 15}}
{"type": "ping", "data": {}}
{"type": "call", "data": {"call_id": "c1", "tool": "read", "args": {...}, "timeout": 30}}
{"type": "approval", "data": {"call_id": "c1", "approved": true}}
```

协议约束：

- **并发多路复用**：一条连接同时挂 N 个在途 `call_id`（IDE 同时 grep+read 很常见）
- **心跳 15s**，2 个周期无响应断开；断线时在途调用全部以 `DEVICE_OFFLINE` 错误立即返回——失败方向安全，不悬死
- 大结果（文件全文/命令输出）`truncated` 标记 + 云端 `read_tool_result` 工具已有分页读取机制，直接复用
- datetime/路径分隔符经 JSON 标准序列化（复用 `core/ws/stream.py` 的 `dumps_event` 兜底经验）

### 3.2 runner 生命周期

- 启动 → 出站连接 → hello；断线 → 指数退避重连（1s/2s/4s...上限 60s），device_key 持久化本地
- 云端重启无感（runner 自动重连）；runner 掉线 → 设备表 status=offline，UI 徽标变灰
- runner 升级：版本号在 hello 里上报，云端检测落后时在设备页提示（不强制）

## 4. 工具集设计（对齐 Claude Code 工具面）

### 4.1 Shell 会话模型（与 Claude Code 一致的前提）

真 shell 语义（管道/重定向/`&&`/环境变量/git）是"在目录下开发"的根基。设计：

- **持久 shell 会话**：runner 为每个 `(session_id)` 维持一个常驻 shell 进程（Windows PowerShell / POSIX bash），`cd`、`export` 跨调用保留——agent 说 `cd src` 后下一调 `bash("pytest")` 就在 `src` 里跑
- 工作区根 = shell 初始 cwd；会话结束/工具重置时 shell 回收
- stdout/stderr 合并流式回传（协议 `result_chunk`）；stdin 常闭（禁交互），需要 TTY 的命令以明确错误失败
- 超时与输出上限双边强制（默认 120s/512KB，runner 侧配置可调）

### 4.2 工具清单（七个，语义对齐 Claude Code 同名工具）

| 工具 | 参数 | 语义（对齐 Claude Code） |
|---|---|---|
| `bash` | command, timeout?, run_in_background? | 完整 shell 执行，持久 cwd/env；后台模式回 task_id 可查输出 |
| `read` | path, offset?, limit? | 文本文件分页读（行号前缀）；图片/PDF 返回类型说明；>2000 行截断提示续读 |
| `write` | path, content | 整文件写入；覆盖已有文件前旧内容入审计（供 diff 与撤销） |
| `edit` | path, old_string, new_string, replace_all? | 精确替换，old_string 必须唯一命中否则报错（照抄 Claude Code Edit） |
| `glob` | pattern, path? | 目录检索（`**/*.py`），按修改时间排序 |
| `grep` | pattern, path?, glob?, output_mode? | 内容检索（ripgrep 语义：files_with_matches/content 模式），头尾截断 |
| `notebook_edit` | path, cell_id?, new_source | Jupyter notebook 单元格编辑（低频，P2 再实现，注册占位先不给模型） |

加上已有的 `todo`（对应 TodoWrite）与 `read_tool_result`（长结果分页，已有），agent 在工作目录内的工具面与 Claude Code 单机端对齐。

注册进现有体系（`features/agent/tool/builtins/local_workspace.py` 的 `LocalWorkspaceTool`，`build_tool_registry` 已注册）。注意勾选粒度：引擎 `resolve_tools` 按**提供者名**（`tool.name`）匹配 `enabled_tools`，多函数工具不按函数名勾选——本地工具的勾选名是 `local_workspace` 一个（同 `group_messaging` 先例），勾上即获得 read/glob/grep 全部三个函数（P1 加 write/edit/bash 仍在同一提供者下，勾选粒度不随工具集扩大而变细）。

### 4.3 与会话的接线（ToolContext 端口）

照 `web_search_port`/`knowledge_search_port` 现成模式：

```python
# chat_service 装配点（单聊与群聊 orchestrator 同样注入）
if "local_workspace" in (agent.enabled_tools or []):
    context["local_workspace_port"] = await build_local_workspace_port(db, user_id, conv)
```

`LocalWorkspacePort` 实现（`features/agent/services/local_workspace/`）：

- 进程内形态：`InProcessExecutor`——直接调本地文件操作模块（与 runner 共享同一套校验库）
- runner 形态：`RunnerExecutor`——查 `WorkspaceBinding` 找设备 → 设备在线？→ 经 RunnerRegistry 取连接 → 发 `call` 等对应 `call_id` 的 result（asyncio.Future 表）
- 未绑定工作区的会话：port 为 None，工具执行返回引导文案（能力缺失优于报错，与 code_execution 的 sandbox 处理同款决策）

### 4.4 提示词

新 prompt 键 `local_workspace_usage`（`shared/prompts/` 注册），内容要点：

- 工作目录即根，所有路径相对根书写；`glob`/`grep` 先行探路再 `read`
- 改文件用 `edit`（精确替换）而非整文件重写；写完关键文件后简述变更
- 首次 `bash` 需用户批准（会话内授信）是正常流程，不是错误
- 群聊追加：coding 成员各自在 worktree 内工作（见第 7 节）

## 5. 安全模型

### 5.1 路径白名单（runner 与 InProcessExecutor 共用同一校验模块）

```
resolve(root, rel) :
  1. 拒绝绝对路径与盘符——一律相对 root
  2. realpath 归一后 must be within realpath(root)   # 防 ../、symlink 逃逸
  3. 系统敏感目录黑名单（用户主目录外的系统目录、.ssh、凭据类文件模式 *.key/*.pem/.env）→ 拦截
  4. 大小写不敏感比较仅对 Windows 生效（平台事实，非分支特判：按 os_type 配置）
```

失败方向：越界一律拒绝执行并返回 `PATH_ESCAPED`（能力缺失优于错误结果）。

### 5.2 风险分级与审批（bash 授信模型）

`bash` 是完整 shell，命令黑白名单防不住（管道/变量/编码全能绕过），安全分层不靠枚举命令，靠**授信 + 越界拒绝 + 可撤销**：

| 级别 | 操作 | 策略 |
|---|---|---|
| 低 | read / glob / grep | 直接执行（用户已显式授权该文件夹） |
| 中 | write / edit（白名单内） | 直接执行，变更入审计流（前端 diff 可见） |
| 高 | **bash（工作区内）** | **首次调用触发审批：卡片展示完整命令 → 批准后本会话 bash 免审**（Claude Code 的 don't-ask-again 语义——逐条审批没法干活）；会话结束授信即失效 |
| 绝对拒绝 | 白名单外的一切路径（**含审批**） | 直接拒绝。审批只针对白名单内的高风险动作，越界无门 |

补充护栏：

- 授信绑定 `(device_id, session_id)`，前端卡片明示"本会话内后续命令将直接执行"
- `git` 操作是 bash 的一部分（worktree/commit/diff 天然可用）；工作区在 git 仓库内时，所有 write/edit 可经 git revert 兜底——删除类破坏建议走回收站（runner 侧尽量实现），失败方向可恢复
- 审批信件流：runner 拦截 → 云端落会话时间线（notice 条目 + 批准/拒绝按钮）→ 批准 → 放行执行；拒绝 / 5 分钟未响应 → `bash` 以 `APPROVAL_DENIED` / `APPROVAL_TIMEOUT` 终止，agent 收到明确错误可向用户解释
- 前端审批卡片复用群聊 notice 条目通道（agentGroup/agent WS 均已有 notice 事件类型）；审批状态机（pending/approved/denied/expired）存云端内存表 + 审计日志

## 6. 单聊接线（前端 + 视图）

### 6.1 前端交互

- 会话头部「工作区」入口 → 绑定弹窗：选设备（在线的才可选）→ 输入/粘贴 runner 侧授权根目录（或 runner 提供的目录浏览选择，P2）→ 确认绑定
- 已绑会话：头部常显根目录徽标；未绑而 agent 勾了文件工具 → 首次使用时提示绑定
- **变更视图（结果区，抄 WorkBuddy 验收体验）**：右侧面板「变更」tab——本次会话所有 write/edit 的 diff 列表（旧内容审计已在 5.2 落），点开看 unified diff；这是"结果可验收"的关键
- 审批卡片：聊天气泡流内出现，含命令全文 + 批准/拒绝按钮；用户不在场时下次进会话仍可见未决审批

### 6.2 消息协议增量

现有单聊 WS 事件集新增：

```
workspace.approval_required  {call_id, risk, summary, detail}   # 渲染审批卡片
workspace.approval_result    {call_id, approved}                 # 关闭卡片
workspace.file_changed       {path, op: write|edit}              # 变更视图实时追加
```

## 7. 群聊接线：多 agent 并行开发

群聊编排（拉起式、round-robin、成员私有会话、投递信箱）**原样不动**，文件能力只是成员的新工具。新增的只有工作区隔离策略：

| 模式 | 适用场景 | 隔离策略 |
|---|---|---|
| 共享工作区 | 讨论/分析类（读为主，写少） | 全成员绑同一 root；写入天然 round-robin 串行，冲突面小 |
| worktree 工作区 | 并行开发群 | 建群绑定时云端经 runner 执行 `git worktree add <root>/.worktrees/<member>-<branch>`，每个 coding 成员单独 root + 分支；汇报合并走 `bash`（git 命令，会话授信后免审） |

多 agent 并行写同一 worktree 的问题与 cc agent teams 同解：**单点文件同一时间只由一个成员写**——头脑风暴串行编排天然满足；若未来做并行 turn，按 feature 边界分配成员与 worktree（本项目 CLAUDE.md 多 agent 规则的产品化）。

群聊审批信件直达群时间线：成员首次 bash → 审批卡片出现在群聊流 → 群主批准授信。

## 8. 本地部署形态（InProcessExecutor 特例）

后端跑在用户机器时：

- 无需 runner/设备/配对（`RunnerDevice` 相关全部跳过）；工作区绑定 = 本地路径选择（前端目录选择经后端 `os.listdir` 浏览，或直接填路径）
- 工具执行走 `InProcessExecutor`：与 runner 共享同一白名单校验模块与风险分级——**审批流照常工作**（本地形态更需要：agent 和用户在同一台机器上，高危操作不能因为"本地"就免审）
- 差异仅此一处，产品语义（工作区/审批/diff）两种形态完全一致

## 9. 分期实施

| 期 | 范围 | 验收 |
|---|---|---|
| **P0 骨架**（后端已落地，待实机 E2E） | RunnerDevice 模型+配对状态机+WS 端点+心跳/重连；read/glob/grep 三个只读工具；单聊绑定工作区（手填路径）；本地形态 InProcessExecutor 同步实现；runner 客户端骨架（`backend/src/runner/`，`python -m novamind.runner join`） | 云端 NovaMind 单聊能读用户本机项目代码并答疑；本地形态同能力 |
| **P1 写入+命令+验收** | write/edit；bash（一次性命令版：每次独立子进程、cwd=工作区根）；变更审计+前端 diff 视图；workspace.file_changed 事件；审批流+会话授信（bash 首次审批） | agent 能改文件看 diff 验收；能跑 `pytest`/`git diff` 并把输出带回回答 |
| **P2 持久会话+并行** | bash 升级持久 shell 会话（cd/export 跨调用保留）+后台模式；notebook_edit；worktree 建群编排；群聊审批信件；目录浏览式选择 | 开发群各成员在自己 worktree 干活并合并 |

## 10. 明确不做（边界）

- 不做 runner 常驻智能/本地模型推理——runner 是哑执行器，升级 agent 能力不需要用户升级 runner
- 不做整目录上传/云端索引（与 MinIO 附件上传是两条路：附件是"给 agent 看的材料"，工作区是"给 agent 干活的地方"，不混用）
- 不做白名单外路径的任何操作（即使审批也不放行——审批只针对白名单内的高风险动作）
- 不做 P0 阶段的目录树浏览选择（手填路径起步，浏览器式选择 P2 再做）
- 不做 runner 自动更新

## 11. 风险与开放问题

| 风险 | 对策 |
|---|---|
| runner 被仿冒连云端 | 配对 token 一次性 + device_key 持久凭证 + 设备吊销；设备页可见异常登录 |
| 云端被攻破试图越权读文件 | 安全校验全部在 runner 侧强制执行（第 1 节决策 3） |
| 长任务期间 runner 掉线 | 在途调用立即 DEVICE_OFFLINE；引擎侧该成员 turn 按失败隔离处理（群聊已有机制） |
| 用户授权过宽（整个盘） | runner 侧授权确认 UI 明示影响范围；敏感目录黑名单始终生效 |
| diff 审计表膨胀 | 变更内容落对象存储（MinIO），元数据进审计表；P1 观察量级再定 |
