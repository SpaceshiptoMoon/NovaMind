# 多 Agent 并行开发工作流规范

> 适用场景:在同一 NovaMind 仓库里,同时开多个 Claude Code(或人工)窗口并行开发,避免互相覆盖改动、把冲突推到可控的 git 合并阶段解决。
> 编码、安全、前后端规则仍以 `CLAUDE.md` / `backend/CLAUDE.md` 为准,本文档不重复,只补充并行协作的工作流约定。

## 1. 核心原则:一 Agent 一 Worktree 一分支

**禁止多个 agent 共享同一个工作目录。** 同一工作目录里,后写的 agent 会直接覆盖先写的,冲突发生在文件系统层,git 来不及介入,且无法追溯。

正确做法:每个 agent 窗口启动前,先给它分配一个独立的 git worktree + 独立分支。worktree 让一个仓库同时拥有多个工作目录,各自 checkout 不同分支,背后共享同一份 `.git`(历史、对象库共用,无需重复 clone)。

```
intelligent/                      ← 仓库根(.git 在此)
├── backend/                      ← 主工作目录(通常留给集成 / 主干同步)
└── ../intelligent-agentA/        ← agent A 的 worktree,分支 feat/agentA-xxx
└── ../intelligent-agentB/        ← agent B 的 worktree,分支 feat/agentB-yyy
```

## 2. 启动流程(每个 agent 窗口)

### 方式 A:手动开 worktree(最可控)

```bash
# 在仓库根目录
git worktree add ../intelligent-agentA -b feat/<scope>-<short-desc>
git worktree add ../intelligent-agentB -b feat/<scope>-<short-desc>

# 各 agent 窗口进入自己的 worktree 再开工
cd ../intelligent-agentA/backend
```

### 方式 B:Claude Code 内置

在 agent 窗口里直接要求开 worktree,它会在 `.claude/worktrees/` 下自动建好并切过去;完成后用 `ExitWorktree` 保留或清理。

### 规则

- worktree 目录**放在仓库外**(如 `../intelligent-agentX`),不要放进 `src/`、`backend/` 等会被扫描的源码目录。
- 新 worktree 一律从**干净基点**建分支(`main` 或当前主干),不要带未提交改动开工——未提交改动属于原工作目录,不会自动跟过来(这正是隔离的意义)。
- 同一个分支**只能被一个 worktree checkout**。git 本身禁止同一分支被两个 worktree 同时占用,遵守这条即可避免两个 agent 写同一分支。

## 3. 分工原则(减少冲突的根本)

worktree 只是把"文件系统静默覆盖"变成"git 可控合并";真正少冲突,靠任务边界清晰。

- **按 feature / 目录边界切任务**:项目天然按 `backend/src/features/<domain>/` 切分,优先让一个 agent 独占一个 feature(`knowledge_space`、`agent`、`qa`、`evaluation`、`skill`、`user`…)。
- **单点共享文件串行化**:以下文件是跨 feature 单点,同一时间**只允许一个 agent 修改**,其余 agent 需要改时排队等前一个合并:
  - `src/shared/prompts/` 提示词注册表(参见记忆 [[prompt-registry-architecture]])
  - `src/core/middleware/router_manager.py`(路由注册)
  - `src/core/middleware/startup_manager.py`(模块初始化注册)
  - `*.example` 配置模板、`CLAUDE.md`、`docs/` 架构文档
  - DB schema 相关模型(无 Alembic,参见 [[db-schema-sync-no-alembic]])
- **跨 feature 接口先约定**:两个 agent 的改动有依赖时(如 A 改 schema、B 调用),先在群里/文档里定接口,再各自实现,避免最后合并时大改对方依赖的签名。
- **不要碰与任务无关的文件**:agent 只动自己任务范围内的文件,顺手重构、批量格式化会无谓扩大冲突面。

## 4. 提交规范

- **频繁、原子提交**:完成一个可独立说明的小步就 commit,不要攒一大坨。小提交让合并冲突更易定位、更易 revert。
- **不长期挂未提交改动**:每天结束前,工作区要么提交、要么 stash,别留半成品过夜——主工作目录尤其如此(它常被用来做集成合并)。
- **提交信息**:遵循现有约定(`type(scope): subject`),如 `feat(knowledge_space): ...`、`fix(agent): ...`、`refactor(prompts): ...`。
- **遵守 Git 钩子**:禁止 `--no-verify` 跳过钩子(CLAUDE.md 已规定),钩子失败先修问题。

## 5. 合并回主干流程

`git merge <branch>` 的语义是"把来源分支合并进**当前所在分支**"。执行前先确认当前分支。

```bash
git checkout main                       # 1. 切到目标分支(要合入的分支)
git pull --ff-only origin main          # 2. 同步远端主干(若用远端)
git merge feat/<scope>-<short-desc>     # 3. 并入来源分支
```

- 多个 agent 分支按完成顺序逐个合入,**先合无冲突的**。
- 合并前先在 worktree 里跑过相关测试(参见 CLAUDE.md 测试章节)。
- 合并后立即在主干验证(`pytest`、`npm run type-check`),再开下一个 merge。

### 当两个分支都改了同一区域

用 rebase 让后做的分支基于已合并的主干重放,冲突更清晰:

```bash
git checkout feat/<scope>-<short-desc>
git rebase main                         # 把本分支改动重放到最新 main 之上
git checkout main && git merge feat/<scope>-<short-desc>   # fast-forward,无冲突
```

## 6. 冲突解决约定

- 冲突发生时,优先找**双方任务意图**来判断保留哪边,而不是机械地按文件顺序选。
- 涉及业务语义的冲突(schema、权限、prompt)由对应 feature 的负责人定,不要让无关 agent 替对方拍板。
- 解决完冲突必须跑测试再提交,不要"看着对就合"。
- 冲突解不掉时,在该文件留明确说明并 @ 对应负责人,不要猜着合。

## 7. 清理流程

agent 任务完成、分支合并后,立即清理 worktree,避免残留:

```bash
git worktree remove ../intelligent-agentA          # 删 worktree 目录
git branch -d feat/<scope>-<short-desc>            # 删已合并的分支
git worktree prune                                 # 清理失效的 worktree 元数据
```

- `git worktree list` 可随时查看当前有哪些 worktree。
- 未合并的分支用 `git branch -D` 强删前,确认改动确实不要了。

## 8. 主工作目录的职责

仓库根 `intelligent/` 主工作目录建议**留给集成合并与主干同步**,不作为某个 agent 的开发主场。理由:它常需要 checkout `main` 跑合并和测试,若同时被某个 agent 占着改代码,合并会和工作区改动打架。

## 9. 禁止事项

- ❌ 多个 agent 写同一工作目录
- ❌ 多个 agent 同时改单点共享文件(见 §3)
- ❌ worktree 建在源码目录内
- ❌ 长期保留未提交改动不提交也不 stash
- ❌ 用 `--no-verify` 跳过钩子
- ❌ 跨任务范围顺手改无关文件 / 批量格式化
- ❌ 合并后不跑测试就推下一个 merge