# UI 参考网站清单（去 AI 味设计参考）

> 用途：给 AI（Claude Code）当设计参考来源，规避 AI 生成 UI 的「AI 味」（紫色渐变大礼包、居中渐变大标题 + 三张等宽卡片、emoji 当图标等公版套路）。
> 场景基准：NovaMind = Vue 3 + Element Plus 的 B 端 Web 控制台。
> **所有条目均于 2026-10-02 逐站实际抓取核实**（含 pricing 页），非凭记忆罗列。

## TL;DR 推荐组合

| 需求 | 首选 | 理由 |
|------|------|------|
| B 端后台参考（免费） | **SaaSFrame** saasframe.io | 唯一「免费 + 素材多 + 纯 web 后台」三条件全满足 |
| 落地页/营销页（免费） | **Lapa Ninja** lapa.ninja | 7,300+ 全免费零摩擦 |
| 直接喂给 AI | **Landingfolio MCP**（免费 100 请求/天） | 唯一免费 MCP，Claude Code 直连拉截图 |
| 装 Skill 提审美 | taste-skill + emilkowalski/skills | 91.8k / 42.8k star，全开源 |
| 交付前自查 | Checklist Design | 129 条清单完全免费，且有 agent skill |

---

## 一、后台 / 产品 UI 库（B 端参考核心）

### SaaSFrame — https://www.saasframe.io ⭐ 免费首选

- **定位**：专收 Web SaaS 的营销页 + 产品界面 + flows，B 端属性最纯粹（注意域名是单数 saasframe，不是 saasframes）
- **素材量**：5,000+ 真实设计示例、693 家 SaaS 公司
- **分类**：Dashboard 176、Account Setup 598、Onboarding 351、Add & Edit 390、Settings 184、Billing 44 + 营销页（Landing 289 / Pricing 211），带 desktop/mobile 响应式双视图
- **免费**：免费可浏览大部分库（部分功能有 Upgrade 墙）；Pro $14–18/月（价格测试中）
- **给 AI 用**：Webflow 静态渲染、截图可右键直存、无强登录墙——**对 AI/爬虫最友好的一家**

### Refero — https://refero.design ⭐ AI 接入最优（付费）

- **定位**：Web + iOS 真实产品截图库，口号「Design Research for the AI Era」，Dashboard / Task Management / Billing & Plans 是一级分类
- **素材量**：400+ 产品、142,000+ 屏，每周更新
- **免费**：仅全库 ~3% 预览 + 基础搜索 + 每天 3 次 Research mode；Pro **$10/月（年付 $120）**，有 Lifetime 买断与学生 5 折
- **给 AI 用**：**官方 MCP（Pro 起含）+ 官方 Refero Skill** + Figma 插件 + 以图搜图，agent 建站前直接查真实产品模式库

### Nicely Done — https://nicelydone.club

- **定位**：纯 SaaS/B 端 Web App 的 UX flow + 组件库（Linear、Notion、Stripe 等），web 后台分类最全（Dashboard & Stats、Billing、Team management、Command palette、MFA…）
- **素材量**：500+ SaaS 产品、206,100+ 屏、12,500+ 完整 user flows、29,200+ UI 组件
- **免费**：仅 12 屏预览（可搜全库但只能看 12 屏）；Solo **$15/月（年付）**
- **给 AI 用**：无官方 MCP；浏览层无需登录

### Mobbin — https://mobbin.com

- **定位**：体量最大（1,428 App、621,500+ 屏、323,900 条 flow、200+ 网站），但主体是 C 端移动 App，dashboard 占比低
- **免费**：Free 层内容 Limited（仅近期部分）、收藏上限 3、无搜索/Flows/MCP；Pro 约 **$10/月（年付，区域价有差异）**
- **给 AI 用**：官方 MCP（Pro 起含）+ Deep Search；重 JS 渲染 + 免费层复制受限，直接扒截图难
- **适合**：想看真实 App 某个交互细节（弹窗/表单/流程）时当字典查，不适合当日常参考流

### Page Flows — https://pageflows.com

- **定位**：录屏式 user flow 库（20,000+ App、79,000+ 屏、4,000+ 条 flow 录屏），强调完整交互过程
- **免费**：**无免费计划**——3 天试用 $2.95；$8.25–13/用户/月
- **给 AI 用**：素材主体是视频录屏，对 AI 拿静态参考图不友好；全内容在登录 + 付费墙后

---

## 二、落地页 / 营销页画廊

### Lapa Ninja — https://lapa.ninja ⭐ 完全免费

- **素材量**：7,300+ landing pages、15,000+ 全页截图，另有 550+ 免费设计资源
- **免费**：完全免费浏览、无登录墙、无公开付费项
- **给 AI 用**：截图直出，取材摩擦最小

### Landingfolio — https://landingfolio.com ⭐ 有免费 MCP

- **素材量**：4,000+ 落地页示例、791+ 组件（hero / pricing table / testimonial / CTA 组件级截图）
- **免费**：浏览灵感库免费（带广告）；All Access **$59 一次性终身**解锁全量下载
- **给 AI 用**：**官方 MCP server，免费 100 请求/天、无需信用卡**：
  ```bash
  claude mcp add --transport http landingfolio https://mcp.landingfolio.com/mcp
  ```
  agent 直接拿到组件截图 + 分类 + 源链接
- **注意**：纯灵感库更新停在 2024-10，重心已转向组件库/MCP/模板变现——素材够用但别期待新案例

### Land-book — https://land-book.com

- **素材量**：20,000+ 网站示例、200,000+ 分类 sections（本类最大）
- **免费**：免费注册 Basic（筛选结果受限、3 个 board）；PRO **$6/月起**解锁无限筛选 + 截图下载
- **筛选**：Industry / Style / Type / Typography / Color / Platform 六维 + 页面类型 tab——同类最强

### Minimal Gallery — https://minimal.gallery

- **素材量**：4,300+ 站（Portfolio ~980、Personal ~803、Agency ~757…）
- **免费**：完全免费、无登录墙；条目页含桌面 + iPhone 双截图直出
- **适合**：极简风参考（对齐本项目 Neutral Minimal 设计语言）

### 其他（免费但优先级低）

- **Siteinspire** https://www.siteinspire.com — 8,000+ 站完全免费，但偏艺术/工作室先锋设计，营销页参考匹配度低
- **Recent.design**（原 Godly）— 免费浏览无付费墙，仅媒体类型 tab 无筛选，混品牌/印刷类需自行过滤
- **Awwwards** https://www.awwwards.com — 看图全免费（获奖画廊/Elements 无墙）、筛选体系强，但内容偏 3D/叙事创意站

---

## 三、设计清单与自查

### Checklist Design — https://www.checklist.design ⭐ 完全免费

- **素材量**：**129 条清单**，五大类：Mobile app（25）/ Web app（Dashboard、Billing、Empty State…）/ Website（Landing、Pricing、FAQ、404…）/ Design system（Button、Modal、Tokens、Accessibility…）/ Flows（6）
- **免费**：完全免费无付费墙，靠赞助维持
- **给 AI 用**：三种姿势——网页直接浏览；**作为 agent skill（checklist.design/skill）** 配合 Claude Code 做设计审查；Figma 插件
- **典型条目**：「Login 页面应有密码显示/隐藏切换」「Modal 应支持 ESC 关闭」

### Laws of UX — https://lawsofux.com

- **素材量**：30 条 UX 心理学定律（Fitts、Hick、Jakob、Doherty Threshold、Miller、Peak-End…）
- **免费**：网页内容完全免费（5 种语言，CC BY-NC-ND 4.0），海报免费下载
- **适合**：做设计决策时按定律名检索对照

---

## 四、反 AI 味 Skill（直接装进 Claude Code）

### taste-skill — https://github.com/Leonxlnx/taste-skill ⭐ 91.8k star

- **定位**：「Anti-Slop 前端框架」——阻止 AI 生成千篇一律的样板 UI，核心是三个 1-10 拨盘：DESIGN_VARIANCE / MOTION_INTENSITY / VISUAL_DENSITY，含 GSAP 动效骨架、em-dash 禁用、pre-flight 检查
- **内容量**：13 个 skill（`design-taste-frontend` 主力、`minimalist-ui` Notion/Linear 风、`industrial-brutalist-ui` 粗野主义、`redesign-existing-projects` 改造存量项目…），框架无关（React/Vue 均可）
- **免费**：MIT 开源；2026-02 建仓、最近 push 2026-09-26，活跃
- **安装**：
  ```bash
  npx skills add https://github.com/Leonxlnx/taste-skill
  # 单个装：
  npx skills add https://github.com/Leonxlnx/taste-skill --skill "design-taste-frontend"
  ```

### emilkowalski/skills — https://github.com/emilkowalski/skills ⭐ 42.8k star

- **定位**：Vercel/Linear 出身动效专家 Emil Kowalski 的技能包——修正 agent 动效常识错误（进场动画该用 ease-out 而非 ease-in、用半透明阴影替代实线边框）
- **内容量**：14 个 skill（`emil-design-eng` 主力、`animate` 从零建动画、`review-animations` / `improve-animations` 审计存量、`apple-design` WWDC 原则转译 Web…）
- **免费**：MIT 开源；最近 push 2026-10-02，三仓库中最活跃
- **安装**：
  ```bash
  npx skills@latest add emilkowalski/skills
  ```

### Anthropic 官方 frontend-design — 113 万+ 安装

- **定位**：官方市场验证插件，「产出有辨识度的生产级前端，刻意规避通用 AI 审美（系统字体、紫色渐变、模板组件）」，先确立设计方向（brutalist/maximalist/luxury…）再写码；装上后前端 prompt 自动加载
- **两条等价获取路径**：
  ```bash
  # 插件市场一键装
  /plugin install frontend-design@claude-plugins-official
  # 或从官方仓库拿 SKILL.md 放进 .claude/skills/ 做版本管理
  # https://github.com/anthropics/skills → skills/frontend-design/
  ```
- **注意**：老路径 `frontend-design@claude-code-plugins` 已失效，必须用 `claude-plugins-official`
- 同仓库还有 `theme-factory`（10 套预设主题色/字体）可搭配

---

## 五、怎么喂给 AI（三种姿势）

1. **截图复刻法**（免费，通用性最强）：任一站点拿完整长截图 → 丢给 Claude Code「1:1 还原 + **抽取 DESIGN.md 设计风格文件**」→ 之后所有页面引用这份 tokens，视觉统一。拿得到源码时直接给源码，精度更高
2. **MCP 直连**（让 agent 自己查库）：
   - Landingfolio MCP——**免费** 100 请求/天，装了就能用
   - Refero MCP——需 Pro（$10/月），agent 每个任务先查真实产品模式再动手
3. **Skill 常驻**（把审美内化成规则）：装 taste-skill（管整体方向与反样板）+ emilkowalski/skills（管动效细节），二者互补；再把硬约束（禁渐变紫、禁 emoji 图标、动效 200–300ms + prefers-reduced-motion 回退、非对称布局）写进项目 CLAUDE.md

---

## 六、已核实不可用 / 不推荐（避坑）

| 站点 | 状态 |
|------|------|
| uijar.com | **已死**——域名易主为营销机构官网，原设计模式库仅存 Wayback 存档 |
| screenlane.com | **已并入 Page Flows**（2024-07 合并改名），访问直接重定向 |
| uisources.com | 已改名 **ScreensDesign**，纯 iOS 移动向 + 重 JS SPA 抓取困难，$29/月起，与 web 后台需求不匹配 |
| uinotes.com | 中文**移动 C 端** App 截图库（455 App / 17 万截图，¥19/月）——官方 FAQ 明确**不收网页界面、不收 B 端**，对 NovaMind 参考价值低；仅当需要中文 App 交互细节时用 |

---

## 对 NovaMind 的落地建议

1. 后台页面改版：去 SaaSFrame 按 Dashboard/Settings/Billing 分类找参照 → 截图丢给 Claude Code 复刻 + 抽 tokens 到 `base.css`（唯一权威 token 源，light/dark 成对改）
2. 装两个免费 Skill：`taste-skill`（design-taste-frontend + minimalist-ui 两个子技能最贴合本项目）+ `emilkowalski/skills`（animate）
3. 去 AI 味硬约束已沉淀为正式规范：见 [ui-design-guidelines.md](./ui-design-guidelines.md)（黑名单 / Neutral Minimal token 规则 / 工作流 / 交付自查清单）
