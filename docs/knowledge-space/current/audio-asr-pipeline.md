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

- **DashScope**：录音文件识别热词仅支持百炼控制台预注册的 `phrase_id`，不支持自由
  热词注入——KB 配置了 `hotwords` 时服务端**告警忽略**（日志可见，行为可追踪）。
- **OpenAI 协议**：无热词参数，同上告警忽略。
- 热词能力矩阵：本地 = 全量生效；云端 = 告警忽略。

## 7. 已知边界与后续批次（未实施）

- **ASR 置信度透出**：segment 已采集 `avg_logprob/no_speech_prob`（用于幻觉过滤），
  尚未写入 ES chunk metadata（第二批「产物干净」范围）。
- **LLM 清洗/标点恢复**：未实施（第二批范围）。当前标点完全依赖模型自带输出
  （large-v3 中文标点可用，tiny 差）。
- **说话人分离**：未实施（第四批范围，DashScope `diarization_enabled` 或本地 pyannote）。
- **音频专用切分**：复用通用 recursive + 行锚点切分（第三批范围：停顿边界+话题切分）。
