# RAGFlow DeepDoc 深度解析 & 与 NovaMind 对比

> 调研日期：2026-07-08
>
> 来源：[RAGFlow GitHub](https://github.com/infiniflow/ragflow)、[DeepDoc README](https://huggingface.co/datasets/pandaall/ragflow/blob/main/ragflow-main/deepdoc/README.md)、源码分析

---

## 一、DeepDoc 是什么

DeepDoc 是 RAGFlow（infiniflow 开源）的核心文档解析引擎，**~10,000 行 Python 代码**，分为两大模块：

| 模块 | 文件数 | 代码量 | 职责 |
|------|--------|--------|------|
| `deepdoc/parser/` | 15个文件 | ~6,258行 | 15种格式解析器（PDF/DOCX/Excel/PPT/HTML/MD/EPUB/JSON/图片等） |
| `deepdoc/vision/` | 9个文件 | ~3,745行 | 视觉AI模型：OCR + 布局识别 + 表格结构识别 + XGBoost 文本拼接 |

### 目录结构

```
deepdoc/
├── __init__.py                          # beartype 运行时类型检查
├── README.md / README_zh.md            # 中英文说明文档
│
├── parser/                              # 文档格式解析器（15个文件）
│   ├── __init__.py                     # 解析器统一导出
│   ├── pdf_parser.py                   # ★ 核心 PDF 解析器（~2,019行）
│   ├── docx_parser.py                  # Word 文档解析（184行）
│   ├── excel_parser.py                 # Excel/CSV 解析（317行）
│   ├── ppt_parser.py                   # PowerPoint 解析（105行）
│   ├── html_parser.py                  # HTML 解析（213行）
│   ├── markdown_parser.py             # Markdown 解析（321行）
│   ├── json_parser.py                 # JSON 解析（179行）
│   ├── txt_parser.py                  # 纯文本解析（67行）
│   ├── epub_parser.py                 # EPUB 电子书解析（145行）
│   ├── figure_parser.py              # 图片解析（281行）
│   ├── mineru_parser.py              # MinerU 高级解析（695行）
│   ├── docling_parser.py             # Docling 现代解析（528行）
│   ├── tcadp_parser.py               # 腾讯云 API 解析（549行）
│   ├── paddleocr_parser.py           # PaddleOCR-VL 解析（601行）
│   ├── utils.py                       # 工具函数（54行）
│   └── resume/                        # 简历专用解析器
│       ├── step_one.py                # 第一步：初步实体抽取（189行）
│       ├── step_two.py                # 第二步：实体标准化（691行）
│       └── entities/                  # 实体识别字典
│           ├── corporations.py / degrees.py / industries.py
│           ├── regions.py / schools.py
│
└── vision/                             # 视觉 AI 模型层（9个文件）
    ├── __init__.py                    # 视觉模块导出 + 线程安全锁
    ├── recognizer.py                  # 基础识别器基类（442行）
    ├── ocr.py                         # ★ OCR 引擎（751行）
    ├── layout_recognizer.py          # 布局识别器（456行）
    ├── table_structure_recognizer.py # 表格结构识别器（612行）
    ├── operators.py                   # 图像预处理算子（736行）
    ├── postprocess.py                 # 后处理模块（370行）
    ├── seeit.py                       # 可视化调试工具（87行）
    ├── t_ocr.py                       # OCR 测试入口（105行）
    └── t_recognizer.py               # 识别器测试入口（186行）
```

---

## 二、架构核心：视觉驱动的三层解析

DeepDoc 和 NovaMind 最本质的区别是：**它是"看懂"文档，而不是"读"文档**。

```
NovaMind 当前方案:              DeepDoc 方案:
  文件 → Reader提取纯文本         文件 → 渲染为图像 → OCR检测文字
       → Splitter切分                     → 布局识别（11种元素分类）
       → Embedding                       → 表格结构识别（6种标签）
       → ES                              → XGBoost判断段落合并
                                         → 按文档类型专项切分（9种策略）
                                         → 位置标注 @@page\tx0\tx1\ttop\bottom##
                                         → Embedding → ES
```

### 2.1 三层解析器架构

**第一层：轻量文本解析器** — 不依赖视觉模型，纯格式转换

- `TxtParser`、`JsonParser`、`HtmlParser`、`MarkdownParser`、`EpubParser`

**第二层：Office 文档解析器** — 处理带结构信息的 Office 格式

- `DocxParser`（提取图片/表格/分页符）、`ExcelParser`（CSV 自动检测/合并单元格）、`PptParser`

**第三层：视觉 AI 解析器** — 7种PDF解析策略可选

| 解析器 | 特点 | 适用场景 |
|--------|------|----------|
| **DeepDOC** (默认) | OCR + Layout + TSR + XGBoost | 通用文档，全功能 |
| **PlainParser** | 纯 pypdf 文本提取 | 纯文字PDF，极速 |
| **VisionParser** | VLM 视觉语言模型驱动 | 复杂版面文档 |
| **MinerU** | MinerU 引擎 | 中文文档 |
| **Docling** | IBM Docling 库 | 学术文档 |
| **TCADP** | 腾讯云 API | 企业级云端 |
| **PaddleOCR** | PaddleOCR-VL | OCR 视觉理解 |

### 2.2 Vision 模块 — DeepDoc 的灵魂

这是 NovaMind **完全缺失**的一层。每次初始化加载 4 个模型：

| 模型 | 文件 | 参数量 | 功能 |
|------|------|--------|------|
| **OCR引擎** (PaddleOCR) | `ocr.py` | ~10M | 文字检测框 + 文字识别；优先用 pdfplumber 字符提取，检测到乱码(PUA/CID)自动降级OCR |
| **布局识别器** | `layout_recognizer.py` | 轻量ONNX | 识别11种布局元素：Text/Title/Figure/Figure caption/Table/Table caption/Header/Footer/Reference/Equation |
| **表格结构识别器** | `table_structure_recognizer.py` | 轻量ONNX | 识别6种表格元素：Column/Row/Column Header/Projected Row Header/Spanning Cell |
| **XGBoost拼接分类器** | `pdf_parser.py` | ~1MB | 二分类：上下相邻文本框是否应合并为一个段落 |

### 2.3 完整的 8 步 PDF 解析流水线

```python
# RAGFlowPdfParser.__call__() 核心流程
def __call__(self, fnm, zoomin=3):
    self.__images__(fnm, zoomin)           # ① 逐页渲染为图像 + OCR
    self._layouts_rec(zoomin)              # ② 布局识别：11种元素分类
    self._table_transformer_job(zoomin)    # ③ 表格结构识别：行列表头合并单元格
    self._text_merge()                     # ④ 水平合并：同行相邻文本框拼接
    self._concat_downward()                # ⑤ XGBoost 垂直合并：段落级拼接
    self._filter_forpages()                # ⑥ 过滤：去目录页/致谢/垃圾页
    tbls = self._extract_table_figure(...) # ⑦ 提取表格(→HTML) + 图片 + 标题
    return self.__filterout_scraps(...), tbls  # ⑧ 碎片清洗 + 位置标注
```

#### 步骤详解

**① `__images__` — PDF 渲染 + OCR**

使用 `pdfplumber` 将每个 PDF 页面渲染为 PNG 图像（默认 216 DPI），同时提取该页的字符级坐标 `page_chars`。

随后对每页进行 **OCR 检测**，将 pdfplumber 提取到的字符与 OCR 检测框做 IoU 匹配：
- **匹配成功** → 优先使用 pdfplumber 的文本（精度更高）
- **未匹配** → 将图像区域裁剪后调用 `OCR.recognize_batch()` 补充识别

**② `_layouts_rec` — 布局识别**

调用 LayoutRecognizer（ONNX 模型）识别 11 种布局类型：

| 标签 | 含义 |
|------|------|
| `_background_` | 背景 |
| `Text` | 正文 |
| `Title` | 标题 |
| `Figure` | 图片 |
| `Figure caption` | 图片标题 |
| `Table` | 表格 |
| `Table caption` | 表格标题 |
| `Header` | 页眉 |
| `Footer` | 页脚 |
| `Reference` | 参考文献 |
| `Equation` | 公式 |

同时将每页的局部坐标转换为**全局累加坐标**（跨页统一坐标系）。

**③ `_table_transformer_job` — 表格结构识别**

1. 遍历 `page_layout`，找到所有 `type == "table"` 的区域
2. 裁剪表格图像 → 调用 TableStructureRecognizer (ONNX) 识别 6 种组件：
   - `table column` / `table row`
   - `table column header` / `table projected row header`
   - `table spanning cell`（合并单元格）
3. 将检测到的行/列/表头与 OCR 文本框关联（IoU 匹配），打上 `R/H/C/SP` 等标签
4. 通过 `construct_table()` 重建为 HTML/文本格式

**④ `_text_merge` — 水平文本合并（规则驱动）**

基于规则的相邻文本框水平合并，核心条件：
- 同一布局区域
- 不是 table/figure/equation
- Y 方向距离 < 平均行高 / 3

**⑤ `_concat_downward` — XGBoost 垂直拼接**

用 XGBoost 二分类器判断上下相邻文本框是否合并为一个段落：

- **特征**：Y距离、X重叠度、框高、行间距、上一行尾字符标点特征（逗号→合并，句号→分割）
- **模型**：`InfiniFlow/text_concat_xgb_v1.0`，推理 < 1ms/次
- **工程意义**：纯规则难以处理 PDF 跨行段落边界，深度学习太重，XGBoost 是最优权衡

**⑥ `_filter_forpages` — 过滤**

自动过滤目录页、致谢页、参考文献页等噪音页面。

**⑦ `_extract_table_figure` — 提取**

将识别到的表格重建为 HTML 格式文本（LLM 可理解的表格表示），图片区域裁剪保存并关联标题。

**⑧ `__filterout_scraps` — 碎片清洗 + 位置标注**

清除孤立字符碎片，并为每个文本块添加位置标注：

```
@@页码\tx0\tx1\ttop\bottom##
```

示例：`@@1\t50.0\t500.0\t100.0\t120.0##` = 第1页，左=50, 右=500, 上=100, 下=120

跨页文本使用 `@@1-2` 表示跨页范围。这使得前端可以根据检索结果精确高亮原文位置。

---

## 三、多栏检测 — KMeans 聚类

这是布局分析的关键预处理步骤。PDF 中双栏/三栏论文如果不做分栏处理，左右栏文字会混在一起。

### 3.1 问题

PDF 里每个字都是独立的文本框，PyPDF2 裸读双栏论文的结果：

```
Abstract: This paper proposes a novel method for...
Chapter 1 The quick Chapter 3 Another brown fox topic...
jumps over Chapter 4 the lazy The cat... dog...
Chapter 2 In this...
```

左右两栏的文字完全混在一起，无法正常阅读。

### 3.2 解决方案

**Step 1：pdfplumber 获取逐字坐标**

```python
# pdfplumber 输出每个字符的精确坐标
page.chars = [
    {'x0': 72.0,  'top': 100.0, 'x1': 80.0,  'bottom': 112.0, 'text': 'T'},
    {'x0': 80.0,  'top': 100.0, 'x1': 88.0,  'bottom': 112.0, 'text': 'h'},
    {'x0': 88.0,  'top': 100.0, 'x1': 96.0,  'bottom': 112.0, 'text': 'e'},
    ...
    {'x0': 320.0, 'top': 100.0, 'x1': 330.0, 'bottom': 112.0, 'text': 'A'},  # ← 右栏!
    ...
]
```

核心观察：**同一栏内的文字，x0 坐标相近；不同栏的文字，x0 差别很大**。

```
x0 = 72~96    → 左栏文字
x0 = 320~350  → 右栏文字
```

**Step 2：KMeans 聚类按 x0 分栏**

```python
from sklearn.cluster import KMeans

# 收集这一页所有字符的 x0 坐标
x_coords = [[char['x0']] for char in page.chars]

# 尝试 k=2（假设双栏）
kmeans = KMeans(n_clusters=2, n_init=10)
kmeans.fit(x_coords)
# → 左栏: x0≈72~96  右栏: x0≈320~350
```

**Step 3：Silhouette Score 自动确定 k**

对每页尝试 k=1,2,3,4，选 Silhouette Score（轮廓系数）最高的。该指标衡量"簇内紧凑、簇间远离"的程度（-1到1，越高越好）。

```
单栏: k=1 → score ≈ 0.0（基准线）
双栏: k=2 → score = 0.85 ← 最高！（左右栏间距大，各自紧凑）
三栏: k=3 → score = 0.42（硬拆成3组，边界模糊）
四栏: k=4 → score = 0.21（纯噪音）
```

**Step 4：多数页投票**

```python
from collections import Counter

# 第1页（标题）: k=1 | 第2-12页（正文）: k=2
page_cols = {1: 1, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 2, 8: 2, 9: 2, 10: 2, 11: 2, 12: 2}

global_cols = Counter(page_cols.values()).most_common(1)[0][0]
# → 2（11页双栏 vs 1页单栏，多数为双栏）
```

用多数投票而非逐页不同，因为标题页（单栏）用双栏策略也能正常读（单栏就是"整页一栏"），反之则不行。

**最终输出（双栏示例）：**

```
左栏: ["Abstract: This paper...", "1. Introduction", "The quick brown..."]
右栏: ["3. Method", "Another approach...", "4. Experiments"]
```

---

## 四、文档类型感知切分（9种策略）

DeepDoc 用工厂模式根据 `parser_id` 选择切分策略：

| 模式 | 模块 | 文档类型 | 关键行为 |
|------|------|---------|---------|
| **Naive** | `naive.py` | 通用文档 | Token感知、分隔符拆分 |
| **Book** | `book.py` | 长文书籍 | 层次合并、TOC移除、章节检测 |
| **Paper** | `paper.py` | 学术论文 | 元数据提取（标题/作者/摘要）、分节拆分 |
| **Laws** | `laws.py` | 法律文档 | 树形结构保持法条层级（编→章→条） |
| **Manual** | `manual.py` | 技术手册 | 标题层级保持、section ID 保留 |
| **Q&A** | `qa.py` | 问答对 | 正则提取 Q&A 配对 |
| **Table** | `table.py` | 电子表格 | 按行切分 + 表头保持 |
| **Presentation** | `presentation.py` | 幻灯片 | 逐页切分 |
| **One** | `one.py` | 整体文档 | 全文作为单个语义单元 |

### 4.1 各模式的层级检测方式

**Manual 模式**：
- 使用 `bullets_category()` 检测标题模式如 "Chapter I"、"1.1"、"Section 2"
- DOCX 通过 `docx_question_level()` 从段落样式构建层级栈
- 保留 section ID 以维持父子关系

**Paper 模式**：
- 提取元数据：标题、作者、摘要
- 使用模式匹配检测章节标题："Introduction"、"Methods"、"References"
- 按章节拆分，尊重学术论文结构

**Laws 模式**：
- 使用 `Node` 类构建树形结构
- 通过 `docx_question_level()` 检测深度层级
- 将树扁平化为 chunks，同时保留层级上下文（Chapter → Section → Article）

### 4.2 Token 感知合并（Naive 默认）

```python
chunk_token_num = 512  # 可配置的最大 token 数
delimiter = "\n!?。；！？"  # 主分隔符

# naive_merge():
# 1. 用分隔符分割文本
# 2. 用 num_tokens_from_string() 计数
# 3. 贪婪合并直到达到 token 上限
# 4. 全程保留位置标注
```

---

## 五、NovaMind vs DeepDoc 逐项对比

### 5.1 PDF 解析

| 维度 | NovaMind 当前 | DeepDoc |
|------|:------------:|:-------:|
| 文本提取 | PyPDF2 `extract_text()` | pdfplumber 逐字符提取 + OCR 补漏 |
| 乱码检测 | ❌ | ✅ 检测 PUA/CID 乱码→自动降级 OCR |
| 布局识别 | ❌ | ✅ ONNX 模型，11种元素分类 |
| 表格提取 | ❌ | ✅ 结构识别 + HTML/文本输出 |
| 图片提取 | ❌ | ✅ 按布局区域裁剪+标题关联 |
| 多栏处理 | ❌ 全混在一起 | ✅ KMeans 聚类分栏 |
| 段落合并 | ❌ | ✅ XGBoost 分类器 |
| 位置标注 | ❌ | ✅ `@@页码\tx0\tx1\ttop\bottom##` 格式 |
| 公式识别 | ❌ | ✅ Equation 标签 |
| 目录/脏页过滤 | ❌ | ✅ `_filter_forpages()` 自动过滤 |

### 5.2 DOCX 解析

| 维度 | NovaMind 当前 | DeepDoc |
|------|:------------:|:-------:|
| 段落文本 | ✅ python-docx | ✅ python-docx |
| 表格 | ✅ 提取 cell 文本 | ✅ 提取 + 结构保留 |
| 图片 | ❌ 不提取 | ✅ 提取嵌入图片 |
| 样式层级 | ❌ 不读样式 | ✅ 读 Heading 样式→层级结构 |
| 分页符 | ❌ 忽略 | ✅ 检测→对应页码 |

### 5.3 切分策略

| 维度 | NovaMind 当前 | DeepDoc |
|------|:------------:|:-------:|
| 递归字符切分 | ✅ RecursiveCharacterSplitter | ✅ Naive 模式 |
| 语义切分 | ✅ SemanticSplitter (余弦相似度) | ✅ 类似 |
| 固定大小 | ✅ FixedSizeSplitter | ✅ |
| Markdown 切分 | ✅ MarkdownSplitter | ✅ |
| **按文档类型切分** | ❌ | ✅ 9种策略 |
| 书籍 | ❌ | ✅ 章节检测+TOC移除 |
| 论文 | ❌ | ✅ 摘要/正文/参考文献分离 |
| 法律 | ❌ | ✅ 树形结构保持法条层级 |
| 手册 | ❌ | ✅ 标题层级保持 |
| Q&A | ❌ | ✅ Q&A对检测和匹配 |
| 表格 | ❌ | ✅ 按行切分+表头保持 |
| PPT | ❌ | ✅ 逐页切分 |
| 简历 | ❌ | ✅ 字段级结构化提取(~100字段) |
| 整体 | ❌ | ✅ 全文作为单个语义单元 |

### 5.4 文档格式支持

| 格式 | NovaMind | DeepDoc |
|------|:------:|:-----:|
| PDF | ✅ PyPDF2 | ✅ 7种解析器可选 |
| DOCX | ✅ python-docx | ✅ python-docx + 图片/样式 |
| TXT | ✅ | ✅ |
| MD | ✅ | ✅ |
| HTML | ✅ | ✅ |
| CSV/JSON | ✅ 当TXT读 | ✅ 专业 Parser |
| EPUB | ❌ | ✅ |
| PPT | ❌ (已移除) | ✅ |
| Excel | ❌ (已移除) | ✅ |
| 图片 | ✅ VLM描述 | ✅ VLM + OCR |

---

## 六、借鉴优先级评估

### 6.1 立即可借鉴（低成本高收益）

| 技术 | 难度 | 收益 | 说明 |
|------|:--:|:--:|------|
| **文件编码自动检测** | ⭐ | 高 | 用 `chardet` 替代硬编码 utf-8→gbk 兜底，解决 ParsingConfig `encoding` 死代码 |
| **位置标注格式** | ⭐ | 高 | `@@page\tx0\tx1\ttop\bottom##` 让检索结果可定位到原文位置，前端可高亮 |
| **表格→HTML 输出** | ⭐⭐ | 高 | docx 已有表格数据但只取 cell text，输出 HTML 让 LLM 理解表格结构 |
| **DOCX 样式层级** | ⭐⭐ | 中 | 读 Heading 样式构建层级树，替代当前的纯文本扁平化 |
| **PDF pdfplumber 替代 PyPDF2** | ⭐⭐ | 高 | pdfplumber 提供逐字符坐标，PyPDF2 只有纯文本。这是走向布局分析的基础 |

### 6.2 中期可考虑（需模型集成）

| 技术 | 难度 | 收益 | 说明 |
|------|:--:|:--:|------|
| **PaddleOCR 集成** | ⭐⭐⭐ | 高 | 扫描件PDF支持。DeepDoc 的 `ocr.py` 可直接参考，需处理 ONNX 模型下载和推理 |
| **9种文档类型切分策略** | ⭐⭐⭐ | 高 | 论文/法律/手册/书籍各 ~200行策略模块。可先做 Paper/Manual 两种最常用 |
| **目录/垃圾页过滤** | ⭐⭐ | 中 | 用正则 + 启发式规则过滤致谢/目录/参考文献页 |

### 6.3 长期愿景（需大量投入）

| 技术 | 难度 | 说明 |
|------|:--:|------|
| **布局识别模型** | ⭐⭐⭐⭐⭐ | ONNX 模型（LayoutRecognizer），需 GPU 推理，模型 ~100MB |
| **表格结构识别** | ⭐⭐⭐⭐⭐ | ONNX 模型（TableStructureRecognizer），~50MB |
| **XGBoost 段落合并** | ⭐⭐⭐ | 需训练数据，模型小推理快（<1ms/次） |
| **KMeans 多栏检测** | ⭐⭐⭐ | 依赖 pdfplumber 逐字符坐标 |
| **VLM 驱动的 VisionParser** | ⭐⭐⭐ | 用 GPT-4o/Qwen-VL 看图理解文档结构，已有 VLM 基础设施 |

---

## 七、关键亮点总结

### 7.1 XGBoost 文本拼接 — 最巧妙的工程权衡

PDF 文本框的上下合并用深度学习太重，用纯规则太脆。RAGFlow 训练了一个轻量 XGBoost 二分类器：

- **特征**：Y距离、X重叠度、框高、行间距、上一行尾标点特征
- **模型**：`InfiniFlow/text_concat_xgb_v1.0`，HuggingFace 自动下载
- **推理**：< 1ms/次，可在 CPU 上批量运行
- **效果**：比纯规则准，比深度学习快 100 倍

### 7.2 OCR 融合策略 — 性价比最大化

不是对所有页面无差别 OCR，而是：

1. 先用 pdfplumber 提取字符（免费、精确）
2. 仅当检测到乱码（PUA 编码 / CID 字体 / 字体编码乱码）时才对该区域 OCR
3. OCR 结果与 pdfplumber 结果做 IoU 匹配去重

这使得 90% 的正常 PDF 只用 pdfplumber（极快），仅 10% 的扫描件触发 OCR。

### 7.3 位置标注贯穿全链路

从 PDF 解析到最终 chunk，每个文本块都携带精确的位置信息 `@@page\tx0\tx1\ttop\bottom##`。

前端可以根据这个坐标在原始 PDF 页面上画出高亮框，用户点击检索结果直接跳到原文位置——这是企业级知识库的用户体验关键。

---

## 八、NovaMind 已有的差异化优势

对比之下，NovaMind 在以下方面有独特优势：

| 能力 | 说明 |
|------|------|
| **完整的多模态管道** | 视频/音频/VLM描述 — DeepDoc 不处理视频音频 |
| **9种ES检索模式+RRF融合** | 向量/BM25/混合+跨模态+子句+父块+关键词+假设问题 |
| **假设问题生成** | chunk 自动生成相关假设问题→增强向量检索召回 |
| **文档级去重** | SHA-256 + DB 唯一约束，拒绝重复上传 |
| **异步任务追踪** | DocumentTask + Redis + arq Worker，完整生命周期管理 |
| **语义切分** | SemanticSplitter 基于 Embedding 余弦相似度，DeepDoc 无此策略 |
| **用户可配置切分参数** | KB Config → Pydantic Schema → 实时生效，DeepDoc 为预设参数 |
| **会话级自动RAG** | SessionConfig 绑定知识库，对话自动检索，DeepDoc 无此层 |
| **评估体系** | 测试集管理 + 检索/生成/端到端评估 + LLM-as-Judge 评分 |

---

## 九、DeepDoc 与其他工具对比

| 特性 | DeepDoc | MinerU | PyMuPDF | pdfplumber | PyPDF2 |
|------|:---:|:---:|:---:|:---:|:---:|
| OCR | ✅ | ✅ | ❌ | ❌ | ❌ |
| 表格提取 | ✅ | ✅ | ❌ | ❌ | ❌ |
| HTML表格输出 | ✅ | ✅ | ❌ | ❌ | ❌ |
| 图片提取 | ✅ | ✅ | ✅ | ❌ | ❌ |
| 阅读顺序保持 | ✅ | ✅ | ❌ | ❌ | ❌ |
| 复杂布局分析 | ✅ | ✅ | ❌ | ❌ | ❌ |
| 文档切分 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 公式检测 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 标题/图片标题区分 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 多栏检测 | ✅ | ❌ | ❌ | ❌ | ❌ |

---

## 十、推荐实施路线

```
Phase 1（1-2天）: 编码检测 + 位置标注
  ├─ chardet 自动检测文件编码
  └─ pdfplumber 替换 PyPDF2 + 输出位置标注

Phase 2（1周）: DOCX增强
  ├─ Heading 样式→层级树
  └─ 表格→HTML 输出

Phase 3（2周）: 文档类型感知切分
  ├─ Paper 模式（摘要/正文/参考文献分离）
  └─ Manual 模式（标题层级保持）

Phase 4（1月+）: 选做
  ├─ PaddleOCR（扫描件支持）
  └─ 多栏检测（KMeans聚类）
```
