<template>
  <div class="sub-section">
    <div class="section-head">
      <div>
        <h4 class="sub-title">问题生成参数</h4>
        <p class="sub-desc">
          保存到后端 `question_generation`。关闭后仅保留开关状态，开启时才会提交问题数量和提示词。
        </p>
      </div>
      <el-switch v-model="configForm.qgEnabled" />
    </div>

    <fieldset :disabled="!configForm.qgEnabled" class="qg-fieldset">
      <el-form :model="configForm" label-width="140px" class="config-form">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="LLM 模型">
              <el-select v-model="configForm.qgLlmModel" clearable filterable placeholder="留空时继承空间默认模型" style="width: 100%">
                <el-option v-for="model in llmModels" :key="model.model" :label="model.model" :value="model.model" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="每个分块问题数">
              <el-input-number v-model="configForm.qgMaxQuestions" :min="1" :max="20" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item label="temperature">
              <el-input-number v-model="configForm.qgLlmTemperature" :min="0" :max="2" :step="0.1" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="top_p">
              <el-input-number v-model="configForm.qgLlmTopP" :min="0" :max="1" :step="0.1" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="max_tokens">
              <el-input-number v-model="configForm.qgLlmMaxTokens" :min="100" :max="8192" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="Prompt 模板">
          <el-input
            v-model="configForm.qgPromptTemplate"
            type="textarea"
            :rows="5"
            maxlength="4000"
            placeholder="可选，自定义问题生成提示词模板"
          />
        </el-form-item>
      </el-form>
    </fieldset>
  </div>
</template>

<script setup lang="ts">
import type { AvailableModelItem } from '@/api/types'

type QuestionGenerationFormModel = {
  qgEnabled: boolean
  qgLlmModel: string
  qgLlmTemperature: number
  qgLlmTopP: number
  qgLlmMaxTokens: number
  qgMaxQuestions: number
  qgPromptTemplate: string
}

defineProps<{
  configForm: QuestionGenerationFormModel
  llmModels: AvailableModelItem[]
}>()
</script>

<style scoped>
.sub-section {
  padding: 22px;
  border: 1px solid var(--color-border-light);
  border-radius: 20px;
  background: linear-gradient(180deg, #fff, rgba(250, 249, 255, 0.96));
  box-shadow: var(--shadow-sm);
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.sub-title {
  margin: 0 0 6px;
  font-size: var(--text-lg);
}

.sub-desc {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
}

.qg-fieldset {
  border: 1px solid rgba(99, 102, 241, 0.12);
  border-radius: 18px;
  padding: 18px;
  background: rgba(255, 255, 255, 0.92);
}

.qg-fieldset[disabled] {
  opacity: 0.55;
}

:deep(.el-textarea__inner) {
  line-height: 1.7;
  border-radius: 14px;
}

@media (max-width: 768px) {
  .section-head {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
