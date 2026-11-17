# 知识运营平台设计（定稿）

> 2026-11-16/17 定稿并部分实施。本文是运营域的终态蓝图与批次状态，迭代对着它做加法或减法。
> 历史演进（飞轮化/收件箱化）见 [`../process/knowledge-operations-loop-design.md`](../process/knowledge-operations-loop-design.md) 与 [`kb-ops-loop-summary.md`](./kb-ops-loop-summary.md)。

## 产品定位

知识库会自然劣化（文档过时、内容矛盾、检索退化、缺口累积），运营平台把劣化转译成**可处置的待办**。打开运营区 5 秒知道今天干什么；复杂度由系统消化，不由用户承担。

## 五模块划分（信息架构即页面骨架）

```
源数据 ──→ 解析入库 ──→ 检索 ──→ 生成 ──→ 问题侧     ← 评测归因的故障定位轴
─────────────────────────────────────────────
看板（监控）→ 质检（诊断）→ 处置（行动）→ 验证（闭环） + 事件账本（底座）
```

| 模块 | 定位 | 落点 |
|---|---|---|
| 看板 | 统计监控 | 收件箱结论行 + 折叠趋势 + 资产健康下钻页 |
| 质检 | 内容诊断 | 归因四分法（线上）+ 15 类归因（评测）+ 矛盾/重复/过期检测 |
| 处置 | 待办行动 | 收件箱统一待办（四源混排、忽略需选原因持久留痕） |
| 验证 | 效果闭环 | 本周战果计数；干预回看（设计中，见下） |
| 账本 | 事件底座 | kb_events + ops_actions，口径唯一 |

**形态裁定**（用户拍板，勿漂移）：运营区默认页 = 收件箱，页顶五模块条兼作导航（看板→资产健康、质检→建议队列下钻）；**不建独立工作台页 / 质量基线页**——结果流进现有页面，不加导航层级。

## 三岗位体系

| 岗位 | 界面 | 现状 |
|---|---|---|
| 知识运营者 | 工作台（认领制 + 个人战果） | 认领制未实施（表结构无 claimed 态） |
| 空间管理员 | 策略配置 + SLA 升级链 | 策略面未实施（阈值散在代码） |
| 文档 Owner | 两键通知闭环 | 复审通知已有（超期升级链在 SLA 设计中） |

## 已实施（批次 1 + 评测归因 E1-E3）

- **ops_todo_dispositions**（轻状态表）：忽略态跨会话持久，原因受控枚举（one_shot/non_kb/false_positive，自动分诊判例燃料），撤销删行 + 账本留痕
- **ops_actions**（动作登记簿）：统一处置登记，独立短事务（同 EventRecorder 模式——绑请求事务会丢行）；账白名单决定是否双写 kb_events；`target_kind` 预留 `retrieval_config`（检索调优即干预）
- **GET /kb-ops/spaces/{id}/todos**：四源即时聚合（缺口/复审/低分反馈/评测归因）+ 忽略过滤 + 影响度排序后端化
- **GET /kb-ops/spaces/{id}/onboarding**：冷启动三检查（embedding 生效语义 / 文档≥10 / 近 7 天检索≥30）三态 empty/collecting/ready
- **回归告警接线**：quality_baseline cron 消化最近两个同指纹完成任务，judge_regression 判回归 → 通知管理员 + 落 baseline_regression 动作

## 干预回看设计（定稿未实施，批次 2.5）

ops_actions 已预留 scope/outcome/outcome_detail/evaluated_at 列。实施时照抄：

- **干预面 scope**：动作落账时快照 query 签名集合（gap 聚簇键 / 文档支撑 query 归一 hash），固定队列才能前后对照
- **判定四态**（followup worker 每日，规则进 Policy）：后窗 0 次→`no_demand`（不计战果）；样本 <10→`inconclusive`；零命中率相对降 ≥30% 或点踩归零→`effective`；否则 `ineffective`→生成 `intervention_recheck` 待办回处置队列（parent_action_id 成链）
- 全部数字/阈值/窗口落 outcome_detail（可解释可回放）；前后对照非严格归因，结论标注

## 批次排序与遗留

1. ~~批次 1：三统一地基 + 冷启动~~ ✅（ac688fa9..e16a4da7）
2. ~~评测归因 E1-E3~~ ✅（25d7f792..0b27b35c，详见 [evaluation-attribution-design.md](./evaluation-attribution-design.md)）
3. 批次 2：Metrics 口径注册表 + Policy 配置面（阈值/窗口/权重配置化）
4. 批次 2.5：干预回看 worker + interventions 端点 + 战果切 ops_actions 数据源
5. 欠账：citation_click 前端埋点（正面信号恒零）、self-check 端点（后台件静默运行无观测）、小样本置信抑制

**当前阶段结论**：功能建设封版，进入真实使用验证期——打开 quality_baseline、真实空间走完「缺口→补文档→转测试集→评测归因→待办处置→回归验证」一圈，用真实摩擦驱动下一轮。
