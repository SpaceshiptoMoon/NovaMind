<template>
  <div>
    <div v-if="hasImage" class="sub-section">
      <h4 class="sub-title">图片解析</h4>
      <p class="sub-desc">
        选择 `VLM 描述` 使用视觉语言模型生成图片描述；选择 `DeepDoc OCR` 使用本地 OCR
        提取图片中的文字。
      </p>

      <el-form :model="configForm" label-width="120px" class="config-form">
        <el-form-item label="解析策略">
          <el-radio-group v-model="configForm.imageStrategy">
            <el-radio value="vlm">VLM 描述</el-radio>
            <el-radio value="deepdoc_ocr">DeepDoc OCR</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="configForm.imageStrategy === 'vlm'" label="VLM 模型">
          <el-select
            v-model="configForm.imageVlmModel"
            clearable
            filterable
            placeholder="留空时继承空间默认模型"
            style="width: 100%"
          >
            <el-option
              v-for="model in vlmModels"
              :key="model.model"
              :label="model.model"
              :value="model.model"
            />
          </el-select>
        </el-form-item>
      </el-form>
    </div>

    <div v-if="hasVideo" class="sub-section">
      <h4 class="sub-title">视频解析</h4>
      <p class="sub-desc">
        选择抽帧/去重/描述三阶段的组合预设。高级参数按策略条件展开，留空继承引擎默认值。
      </p>

      <el-form :model="configForm" label-width="120px" class="config-form">
        <el-form-item label="解析策略">
          <el-radio-group v-model="configForm.videoStrategy">
            <el-radio
              v-for="item in videoStrategyItems"
              :key="item.value"
              :value="item.value"
              :disabled="item.disabled"
              >{{ item.label }}</el-radio
            >
          </el-radio-group>
          <div class="strategy-desc">
            {{ videoStrategyItems.find((i) => i.value === configForm.videoStrategy)?.desc }}
          </div>
        </el-form-item>
        <el-form-item v-if="configForm.videoStrategy !== 'scene'" label="抽帧间隔">
          <el-slider
            v-model="configForm.videoFrameInterval"
            :min="0.5"
            :max="60"
            :step="0.5"
            show-input
            :show-input-controls="false"
          />
          <span class="field-hint">相邻帧间隔秒数，默认 5（动作密集视频建议调小防关键动作被跳过）</span>
        </el-form-item>
        <el-form-item label="最大帧数">
          <el-input-number
            v-model="configForm.videoMaxFrames"
            :min="1"
            :max="1000"
            style="width: 100%"
          />
          <span class="field-hint">默认 60；长视频建议调大（5s 间隔下 60 帧 ≈ 5 分钟）</span>
        </el-form-item>
        <el-form-item v-if="configForm.videoStrategy === 'scene'" label="场景阈值">
          <el-input-number
            v-model="configForm.videoSceneThreshold"
            :min="0"
            :max="1"
            :step="0.05"
            :precision="2"
            placeholder="0.3"
            style="width: 100%"
          />
          <span class="field-hint">切换点灵敏度，0~1，默认 0.3（越小越敏感、抽帧越密）</span>
        </el-form-item>
        <el-form-item v-if="configForm.videoStrategy === 'dedup'" label="去重阈值">
          <el-input-number
            v-model="configForm.videoDedupSimilarityThreshold"
            :min="0"
            :max="1"
            :step="0.01"
            :precision="2"
            placeholder="0.95"
            style="width: 100%"
          />
          <span class="field-hint">相似度阈值，0~1，默认 0.95（越大去重越严格）</span>
        </el-form-item>
        <el-form-item v-if="configForm.videoStrategy === 'grouped'" label="分组大小">
          <el-input-number
            v-model="configForm.videoGroupSize"
            :min="1"
            :max="20"
            placeholder="3"
            style="width: 100%"
          />
          <span class="field-hint">每组喂 VLM 多图的帧数，默认 3（多图不支持时自动降级逐帧）</span>
        </el-form-item>
        <el-form-item v-if="configForm.videoStrategy === 'frame_seq'" label="段帧数上限">
          <el-input-number
            v-model="configForm.videoFrameSeqChunkFrames"
            :min="8"
            :max="512"
            placeholder="512"
            style="width: 100%"
          />
          <span class="field-hint">
            每段喂 VLM 的最大帧数，8~512，默认 512（API 硬限）；长视频建议配合抽帧间隔调大间隔而非减段帧数
          </span>
        </el-form-item>
        <el-form-item v-if="configForm.videoStrategy === 'video_native'" label="单片时长">
          <el-input-number
            v-model="configForm.videoNativeChunkSec"
            :min="30"
            :max="540"
            :step="30"
            placeholder="540"
            style="width: 100%"
          />
          <span class="field-hint">
            单片时长上限（秒），30~540，默认 540（服务商 10 分钟硬限留裕量）；按场景切换点聚片
          </span>
        </el-form-item>
        <el-form-item v-if="configForm.videoStrategy === 'video_native'" label="尾片阈值">
          <el-input-number
            v-model="configForm.videoNativeMinTailSec"
            :min="0"
            :max="120"
            :step="5"
            placeholder="30"
            style="width: 100%"
          />
          <span class="field-hint">尾片短于该秒数并入前片，0~120，默认 30</span>
        </el-form-item>
        <el-form-item v-if="configForm.videoStrategy === 'video_native'" label="片间并发">
          <el-input-number
            v-model="configForm.videoNativeConcurrency"
            :min="1"
            :max="4"
            placeholder="2"
            style="width: 100%"
          />
          <span class="field-hint">切片直输的并发上限，1~4，默认 2（切片上传+直输均较重）</span>
        </el-form-item>
        <el-form-item
          v-if="configForm.videoStrategy === 'video_native'"
          label="拒绝降级"
        >
          <el-switch v-model="configForm.videoNativeFallbackToFrameSeq" />
          <span class="field-hint">
            服务商明确拒收视频输入时自动降级为帧序列策略；关闭则直接失败
          </span>
        </el-form-item>
        <el-form-item v-if="configForm.videoStrategy === 'scene'" label="最小帧间隔">
          <el-input-number
            v-model="configForm.videoSceneMinInterval"
            :min="0.1"
            :max="10"
            :step="0.5"
            :precision="1"
            placeholder="2"
            style="width: 100%"
          />
          <span class="field-hint">
            相邻场景帧最小间隔秒数，默认 2（动作密集如下锅/倒料建议调小，防 2-3 秒动作被跳过）
          </span>
        </el-form-item>
        <el-form-item label="视觉描述">
          <el-switch v-model="configForm.videoVlmDescriptionEnabled" />
        </el-form-item>
        <el-form-item v-if="configForm.videoVlmDescriptionEnabled" label="VLM 模型">
          <el-select
            v-model="configForm.videoVlmModel"
            clearable
            filterable
            placeholder="必选：留空将报错要求显式选择"
            style="width: 100%"
          >
            <el-option
              v-for="model in vlmModels"
              :key="model.model"
              :label="model.model"
              :value="model.model"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="音轨转写">
          <el-switch v-model="configForm.videoTranscribeAudio" />
          <span class="field-hint">
            提取音轨做 ASR 转写，旁白按时间归并进对应帧（做菜视频的用量/火候等关键信息多在旁白里，建议开启）
          </span>
        </el-form-item>
        <el-form-item v-if="configForm.videoTranscribeAudio" label="ASR 模型">
          <el-select
            v-model="configForm.videoAsrModel"
            clearable
            filterable
            placeholder="默认：本地 Whisper（免费）"
            style="width: 100%"
          >
            <el-option-group label="本地">
              <el-option label="本地 Whisper（免费）" value="faster-whisper-tiny" />
            </el-option-group>
            <el-option-group v-if="asrModels.length" label="云端模型">
              <el-option
                v-for="model in asrModels"
                :key="model.model"
                :label="model.model"
                :value="model.model"
              />
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item v-if="configForm.videoTranscribeAudio" label="旁白语言">
          <el-select
            v-model="configForm.videoAsrLanguage"
            clearable
            placeholder="自动检测"
            style="width: 100%"
          >
            <el-option label="自动检测" value="" />
            <el-option label="中文" value="zh" />
            <el-option label="英文" value="en" />
            <el-option label="日文" value="ja" />
            <el-option label="韩文" value="ko" />
          </el-select>
        </el-form-item>
        <el-form-item label="步骤综合">
          <el-switch v-model="configForm.videoStepsEnabled" />
          <span class="field-hint">
            用 LLM 把逐帧描述与旁白综合为可执行的操作步骤（带帧层覆盖率校验，漏帧自动重试，仍缺则告警跳过不阻塞文档）
          </span>
        </el-form-item>
        <el-form-item v-if="configForm.videoStepsEnabled" label="综合 LLM">
          <el-select
            v-model="configForm.videoStepsLlmModel"
            clearable
            filterable
            placeholder="留空时继承空间默认 LLM"
            style="width: 100%"
          >
            <el-option
              v-for="model in llmModels"
              :key="model.model"
              :label="model.model"
              :value="model.model"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="configForm.videoStepsEnabled" label="步骤上限">
          <el-input-number
            v-model="configForm.videoStepsMaxSteps"
            :min="1"
            :max="200"
            style="width: 100%"
          />
          <span class="field-hint">超出的步骤截断，默认 30（长视频可调大）</span>
        </el-form-item>
      </el-form>
    </div>

    <div v-if="hasAudio" class="sub-section">
      <h4 class="sub-title">音频解析</h4>
      <p class="sub-desc">
        ASR 模型可选本地 Whisper 或已配置的云端模型；默认使用本地 Whisper（免费，无需配置）。
      </p>

      <el-form :model="configForm" label-width="120px" class="config-form">
        <el-form-item label="ASR 模型">
          <el-select
            v-model="configForm.audioAsrModel"
            clearable
            filterable
            placeholder="默认：本地 Whisper（免费）"
            style="width: 100%"
          >
            <el-option-group label="本地">
              <el-option label="本地 Whisper（免费）" value="faster-whisper-tiny" />
            </el-option-group>
            <el-option-group
              v-if="asrModels.length"
              label="云端模型"
            >
              <el-option
                v-for="model in asrModels"
                :key="model.model"
                :label="model.model"
                :value="model.model"
              />
            </el-option-group>
          </el-select>
          <div v-if="configForm.audioAsrModel" class="field-hint">
            {{ configForm.audioAsrModel === 'faster-whisper-tiny'
              ? '使用本地 Whisper 转写，无需 API 配置'
              : '使用该云端模型的 API 凭证转写，请在模型管理中确认已配置' }}
          </div>
        </el-form-item>
        <el-form-item label="语言">
          <el-select
            v-model="configForm.audioAsrLanguage"
            clearable
            placeholder="自动检测"
            style="width: 100%"
          >
            <el-option label="自动检测" value="" />
            <el-option label="中文" value="zh" />
            <el-option label="英文" value="en" />
            <el-option label="日文" value="ja" />
            <el-option label="韩文" value="ko" />
          </el-select>
        </el-form-item>
        <el-form-item label="热词">
          <el-input
            v-model="configForm.audioHotwordsText"
            type="textarea"
            :rows="2"
            placeholder="产品名、人名、术语等，用逗号/顿号分隔，如：NovaMind，RAG，知识库"
          />
          <div class="field-hint">
            提升专有名词识别率；仅本地 ASR 生效（云端模型暂不支持，保存后仍会保留配置）。
          </div>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
/** 知识库配置弹窗的多模态解析分区：图片/视频/音频三块的解析策略与参数表单 */
import type { AvailableModelItem } from '@/api/types'
import { type ImageStrategy, type VideoStrategy, videoStrategyItems } from './kbConfig'

type MultimodalParsingFormModel = {
  imageStrategy: ImageStrategy
  imageVlmModel: string
  videoStrategy: VideoStrategy
  videoFrameInterval: number
  videoMaxFrames: number
  videoVlmDescriptionEnabled: boolean
  videoVlmModel: string
  videoSceneThreshold: number | null
  videoDedupSimilarityThreshold: number | null
  videoGroupSize: number | null
  videoFrameSeqChunkFrames: number | null
  videoNativeChunkSec: number | null
  videoNativeMinTailSec: number | null
  videoNativeConcurrency: number | null
  videoNativeFallbackToFrameSeq: boolean
  videoSceneMinInterval: number | null
  videoTranscribeAudio: boolean
  videoAsrModel: string
  videoAsrLanguage: string
  videoStepsEnabled: boolean
  videoStepsLlmModel: string
  videoStepsMaxSteps: number
  audioAsrModel: string
  audioAsrLanguage: string
  audioHotwordsText: string
}

defineProps<{
  configForm: MultimodalParsingFormModel
  hasImage: boolean
  hasVideo: boolean
  hasAudio: boolean
  vlmModels: AvailableModelItem[]
  asrModels: AvailableModelItem[]
  llmModels: AvailableModelItem[]
}>()
</script>

<style scoped>
.sub-section {
  margin-bottom: 20px;
  padding: 22px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card-elevated);
  box-shadow: var(--shadow-sm);
}

.sub-title {
  margin: 0 0 6px;
  font-size: var(--text-lg);
}

.sub-desc {
  margin: 0 0 18px;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
}

:deep(.el-radio-group) {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

:deep(.el-radio) {
  margin-right: 0;
  padding: 10px 14px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
}

:deep(.el-radio.is-checked) {
  border-color: var(--color-border-focus);
  background: var(--color-primary-subtle);
}

.strategy-desc {
  margin-top: 6px;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.field-hint {
  display: block;
  margin-top: 4px;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
}
</style>
