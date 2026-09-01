<template>
  <div>
    <div v-if="hasImage" class="sub-section">
      <h4 class="sub-title">图片解析</h4>
      <p class="sub-desc">选择 `VLM 描述` 使用视觉语言模型生成图片描述；选择 `DeepDoc OCR` 使用本地 OCR 提取图片中的文字。</p>

      <el-form :model="configForm" label-width="120px" class="config-form">
        <el-form-item label="解析策略">
          <el-radio-group v-model="configForm.imageStrategy">
            <el-radio value="vlm">VLM 描述</el-radio>
            <el-radio value="deepdoc_ocr">DeepDoc OCR</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="configForm.imageStrategy === 'vlm'" label="VLM 模型">
          <el-select v-model="configForm.imageVlmModel" clearable filterable placeholder="留空时继承空间默认模型" style="width: 100%">
            <el-option v-for="model in vlmModels" :key="model.model" :label="model.model" :value="model.model" />
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
            >{{ item.label }}</el-radio>
          </el-radio-group>
          <div class="strategy-desc">
            {{ videoStrategyItems.find((i) => i.value === configForm.videoStrategy)?.desc }}
          </div>
        </el-form-item>
        <el-form-item v-if="configForm.videoStrategy !== 'scene'" label="抽帧间隔">
          <el-slider v-model="configForm.videoFrameInterval" :min="1" :max="60" show-input :show-input-controls="false" />
        </el-form-item>
        <el-form-item label="最大帧数">
          <el-input-number v-model="configForm.videoMaxFrames" :min="1" :max="200" style="width: 100%" />
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
        <el-form-item label="视觉描述">
          <el-switch v-model="configForm.videoVlmDescriptionEnabled" />
        </el-form-item>
        <el-form-item v-if="configForm.videoVlmDescriptionEnabled" label="VLM 模型">
          <el-select v-model="configForm.videoVlmModel" clearable filterable placeholder="必选：留空将报错要求显式选择" style="width: 100%">
            <el-option v-for="model in vlmModels" :key="model.model" :label="model.model" :value="model.model" />
          </el-select>
        </el-form-item>
      </el-form>
    </div>

    <div v-if="hasAudio" class="sub-section">
      <h4 class="sub-title">音频解析</h4>
      <p class="sub-desc">ASR 模型与语言参数互不冲突，空值时回退默认配置。</p>

      <el-form :model="configForm" label-width="120px" class="config-form">
        <el-form-item label="ASR 模型">
          <el-select v-model="configForm.audioAsrModel" clearable filterable placeholder="默认 whisper-1" style="width: 100%">
            <el-option v-for="model in asrModels" :key="model.model" :label="model.model" :value="model.model" />
          </el-select>
        </el-form-item>
        <el-form-item label="语言">
          <el-select v-model="configForm.audioAsrLanguage" clearable placeholder="自动检测" style="width: 100%">
            <el-option label="自动检测" value="" />
            <el-option label="中文" value="zh" />
            <el-option label="英文" value="en" />
            <el-option label="日文" value="ja" />
            <el-option label="韩文" value="ko" />
          </el-select>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
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
  audioAsrModel: string
  audioAsrLanguage: string
}

defineProps<{
  configForm: MultimodalParsingFormModel
  hasImage: boolean
  hasVideo: boolean
  hasAudio: boolean
  vlmModels: AvailableModelItem[]
  asrModels: AvailableModelItem[]
}>()
</script>

<style scoped>
.sub-section {
  margin-bottom: 20px;
  padding: 22px;
  border: 1px solid var(--color-border-light);
  border-radius: 20px;
  background: linear-gradient(180deg, #fff, rgba(250, 249, 255, 0.96));
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
  background: #fff;
}

:deep(.el-radio.is-checked) {
  border-color: rgba(17, 24, 39, 0.35);
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
