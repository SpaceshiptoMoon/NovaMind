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

## 附：调研资产位置

- `.tmp/oss-ref/{docling, marker, VideoRAG, RAG-Anything}`：镜像克隆源码（gitignore）
- `C:/Users/xl/Desktop/project/MinerU`：MinerU 本地快照（2026-08-14）
- `.tmp/ragflow`：ragflow 上游（本地基线 2a83ad6 + 已 fetch 的 main）
- 本文档引用的行号以上述快照为准，上游演进后需复核。
