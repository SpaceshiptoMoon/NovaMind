<template>
  <div class="sub-section">
    <h4 class="sub-title">文本解析</h4>
    <p class="sub-desc">文本按文件类型配置策略。PDF 支持额外的 parser 和 OCR。</p>

    <el-form :model="configForm" label-width="120px" class="config-form">
      <el-row :gutter="24">
        <el-col :span="12">
          <el-form-item label="PDF 策略">
            <el-select v-model="configForm.pdfStrategy" style="width: 100%">
              <el-option label="default" value="default" />
              <el-option label="deepdoc" value="deepdoc" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col v-if="configForm.pdfStrategy === 'deepdoc'" :span="12">
          <el-form-item label="PDF Parser">
            <el-select v-model="configForm.deepdocParser" filterable style="width: 100%">
              <el-option
                v-for="option in deepdocParserOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="PDF OCR">
            <el-switch v-model="configForm.pdfOcrEnabled" />
          </el-form-item>
        </el-col>
      </el-row>

      <div class="text-strategy-grid">
        <div v-for="item in textStrategyItems" :key="item.key" class="text-strategy-item">
          <span class="text-strategy-label">{{ item.label }}</span>
          <el-select v-model="configForm[item.key]" style="width: 180px">
            <el-option label="default" value="default" />
            <el-option label="deepdoc" value="deepdoc" />
          </el-select>
        </div>
      </div>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { deepdocParserOptions, textStrategyItems } from './kbConfig'
import type { PdfParserName } from '@/api/types'
import type { TextStrategy } from './kbConfig'

type TextParsingFormModel = {
  pdfStrategy: TextStrategy
  deepdocParser: PdfParserName
  pdfOcrEnabled: boolean
  docxStrategy: TextStrategy
  excelStrategy: TextStrategy
  pptStrategy: TextStrategy
  epubStrategy: TextStrategy
  markdownStrategy: TextStrategy
  htmlStrategy: TextStrategy
  txtStrategy: TextStrategy
  jsonStrategy: TextStrategy
}

defineProps<{
  configForm: TextParsingFormModel
}>()
</script>
