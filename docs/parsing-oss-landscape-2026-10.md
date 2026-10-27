# 全模态解析开源项目对标调研（2026-10-27）

> 调研方式：本地源码深探（MinerU 2026-08 快照、ragflow 上游 main 实拉对比）
> + 镜像浅克隆源码深探（docling 2.142 / marker 2.0 / VideoRAG / RAG-Anything 1.4.4，
> 存于 `.tmp/oss-ref/`，gitignore 本地资产）+ 市场扫描（OmniDocBench v1.6 榜单、
> 2026 OCR/VLM 横评、中文 ASR 生态）。
> 用途：为 NovaMind `engines/document` 全模态解析模块的下一步演进提供对标输入。
> 所有源码结论均经子代理逐文件核实，路径可复查。

---

## 一、市场格局总览（2026-10 时点）

### 1.1 文档解析：VLM 原生模型已成主流，小模型反超大 VLM

OmniDocBench v1.6（2026-09 更新）头部排名：

| 模型 | 参数量 | License | 得分 | 备注 |
|---|---|---|---|---|
| TeleOCR | 1.2B | Apache 2.0 | 96.91 | 2026-08 |
| OvisOCR2 | 0.8B | Apache 2.0 | 96.47 | 2026-07 |
| PaddleOCR-VL-1.6 | 0.9B | Apache 2.0 | 96.34 | 109 语言，Baidu |
| MinerU2.5-Pro | 1.2B | Apache 2.0（权重） | 95.75 | OpenDataLab |
| GLM-OCR | 0.9B | MIT | 95.22 | 智谱，与平台同源 |
| DeepSeek-OCR 2 | 3B | Apache 2.0 | 90.25 | 视觉 token 压缩路线 |
| olmOCR 2 | 7B | Apache 2.0 | —（olmOCR-Bench 82.4） | Ai2 |

三个行业信号：

1. **1B 级专用文档模型已反超 235B 通用 VLM**（Qwen3-VL-235B 仅 89.78）——
   「解析用专用小模型、理解用通用大模型」的分工定型。
2. **鲁棒性反直觉**（Wild-OmniDocBench：实拍/弯折/屏摄页）：PaddleOCR-VL 从
   91.9 跌到 72.2、MinerU2.5 从 90.7 跌到 70.9，而 dots.ocr 与 Qwen3-VL 只跌
   约 10 分——榜单冠军在真实脏数据上不稳，选型必须带自有语料实测。
3. **hybrid 路由模式成为引擎标配**（Docling/Marker/MinerU 一致）：数字 PDF 走
   文本层/layout 小模型快速路径，扫描页路由给 VLM OCR——正是 NovaMind
   `default/deepdoc/external_ocr` 三路径的同款思路，业界已验证。

### 1.2 引擎层：三大全能选手 + 两个特化选手

| 引擎 | 定位 | 一句话画像 |
|---|---|---|
| **Docling**（IBM，MIT，Linux Foundation） | RAG 全能选手 | 格式覆盖最广、CPU 可跑、音频/视频管线居然也有，CJK 二等公民 |
| **MinerU**（OpenDataLab） | 精度怪兽 | pipeline+VLM+hybrid 三后端，默认 hybrid；中文生态最好 |
| **Marker**（Datalab） | 速度/工程标杆 | 2.x 重构为「共享 surya VLM 服务器 + 瘦客户端」，28 个 processor 链 |
| Apache Tika | 纯文本兜底 | 1400 格式，无智能但永不出错 |
| Granite-Docling | 端侧 VLM | 258M，嵌入 Docling 管线 |

### 1.3 全模态（音视频）摄取：没有成熟王者，我们已在第一梯队

- **RAG-Anything**（HKUDS）：最接近 NovaMind 形态——MinerU 解析 + 模态
  processor + LightRAG 知识图谱；视频走 SceneDetect+关键帧 VLM+音轨转写双通道。
- **VideoRAG**（HKUDS，论文算法版）：工程很糙（30s 等分、无场景检测、无去重、
  无 OCR），但**查询期两阶段粗细描述**是好设计。
- **Docling 视频/音频管线**：存在但基础（ffmpeg 抽音轨+固定间隔/场景帧采样+
  说话人分离）。
- **结论**：NovaMind 视频模块的 7 策略矩阵 + steps 步骤综合 + 双轨融合，在
  开源全模态里属第一梯队；短板不在视频而在文档 VLM 化与质量账本（见第四节）。

### 1.4 ASR 生态（音频侧对标）

faster-whisper 仍是多语种首选；中文优先生态：**SenseVoice-Small**（234M 非自
回归，比 Whisper-Large 快 15 倍，带情绪/音频事件）、**Paraformer**（时间戳精）、
**Fun-ASR-Nano**（800M，流式+方言+热词）、**Qwen3-ASR**（2026-01，0.6B/1.7B，
22 方言，独立包 qwen-asr）、**FireRedASR**（小红书，中文公开基准第一）。
运行时层 sherpa-onnx 覆盖面最广。

---

## 二、五个项目源码深探要点

### 2.1 MinerU（本地快照 2026-08，≈3.x）

- **架构**：五后端 `pipeline / vlm-engine / vlm-http-client / hybrid-engine /
  hybrid-http-client`（`mineru/cli/backend_options.py`），**默认 hybrid**——
  pipeline 的 PP-DocLayoutV2 出版面框喂 VLM 抽取（medium effort），或 VLM 两步
  抽取+layout 小模型做标题二分（high effort）。CLI 是编排器：无 `--api-url`
  时自启本地 FastAPI，多文档按页数 first-fit-decreasing 装箱。
- **产物契约**：`middle.json` 是唯一真源（block/line/span 三级 + index），md/
  content_list/content_list_v2 全由同一 `union_make` 确定性派生；甚至支持客户端
  拿 middle.json 自产视图（`client_side_output.py`）保证两端产物 bit 级一致。
  content_list 坐标统一 0-1000 归一化整数。
- **模型栈**：PP-DocLayoutV2（**layout 头直接预测阅读序**，非规则排序）、
  UniMERNet/pp-FormulaNet（公式）、PaddleOCR 移植纯 PyTorch 版（OCR）、
  SLANet-Plus（无线表）+ UNet（有线表）双模型路由（置信度<0.9 回退有线）。
  **表格 HTML 内嵌公式/图片**：表内公式 mask 后以 `<eq>latex</eq>` 注入单元格，
  内嵌图转 base64 `<img>`。
- **资源工程**：processing window（默认 64 页）统一「单文档超长」与「多文档
  混批」；显存自适应 batch ratio（≥32G→16 … else 1）+ `MINERU_VIRTUAL_VRAM_SIZE`
  运维声明配额；`/health` 返回 `max_concurrent_requests`，客户端据此自适应并发。
- **反面教材（与我们纪律相悖，引以为戒）**：`do_parse` 用 `os.environ['MINERU_VLM_FORMULA_ENABLE']`
  向下游传参、env 覆盖显式入参、模型名非法 `exit(1)` 而非抛异常、import 期读
  env 选模型导致同进程无法混用两种公式模型。

### 2.2 Docling（v2.142，2026-10）

- **架构**：`DocumentConverter → FormatOption{pipeline_cls, backend} → backend
  解析 / pipeline 编排` 三层；**pipeline 实例按 `(class, options_hash)` 缓存
  复用**——重模型初始化与请求参数解耦。PDF 经典管线是**多线程 stage 流水线**
  （preprocess→layout→ocr→table→assemble 各自独立线程 + bounded queue 背压）。
- **失败处理（业界最完整，重点对标对象）**：
  - `ConversionStatus{SUCCESS, PARTIAL_SUCCESS, FAILURE, SKIPPED}`，基类注释写死
    「有 error 的完成 ≠ SUCCESS」；
  - `ErrorItem{component_type, module_name, error_message, category, page_no}`
    + **九类 FailureCategory**（POLICY/CAPACITY/TIMEOUT/INFERENCE_FAILURE/…）；
  - 页级失败装进队列项流转，失败页**仍补进 document.pages 保持页码正确**；
  - `document_timeout` 绝对 deadline：超时向 run_id 集合熔断，各 stage 快速失败
    在途页，超时是显式建模的一等公民；
  - OCR 语言不支持 = 显式异常（"never silently substitutes a different recognizer"）。
- **可插拔**：8 种 OCR 引擎 + 3 种表格引擎 + 3 种图片描述实现，经
  kind-discriminated options + pluggy 工厂注册；外部插件
  `allow_external_plugins=False` 时 import 前即拒（安全门禁）。
- **VLM 路由**：24 个 preset（granite_docling/deepseek_ocr/got_ocr/qwen/glmocr/
  mineru2_pro/dots_ocr…），换 VLM = 换 pipeline 类，入口不变。
- **音频/视频**：AudioInput→AsrPipeline（whisper/whisper_s2t/mlx-whisper，**转写
  为空直接 FAILURE**）；VideoInput→VideoPipeline（ffmpeg 抽音轨+帧采样+说话人
  分离按时间戳并入文档）。图片输入=包装成单页 paginated 走完整 PDF 模型链。
- **质量账本**：parse/layout/table/ocr 四维置信度评分（POOR~EXCELLENT），
  `parse_score` 取最差 10% 页分位数——刻意反映短板页。
- **弱点**：依赖重（docling-parse 原生库 + docling-ibm-models，FAQ 全是安装冲突）；
  自家模型全英文训练，**CJK 二等公民**（zh-Hans 靠 OCR 层 BCP-47 硬撑）——
  这是 NovaMind 的差异化空间；半年内 API 迁移阵痛（monorepo、deprecation 并存）。

### 2.3 Marker（v2.0，2026-10）

- **架构**：2.x 大重构——**共享 surya VLM 推理服务器 + 瘦客户端**，worker 进程
  零模型；layout/OCR/表格/公式全走 VLM，数字页表格退化为纯 CPU pdftext 启发式。
  五段流水线：Provider（7 格式魔数路由）→ Builder（layout/line/ocr）→
  StructureBuilder（成组）→ 28 个 processor 链 → Renderer。
- **Block 模型**：31 种 block 类型 + `BlockId`（`/page/0/Table/3`）O(1) 自愈索引；
  registry + `override_map` 支持整类替换（依赖注入式扩展点）；每 block 带
  `metadata: {llm_request_count, llm_error_count, llm_tokens_used}`——**逐块 LLM
  记账**，页级聚合成质量账本随产物下发。
- **关键实测结论**（源码注释引 olmocr-bench）：**数字 PDF 阅读序用 PDF 字符流
  排序（75%）优于学习序模型（56%）**——别迷信模型排序。
- **参数透传**：`assign_config` 一份 config dict 广播全链 + **类名前缀键消歧**
  （`MarkdownRenderer_remove_blocks`）+ hasattr 白名单防误配——比我们的透传
  更优雅，值得抄。
- **LLM 三层防线**：service 重试（429/503 指数退避，JSON 解析失败 temperature
  0→0.2 再试）→ processor 整体 try/except 记 `llm_error_count` 保留原块 →
  meta 处理器再兜一层。所有简单 LLM 处理器合流单个 ThreadPoolExecutor 并发。
- **VLM 输出卫生三件套**：重复循环检测→丢弃；标签截断→BeautifulSoup 重序列化
  补齐；debug 属性剥离。凡接 LLM 的纠错环节都该有。
- **弱点**：失败只进日志不进产物结构化字段；进程级全局注册表多租户会互相污染；
  无公式/表格小模型，重度数学文档全押 VLM。

### 2.4 VideoRAG（HKUDS 论文算法版 + Vimo 产品版）

- **管线**：30s 固定切段 → 每段 faster-whisper 转写 + 5 帧均匀采样 VLM 描述
  （**prompt 内嵌该段 transcript 的早期融合**——描述画面时"听得见"语音）→
  ImageBind 段级视频向量 → 文本 chunk + 实体图。
- **查询期设计（精华，工程糙但思路好）**：
  1. **两阶段粗细 caption**：入库 5 帧粗描述，检索命中后仅对存活段 15 帧+query
     关键词精描——省 token 且描述带查询针对性；
  2. **LLM 段级过滤**：召回段先粗 caption 让 LLM 答 yes/no 再精处理；
  3. **双查询改写**：同一 query 派生「实体检索陈述句」与「视觉场景描述句」
     分别走文本/视觉双通道；
  4. **答案强制时间戳引用格式**：CSV 数据表（video_name/start/end/content）进
     prompt + `[n] video, 05:30, 08:00` 引用规范，前端可直接渲染跳转。
- **对比结论**：无场景检测、无帧去重、无 OCR/字幕解析、无原生视频直输、模型
  路径硬编码、ImageBind 每查询重载显存、用 `eval()` 解析时间戳——NovaMind 视频
  模块（7 策略+steps+双轨融合）在其之上；可偷的是上面四条查询期设计。

### 2.5 RAG-Anything（v1.4.4）

- **架构**：`解析器（MinerU/Docling/PaddleOCR 注册表）→ content_list 协议 →
  模态 processor（image/table/equation/generic 兜底）→ LightRAG 图+向量`。
  content_list（`{type, text/img_path/table_body/latex, page_idx, caption}`）是
  parse 与下游的唯一契约，MinerU v2 分页格式→flat 的适配器是**无 IO 纯函数**。
- **分离时注入结构语境**：拆 content_list 的同时由 heading_chain 生成
  `_section_path`（"Introduction > Method"）与 `_neighbor_text`（前后 3 块），
  注入图片 VLM prompt——图片描述带章节语境，检索命中率更高。
- **视频双通道的边界处理（比朴素双轨多两层）**：
  `_add_audio_only_segments`——落在保留场景之外的语音段补成 audio-only 行
  （语音零丢失且不重复 VLM 调用）；`_plan_windows`——窗口受场景数（50）+
  token 预算双约束，超限均匀重分配**只合并不丢弃**。
- **跨模态关联的零成本方案**：chunk 内抽出的每个实体自动加一条 weight=10 的
  `belongs_to` 边到所属图片/表格/视频主实体——纯规则边，不花 LLM。
- **media_sha256 内容寻址** + parse_method+kwargs 纳入解析缓存键。
- **弱点**：无 bbox 坐标、无说话人分离/语义切分、每场景仅中点 1 帧、多模态
  单项失败静默丢弃（LightRAG 挂了多模态阶段整体静默跳过）、env 直读多处、
  chunk 文本内嵌绝对路径。

### 2.6 ragflow 上游：DeepDoc 已被整体移除（重大信号）

实拉上游 main 对比本地基线（2a83ad6, 2026-07-10）：**deepdoc/ 目录已不存在**
（61 文件 -71335 行），ragflow 1.0-rc2 重构为 Go+Python 混合栈，Python 侧依赖
里 torch/OCR/layout 全部消失。含义：

- 我们 vendored 的 DeepDoc（含全部自有修复：分窗批处理、公式守卫、PUA 归一等）
  从此是**完全独立的自有资产**，「上游对齐」策略在解析层终结；
- ragflow 官方把解析外置的方向（独立解析服务/外部引擎）与行业 hybrid 路由
  趋势一致——我们的 engines/document 引擎层归属（AGENTS.md 的引擎层独立约定）
  被上游实践反向验证。

---

## 三、NovaMind 现状定位（对照后的自评）

**已对齐业界最佳实践的部分**：
- parse→split→embed 三级指纹链——**Docling/Marker/RAG-Anything 都没有**，是我们的差异化优势；
- 失败显式暴露 + 门禁报错精确可行动（openai_video 门禁、external_ocr 空凭据报错）——与 Docling 哲学同源；
- 引擎零配置依赖/参数透传——比 MinerU（env 传参）、RAG-Anything（env 绕过 config）干净；
- 视频 7 策略 + steps + 双轨融合——全模态开源第一梯队；
- 表格/公式/图片/坐标产物、坐标入 ES（RAG-Anything 没有 bbox）。

**明确落后/空白的部分**（详见第四节）：
1. 失败语义无结构化分类学（对照 Docling 的 ErrorItem + 九类 FailureCategory + PARTIAL_SUCCESS）；
2. 无质量/置信度账本（对照 Docling 四维评分、Marker 逐块 LLM 记账）；
3. 文档侧无 VLM 解析路径（PaddleOCR-VL/GLM-OCR/MinerU2.5 时代缺位）；
4. 阅读序纯规则（对照 PP-DocLayoutV2 读序头、且数字 PDF 该学 Marker 用字符流）;
5. 图片无「章节语境注入」（对照 RAG-Anything 的 section_path + neighbor_text）；
6. 无文档级超时预算（对照 Docling document_timeout）；
7. 查询期无视频粗细两阶段描述（对照 VideoRAG）。

---

## 四、可借鉴清单（按优先级）

### P0——低成本高收益，直接可做

| # | 项 | 出处 | 落点 |
|---|---|---|---|
| 1 | **结构化失败模型**：错误分类枚举（策略/超时/推理失败/依赖缺失/输入问题）+ 页级定位 + PARTIAL_SUCCESS 状态 | Docling `base_models.py:323,347` | 任务错误面板与重试路由；`document_tasks` 终态信息结构化 |
| 2 | **文档级解析超时预算**：绝对 deadline + 在途页熔断，超时显式分类而非 kill | Docling `standard_pdf_pipeline.py:928` | worker 侧 `process_document_task` |
| 3 | **图片描述注入章节语境**：分块时维护标题路径 + 前后文，喂 VLM prompt | RAG-Anything `utils.py:219` | `pipeline_steps` 图片分支 |
| 4 | **数字 PDF 阅读序改用字符流位置**（75% vs 56% 实测），模型读序只兜扫描页 | Marker `builders/line.py` | DeepDoc 排序层 |
| 5 | **VLM 输出卫生三件套**：重复循环检测/截断标签补齐/属性剥离 | Marker `builders/ocr.py` | vlm 描述与 rewrite/steps 环节 |
| 6 | **音轨语音零丢失**：视频场景切分后，场景外语音段补 audio-only 行 | RAG-Anything `modalprocessors_video.py:401` | 视频双轨融合 |
| 7 | **pdfium 坏页重写跳页 + warning**（不可用页不炸整个文档） | MinerU `common.py:194-247` | DeepDoc PDF 输入层 |

### P1——需要规划，中期做

| # | 项 | 出处 | 说明 |
|---|---|---|---|
| 8 | **文档 VLM 解析路径**（策略第 4 条）：接入 PaddleOCR-VL-1.6 / GLM-OCR（MIT，与平台同源）/ MinerU2.5 之一，与 default/deepdoc/external_ocr 构成四路径路由；GLM-OCR 优先（MIT + 智谱生态 + 中文） | §1.1；Docling 24-preset 模式 | 走 vlm pipeline 类切换、入口不变的 Docling 模式 |
| 9 | **质量/置信度账本**：逐块/逐页 LLM 与 OCR 记账 + 四维评分随产物下发，低分页质检分流 | Docling 置信度体系 + Marker BlockMetadata | 解析产物 schema 增量扩展 |
| 10 | **middle.json 单一真源**：收敛「MD+坐标+分块」三视图为一份结构化中间层 + N 个确定性渲染器 | MinerU `common.py:259-348` | 防三视图漂移，客户端可重放产物 |
| 11 | **查询期视频两阶段描述**：入库粗描述，检索命中后按 query 精描 | VideoRAG `_op.py:666-714` | 检索链路 + 视频引擎 |
| 12 | **表格 HTML 内嵌公式/图片**：表内公式 mask→`<eq>` 注入单元格 | MinerU `batch_analyze.py:318-405` | DeepDoc 表格链路 |
| 13 | **模型/管线实例按 (class, options_hash) 缓存复用** | Docling `document_converter.py:945` | 引擎进程内热复用 |
| 14 | **分段失败分级语义**：能力级硬失败 / 页级跳过（留痕）/ 块级丢弃（留痕） | MinerU + Docling 综合 | 与现有「显式暴露」原则互补而非冲突 |

### P2——观望/按需

- 跨页表格合并（MinerU `runtime_utils.py`，DeepDoc 已有部分能力）；
- ASR 本地档增配 SenseVoice-Small（中文速度 15x）或 Fun-ASR-Nano（热词+方言+流式），作为 faster-whisper 之外的本地协议选项；
- belongs_to 规则边/实体图谱（若做知识图谱检索）；
- 冗余格式长尾（LaTeX/XBRL/iWork，Docling 有但企业 KB 场景低频）；
- 内容级 fingerprint 缓存键扩展（parse_method+kwargs 纳入键，RAG-Anything `_generate_cache_key`）。

### 反面教材（行业都踩过，我们纪律已防）

- MinerU：env 传参跨模块、env 覆盖显式入参、引擎深处 `exit(1)`、import 期读 env 选模型；
- Marker：进程级全局注册表（多租户互相污染）、async 端点里同步调转换阻塞事件循环；
- RAG-Anything：LightRAG 挂了多模态阶段静默跳过、失败项只进日志、chunk 内嵌绝对路径；
- VideoRAG：`eval()` 解析时间戳、模型每查询重载。

---

## 五、对上游资产策略的影响

1. **DeepDoc vendored 副本升级为完全自有资产**：上游已删除解析层，后续不再有
   「上游对齐」可用；自有修复（13 项遗留清零、金样语料、分窗批处理等）即最终形态，
   演进方向参照 P0/P1 清单自决。
2. **引擎层独立归属（AGENTS.md 约定）被上游实践验证**：解析能力从 RAG 框架中
   外置是大势（ragflow Go 重构外置解析、RAG-Anything 依赖 MinerU 独立进程）。
3. 新增引擎能力时优先以「可插拔策略 + 注册表」形态接入（Docling pluggy 门禁、
   Marker override_map 是扩展点设计参照），避免深耦合。

---

## 六、第二轮 GitHub 补充扫描（2026-10-27，同日）

> 方式：GitHub Search API 六主题检索 + 定向核实 25+ 候选，四个新项目源码深探
> （opendataloader-pdf / unstructured / olmocr / WeKnora 本地库），存 `.tmp/oss-ref/`。

### 6.1 新发现项目目录（按相关度分层）

**引擎/管线层（此前遗漏的重要项目）**：

| 项目 | 星数 | 活跃 | 一句话定位 |
|---|---|---|---|
| **opendataloader-pdf**（Hancom） | 30.0k | 🟢 10-27 | Java+veraPDF 几何规则、零 ML 的确定性解析器 + **页级 triage 混合编排**；我们 LegacyDeepDocParserId 里 `pdf_opendataloader` 的本体 |
| **Unstructured** | 15.6k | 🟢 10-26 | 老牌文档 ETL；模型已过时（自报表格 0.426）但**元素模型/分块管线/坐标 schema 仍是领域最完整参考实现** |
| **surya**（Datalab） | 21.5k | 🟢 | Marker 的引擎独立版：OCR/layout/读序/表格 90+ 语言 |
| **olmocr**（Ai2） | 19.8k | 🟢 | 面向 LLM 语料的 PDF 线性化管道；v2 放弃锚定、纯 VLM+温度阶梯重试 |
| **pdf-craft**（oomol-lab） | 6.4k | 🟢 | 扫描 PDF 专精转换 |
| **deepdoctection** | 3.3k | 🟢 | Document AI 管线聚合器 |
| **GROBID** | 5.2k | 🟢 | 学术论文 PDF 信息抽取（引文/章节/参考文献），企业 KB 学术场景可用 |
| **pymupdf4llm** | 2.3k | 🟢 | 务实快路径 PDF→MD（对应 Docling NativePdfPipeline 的定位） |
| **omniparse** | 7.9k | 🟡 2025-12 停更 | 全模态摄取（文档→多媒体），早期同类，已停滞 |
| docstrange / DocSlicer / anyparse / anymd / doc7 / kordoc(韩文) / LongParser | 0.1-1.6k | 各异 | 新一代轻量 MD 化浪潮，多数是 API 包装 |
| TurboOCR / OpenOCR / indra(Datalab 1M 参数 CPU OCR) | 1-1.5k | 🟢 | OCR 部署优化与小模型 |

**模型层补充**：MonkeyOCR 6.6k + MonkeyOCRv2（结构-识别-关系三元范式，视觉编码器
独立成项目）、GOT-OCR2.0 8.2k（停更）、OmniParser（微软 25.5k，屏幕解析供 GUI
Agent，邻域不同）。

**平台层（KB 产品的解析侧对照）**：WeKnora 35.5k（本地有源码，深探见 6.2）、
FastGPT 29.9k、MaxKB 23k、QAnything 14.2k（网易，2026-09 后趋缓）。注意
**WeKnora-pro 分叉的卖点就是换 MinerU-API 解析后端**——平台把解析外包给
MinerU 再次成为行业选择。

**音频/视频层**：whisperX 24.9k（词级时间戳+说话人分离，比 faster-whisper 多
对齐与分离能力）、pyannote-audio 10.7k（分离构件）、NVIDIA video-search-and-summarization
1.9k（GPU 视频 RAG 参考架构：长视频摘要=分段+密集描述聚合，MCP 接入）、
video-context-mcp / PixelML(av)（视频记忆类新形态）。

### 6.2 四个新项目源码深探要点

**opendataloader-pdf**（Hancom 出品，Java 11+，Python/Node 为 JVM 包装器）：
- **零 ML 路线**：PDFBox + veraPDF 几何规则——标题=字号/字重/位置 0.75 概率
  启发式，阅读序=XY-Cut++（arXiv:2504.10258），本地表格准确率自报仅 0.489；
  公式/OCR/图片描述全靠 hybrid 模式外包给 **docling-serve 兼容后端**（协议
  `/v1/convert/file`——我们可自实现此端点挂自家 VLM）。
- **独门功夫：Tagged PDF 结构树直读**——`struct-tree > hybrid > 启发式` 优先级，
  命中结构树即"作者意图的精确版式，无猜测"；同时反向生成 Tagged PDF（无障碍回写）。
- **页级 triage 混合路由，常数全开源**：线框比>0.3、对齐短线组≥5、大图≥11% 且
  宽高比≥1.75 判表格页、图占≥40% 且非空文本块≤5 判扫描页——简单页本地 0.02s、
  复杂页送 AI、按页序合并。**可直接移植进我们的路由层做页级细分**。
- **AI 安全过滤**：隐藏文本/off-page/透明字/tiny 字/隐藏 OCG 的 prompt-injection
  防护 + 可配置 sanitize 规则文件——企业知识库刚需。
- 产物 JSON 契约：每元素 `type/id/page/bbox/字体字号`。失败语义：魔数前置校验、
  密码分支、临时目录 fail-fast（防"静默丢文本假成功"）、hybrid 健康检查+fallback。
- 再评估结论：**值得升级出 LegacyDeepDocParserId 遗留列表**——定位是「极快确定性
  本地解析器 + 页级混合编排器」，不是又一个 DeepDoc；弱点是每 convert 起 JVM、
  中文场景需实测、韩式特调痕迹。

**Unstructured**（0.27.36-dev，活跃且 OSS 未空心化）：
- 模型侧已过时（hi_res 默认还是 2023 世代 YOLOX，官方自报 OSS 表格 0.426 vs
  商业 API 0.866）；**护城河在框架与数据契约**。
- **三路合并**：模型 layout 框 + pdfminer 文本层优先填充 + OCR 只补无文本的框
  （子区域重叠阈值 0.5）——比整页 OCR 和纯 VLM 都稳，框级合并算法值得直接抄。
- **内容流复杂度探测器**：正则数 content stream graphics/text ops 判 CAD 类
  直送 hi_res + 依赖感知的降级链（hi_res→ocr_only→fast）。
- 坐标 schema：PixelSpace/PointSpace/Relative 三坐标系 + Orientation 互转，
  序列化自带 layout_width/height（消除"坐标相对哪个页面尺寸"歧义）。
- **ConsolidationStrategy**：分块时逐字段声明收敛策略（坐标 DROP/页码 FIRST/
  表格 HTML 拼接），chunk 带 `orig_elements` 回指源元素；元素 ID=sha256(文件+
  文本+页+序号) 确定性生成——**指纹可锚 element 级，chunk 变更不动 element 指纹**。
- 表格切分：lxml 按行/单元格切 + 续片重复表头 + text 与 text_as_html 同步 +
  `table_id/chunk_index/is_continuation` 可重建原表。
- 失败哲学一句话：**数据质量问题降级留痕、环境/资源问题快失败**。

**olmOCR**（v0.4.27，Ai2，Apache 2.0）：
- **关键纠偏**：所谓 anchoring 是「把文字层带坐标注入 VLM 的输入 prompt」
  （输入侧锚定），**不是输出侧字符对齐回填坐标**；且 olmOCR-2 起连输入锚定也
  弃用了（纯页图+YAML front matter）。全库没有任何字符对齐代码。
- 拿来即用三件套：**温度阶梯重试** [0.1,0.1,0.2,0.3,0.5,0.8,0.9,1.0]（克服
  VLM 重复退化）、**旋转闭环**（模型自报 rotation_correction → PIL 旋转重发，
  累计角度最多 8 次）、**pdftotext 兜底 + 文档级 1/250 页错误率丢弃阈值**。
- 轻量质检闸门：`repeatdetect.py`（零依赖尾部 n-gram 重复检测）+ BaselineTest
  规则（空白页/CJK 乱入英文文档检测）——成本低到可每页跑。
- **topcoherency 锚定选择器**：同页用 pdftotext/pdfium/pypdf 三引擎提取，
  SmolLM-135M log-likelihood 选最连贯的——比字符数阈值更有语义依据的
  「是否信任文字层」判定，可用于 default 路由升级。
- 定位是离线批处理（vLLM 常驻 + S3 乐观锁队列，500 页/组），不适合照搬在线
  单文档解析；但其「本地 vLLM + OpenAI 兼容」部署形态是自建 GPU external_ocr
  的现成蓝本。
- 若要 external_ocr 补字符级坐标：olmOCR 没有现成代码，需自建对齐层
  （pdfreport 元素序列当参照串 + rapidfuzz 模糊对齐回填）——**这是可超越它的点**。

**WeKnora 解析模块**（35.5k，本地快照，docreader Python gRPC sidecar + Go 宿主）：
- **架构立场鲜明**：解析器只做「文件→markdown+图片引用」（docreader 头注释明写
  *No chunking, no storage, no OCR, no VLM*），扫描页 OCR/图片描述作为下游
  `image:multimodal` 异步任务 fan-out——大扫描 PDF 的解析 RPC 不被 VLM 阻塞。
- **PDF 逐页路由 + 双通道互验**（`docreader/parser/pdf_parser.py` 1600 行精华）：
  图片面积覆盖率≥0.5 判扫描页（注释：信文字层曾致 RAG 乱码）；几何版式与纯文本
  互相自检——版式重建碎裂（单字行/乱码行占比）回退纯文本，纯文本高质量（含引用
  正则）跳过昂贵几何处理。**可作 DeepDoc 前置的廉价预分类**。
- **引擎注册表带 CheckAvailable 探活**：`ListEngines` 把「这个引擎现在能不能用、
  为什么不能用」返回给前端（MinerU key 没配、Java 不在 PATH 都在选择时告知而非
  解析时爆）。
- **chunker 策略链 + 校验器 + 诊断**：每层分块结果先过字符守恒校验再采纳，
  `SplitWithDiagnostics` 输出「哪层赢、其他层为何被拒」——split 阶段质量回归/
  预览端点的现成设计。表头跨 chunk 前置（header_tracker）低成本高收益。
- 大扫描 PDF 流式 RPC 分帧回传图片、pdfium 进程全局锁 + 命名信号量限流
  （注释记录真实死锁事故）。
- 弱点：chunk 不带页码/坐标（纯 markdown 中间表示丢结构）、无本地 OCR/ASR、
  视频硬拒绝、解析行为参数 env 直读需重启。

### 6.3 补充扫描新增的可借鉴项（并入主清单）

| 优先级 | 项 | 出处 | 落点 |
|---|---|---|---|
| **P0+** | 页级 triage 路由（几何常数全开源：线框比 0.3 / 大图 11%+宽高比 1.75 / 扫描页 40%） | opendataloader `TriageProcessor.java` | DeepDoc 前置页级细分，简单页跳过模型 |
| **P0+** | 双通道互验回退（版式 vs 纯文本互相自检） | WeKnora `pdf_parser.py:934-966` | 同上 |
| **P0** | Tagged PDF 结构树直读分支（近零成本、命中即免启发式） | opendataloader `TaggedDocumentProcessor` | default 路由前置 |
| **P0** | 温度阶梯重试 + 旋转闭环 + pdftotext 兜底三件套 | olmOCR `pipeline.py` | external_ocr 路径 |
| **P0** | 引擎可用性探针（CheckAvailable + 不可用原因进选择接口） | WeKnora `engines.go:77-82` | 引擎装配/描述符端点 |
| P1 | 三路合并（模型框+文本层优先+OCR 补空） | Unstructured `ocr.py:377-407` | deepdoc/external_ocr 融合 |
| P1 | 坐标 schema 对齐（三坐标系+layout 宽高随行） | Unstructured `coordinates.py` | 坐标产物契约 |
| P1 | element 级确定性 ID + chunk→orig_elements 溯源 | Unstructured `elements.py:812` | 指纹链细化 |
| P1 | chunker 校验器+诊断输出、表头跨 chunk 前置 | WeKnora `chunker/strategy.go` | split 阶段 |
| P1 | AI 安全过滤（隐藏文本/离页文字 sanitize 规则） | opendataloader `ContentSanitizer` | 解析安全层（防注入已有基础，补 sanitize 规则化） |
| P2 | topcoherency 文字层评分器 | olmOCR `anchor.py:28-45` | default 路由判定 |
| P2 | repeatdetect 重复检测闸门 | olmOCR | VLM 输出在线质检 |
| P2 | external_ocr 字符级坐标回填（自建对齐层，超越 olmOCR 的点） | 自研方向 | 引用定位 |

### 6.4 二轮扫描后的格局修正

- **「平台自研解析」已死**：ragflow 删 deepdoc、WeKnora-pro 换 MinerU-API、
  opendataloader 的 hybrid 外包给 docling-serve——**头部项目全部走向「轻编排 +
  外置解析引擎」**；NovaMind 的 engines/document 引擎层独立归属与行业终局一致，
  且我们是少数保留自研小模型流水线的（差异化保留）。
- **确定性与智能性的分工线**：opendataloader（纯几何、0.015s/页、确定性输出）
  与 VLM 路线并存在同一编排器里、按页 triage——「数字页确定性好又快、脏页给
  智能」是收敛出的终局架构，比我们目前的文档级三路由粒度更细。
- unstructured 证明：**框架与数据契约的生命周期远长于模型**——它的元素模型还是
  商业 API 的底座。我们的产物契约（MD+坐标+指纹链）值得按此标准打磨成「可承载
  任何引擎」的互换格式。

---

## 附：调研资产位置

- `.tmp/oss-ref/{docling, marker, VideoRAG, RAG-Anything, opendataloader-pdf, unstructured, olmocr}`：镜像克隆源码（gitignore）
- `C:/Users/xl/Desktop/project/MinerU`：MinerU 本地快照（2026-08-14）
- `C:/Users/xl/Desktop/project/WeKnora`：WeKnora 本地快照（解析模块见 `docreader/`）
- `.tmp/ragflow`：ragflow 上游（本地基线 2a83ad6 + 已 fetch 的 main）
- 本文档引用的行号以上述快照为准，上游演进后需复核。
