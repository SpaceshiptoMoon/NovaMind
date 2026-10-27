# 解析模块测试矩阵（组合空间全覆盖清单）

> 范围：`backend/src/engines/document` + `backend/src/shared/document` 全部解析器参数组合。
> 组合空间依据：`knowledge_base_schema.py` 的 ParsingConfig/SplittingConfig 权威定义。
> 状态标记：✅ 已有自动化覆盖 / ⬜ 待补 / 🔶 需外部依赖（API key / 模型下载）后实测 / 🟡 本机已真机验证（probe 脚本）。
> 依赖服务不可达时集成项自动 skip；外部依赖项以「桩验证报错路径 + 有 key 后真测」两段覆盖。

## 执行记录

**2026-10-27（夜）解析质量批次**（不加引擎，完善解析手段——图片/Excel/Word 准确性与边界 case）：

- **Excel**（deepdoc 路径，deepdoc-only 策略真机验证 ✓）：
  合并单元格值展开（左上值填充全区域，此前合并维度全空致行语义断裂）；
  公式无缓存值回填（程序生成的 xlsx data_only 视角为 None，二次加载公式
  视图按字面量填回，20MB 内存护栏）；数值/日期格式化（1200.0→1200、
  零点时间去尾、bool 中文化、控制字符剔除，html 与行文本双出口共用）。
  真机：复杂 xlsx（合并+公式+浮点+日期）chunk 内容全部正确。
- **Word**（deepdoc 路径，真机验证 ✓）：
  body 物理序重构——表格在文档中部不再堆到文档尾（sections 带 table_index
  占位，runtime 按位回插 + 尾部残留兜底）；标题层级映射 # 数量（H2→##，
  路径语境保留）；numPr 列表段加「• 」前缀（真实序号 Word 渲染期生成拿
  不到，保住列表成员语义）；文本框（w:txbxContent）内容以 TextBox 段落
  提取（此前整体丢失；注意非注册类元素 xpath 需显式 nsmap）。
  真机：复杂 docx chunk = `# 项目报告 → ## …> 财务数据 → 表格(原位) →
  结论 → • 行动项 → 文本框` 全序正确。
- **图片**：VLM 输入降采样——超长边 >2000px 主动 LANCZOS 缩图 + EXIF 转正
  （防服务商端不可控压缩丢密集小字；仅 VLM 通道，OCR 保持原分辨率；
  解码失败原样上送不在本地引入新失败面）。
- **Excel 二批（多级表头+嵌入图片，真机验证 ✓）**：表头行数探测（数值占比
  启发式，最多 3 行；首行数值主导判无表头表用列字母占位）+ 两级折成复合
  表头（「Q1 > 收入」，html/行文本双出口同源）；工作表嵌入图片提取
  （ws._images → PIL png 化重编码，EMF/WMF 不可解码跳过告警）→ figure_regions
  契约复用 PDF figure 上传管线（宿主门禁放宽 xlsx/xls，占位符替换短路径）；
  单元格内换行转 <br/>。真机：复合表头 chunk + figure 短路径入库确认。
- **Excel 三批（版面语义层，真机验证 ✓）**：新增 `parsers/excel_layout.py`
  ——值网格 → **两阶段投影连通域分岛**（一 sheet 多张表切开，密度自适应
  阈值 + 列 gap 永不放宽）→ **两级缝合后处理**（小标题并入下表、被切断
  的表按列重叠率缝回，占用判定排除纯样式格）→ 前置区三信号（banner 横
  合并 / KV 行 / 稀疏行，有 contrast 列的行永不误判）→ 表头 band（数据
  首行 = 首个含数值形态格的行，其上非前置行即 band，复合表头折叠保留）。
  附：**图表 range 回读缓存值重建数据表**（图表（bar）caption + 类别/系列
  列）、**批注内联**（`[note(作者): 文本]`）、**citation caption**
  （`Sheet!A1:F18` 进表格 caption）。真机：多岛 sheet 分表、批注内联、
  图表数据表全部入库确认。
- **Excel 四批（剩余棘手项收口，真机验证 ✓）**：**小计/总计行打标**
  （`[小计] ` 前缀，聚合词启发式；打标不剔除——用户可能就问总计）；
  **表内小节层级**（Excel 行分组 outlineLevel Tier1 + 左缘横合并行 Tier2
  → `[节] 标注` 行并按小节断表续排；注意 row_dimensions 键 1-based 需转
  0-based）；**转置表**（首行数值主导 + 首列文本密度 → 首列作行表头 th，
  caption 标注转置形态）；**单位挂接**（前置「单位：X」提取挂 caption，
  单位词排除括号防双括号）；**无表头诚实标注**（caption 注明「按列字母
  标注」）；合并区展开前快照回写（banner/小节判定需要原始合并信息）。
  三级表头 + 不规则级数回归补齐（2024年>上半年>收入 实证）。
- 边界 case 存量盘点：空文件/GBK/UTF16/损坏/扫描件 0 字符/合并去重/seek
  崩溃/坏图/加密 PDF/zip 炸弹此前已覆盖；本批新增公式无缓存值与大图两枚。
- 回归：解析矩阵 58 + deepdoc 179 + 准确性夹具 7 + 降采样 4 全绿。
- 注意：default 策略的 docx 走 shared reader（朴素线性化，无标题/顺序治理）
  ——质量改进在 deepdoc 策略生效，前端选型提示可在描述符层暴露。

**2026-10-27（晚）MinerU 外部引擎接入**（strategy=mineru 新增为 PDF 第四解析路径）：

- 适配层：`engines/document/integrations/mineru/`（适配 MinerU 4.x「常驻服务 +
  CLI 客户端」形态——`mineru server start` 模型驻留，适配层经 `mineru parse`
  子进程提交，tier 档位透传，页标记剥离后入库）；独立 venv 安装（mineru[core]
  4.0.12），宿主从 YAML `mineru` 段透传 cli_path/tier/timeout（零 env 依赖）
- 失败纪律：cli_path 为空/可执行缺失/服务未运行 → `MineruNotAvailableError`
  （Permanent 不可重试，带安装与启动指引）；超时/非零退出/产物缺失 →
  `MineruExecutionError`（可重试）
- 真测：`pdf-mineru` 组合 PASS（16s，1 chunk，标记已剥离，检索命中标记）；
  单测 8 项（fail-fast×3 / 产物收集×3 / 策略归一 / schema 流转）+ 描述符 9 项全绿；
  策略基线测试更新为四策略门禁（default/deepdoc/external_ocr/mineru）

**2026-10-27（下）门禁后真测与云端依赖定性**（承接当日上轮；VLM 凭证临时翻转
openai_video 后已还原）：

- **frame_seq 真测 PASS**（hardcut.mp4×1s 间隔凑足帧数，4 chunks）——openai_video
  门禁过后的全链真跑。注意 DashScope 帧序列单次请求有 **≥4 帧下限**（probe.mp4
  4 秒仅 1 帧时引擎显式报「帧序列不足单次请求下限：1 < 4」，不白烧调用）→ 四区 🟡
- **video_native 环境阻塞定性**：代码路径已通到真实服务商请求，DashScope 返回
  400「provided URL does not appear to be valid」——切片走 MinIO URL，云端 VLM
  拉不到 NAT 后的本机 MinIO。与云端 ASR 同根：**需要公网可达的
  minio.public_endpoint 才能真测**。报错原文精确上浮，失败方向安全。
- **云端 ASR（DashScope filetrans）环境阻塞定性**：凭证路由/提交/轮询/报错上浮
  全链代码路径已验证；阻塞点同样是音频经 MinIO 预签名 URL 交云端拉取——本机
  不可达 → SERVER_ERROR。另发现凭证 id37 模型名 `paraformer-v1` 对文件转写
  API 已失效（提交即 404 Model not exist），需换 paraformer-v2 等有效名。
- runner 传输层教训：uvicorn keep-alive 竞态会让复用连接的轮询偶发
  RemoteProtocolError/ReadError，被误报成文档失败——runner 已改
  `Connection: close` + HTTPTransport(retries=3)，判定以 worker 日志为最终权威。
- 全量 pytest 回归：3190 passed / 4 failed——wiki_reprocess_scrub×2（已知存量）+
  agent 工具注册基线×2（`test_baseline_tools_registered`/
  `test_all_builtin_tools_pass_registration_validation`，10-19 工具工程化批次
  cc97c5ef 起基线漂移：features/agent 的 consult_member/todo/group_messaging/
  local_workspace 等入册未同步基线，与本轮改动无关，归属 agent 模块待修）。

**2026-10-27（上）配置矩阵端到端真测**（真实服务全链：建 KB→上传→arq worker→ES 索引→BM25 检索命中；
runner：`backend/test_data/_probe/probe_config_matrix.py`，结果 JSON 同目录）——35 组合 34 PASS：

- **文本族 ×8 切分**（recursive/fixed_size/markdown/semantic/delimiter/sentence_window/
  parent_child/hierarchical）：全 PASS，均含唯一标记检索命中断言 → 一区 ×8 列全部补齐 🟡
- **文本族 8 文档类型**（docx/epub/html/json/txt/csv/xlsx/pptx）：全 PASS；
  **xlsx/pptx 上传白名单已放开**（FileFormatSpec 登记 + 校验器 OOXML 深检本就就绪 + 前端 accept 同步），
  「excel/ppt 半接线」收口 → 1.4 节 🟡
- **PDF 三路径**：default ✅ / deepdoc full（扫描件 OCR 真跑，24s）✅ /
  external_ocr（DashScope qwen3.5-ocr 真调用，chunk 内容即扫描页文字）✅ → 1.1 节 EO 行 🟡
- **图片四策略**：deepdoc_ocr ✅ / vlm（qwen3.7-flash 真描述）✅ /
  combined（结构化 caption + OCR 交叉校验【图中文字】段）✅ / external_ocr ✅ → 二区 🟡
- **视频六策略**：simple ✅ / scene+transcribe_audio（hardcut 双硬切+音轨 ASR）✅ /
  grouped ✅ / rewrite（LLM 真重写）✅ / frame_seq 🔒GATE / video_native 🔒GATE
  （两者门禁报错精确可行动：「请在模型管理中把所选 VLM 模型的协议改为 openai_video」——
  显式暴露原则生效，非缺陷）→ 四区 🟡
- **音频三配置**：本地 faster-whisper × recursive / pause_topic / clean_enabled 全 PASS
  （首跑暴露空间 config 显式 null 段崩溃 bug，已修——见下）→ 三区 🟡
- **本轮揪出并修复**：空间 config 历史行显式 `"asr": null`（旧创建序列化未 exclude_none）
  令 `.get("asr", {})` 拿到 None，音频文档对未配置 ASR 的新空间解析必崩
  （`'NoneType' object has no attribute 'get'`）。三层修复：创建序列化
  `exclude_none`（堵源头）+ Space 模型段 getter `or {}`（兜存量）+
  `_space_asr_cfg` 归一（消费点）；回归测试
  `test_space_config_null_sections.py`（写/模型/消费三层正反用例）。
- 判定口径说明：chunks API 读 ES，任务完成后 ~1s 刷新窗口内可能读到 0，
  runner 已带重试；该窗口属 ES 最终一致性，非管道缺陷。

**2026-10-26 首轮全量执行**（本机：模型已缓存 + ffmpeg + 无外部 API key）：

- **批 1+2 文本族**：`tests/engines/document/test_parsing_matrix.py` —— 56 passed
  （TXT/MD/HTML/JSON/DOCX/PDF default × 8 切分 = 48；deepdoc × 8 文档类型全组合 = 8，
  每类内层循环 8 切分策略）。→ 一区 T-PDF-DEF/T-DOCX-DEF/T-MD-DEF/T-HTML-DEF/
  T-JSON-DEF ×8、T-DOCX-DD/T-EPUB/T-EXCEL/T-PPT/T-MD-DD/T-HTML-DD/T-JSON-DD/T-TXT-DD 全 ✅
- **批 3 多模态**：`tests/integration/test_media_matrix.py` —— 10 passed
  （真实语音 ASR/静音/损坏/格式探测/音轨提取/固定抽帧/场景硬切/串联 ASR/时间对齐/
  片尾告别语保留）。→ 三区 T-AUD-LOCAL-REC/PAUSE 部分/SILENT/BROKEN/HOTWORDS(单测)/
  BUSY/POOL-CRASH、四区抽帧层与 T-VID-TRANSCRIBE/T-VID-TIMEALIGN 全 ✅
- **批 4 图片**：`tests/engines/document/deepdoc/test_image_deepdoc_ocr.py` —— 2 passed
  （png OCR 文字识别 + 无字图空产物）。→ 二区 T-IMG-DDOCR 代表项 ✅
- **批 5 PDF deepdoc full（高内存末批）**：TestPdfDeepdocFull 2 passed
  （full+recursive / full+fixed_size）+ 扫描件 OCR 真跑（视觉文字完整识别）。
  → T-PDF-DD 的 REC/FIX 两切分 ✅（其余 6 切分待补，同引擎参数差异低风险）
- **F 系列**：22 passed（layout/formula 两态、注入点、策略导出）→ 五区全 ✅

**剩余 ⬜**：文本族 deepdoc×8 切分中 6 个未跑切分（同引擎参数差异，低风险）、
🔶 VLM/云端 ASR/外部 OCR 真测（需 API key 环境）。

## 组合编号规则

`T-<模态>-<解析>-<切分/策略>-<变体>`；边界专项 `B-*`；失败策略 `F-*`。

---

## 一、文本族（解析 × 切分 全组合：136 项核心 + 边界）

切分维度 8 策略统一缩写：`REC`=recursive / `SEM`=semantic / `FIX`=fixed_size / `MD`=markdown / `DEL`=delimiter / `SW`=sentence_window / `PC`=parent_child / `HIE`=hierarchical。

### 1.1 PDF（3 解析路径 × 8 切分 = 24 + 变体 8）

| 编号 | 组合 | 验证要点 | 状态 |
|---|---|---|---|
| T-PDF-DEF-×8 | default reader × 8 切分 | 文字层全文完整性（MARK 不丢）；页码 PUA 归一；SEM 需 embedding 桩 | ⬜（DEF+REC 已有散测，其余待补） |
| T-PDF-DD-×8 | deepdoc full × 8 切分 | reading_order 坐标链、表格/图注区域、哨兵重切（tagged_rechunk）对每种切分器穿越后坐标可恢复 | 🟡 pdf_full+REC 已真机验证；其余 ⬜ |
| T-PDF-EO-DOC-×8 | external_ocr(document_parsing) × 8 切分 | 🔶 需 ocr api_key；版面 layouts 归一 | ⬜ |
| T-PDF-EO-ML-×8 | external_ocr(multi_lan) × 8 切分 | 🔶 同上 | ⬜ |
| T-PDF-PARSER-NONE | deepdoc + strategy=default 残留 parser | parser 字段自动清空不 500 | ✅ |
| T-PDF-POLICY-RAISE | deepdoc + model_failure_policy=raise + 坏模型 | LayoutInferenceError 上抛 | ✅ |

### 1.2 DOCX（2 × 8 = 16）

| 编号 | 组合 | 验证要点 | 状态 |
|---|---|---|---|
| T-DOCX-DEF-×8 | default × 8 切分 | 标题/段落/表格文本抽取；**合并单元格去重**（红队 P1-2） | ⬜ |
| T-DOCX-DD-×8 | deepdoc × 8 切分 | 结构保留（表格/图注坐标）；内嵌图片占位 | ⬜ |

### 1.3 TXT / MD / HTML / JSON（各 2 × 8 = 16 × 4）

| 编号 | 组合 | 验证要点 | 状态 |
|---|---|---|---|
| T-TXT-DEF-×8 | txt × 8 切分 | 编码回落（UTF-8/UTF-16 BOM/GBK）；锚点类内容（音频切分共用此链） | 🟡 gbk/UTF-16 已真机验证；×8 组合 ⬜ |
| T-MD-DEF-×8 | md × 8 切分 | 标题/列表结构；**切句复用权威正则**（3.14/e.g. 不切碎） | ⬜ |
| T-HTML-DEF-×8 | html × 8 切分 | 实体解码、表格 | ⬜ |
| T-JSON-DEF-×8 | json × 8 切分 | dict 结构拍平 | ⬜ |
| T-{DOCX,MD,HTML,JSON}-DD-×8 | deepdoc × 32 | 同 deepdoc 契约键（chunk_structure 等） | ⬜ |

### 1.4 EPUB / EXCEL / PPT（各 1 × 8 = 24）

| 编号 | 组合 | 验证要点 | 状态 |
|---|---|---|---|
| T-EPUB-×8 | deepdoc × 8 切分 | spine 顺序；OCF 最小结构 | 🟡 EPUB+默认切分已真机验证 |
| T-EXCEL-×8 | deepdoc × 8 切分 | **路径形态输入**（红队 seek 崩溃修复回归）；html 表格块回退行文本 | 🟡 xlsx+默认已真机验证；8 切分 ⬜ |
| T-PPT-×8 | deepdoc × 8 切分 | 形状阅读序（top 分桶+left）；缓存键修复回归 | 🟡 pptx+默认已真机验证 |

### 1.5 文本边界专项（B-TEXT）

| 编号 | 场景 | 状态 |
|---|---|---|
| B-TEXT-EMPTY | 空文件 → read_full_text 空串 → 管道 `_raise_on_empty_parse` 报错引导 | ✅ |
| B-TEXT-GBK / B-TEXT-UTF16 | GBK 回落；UTF-16 BOM 解码（红队 P1-1 修复回归） | ✅ |
| B-TEXT-CORRUPT | 损坏文件 → 打开类失败**上抛**（不再误诊扫描件） | ✅ |
| B-TEXT-SCAN-PDF | 扫描件 default 路径 0 字符 → 报错引导切 full | ✅ |
| B-DOCX-MERGED-CELLS | 合并单元格去重（P1-2 回归） | ✅ |

---

## 二、图片（4 解析 × 8 切分 = 32，全部依赖外部/模型分档）

| 编号 | 组合 | 验证要点 | 状态 |
|---|---|---|---|
| T-IMG-VLM-×8 | vlm × 8 切分 | 🔶 caption 生成 → 文本 embedding；空响应/配额失败路径（fail fast 默认） | ⬜ |
| T-IMG-DDOCR-×8 | deepdoc_ocr × 8 切分 | 本地 OCR 真跑（模型已缓存）；无字图 0 块行为 | 🟡 figure 路径已真机验证 |
| T-IMG-COMB-×8 | combined × 8 切分 | OCR 逐字层 + VLM caption 合并去重；幻觉信号 warning-only | ⬜ |
| T-IMG-EO-×8 | external_ocr × 8 切分（× ocr_task 2 子态） | 🔶 multi_lan 单图/document_parsing PDF | ⬜（空凭据报错路径 ✅） |
| T-IMG-VLM-NOMODEL | vlm 策略未配模型 | 显式报错不兜底 | ✅ |
| T-IMG-QUOTA-SKIP | vlm_skip_on_quota_error=True | 占位描述继续，文档不失败 | ✅ |

---

## 三、音频（3 ASR × 清洗 × 切分模式 ≈ 54 有效组合，核心 18 项）

| 编号 | 组合 | 验证要点 | 状态 |
|---|---|---|---|
| T-AUD-LOCAL-REC | 本地 faster-whisper + recursive | **真实中文语音转写**（SAPI TTS）；繁体输出记录 | ✅ |
| T-AUD-LOCAL-PAUSE | 本地 + pause_topic | 停顿边界切分（gap 阈值强制切边界）；锚点时间对齐 | 🟡 时间对齐已真机验证 |
| T-AUD-LOCAL-CLEAN | 本地 + clean_enabled | LLM 清洗 🔶；清洗失败降级 raw | ⬜ |
| T-AUD-LOCAL-HOTWORDS | 本地 + hotwords | 热词注入解码 | ✅（单测层） |
| T-AUD-LOCAL-SILENT | 静音音频 | 0 段不崩（幻觉过滤） | ✅ |
| T-AUD-LOCAL-BROKEN | 损坏音频（1KB 假 wav） | AudioFileInvalidError 永久错误，不回退云端 | ✅ |
| T-AUD-DASH-×3 | DashScope × (plain/diarization×speaker_count) | 🔶 需 key；speaker_id 入 metadata；热词告警忽略 | ⬜ |
| T-AUD-OPENAI-×2 | OpenAI Whisper API × (language 透传/损坏音频) | 🔶 需 key；临时文件清理 | ⬜ |
| T-AUD-BUSY | 本地忙碌（租约被占） | LocalASRBusyError 延后重入队；Redis 租约互斥 | ✅ |
| T-AUD-POOL-CRASH | 进程池崩溃 | 重建 + 重试，不永久挂死 | ✅ |

---

## 四、视频（7 策略 × 音轨/步骤叠加 ≈ 28 项）

| 编号 | 组合 | 验证要点 | 状态 |
|---|---|---|---|
| T-VID-SIMPLE | simple（固定间隔+逐帧） | 🔶 需 VLM；抽帧 5 帧/时间戳精确已真机验证 | 🟡 抽帧层 ✅；VLM 段 🔶 |
| T-VID-SCENE | scene | **双场景硬切捕获**（阈值标定修复回归：2 帧 [0.0,4.0]） | ✅ 真机验证 |
| T-VID-DEDUP | dedup | 阈值标定回归：静态视频去重后 ≥1 帧不空、硬切不误丢 | ✅ 真机验证 |
| T-VID-GROUPED | grouped | 多帧一组连贯描述 🔶；组失败降级逐帧 | ⬜ |
| T-VID-REWRITE | rewrite | 逐帧描述 + LLM 重写锚点校验 🔶 | ⬜ |
| T-VID-FRAMESEQ | frame_seq | 伪视频分段（512 帧上限/尾段并入）🔶 | ⬜ |
| T-VID-NATIVE | video_native | 🔶 切片直输 + scene 强制 + 被拒降级 frame_seq 开关两态 | ⬜ |
| T-VID-NATIVE-MEM | video_native 长视频内存 | 切片在信号量内（P1-1 回归：sem 外无 read_bytes） | ✅（代码层） |
| T-VID-NATIVE-GOP | -c copy 关键帧前滚 | av 探测实际起点校正 prompt 口径 | ✅（代码层） |
| T-VID-TRANScribe | 任意策略 + transcribe_audio=True | **音轨提取→ASR 串联**（TTS 语音全文本转写） | ✅ 真机验证 |
| T-VID-STEPS | steps_enabled | 步骤综合双层覆盖率校验 🔶 | ⬜ |
| T-VID-TIMEALIGN | 锚点时间对齐 | 锚点剥离 + start_time/end_time 对齐 + 无锚点标未知 | ✅ 真机验证 |
| T-VID-SHORT/STATIC | 超短视频/静态视频 | scene 兜底均匀采样（P0-2 回归：≤1 选中触发） | ✅ 真机验证 |

---

## 五、失败策略与全局开关（F 系列）

| 编号 | 组合 | 验证要点 | 状态 |
|---|---|---|---|
| F-LAYOUT-HEURISTIC | model_failure_policy=heuristic_fallback | 推理失败窗回退启发式，layout_source=heuristic 可见 | ✅ |
| F-LAYOUT-RAISE | =raise | LayoutInferenceError 上抛 | ✅ |
| F-FORMULA-KEEP | deepdoc_formula 缺模型 + keep_ocr_text | 公式区域保留 OCR 文本 | ✅ |
| F-FORMULA-RAISE | =raise | FormulaModelUnavailableError 上抛 | ✅ |
| F-SNAPSHOT-OFF | snapshots_enabled=false | 快照读写全跳过，重试走全量 | ✅ |
| F-UNKNOWN-STRATEGY | parsing/splitting 未知策略名 | 显式报错不静默落 default | ✅ |
| F-EMPTY-PARSE | 解析 0 字符 | 报错引导（plain→建议 full） | ✅ |
| F-QG-DISABLED | question_generation.enabled=false | 跳过生成，metrics 可见 | ✅ |

---

## 执行基准

- **单元/集成层**：`backend/tests/`（101+ 文件，解析域 716 passed）——上表 ✅ 项的自动化落点。
- **真机实测脚本**：`backend/test_data/_probe/`（本地保留）：`probe_all_parsers.py`（27 项）、`probe_asr_real.py`、`probe_video.py`、`probe_time_align.py`、`probe_p0_verify.py`、`probe_last_phrase.py`。
- **待补优先级**：⬜ 项按「文本族 ×8 切分组合矩阵 > 图片 combined > 视频需 VLM 项」排序；🔶 项在有 API key 的环境一次性补齐。
- **组合新增守门**：新增解析策略/参数时必须同步本矩阵 + `runtime_settings`/`parsing-descriptors` 端点（若涉及）。
