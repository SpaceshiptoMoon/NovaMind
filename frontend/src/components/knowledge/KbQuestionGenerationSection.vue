<template>
  <el-form :model="configForm" label-width="140px" class="config-form">
    <el-form-item label="启用问题生成">
      <el-switch v-model="configForm.qgEnabled" />
    </el-form-item>

    <fieldset :disabled="!configForm.qgEnabled" class="qg-fieldset">
      <el-row :gutter="24">
        <el-col :span="12">
          <el-form-item label="最大问题数">
            <el-input-number v-model="configForm.qgMaxQuestions" :min="1" :max="20" style="width: 100%" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="temperature">
            <el-input-number v-model="configForm.qgLlmTemperature" :min="0" :max="2" :step="0.1" style="width: 100%" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="24">
        <el-col :span="12">
          <el-form-item label="top_p">
            <el-input-number v-model="configForm.qgLlmTopP" :min="0" :max="1" :step="0.1" style="width: 100%" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="max_tokens">
            <el-input-number v-model="configForm.qgLlmMaxTokens" :min="100" :max="8192" style="width: 100%" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="Prompt 模板">
        <el-input
          v-model="configForm.qgPromptTemplate"
          type="textarea"
          :rows="4"
          maxlength="4000"
          placeholder="可选，自定义问题生成模板"
        />
      </el-form-item>
    </fieldset>
  </el-form>
</template>

<script setup lang="ts">
type QuestionGenerationFormModel = {
  qgEnabled: boolean
  qgLlmTemperature: number
  qgLlmTopP: number
  qgLlmMaxTokens: number
  qgMaxQuestions: number
  qgPromptTemplate: string
}

defineProps<{
  configForm: QuestionGenerationFormModel
}>()
</script>

<style scoped>
.qg-fieldset {
  border-radius: 20px;
}

:deep(.el-textarea__inner) {
  border-radius: 16px;
  line-height: 1.7;
}
</style>
