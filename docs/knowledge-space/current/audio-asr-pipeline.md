# 音频 ASR 全链路（识别质量层）

> 权威代码位置：`backend/src/engines/document/media/audio/audio_utils.py`（引擎）、
> `backend/src/features/knowledge_space/services/media_processing.py`（宿主路由/编排）。
> 本文回答四个问题：模型从哪来、参数谁说了算、产物怎么变干净、配置变化后快照如何失效。

## 1. 模型解析链（配置 → 路由 → 转写 → 部署预装，全链同源）

```
KB 配置 audio.asr_model / 空间配置 asr.model          ← 用户在 KB/空间 UI 显式选择
        │ 有值 → 按名路由（faster-whisper-* 家族 → local；其它 → 云端凭证精确匹配）
        ▼ 空
YAML knowledge_base.parsing.local_whisper_model       ← 部署档位（默认空 = 引擎默认）
        │ 有值 → faster-whisper-{slug}（如 faster-whisper-small）
        ▼ 空
引擎默认 DEFAULT_LOCAL_WHISPER_MODEL（large-v3，生产档）
```

- **云端模型**（如 `whisper-1`/`paraformer-v2`）：按「uploader_id + model_type=asr + 模型名
  精确匹配」查用户模型配置，凭证的 `protocol` 决定 dashscope/openai 分发；查不到抛
  `PermanentProcessingError`（no-fallback，不串用其它配置）。
- **本地家族**（`faster-whisper-tiny/base/small/medium/large-v2/large-v3`）：协议恒
  `local`，不查凭证；非法档位（如 `faster-whisper-huge`）在路由层 fail fast。
- **模型目录解析**（`_resolve_local_whisper_model_dir`）：
  1. YAML `local_whisper_model_dir`（显式目录，存量部署兼容，最高优先）
  2. YAML `local_whisper_model`（档位名）→ `backend/.cache/faster-whisper/{档位}`
  3. YAML `asr.local_whisper_model_dir`（第二回退目录，可引用 `${VAR}` 环境占位符）
  4. 档位缺省 → 引擎默认档 `DEFAULT_LOCAL_WHISPER_MODEL`（large-v3）

## 2. 开发机 vs 生产（同一代码，两套配置法）

| | 开发机（8GB 无 GPU） | 生产（GPU/大内存服务器） |
|---|---|---|
| YAML `local_whisper_model` | **显式配置** `small`（~460MB，CPU int8 可跑） | 留空（= large-v3，中文 CER 最低） |
| `local_whisper_device` | 留空（auto 探测无 CUDA → CPU） | 留空（auto 探测 CUDA → GPU + float16） |
| `local_whisper_compute_type` | 留空（auto） | 留空（auto） |
| 模型预装 | `python scripts/download_faster_whisper_model.py --model small` | `deploy.sh`/`deploy.ps1` 自动按 YAML 档位预装 |
| 需要改回 tiny | YAML 改 `local_whisper_model: tiny` | 同左（tiny ~75MB，CER 高，仅排障用） |

> 原则：默认值面向生产，开发机约束通过**显式配置**表达，不把低配焊进代码。

## 3. 转写参数（识别准的三道闸）

引擎层 `transcribe()` 参数（`audio_utils._transcribe_in_subprocess`）：

| 参数 | 值 | 依据 |
|---|---|---|
| `vad_filter` | YAML `local_whisper_vad_enabled`（默认 True） | silero VAD 切静音/噪声，省算力+抑制静音段幻觉 |
| `condition_on_previous_text` | 恒 False | 切断跨窗口上下文复制——长音频重复幻觉的最大来源 |
| `hotwords` | KB `audio.hotwords`（空格拼接） | faster-whisper 原生热词注入，专有名词命中率提升 |
| `beam_size` | YAML `local_whisper_beam_size`（默认 5） | Whisper 官方默认 |
| `device`/`compute_type` | YAML（默认 auto/auto） | 生产 GPU 自动用卡，开发机自动落 CPU+int8 |
| `no_speech_threshold`/`log_prob_threshold` | 上游默认 0.6/-1.0 | OpenAI Whisper 官方同款 |

解码窗口层之上再加 segment 级兜底过滤（`_filter_hallucinated_segments`）：
- `no_speech_prob > 0.6 且 avg_logprob < -1.0` → 丢弃（模型自己没把握的段，静音/噪声编造）；
- 相邻 segment 文本完全相同 → 折叠为一条（静音/音乐段典型重复幻觉；非相邻重复不动）。

## 4. 快照失效语义（配置变化 → 正确重转写）

音频解析指纹 = 文件哈希 + 解析配置 + **`asr_engine` 引擎参数块**（`_audio_asr_fingerprint_params`）：
`protocol/model/model_dir/model_slug/device/compute_type/beam_size/vad_enabled/hotwords`（热词排序后参与哈希）。

任一变化（切档位、改设备、加热词、换协议）→ 指纹变化 → 存量音频文档下次 RETRY
重新转写；未变化的 RETRY 仍命中快照免重跑。指纹构造是命中检查与保存侧共用的单一
事实源（`_audio_asr_fingerprint_params`），两处不会漂移。

## 5. 部署预装（deploy 脚本 ↔ 下载脚本 ↔ 运行时三方同源）

- 下载脚本 `scripts/download_faster_whisper_model.py`：`--model` 显式档位 > YAML
  `local_whisper_model` > 引擎默认；`--model-dir` 显式目录 > YAML `local_whisper_model_dir`
  > 缓存命名约定 `backend/.cache/faster-whisper/{档位}`。
- `deploy.sh` / `deploy.ps1`：部署期容器内按同一档位解析链预装，落
  `./backend/.cache/faster-whisper/{档位}`（compose 挂载为 `/app/.cache/faster-whisper`）。
- checksum：`model_manager.MODEL_CHECKSUMS` 已登记档位（tiny）按内容哈希硬校验；
  未登记档位软校验（非空 + 运行时 CTranslate2 加载自检——损坏文件加载即报错，
  不会产出错误转写）。

## 6. 云端轨边界

- **热词**：DashScope 录音文件识别热词仅支持百炼控制台预注册的 `phrase_id`，
  不支持自由热词注入——KB 配置了 `hotwords` 时服务端**告警忽略**（日志可见，
  行为可追踪）。OpenAI 协议无热词参数，同上告警忽略。
- **说话人分离**（批次④）：DashScope 协议 `diarization_enabled=true`（可选
  `speaker_count` 2~100 参考值，仅单声道、建议 ≤2h），segment 带 `speaker_id`
  （0 起始整数）；transcript 行内追加 `[说话人N]` 标签（人可读），chunk
  `metadata.speaker_id` 聚合去重（逗号串，ES keyword）。本地 faster-whisper
  协议暂不支持（需 pyannote 额外模型），配置后告警忽略。

## 7. 批次②③④产物链（2026-10-05 实施）

### 双产物（raw + clean）
- raw 全文：`{base}_parsed/full_text.md`（`persist_parsed_text`，解析后立即落库）；
- clean 全文（`audio.clean_enabled=true` 时）：`{base}_parsed/clean_text.md`
  （LLM 逐批清洗，`audio.clean_llm_model` 留空 = 用户默认 LLM）；
- **入库检索用 clean**，raw 溯源；清洗硬契约 = **行数不变**（逐行与 raw 锚点
  对齐），行数漂移/LLM 失败整批降级 raw（宁可不清洗，不丢内容不错位）；
- clean 配置（`asr_clean`）与引擎参数（`asr_engine`）均进解析指纹——开关/
  模型变化 → RETRY 重新清洗；快照 payload 带 `clean_text`，resume 免重清洗。

### 置信度与说话人写 ES
- segment 采集 `avg_logprob/no_speech_prob`；`sigmoid(avg_logprob)` 归一 0~1，
  按 chunk 覆盖的锚点聚合均值 → `metadata.confidence`（float，可按质量过滤）；
- `metadata.speaker_id`：聚合去重的说话人标签串；无数据不写键（保持 None 语义）；
- 聚合发生在 `run_post_parse_tail` 切分后、锚点剥离前（pipeline_steps 1.4 步），
  随切分快照持久化——resume 免重聚合。

### 音频专用切分（`audio.split_mode="pause_topic"`）
- 引擎 `group_transcript_segments`：停顿间隙（`audio.pause_gap_seconds`，默认
  0.8s）强制切组（硬墙，不跨边界合并），组内按 `splitting.chunk_size` 封组；
- 产出 prechunked items 走 structural 切分路径，锚点行原样保留 → 切分后
  `align_chunk_times` 正常反查时间；None/recursive 维持通用 line_aware 切分。

### chunk 区间回跳播放
- 端点 `GET /api/v1/spaces/{sid}/knowledge-bases/{kid}/documents/{did}/audio/clip
  ?start=&end=`：MinIO 流式落盘原件 → ffmpeg 切片（`clip_extractor.py`）→
  mp3 字节响应（16kHz 单声道）；鉴权与图片代理一致（space member + KB 校验）；
- 前端检索结果卡片「▶ 播放片段」（SearchView）：按 chunk `metadata.start_time/
  end_time` 请求切片，Blob URL 播放；说话人标签同卡片展示。

### CER/WER 评测基建
- `engines/document/media/audio/evaluation.py`：Levenshtein 对齐（字符/词两级），
  CER 主指标（中文）、WER 可选；评测前归一（去标点/空白/大小写）——标点差异
  不污染识别准确率；`evaluate_transcript(ref, hyp)` 综合入口。上层接入
  kb-ops 质量基线或独立评测脚本时直接调用，本身无 IO/feature 依赖。
