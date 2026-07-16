<template>
  <div class="sub-section">
    <h4 class="sub-title">文本解析</h4>
    <p class="sub-desc">按文件类型设置解析策略。PDF 额外支持 parser 与 OCR，其他文本类型仅支持 `default / deepdoc`。</p>

    <el-form :model="configForm" label-width="120px" class="config-form">
      <div class="pdf-panel">
        <div class="panel-title">PDF 专属参数</div>
        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item label="解析策略">
              <el-select v-model="configForm.pdfStrategy" style="width: 100%">
                <el-option label="default" value="default" />
                <el-option label="deepdoc" value="deepdoc" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col v-if="configForm.pdfStrategy === 'deepdoc'" :span="8">
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
          <el-col :span="8">
            <el-form-item label="启用 OCR">
              <el-switch v-model="configForm.pdfOcrEnabled" />
            </el-form-item>
          </el-col>
        </el-row>
      </div>

      <div class="text-strategy-grid">
        <div v-for="item in textStrategyItems" :key="item.key" class="text-strategy-item">
          <div class="text-strategy-copy">
            <span class="text-strategy-label">{{ item.label }}</span>
            <small>对应 `parsing.text.{{ item.key.replace('Strategy', '').replace('json', 'json') }}`</small>
          </div>
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

.pdf-panel {
  margin-bottom: 18px;
  padding: 18px;
  border: 1px solid rgba(99, 102, 241, 0.12);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.92);
}

.panel-title {
  margin-bottom: 14px;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
}

.text-strategy-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}

.text-strategy-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--color-border-light);
  border-radius: 16px;
  background: #fff;
}

.text-strategy-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.text-strategy-label {
  color: var(--color-text);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
}

.text-strategy-copy small {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}
</style>
