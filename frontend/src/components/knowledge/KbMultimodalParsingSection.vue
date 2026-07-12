<template>
  <div>
    <div v-if="hasImage" class="sub-section">
      <h4 class="sub-title">图片解析</h4>
      <p class="sub-desc">OCR 与 VLM 二选一；只有在 VLM 策略下才需要选择 VLM 模型。</p>

      <el-form :model="configForm" label-width="120px" class="config-form">
        <el-form-item label="解析策略">
          <el-radio-group v-model="configForm.imageStrategy">
            <el-radio value="ocr">ocr</el-radio>
            <el-radio value="vlm">vlm</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="configForm.imageStrategy === 'vlm'" label="VLM 模型">
          <el-select v-model="configForm.imageVlmModel" clearable filterable placeholder="系统默认" style="width: 100%">
            <el-option v-for="model in vlmModels" :key="model.model" :label="model.model" :value="model.model" />
          </el-select>
        </el-form-item>
      </el-form>
    </div>

    <div v-if="hasVideo" class="sub-section">
      <h4 class="sub-title">视频解析</h4>
      <p class="sub-desc">控制抽帧频率、最大抽帧数量，以及是否启用视觉描述。</p>

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
          <el-select v-model="configForm.videoVlmModel" clearable filterable placeholder="系统默认" style="width: 100%">
            <el-option v-for="model in vlmModels" :key="model.model" :label="model.model" :value="model.model" />
          </el-select>
        </el-form-item>
      </el-form>
    </div>

    <div v-if="hasAudio" class="sub-section">
      <h4 class="sub-title">音频解析</h4>
      <p class="sub-desc">ASR 模型和语言配置可以同时设置，两者并不冲突。</p>

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
:deep(.el-radio-group) {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

:deep(.el-radio) {
  margin-right: 0;
  padding: 10px 14px;
  border: 1px solid rgba(31, 41, 55, 0.08);
  border-radius: 999px;
  background: #fff;
}

:deep(.el-radio.is-checked) {
  border-color: rgba(177, 77, 34, 0.38);
  background: rgba(177, 77, 34, 0.08);
}
</style>
