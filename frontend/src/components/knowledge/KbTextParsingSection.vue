<template>
  <div class="sub-section">
    <h4 class="sub-title">文本解析</h4>
    <p class="sub-desc">
      按文件类型设置解析策略：默认或 DeepDoc。扫描件等图片型 PDF 请选 DeepDoc；Excel、PPT、EPUB
      仅支持 DeepDoc。
    </p>

    <el-form :model="configForm" label-width="120px" class="config-form">
      <div class="pdf-panel">
        <div class="panel-title">PDF 专属参数</div>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="解析策略">
              <el-select v-model="configForm.pdfStrategy" style="width: 100%">
                <el-option label="默认" value="default" />
                <el-option label="DeepDoc" value="deepdoc" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
      </div>

      <div class="text-strategy-grid">
        <div v-for="item in textStrategyItems" :key="item.key" class="text-strategy-item">
          <div class="text-strategy-copy">
            <span class="text-strategy-label">{{ item.label }}</span>
          </div>
          <!-- deepdocOnly 类型仅 DeepDoc 一个合法选项（后端 Literal["deepdoc"]），不显示「默认」 -->
          <el-select v-model="configForm[item.key]" style="width: 180px">
            <el-option v-if="!item.deepdocOnly" label="默认" value="default" />
            <el-option label="DeepDoc" value="deepdoc" />
          </el-select>
        </div>
      </div>
    </el-form>
  </div>
</template>

<script setup lang="ts">
/** 知识库配置弹窗的文本解析分区：PDF 专属解析策略 + 各文本类型解析策略 */
import { textStrategyItems } from './kbConfig'
import type { TextStrategy } from './kbConfig'

type TextParsingFormModel = {
  pdfStrategy: TextStrategy
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
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card-elevated);
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

.field-hint {
  margin-top: 4px;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
}

.pdf-panel {
  margin-bottom: 18px;
  padding: 18px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  background: var(--color-bg-card);
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
  background: var(--color-bg-card);
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
