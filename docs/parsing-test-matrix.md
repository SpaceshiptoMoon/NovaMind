# 解析模块测试矩阵（组合空间全覆盖清单）

> 范围：`backend/src/engines/document` + `backend/src/shared/document` 全部解析器参数组合。
> 组合空间依据：`knowledge_base_schema.py` 的 ParsingConfig/SplittingConfig 权威定义。
> 状态标记：✅ 已有自动化覆盖 / ⬜ 待补 / 🔶 需外部依赖（API key / 模型下载）后实测 / 🟡 本机已真机验证（probe 脚本）。
> 依赖服务不可达时集成项自动 skip；外部依赖项以「桩验证报错路径 + 有 key 后真测」两段覆盖。

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
