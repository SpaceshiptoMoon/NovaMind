<template>
  <div class="sub-section">
    <div class="section-head">
      <div>
        <h4 class="sub-title">Wiki 自动生成</h4>
        <p class="sub-desc">
          开启后，文档解析完成时由 LLM 自动整理出互相链接的实体页、概念页与摘要页，
          在知识库「Wiki」页签浏览。生成会增加模型调用。
        </p>
      </div>
      <el-switch v-model="configForm.wikiEnabled" />
    </div>

    <fieldset :disabled="!configForm.wikiEnabled" class="wiki-fieldset">
      <el-form :model="configForm" label-width="140px" class="config-form">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="LLM 模型">
              <el-select
                v-model="configForm.wikiLlmModel"
                clearable
                filterable
                placeholder="留空时使用知识库默认模型"
                style="width: 100%"
              >
                <el-option
                  v-for="model in llmModels"
                  :key="model.model"
                  :label="model.model"
                  :value="model.model"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="抽取粒度">
              <el-select v-model="configForm.wikiGranularity" style="width: 100%">
                <el-option
                  v-for="item in wikiGranularityItems"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                >
                  <span>{{ item.label }}</span>
                  <small class="granularity-desc">{{ item.desc }}</small>
                </el-option>
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="单文档页数上限">
              <el-input-number
                v-model="configForm.wikiMaxPages"
                :min="1"
                :max="500"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="内容风格指令">
          <el-input
            v-model="configForm.wikiContentInstructions"
            type="textarea"
            :rows="3"
            maxlength="2000"
            placeholder="可选。控制页面语气、结构与侧重点，例如「面向新员工，多用列表」"
          />
        </el-form-item>

        <el-form-item label="抽取侧重指令">
          <el-input
            v-model="configForm.wikiExtractionInstructions"
            type="textarea"
            :rows="3"
            maxlength="2000"
            placeholder="可选。控制实体/概念抽取侧重，例如「重点提取产品名称与技术架构」"
          />
        </el-form-item>
      </el-form>
    </fieldset>
  </div>
</template>

<script setup lang="ts">
import type { AvailableModelItem } from '@/api/types'
import { wikiGranularityItems } from './kbConfig'

type WikiFormModel = {
  wikiEnabled: boolean
  wikiLlmModel: string
  wikiGranularity: 'focused' | 'standard' | 'exhaustive'
  wikiMaxPages: number
  wikiContentInstructions: string
  wikiExtractionInstructions: string
}

defineProps<{
  configForm: WikiFormModel
  llmModels: AvailableModelItem[]
}>()
</script>

<style scoped>
.sub-section {
  padding: 22px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card-elevated);
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

.wiki-fieldset {
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-2xl);
  padding: 18px;
  background: var(--color-bg-card);
}

.wiki-fieldset[disabled] {
  opacity: 0.55;
}

.granularity-desc {
  margin-left: 8px;
  color: var(--color-text-muted);
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
