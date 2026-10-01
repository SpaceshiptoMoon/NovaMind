# 知识运营闭环（KB-OPS Loop）架构与收官总结

> **文档性质**：正式总结——知识运营闭环全量落地后的系统现状（八批次 + 前端 + 收尾，2026-10-01 至 10-02 完成）。
> **上游文档**：设计推演见 [`../process/knowledge-operations-loop-design.md`](../process/knowledge-operations-loop-design.md)（痛点→归因模型→三回路→调研）；执行计划见 [`../../plans/active/knowledge-operations-loop-plan.md`](../../plans/active/knowledge-operations-loop-plan.md)。本文回答「现在系统里有什么、在哪里、怎么用」。
> **代码归属**：`backend/src/features/knowledge_ops/`（新 feature）+ 对 qa / knowledge_space / evaluation / notification 的增量接线。

---

## 一、一句话定位

**NovaMind 不只是「会答」的知识库，而是「会养」的知识资产系统。** 竞品（开源四家 Dify/FastGPT/RAGFlow/MaxKB）都在卷「回答更准」，没有人系统化解决「知识库如何不烂掉」；商业 SaaS（Glean/Guru/eGain）验证了运营闭环的付费意愿但无私有化 RAG 深度。「私有化 DeepDoc 解析 × 知识运营闭环」是本项目的差异化定位。

**核心论点**：知识库的真实资产不是 chunk 而是用户信任；知识库死亡螺旋（错误回答→信任流失→失败信号消失→改进失据）的根因是反馈回路断裂。运营 = 修复两条回路：

```
回路 A（消费→供给）：用户问不上的问题 → 归因 → gap 清单 → 周报 → 补内容
回路 B（供给→消费）：新版上传 → 建议 → 人工采纳 → 旧版下线 → 检索即时生效
```

---

## 二、系统全景（当前事实）

### 2.1 新 feature：`knowledge_ops`

| 组件 | 位置 | 职责 |
|------|------|------|
| **KbEvent 账本** | `models/kb_event.py` | 只追加运营事件（query_reformulate / citation_click / 归因类），脱敏+截断在写入端口保证；查询侧信号（问答量/零命中/低分）不进账本——由 `question_answers.extra` + 批次 2b 看板承担，避免双事实源 |
| **EventRecorder** | `services/event_recorder.py` | 旁路写入端口：独立短事务+显式 commit、**全异常吞掉**（账本挂了问答照常）、redact 脱敏、512 截断 |
| **QueryReformulateDetector** | `services/query_reformulate_detector.py` | 会话内改写检测（检索失败强信号）：同会话 120s 窗（YAML 可配）+ 字符 3-gram Jaccard ≥0.5 双门槛，仅 RAG 会话；比对目标取 question_answers 最新 user 消息（R2 models 直查防环） |
| **attribution_worker** | `tasks/attribution_worker.py` | 归因流水线（cron 每 30 分钟）：拉失败问答（零命中/低分/点踩，与看板同口径）→ 以会话 RAG 配置**重放检索**（原始阈值+降阈值两轮）→ 四分归因 → 写回 `extra.attribution` |
| **GapRepository / GapReportService** | `repository/gap_repository.py`、`services/gap_report_service.py` | gap 清单（content_gap 归一化聚类+频次排序）/ 待归因计数 / 归因分布；空间双通道过滤 |
| **weekly_digest** | `tasks/weekly_digest.py` | 周报 cron（每周一 09:23）：逐空间聚合上周 gap → 通知全部成员；**空窗不发**（防告警疲劳） |
| **SuggestionRepository / new_version_detector** | `repository/suggestion_repository.py`、`services/new_version_detector.py` | 复审建议队列（new_version/contradiction 两类型）；新版识别=文件名归一化完全一致才建议（零误报口径），挂上传管道步骤 9 旁路 |
| **review_reminder** | `tasks/review_reminder.py` | 复审提醒 cron（每日 10:07）：扫 next_review_at 临期/过期 → 通知 owner |
| **GovernanceRepository / contradiction_detector** | `repository/governance_repository.py`、`services/contradiction_detector.py` | 重复文档分组（file_hash+归一化名）/ 贡献统计（点击+支撑）/ 矛盾检测（3-gram 带 0.55~0.99 外过滤 → LLM 判定 → 建议队列，判定失败/false 一律不建——宁漏勿误） |

### 2.2 对既有模块的增量接线

| 模块 | 改动 | 批次 |
|------|------|------|
| **qa** | 埋点接线 `_maybe_detect_query_reformulate`（_prepare_chat 尾部，chat/chat_stream 两出口全覆盖）；`POST /qa/message/{id}/citation-click`；反馈落行 space 从会话配置兜底 | O1/O2/A2 |
| **knowledge_space** | Document 模型生命周期六列（lifecycle_status/owner_id/effective_date/review_cycle_days/next_review_at/superseded_by_doc_id）+ `SCHEMA_MIGRATIONS` 幂等补列 + owner 存量回填；**LifecycleService 状态机**（ES chunk `update_by_query` 同步，失败回滚 DB；转换后失效检索缓存）；chunk 写入注入 lifecycle_status；转换/确认复审/复审策略 API | B1/B2 |
| **shared/storage** | ES mapping 加 `lifecycle_status` keyword；**检索排除式过滤挂 `_build_kb_filter` 单点**（5 处检索路径全生效）：`must_not terms superseded/archived`——missing 字段自动可召回，存量零回填（语义已对真实 ES 实测钉死） | B1 |
| **evaluation** | 合成测试集生成（chunks 采样→LLM 出 QA→落测试集，配额 YAML 默认 20 成本硬闸）；`config_fingerprint`（EvaluationConfig 质量子集稳定 hash）；gap→测试集 flywheel；修三处存量并发缺陷（后台协程 session 生命周期/单 session 并发撞 aiomysql——并发退化为串行，正确性优先） | C |
| **notification** | NotificationType 三枚举：KB_OPS_WEEKLY_DIGEST / KB_REVIEW_DUE（kb_contradiction_confirmed 以字符串常量发送） | A2/B2/D |
| **frontend** | `SpaceGapReportView`（KPI/归因分布/缺口清单）、`SpaceKbOpsView`（建议处置/重复内容/文档价值三 tab + 矛盾扫描触发）、洞察页↔缺口报告↔运营页互链、通知中心四类型文案、正文角标与来源卡点击上报 | O2/前端批次 |

### 2.3 API 面（`/api/v1/kb-ops` 前缀，manifest 自动发现）

```
GET  /spaces/{id}/events                          事件分页列表（成员）
GET  /spaces/{id}/gap-report                      缺口报告：KPI+归因分布+清单（成员）
GET  /spaces/{id}/review-suggestions              建议列表（成员）
POST /spaces/{id}/review-suggestions/{sid}/resolve  处置（admin；accept 联动 supersede/通知 owner）
POST /spaces/{id}/gap-report/test-set             gap→测试集 flywheel（成员）
GET  /spaces/{id}/duplicates                      重复文档分组（成员）
POST /spaces/{id}/contradiction-scan              触发矛盾检测（admin）
GET  /spaces/{id}/citation-stats                  点击+支撑统计（成员）

POST /spaces/{id}/knowledge-bases/{kb}/documents/{did}/lifecycle/{supersede|archive|reactivate}  （admin）
POST /spaces/{id}/knowledge-bases/{kb}/documents/{did}/confirm-review          （owner/admin）
PATCH /spaces/{id}/knowledge-bases/{kb}/documents/{did}/review-settings        （owner/admin）
POST /spaces/{id}/knowledge-bases/{kb}/evaluation/test-sets/generate           （editor）
```

### 2.4 cron 任务（嵌入式 arq Worker）

| 任务 | 周期 | 职责 |
|------|------|------|
| `attribute_pending_events` | 每 30 分钟 | 失败问答四分归因 |
| `send_weekly_kb_ops_digest` | 周一 09:23 | 知识运营周报 |
| `send_review_reminders` | 每日 10:07 | 复审到期提醒 |

### 2.5 YAML 配置（`knowledge_ops` 段，全部可在 `default.example` 查阅）

改写检测窗口/阈值、归因低分/降级阈值/回溯窗/批上限、复审提前量/默认周期、测试集配额、质量基线开关（默认关）。

---

## 三、七问验收（设计文档 §七 的原始验收标准）

管理员五分钟内可答：

| # | 问题 | 数据面 |
|---|------|--------|
| 1 | 这周多少问题答不上来？top 10？ | gap-report API/页 ✅（failure_total + 归因分布 + 聚类清单） |
| 2 | 哪些文档最常支撑回答/从未被用？ | citation-stats ✅（真实数据：doc576 支撑 14 次） |
| 3 | 多少文档超一年未更新仍被引用？ | 生命周期字段 + 复审提醒 ✅ |
| 4 | 用户点了踩之后发生了什么？ | 点踩→归因→gap 清单→周报 ✅（真实闭环验证） |
| 5 | 上月 vs 本月答案质量？ | 基线报告 + compare API ✅（KB6 真实基线：hit_rate=1.0/mrr=0.908/faithfulness=9.1） |
| 6 | 新文档和存量打架了吗？ | 矛盾检测→建议队列 ✅（真实 LLM 精准命中构造矛盾） |
| 7 | 「退货政策」有几份？ | duplicates 视图 ✅（仅展示+建议流处置，不自动合并） |

---

## 四、落地过程中的关键教训（供后续批次复用）

### 4.1 真实接口验证的价值（全程抓到 10+ 个单测测不出的真 bug）

- **时区混算**（O1）：DB 读回 naive datetime 与 `now_china()`（aware）相减必 TypeError——改写检测生产环境会静默失效；
- **space 锚点五处同根因**（O2→D 贯穿）：消息行不回填 space_id（RAG 绑定在 session_config）→ citation_click/归因候选/反馈表/support_stats 四处连锁 NULL——统一修复为「会话 RAG 配置兜底」；
- **基建故障 vs 内容缺口**（A1）：重放全部 KB 失败（如 encryption_key 缺失）不能归因 content_gap——改为抛错留空重试（宁缺勿错）；
- **MySQL 方言**（B2）：`ORDER BY NULLS LAST` 不支持（SQLite 单测全绿、真实接口 500）→ `score IS NULL` 兼容写法；
- **ES 检索缓存**（B1）：lifecycle 转换不清缓存则同 query 窗口内下线不生效；
- **evaluation 三处存量并发缺陷**（C）：后台协程用请求级 session/5 并发共享单 session 撞 aiomysql——真实跑批五轮才通，每轮剥一层。

**方法论**：每批次「pytest 全量 + 真实环境（ES/MinIO/MySQL/Redis/真实 LLM）端到端」双验证是硬约定；正反两用例防案例特例化漂移；失败方向安全（旁路吞异常/幂等不覆盖/基建故障留空）贯穿所有写入路径。

### 4.2 架构决策记录

- **query 信号不进 kb_events**：批次 2b 看板已消费 extra，双事实源是负债；
- **归因写 `question_answers.extra.attribution`** 而非账本：与看板同源可联查；
- **检索排除式过滤**（must_not）而非白名单：存量零回填；
- **cron 跑批降级为 API 驱动**（C）：复刻请求级依赖装配是错误架构，不硬凑；
- **矛盾检测带上限 0.99**：「v2 抄 v1 改关键事实」实测 sim=0.98 是矛盾最高发形态，不能武断排除；
- **生命周期转换 ES 同步失败回滚 DB**：不留「DB 下线但检索照出」的错误状态。

### 4.3 遗留 backlog（有意推迟，非缺陷）

1. `permission_boundary` 归因 stub——待检索层权限过滤（原 IMPROVEMENT 文档 P2-1）接线后补第四分；
2. 质量基线自动跑批——需先给 EvaluationService 做无请求依赖的装配工厂；
3. 归因/矛盾/相似度全套阈值——跑两三周真实数据看误报率后校准；
4. `EVALUATION_CONCURRENCY` 退化为串行——彻底修复需每协程独立 session（evaluation 存量架构债）；
5. kb_events 分区/归档——等真实量级数据。

---

## 五、提交清单（main 主线，全部已推送 origin）

| commit | 批次 | 内容 |
|--------|------|------|
| `22d8c23` | docs | 设计文档 + 开发计划 |
| `7e38367` + `3db6825` + `717e78e` | O1 | 事件账本 + 改写检测（含测试补全修时区 bug） |
| `799627e` | O2 | citation_click + 事件查询 API + 前端上报 |
| `108b538` | A1 | 归因流水线 |
| `2e6a73e` | A2 | gap 清单 + 管理视图 + 周报（M2） |
| `e02232d` | B1 | 生命周期状态机 + 检索排除式过滤 |
| `c99e257` | B2 | 替换建议 + 复审提醒（M3） |
| `454ca04` | C | 质量基线 + 合成测试集 + flywheel（M4） |
| `1228925` | D | 重复视图 + 矛盾队列 + 贡献统计（M5 收官） |
| `fa7b737` | 收尾 | 复审策略设置 API（提醒链路启动器） |
| `4a825ff` | 前端 | 运营管理页 + 入口互链 + 通知文案（浏览器走查 + 375px 零溢出） |
