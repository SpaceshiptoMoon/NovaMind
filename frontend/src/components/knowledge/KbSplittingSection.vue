<template>
  <div>
    <div class="sub-section">
      <h4 class="sub-title">文本切分主策略</h4>
      <p class="sub-desc">对应 `splitting.strategy`。页面会根据后端规则，只展示当前策略真正生效的参数。</p>

      <el-form :model="configForm" label-width="140px" class="config-form">
        <el-form-item label="切分策略">
          <el-select v-model="configForm.splittingStrategy" style="width: 100%">
            <el-option label="recursive" value="recursive" />
            <el-option label="fixed_size" value="fixed_size" />
            <el-option label="markdown" value="markdown" />
            <el-option label="semantic" value="semantic" />
          </el-select>
        </el-form-item>

        <div class="strategy-tip">
          <strong>{{ strategyTitle }}</strong>
          <span>{{ strategyDesc }}</span>
        </div>

        <template v-if="configForm.splittingStrategy === 'recursive' || configForm.splittingStrategy === 'fixed_size'">
          <el-row :gutter="20">
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
          <el-row :gutter="20">
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
          <el-row :gutter="20">
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
              style="max-width: 520px"
            />
          </el-form-item>
        </template>
      </el-form>
    </div>

    <div v-if="hasAudio" class="sub-section">
      <h4 class="sub-title">音频切分覆盖</h4>
      <p class="sub-desc">对应 `splitting.audio`。仅覆盖音频转写文本的切分方式。</p>

      <el-form :model="configForm" label-width="140px" class="config-form">
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
      <h4 class="sub-title">视频切分覆盖</h4>
      <p class="sub-desc">对应 `splitting.video`。后端只支持固定策略，因此这里仅配置 `chunk_size`。</p>

      <el-form :model="configForm" label-width="140px" class="config-form">
        <el-form-item label="chunk_size">
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
    recursive: '使用 chunk_size、chunk_overlap、min_chunk_size 进行层级文本切分。',
    fixed_size: '使用固定长度窗口切分，仅依赖 chunk_size 与 chunk_overlap。',
    markdown: '按 Markdown 层级切分，主要使用 max_chunk_size 与 min_chunk_size。',
    semantic: '基于语义相似度切分，依赖 max_chunk_size、batch_size、similarity_threshold。',
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
