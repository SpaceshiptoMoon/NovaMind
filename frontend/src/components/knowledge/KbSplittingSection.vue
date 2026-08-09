<template>
  <div>
    <div class="sub-section">
      <h4 class="sub-title">文本切分主策略</h4>
      <p class="sub-desc">按所选切分策略只展示真正生效的参数。</p>

      <el-form :model="configForm" label-width="140px" class="config-form">
        <el-form-item label="切分策略">
          <el-select v-model="configForm.splittingStrategy" style="width: 100%">
            <el-option label="递归" value="recursive" />
            <el-option label="定长" value="fixed_size" />
            <el-option label="Markdown" value="markdown" />
            <el-option label="语义" value="semantic" />
          </el-select>
        </el-form-item>

        <div class="strategy-tip">
          <strong>{{ strategyTitle }}</strong>
          <span>{{ strategyDesc }}</span>
        </div>

        <template v-if="configForm.splittingStrategy === 'recursive' || configForm.splittingStrategy === 'fixed_size'">
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="分块大小">
                <el-input-number v-model="configForm.splittingChunkSize" :min="100" :max="4000" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="分块重叠">
                <el-input-number v-model="configForm.splittingChunkOverlap" :min="0" :max="500" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <el-form-item v-if="configForm.splittingStrategy === 'recursive'" label="最小分块大小">
          <el-input-number v-model="configForm.splittingMinChunkSize" :min="0" :max="2000" style="width: 260px" />
        </el-form-item>

        <template v-if="configForm.splittingStrategy === 'markdown'">
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="最大分块大小">
                <el-input-number v-model="configForm.splittingMaxChunkSize" :min="100" :max="8000" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="最小分块大小">
                <el-input-number v-model="configForm.splittingMinChunkSize" :min="0" :max="2000" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <template v-if="configForm.splittingStrategy === 'semantic'">
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="最大分块大小">
                <el-input-number v-model="configForm.splittingMaxChunkSize" :min="100" :max="8000" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="批次大小">
                <el-input-number v-model="configForm.splittingBatchSize" :min="1" :max="100" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="相似度阈值">
            <el-slider
              v-model="configForm.splittingSimilarityThreshold"
              :min="0"
              :max="1"
              :step="0.05"
              show-input
              :show-input-controls="false"
              style="max-width: 520px"
            />
          </el-form-item>
        </template>
      </el-form>
    </div>

    <div v-if="hasAudio" class="sub-section">
      <h4 class="sub-title">音频切分覆盖</h4>
      <p class="sub-desc">仅覆盖音频转写文本的切分方式。</p>

      <el-form :model="configForm" label-width="140px" class="config-form">
        <el-form-item label="切分策略">
          <el-radio-group v-model="configForm.audioChunkStrategy">
            <el-radio value="sentence">按句</el-radio>
            <el-radio value="fixed">定长</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="configForm.audioChunkStrategy === 'fixed'" label="分块大小">
          <el-input-number v-model="configForm.audioChunkSize" :min="100" :max="4000" style="width: 100%" />
        </el-form-item>
      </el-form>
    </div>

    <div v-if="hasVideo" class="sub-section">
      <h4 class="sub-title">视频切分覆盖</h4>
      <p class="sub-desc">视频切分仅支持定长策略，这里只配置分块大小。</p>

      <el-form :model="configForm" label-width="140px" class="config-form">
        <el-form-item label="分块大小">
          <el-input-number v-model="configForm.videoChunkSize" :min="100" :max="4000" style="width: 100%" />
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
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

const props = defineProps<{
  configForm: SplittingFormModel
  hasAudio: boolean
  hasVideo: boolean
}>()

const strategyTitle = computed(() => {
  const labels: Record<string, string> = {
    recursive: '递归切分',
    fixed_size: '固定长度切分',
    markdown: 'Markdown 结构切分',
    semantic: '语义切分',
  }
  return labels[props.configForm.splittingStrategy] || '文本切分'
})

const strategyDesc = computed(() => {
  const descriptions: Record<string, string> = {
    recursive: '使用分块大小、分块重叠、最小分块大小进行层级文本切分。',
    fixed_size: '使用固定长度窗口切分，仅依赖分块大小与分块重叠。',
    markdown: '按 Markdown 层级切分，主要使用最大分块大小与最小分块大小。',
    semantic: '基于语义相似度切分，依赖最大分块大小、批次大小、相似度阈值。',
  }
  return descriptions[props.configForm.splittingStrategy] || ''
})
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

.strategy-tip {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 18px;
  padding: 14px 16px;
  border: 1px solid rgba(99, 102, 241, 0.12);
  border-radius: 16px;
  background: rgba(238, 242, 255, 0.5);
}

.strategy-tip strong {
  font-size: var(--text-sm);
}

.strategy-tip span {
  color: var(--color-text-secondary);
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
