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
            <el-option label="分隔符" value="delimiter" />
            <el-option label="句子窗口" value="sentence_window" />
            <el-option label="父子分块" value="parent_child" />
          </el-select>
        </el-form-item>

        <div class="strategy-tip">
          <strong>{{ strategyTitle }}</strong>
          <span>{{ strategyDesc }}</span>
        </div>

        <template
          v-if="
            configForm.splittingStrategy === 'recursive' ||
            configForm.splittingStrategy === 'fixed_size' ||
            configForm.splittingStrategy === 'delimiter' ||
            configForm.splittingStrategy === 'parent_child'
          "
        >
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="分块大小">
                <el-input-number
                  v-model="configForm.splittingChunkSize"
                  :min="100"
                  :max="4000"
                  style="width: 100%"
                />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="分块重叠">
                <el-input-number
                  v-model="configForm.splittingChunkOverlap"
                  :min="0"
                  :max="500"
                  style="width: 100%"
                />
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <el-form-item
          v-if="configForm.splittingStrategy === 'parent_child'"
          label="父块大小"
        >
          <el-input-number
            v-model="configForm.splittingParentChunkSize"
            :min="100"
            :max="8000"
            style="width: 260px"
          />
          <div class="field-hint">
            须 ≥ 分块大小；父块只作召回后回带的上下文容器，不参与检索召回，也不做向量化。
          </div>
        </el-form-item>

        <el-form-item
          v-if="configForm.splittingStrategy === 'sentence_window'"
          label="窗口句数（每侧）"
        >
          <el-input-number
            v-model="configForm.splittingWindowSize"
            :min="0"
            :max="10"
            style="width: 260px"
          />
          <div class="field-hint">
            召回命中句后向前/向后各扩展 N 句拼成上下文；0 表示不扩窗。每句一个分块，分块数量与向量化成本随句数增长。
          </div>
        </el-form-item>

        <el-form-item
          v-if="
            configForm.splittingStrategy === 'recursive' ||
            configForm.splittingStrategy === 'delimiter'
          "
          label="最小分块大小"
        >
          <el-input-number
            v-model="configForm.splittingMinChunkSize"
            :min="0"
            :max="2000"
            style="width: 260px"
          />
        </el-form-item>

        <template v-if="configForm.splittingStrategy === 'delimiter'">
          <el-form-item label="分隔符">
            <el-select
              v-model="separatorDisplay"
              multiple
              filterable
              allow-create
              default-first-option
              :reserve-keyword="false"
              placeholder="未选择时默认按空行切分；可键入自定义（\n 表示换行）"
              style="width: 100%"
            >
              <el-option
                v-for="opt in SEPARATOR_PRESETS"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
            <div class="field-hint">
              分隔符只作切分边界，不保留在分块中；多个分隔符同时生效（按序级联）。
            </div>
          </el-form-item>
        </template>

        <template v-if="configForm.splittingStrategy === 'markdown'">
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="最大分块大小">
                <el-input-number
                  v-model="configForm.splittingMaxChunkSize"
                  :min="100"
                  :max="8000"
                  style="width: 100%"
                />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="最小分块大小">
                <el-input-number
                  v-model="configForm.splittingMinChunkSize"
                  :min="0"
                  :max="2000"
                  style="width: 100%"
                />
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <template v-if="configForm.splittingStrategy === 'semantic'">
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="最大分块大小">
                <el-input-number
                  v-model="configForm.splittingMaxChunkSize"
                  :min="100"
                  :max="8000"
                  style="width: 100%"
                />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="批次大小">
                <el-input-number
                  v-model="configForm.splittingBatchSize"
                  :min="1"
                  :max="100"
                  style="width: 100%"
                />
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
  </div>
</template>

<script setup lang="ts">
/** 知识库配置弹窗的文本切分分区：按所选切分策略只展示真正生效的参数 */
import { computed } from 'vue'

type SplittingFormModel = {
  splittingStrategy: string
  splittingChunkSize: number
  splittingChunkOverlap: number
  splittingMinChunkSize: number
  splittingMaxChunkSize: number
  splittingSimilarityThreshold: number
  splittingBatchSize: number
  splittingSeparators: string[]
  splittingWindowSize: number
  splittingParentChunkSize: number
}

const props = defineProps<{
  configForm: SplittingFormModel
}>()

/** 分隔符预设项：label 供人读，value 是提交给后端的真实分隔符串。 */
const SEPARATOR_PRESETS: Array<{ label: string; value: string }> = [
  { label: '空行（默认）', value: '\n\n' },
  { label: '换行', value: '\n' },
  { label: '空行 + 分隔线', value: '\n\n---\n\n' },
  { label: 'Markdown 一级标题', value: '\n# ' },
  { label: 'Markdown 二级标题', value: '\n## ' },
  { label: '水平线 ----', value: '----' },
  { label: '竖线 |', value: '|' },
]

/** 控制字符 → 可见转义文本（用于 tag 展示与 allow-create 输入翻译）。 */
function escapeSeparator(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/\t/g, '\\t')
}

/** 转义文本 → 真实分隔符（\n → 换行、\t → 制表符；其余按字面量）。 */
function unescapeSeparator(text: string): string {
  return text.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
}

/**
 * 多选框的显示值层：真实分隔符串 → 转义文本。
 * 预设项命中时 tag 显示人读 label；自定义项显示转义后的可见文本
 * （真实换行直接进 tag 会渲染成空白，无法辨识）。
 */
const separatorDisplay = computed({
  get: () =>
    props.configForm.splittingSeparators.map((value) => {
      const preset = SEPARATOR_PRESETS.find((opt) => opt.value === value)
      return preset ? preset.label : escapeSeparator(value)
    }),
  set: (displayValues: string[]) => {
    props.configForm.splittingSeparators = displayValues.map((display) => {
      const preset = SEPARATOR_PRESETS.find((opt) => opt.label === display)
      if (preset) return preset.value
      const existed = props.configForm.splittingSeparators.find(
        (value) => escapeSeparator(value) === display,
      )
      if (existed !== undefined) return existed
      return unescapeSeparator(display)
    })
  },
})

const strategyTitle = computed(() => {
  const labels: Record<string, string> = {
    recursive: '递归切分',
    fixed_size: '固定长度切分',
    markdown: 'Markdown 结构切分',
    semantic: '语义切分',
    delimiter: '分隔符切分',
    sentence_window: '句子窗口切分',
    parent_child: '父子分块',
  }
  return labels[props.configForm.splittingStrategy] || '文本切分'
})

const strategyDesc = computed(() => {
  const descriptions: Record<string, string> = {
    recursive: '使用分块大小、分块重叠、最小分块大小进行层级文本切分。',
    fixed_size: '使用固定长度窗口切分，仅依赖分块大小与分块重叠。',
    markdown: '按 Markdown 层级切分，主要使用最大分块大小与最小分块大小。',
    semantic: '基于语义相似度切分，依赖最大分块大小、批次大小、相似度阈值。',
    delimiter:
      '按自定义分隔符切段，分隔符不保留；超长段按分块大小+重叠硬切，碎段按最小分块大小合并。',
    sentence_window:
      '每句一个检索单元，召回精度高；检索命中后自动带上下句拼窗口。分块数量随句数增长，向量化成本较高。',
    parent_child:
      '小块（分块大小）参与检索召回，命中后自动回带所属大块（父块大小）全文作上下文；父块间不重叠、不做向量化。',
  }
  return descriptions[props.configForm.splittingStrategy] || ''
})
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

.strategy-tip {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 18px;
  padding: 14px 16px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  background: var(--color-info-subtle);
}

.strategy-tip strong {
  font-size: var(--text-sm);
}

.strategy-tip span {
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
}

.field-hint {
  margin-top: 4px;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  line-height: var(--leading-relaxed);
}
</style>
