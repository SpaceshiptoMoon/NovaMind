<template>
  <div>
    <div class="sub-section">
      <h4 class="sub-title">文本切分</h4>

      <el-form :model="configForm" label-width="120px" class="config-form">
        <el-form-item label="切分策略">
          <el-select v-model="configForm.splittingStrategy" style="width: 100%">
            <el-option label="recursive" value="recursive" />
            <el-option label="fixed_size" value="fixed_size" />
            <el-option label="markdown" value="markdown" />
            <el-option label="semantic" value="semantic" />
          </el-select>
        </el-form-item>

        <template v-if="configForm.splittingStrategy === 'recursive' || configForm.splittingStrategy === 'fixed_size'">
          <el-row :gutter="24">
            <el-col :span="12">
              <el-form-item label="chunk_size">
                <el-input-number v-model="configForm.splittingChunkSize" :min="100" :max="4000" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="chunk_overlap">
                <el-input-number v-model="configForm.splittingChunkOverlap" :min="0" :max="500" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <el-form-item v-if="configForm.splittingStrategy === 'recursive'" label="min_chunk_size">
          <el-input-number v-model="configForm.splittingMinChunkSize" :min="0" :max="2000" style="width: 260px" />
        </el-form-item>

        <template v-if="configForm.splittingStrategy === 'markdown'">
          <el-row :gutter="24">
            <el-col :span="12">
              <el-form-item label="max_chunk_size">
                <el-input-number v-model="configForm.splittingMaxChunkSize" :min="100" :max="8000" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="min_chunk_size">
                <el-input-number v-model="configForm.splittingMinChunkSize" :min="0" :max="2000" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <template v-if="configForm.splittingStrategy === 'semantic'">
          <el-row :gutter="24">
            <el-col :span="12">
              <el-form-item label="max_chunk_size">
                <el-input-number v-model="configForm.splittingMaxChunkSize" :min="100" :max="8000" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="batch_size">
                <el-input-number v-model="configForm.splittingBatchSize" :min="1" :max="100" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="similarity_threshold">
            <el-slider
              v-model="configForm.splittingSimilarityThreshold"
              :min="0"
              :max="1"
              :step="0.05"
              show-input
              :show-input-controls="false"
              style="max-width: 480px"
            />
          </el-form-item>
        </template>
      </el-form>
    </div>

    <div v-if="hasAudio" class="sub-section">
      <h4 class="sub-title">音频切分</h4>

      <el-form :model="configForm" label-width="120px" class="config-form">
        <el-form-item label="切分策略">
          <el-radio-group v-model="configForm.audioChunkStrategy">
            <el-radio value="sentence">sentence</el-radio>
            <el-radio value="fixed">fixed</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="configForm.audioChunkStrategy === 'fixed'" label="chunk_size">
          <el-input-number v-model="configForm.audioChunkSize" :min="100" :max="4000" style="width: 100%" />
        </el-form-item>
      </el-form>
    </div>

    <div v-if="hasVideo" class="sub-section">
      <h4 class="sub-title">视频切分</h4>

      <el-form :model="configForm" label-width="120px" class="config-form">
        <el-form-item label="chunk_size">
          <el-input-number v-model="configForm.videoChunkSize" :min="100" :max="4000" style="width: 100%" />
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { AudioChunkStrategy } from './kbConfig'

type SplittingFormModel = {
  splittingStrategy: string
  splittingChunkSize: number
  splittingChunkOverlap: number
  splittingMinChunkSize: number
  splittingMaxChunkSize: number
  splittingSimilarityThreshold: number
  splittingBatchSize: number
  audioChunkStrategy: AudioChunkStrategy
  audioChunkSize: number
  videoChunkSize: number
}

defineProps<{
  configForm: SplittingFormModel
  hasAudio: boolean
  hasVideo: boolean
}>()
</script>
