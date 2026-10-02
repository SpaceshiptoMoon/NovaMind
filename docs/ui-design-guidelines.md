# NovaMind 前端设计规范 —— 去 AI 味设计说明文档

> **文档定位**：给 AI（Claude Code）与开发者共同遵守的前端视觉规范。目标：让生成的页面看起来是「为 NovaMind 而做的」，而不是「某个 AI 随手生的公版」。
> **权威声明**：颜色/间距/圆角/动效等 token 的唯一权威是 `frontend/src/assets/base.css`。本文档解释 token 背后的设计意图与使用禁忌；两者冲突时以 base.css 实际值为准，并同步修订本文。
> **配套文档**：设计参考网站清单（逐站实测免费边界与素材量）见 [ui-reference-sites.md](./ui-reference-sites.md)。

---

## 一、什么是「AI 味」（黑名单）

AI 生成的 UI 有一眼可辨的公版套路。以下症状**出现任意一条即视为不合格**：

| # | 症状 | 说明 |
|---|------|------|
| 1 | 紫蓝渐变大礼包 | `#6366F1 → #8B5CF6` 类渐变主色、发光按钮、渐变背景块。本项目已明确弃用靛紫（见 base.css 头注释） |
| 2 | 居中渐变大标题 + 三张等宽 ✓ 卡片 | 营销页公版三件套；后台页面更不允许出现居中英雄区 |
| 3 | emoji 当图标 | `🚀` `✨` `💡` 一律禁止；图标只用 Element Plus Icons 或自绘 SVG |
| 4 | 默认蓝当主色 | Tailwind `#3B82F6` / Element Plus 默认 `#409EFF` 直接当主色 |
| 5 | 廉价质感 | 大面积彩色投影、发光边框、超大盘子圆角（>24px）、渐变描边 |
| 6 | 假数据套话 | 「10,000+ 用户信赖」「释放无限可能」类占位文案与虚假社会证明 |
| 7 | 风格漂移 | 每个页面各一套配色/圆角/间距——没有统一 token 的典型症状 |
| 8 | 浮夸动效 | 500ms+ 的弹跳入场、视差滚动、无 `prefers-reduced-motion` 回退 |
| 9 | 一屏塞满渐变卡片 | 到处都是带图标 + 渐变顶边的「信息卡」，卡片密度失真、层级靠颜色硬凹 |
| 10 | AI 腔文案 | 「太棒了！」「让我们开始吧！」；中英混排、感叹号滥用 |

> 根因：AI 默认输出「安全牌公版」，因为缺设计决策。解法不是换模型，而是**把决策固化成规范与 token**，让 AI 只剩执行空间。

---

## 二、本项目的答案：Neutral Minimal（白名单）

设计语言已从靛紫迁移到「灰底白卡 + 软黑主按钮」，对标 shadcn/ui neutral / Linear / LobeChat 的扁平气质。核心原则：

### 2.1 色彩

- **主色 = 软黑深灰** `#3f3f46`（zinc-700）：按钮/图标/链接/活动态。深按钮 hover **提亮**（`#52525b`）而非加深——深色按钮 hover 变深会「下陷」
- **灰底托白卡**：页面底 `#f5f5f5`，卡片 `#ffffff`，分层靠**底色差 + 发丝线**（`#e5e5e5` border），不靠阴影硬凹
- **全 UI 无纯 `#000` / 纯 `#FFF` 大平面**：文字最深 `#171717`，卡片最白 `#ffffff` 仅作卡底
- **阴影只给浮层一档**（Linear 扁平气质）：`--shadow-xs~sm` 透明度 0.03–0.04，只有 dropdown/modal 才用 `--shadow-lg+`
- **语义色四族**（success/warning/danger/info）+ 各自 subtle 底，仅用于状态表达，**不参与装饰**；暗色下语义色文字提亮、subtle 底改透明底
- **改色铁律**：任何新颜色先进 base.css，light/dark **成对添加**；页面样式里禁止出现新 hex 字面量

### 2.2 字体排印

- 正文/标题 Inter + PingFang SC / Microsoft YaHei；代码/ID/坐标/数字列 JetBrains Mono（`--font-mono`）
- 字号阶梯 `12/13/15/16/17/18/22/28/36`——标题用 `--text-2xl`(22px) 已足够「大气」，**不靠超大字号撑气场**
- 标题 `letter-spacing: -0.025em` + `text-wrap: balance`；正文 `line-height 1.5`
- 数据表格中的 ID、hash、路径、金额用 mono + `tabular-nums`，专业感来自等宽而非花哨字体

### 2.3 布局

- **后台页面一律左对齐网格**，页头模式固定为：eyebrow 小标（可选）→ 大标题 → 描述文字，右侧 `.header-actions` 放主操作按钮（范本：`ModelConfigView.vue`）
- 页面容器**必须显式 `width: 100%` + `max-width`**——在 flex column 容器里只写 `margin: 0 auto` 会让 cross-axis auto margin 吞掉 stretch，页面退化成 fit-content 宽，切 tab 时整页跳动（实测踩坑）
- 统计卡条用 `repeat(N, minmax(0, 1fr))`；自适应卡片上限写在**卡片自身**（`max-width` + `justify-self: center`），不写在轨道的 minmax max 值里——auto-repeat 按 max 计数轨道（实测踩坑）
- 空状态/加载态/错误态**三态齐全**，空状态给操作入口而不是白屏

### 2.4 抗压缩（引用既有规范，不重复）

布局骨架闭合、文本溢出收敛、响应式三档降级的完整规则见 `frontend/CLAUDE.md`「抗压缩布局规范」，黄金基准 `DocumentTaskBatchView.vue`。**本规范不替代它，交付前必须按其验证口径（DevTools 拖到 ~320px）过一遍。**

### 2.5 动效

- 全部动效落在既有 token 上：`--transition-fast` 120ms（颜色/hover）、`--transition-base` 200ms（显隐/位移）、`--transition-slow` 300ms（大面积过渡）；弹性曲线 `--transition-spring` 仅限拖拽/弹层
- 入场/反馈动效 200–300ms、ease 系曲线，**进场用 ease-out 不用 ease-in**
- 大面积动画必须提供 `prefers-reduced-motion` 静态回退
- **克制优先**：后台工具类 UI 的动效只服务「状态连续性」（加载、展开、定位），不做装饰性动画

---

## 三、设计工作流（从参考到落地）

### 第 1 步：找参照

按需查 [ui-reference-sites.md](./ui-reference-sites.md)（免费边界已逐站实测）：

| 场景 | 去处 |
|------|------|
| 后台/控制台页面 | SaaSFrame（saasframe.io，免费可浏览大部分库） |
| 落地页/营销页 | Lapa Ninja（全免费）、Landingfolio |
| 极简风对照 | Minimal Gallery（全免费，最贴本项目气质） |
| 交互细节/流程 | Mobbin（免费档可当字典查）、Page Flows（付费） |
| 交付自查标准 | Checklist Design（129 条全免费） |

挑选标准：**信息密度、层级手法、留白节奏**可迁移的才参考；皮（配色/字体）不可直接搬——皮必须出自 base.css。

### 第 2 步：截图复刻 + 抽取 token

把选中的截图丢给 AI，指令模板：

```text
请参考该截图的信息布局、层级与密度手法，用 NovaMind 现有设计语言实现：
1. 严格遵守 docs/ui-design-guidelines.md 的黑名单与 token 规则
2. 所有颜色/间距/圆角/动效只用 frontend/src/assets/base.css 现有 token
3. 若确需新 token：先在 base.css 中 light/dark 成对新增，再引用
4. 达到 frontend/CLAUDE.md 抗压缩规范的鲁棒性（320px 不穿模）
```

> **与通用教程的关键差异**：网上流行的「复刻 + 抽 DESIGN.md」流程针对无 token 的新项目；本项目 token 权威已存在，抽取结论必须**合并回 base.css**，绝不允许页面里硬编码新颜色、或在项目里另立一份平行 DESIGN.md 造成双源漂移。

### 第 3 步：交付自查（逐条勾选）

- [ ] 黑名单十条逐条过——无渐变紫/默认蓝/emoji 图标/居中英雄区/假数据文案
- [ ] 新样式 grep 无新增 hex 字面量；新增 token 已在 base.css 成对补 light/dark
- [ ] 布局三档验证：宽屏 / 中屏断点 / DevTools 拖到 ~320px 不穿模不溢出
- [ ] flex 滚动链每层显式闭合（纵向 `min-height: 0`、横向 `min-width: 0`）
- [ ] 长文本（ID/文件名/URL）有省略号收敛，表格列有 `min-width`
- [ ] 空态/加载态/错误态齐全，空态给操作入口
- [ ] 动效 120–300ms 且用既有 transition token；大面积动画有 reduced-motion 回退
- [ ] 文案为自然中文，无 AI 腔、无虚假社会证明
- [ ] `npm run type-check` + `npm run lint` 通过；浏览器实测主流程

---

## 四、可选增强：审美 Skill

以下开源 Skill 可为 AI 提供额外审美约束（安装方式与 star 数见 [ui-reference-sites.md](./ui-reference-sites.md) 第四节）：

| Skill | 管什么 | 与本规范的关系 |
|-------|--------|----------------|
| taste-skill `minimalist-ui` 子技能 | Notion/Linear 式极简审美 | 方向一致，可装 |
| emilkowalski/skills `animate` | 动效细节（曲线/时长/属性） | 补充本规范 2.5 节 |
| Anthropic 官方 frontend-design 插件 | 通用反公版审美 | 与本规范冲突时**本规范优先**（token 权威在 base.css） |

> Skill 提供的是通用品味；本规范 + base.css 提供的是 NovaMind 的具体品味。**先读本规范，再让 Skill 生效。**
