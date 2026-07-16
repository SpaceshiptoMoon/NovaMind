<template>
  <div>
    <div v-if="hasImage" class="sub-section">
      <h4 class="sub-title">图片解析</h4>
      <p class="sub-desc">对应 `parsing.image`。选择 `ocr` 时不会提交 `vlm_model`，选择 `vlm` 时可覆盖空间默认视觉模型。</p>

      <el-form :model="configForm" label-width="120px" class="config-form">
        <el-form-item label="解析策略">
          <el-radio-group v-model="configForm.imageStrategy">
            <el-radio value="ocr">ocr</el-radio>
            <el-radio value="vlm">vlm</el-radio>
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
      <p class="sub-desc">对应 `parsing.video`。控制抽帧节奏、最大帧数，以及是否追加视觉描述。</p>

      <el-form :model="configForm" label-width="120px" class="config-form">
        <el-form-item label="抽帧间隔">
          <el-slider v-model="configForm.videoFrameInterval" :min="1" :max="60" show-input :show-input-controls="false" />
        </el-form-item>
        <el-form-item label="最大帧数">
          <el-input-number v-model="configForm.videoMaxFrames" :min="1" :max="200" style="width: 100%" />
        </el-form-item>
        <el-form-item label="视觉描述">
          <el-switch v-model="configForm.videoVlmDescriptionEnabled" />
        </el-form-item>
        <el-form-item v-if="configForm.videoVlmDescriptionEnabled" label="VLM 模型">
          <el-select v-model="configForm.videoVlmModel" clearable filterable placeholder="留空时继承空间默认模型" style="width: 100%">
            <el-option v-for="model in vlmModels" :key="model.model" :label="model.model" :value="model.model" />
          </el-select>
        </el-form-item>
      </el-form>
    </div>

    <div v-if="hasAudio" class="sub-section">
      <h4 class="sub-title">音频解析</h4>
      <p class="sub-desc">对应 `parsing.audio`。ASR 模型与语言参数互不冲突，空值时回退默认配置。</p>

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
import type { ImageStrategy } from './kbConfig'

type MultimodalParsingFormModel = {
  imageStrategy: ImageStrategy
  imageVlmModel: string
  videoFrameInterval: number
  videoMaxFrames: number
  videoVlmDescriptionEnabled: boolean
  videoVlmModel: string
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
  border-color: rgba(99, 102, 241, 0.35);
  background: var(--color-primary-subtle);
}
</style>
