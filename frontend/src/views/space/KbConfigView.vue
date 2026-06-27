<template>
  <div class="kb-config-page">
    <PageHeader title="知识库配置" show-back :back-to="goListPath">
      <template #title-suffix>
        <span v-if="kbName" class="kb-name-tag">· {{ kbName }}</span>
      </template>
    </PageHeader>

    <el-card v-loading="loading" shadow="never" class="config-card">
      <el-steps :active="currentStep" finish-status="success" align-center class="steps-bar">
        <el-step
          v-for="(s, i) in steps"
          :key="s.title"
          :title="s.title"
          :class="{ clickable: i <= maxReachedStep }"
          @click="goToStep(i)"
        />
      </el-steps>

      <!-- 第 1 步：解析策略 -->
      <section v-show="currentStep === 0" class="step-section">
        <h3 class="step-title">解析策略</h3>
        <p class="step-desc">配置文档解析时的图片、表格、OCR 与编码提取行为。</p>
        <el-form ref="parsingFormRef" :model="configForm" :rules="parsingRules" label-width="110px">
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="提取图片">
                <el-switch v-model="configForm.parsingExtractImages" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="提取表格">
                <el-switch v-model="configForm.parsingExtractTables" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="启用 OCR">
                <el-switch v-model="configForm.parsingOcrEnabled" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="保留结构">
                <el-switch v-model="configForm.parsingPreserveStructure" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="文件编码" prop="parsingEncoding">
            <el-input v-model="configForm.parsingEncoding" placeholder="utf-8" style="max-width: 320px" />
          </el-form-item>
        </el-form>
      </section>

      <!-- 第 2 步：分块策略 -->
      <section v-show="currentStep === 1" class="step-section">
        <h3 class="step-title">分块策略</h3>
        <p class="step-desc">配置文档切分方式与分块参数。</p>
        <el-form ref="splittingFormRef" :model="configForm" :rules="splittingRules" label-width="110px">
          <el-form-item label="切分策略" prop="splittingStrategy">
            <el-select v-model="configForm.splittingStrategy" style="width: 100%">
              <el-option label="递归字符切分" value="recursive">
                <span>递归字符切分</span>
                <span style="float: right; color: var(--el-text-color-secondary); font-size: 12px">
                  按段落 → 句号 → 换行 → 空格逐级切分
                </span>
              </el-option>
              <el-option label="固定大小切分" value="fixed_size">
                <span>固定大小切分</span>
                <span style="float: right; color: var(--el-text-color-secondary); font-size: 12px">
                  按固定字符数截断
                </span>
              </el-option>
              <el-option label="Markdown 结构切分" value="markdown">
                <span>Markdown 结构切分</span>
                <span style="float: right; color: var(--el-text-color-secondary); font-size: 12px">
                  按 # ~ ###### 标题层级切分
                </span>
              </el-option>
              <el-option label="语义切分" value="semantic">
                <span>语义切分</span>
                <span style="float: right; color: var(--el-text-color-secondary); font-size: 12px">
                  基于向量相似度识别语义边界
                </span>
              </el-option>
            </el-select>
          </el-form-item>

          <!-- recursive / fixed_size 公共字段 -->
          <template v-if="configForm.splittingStrategy === 'recursive' || configForm.splittingStrategy === 'fixed_size'">
            <el-form-item label="分块大小">
              <el-input-number
                v-model="configForm.splittingChunkSize"
                :min="500"
                :max="4000"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="重叠字符数">
              <el-input-number
                v-model="configForm.splittingChunkOverlap"
                :min="0"
                :max="500"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="最小分块大小">
              <el-input-number
                v-model="configForm.splittingMinChunkSize"
                :min="0"
                :max="2000"
                style="width: 100%"
              />
            </el-form-item>
          </template>

          <!-- markdown -->
          <template v-if="configForm.splittingStrategy === 'markdown'">
            <el-form-item label="最大分块大小">
              <el-input-number
                v-model="configForm.splittingMaxChunkSize"
                :min="100"
                :max="8000"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="最小分块大小">
              <el-input-number
                v-model="configForm.splittingMinChunkSize"
                :min="10"
                :max="1000"
                style="width: 100%"
              />
            </el-form-item>
          </template>

          <!-- semantic -->
          <template v-if="configForm.splittingStrategy === 'semantic'">
            <el-form-item label="最大分块大小">
              <el-input-number
                v-model="configForm.splittingMaxChunkSize"
                :min="100"
                :max="8000"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="相似度阈值">
              <el-slider
                v-model="configForm.splittingSimilarityThreshold"
                :min="0"
                :max="1"
                :step="0.05"
                show-input
                :show-input-controls="false"
              />
            </el-form-item>
            <el-form-item label="批处理大小">
              <el-input-number
                v-model="configForm.splittingBatchSize"
                :min="1"
                :max="100"
                style="width: 100%"
              />
            </el-form-item>
          </template>
        </el-form>
      </section>

      <!-- 第 3 步：生成策略 -->
      <section v-show="currentStep === 2" class="step-section">
        <h3 class="step-title">生成策略</h3>
        <p class="step-desc">为每个分块生成假设性问题（HyDE），用于问题检索模式。可关闭。</p>
        <el-form ref="generationFormRef" :model="configForm" :rules="generationRules" label-width="110px">
          <el-form-item label="启用问题生成">
            <el-switch v-model="configForm.qgEnabled" />
          </el-form-item>
          <fieldset :disabled="!configForm.qgEnabled" class="qg-fieldset">
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="LLM 模型">
                  <el-select v-model="configForm.qgLlmModel" placeholder="用户默认" clearable style="width: 100%">
                    <el-option
                      v-for="m in llmModels"
                      :key="m.model"
                      :label="m.model"
                      :value="m.model"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="通信协议">
                  <el-select v-model="configForm.qgLlmProtocol" placeholder="用户默认" clearable style="width: 100%">
                    <el-option
                      v-for="p in llmProtocols"
                      :key="p"
                      :label="p"
                      :value="p"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="8">
                <el-form-item label="温度">
                  <el-input-number
                    v-model="configForm.qgLlmTemperature"
                    :min="0"
                    :max="2"
                    :step="0.1"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="Top P">
                  <el-input-number
                    v-model="configForm.qgLlmTopP"
                    :min="0"
                    :max="1"
                    :step="0.1"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="最大 Tokens">
                  <el-input-number
                    v-model="configForm.qgLlmMaxTokens"
                    :min="100"
                    :max="8192"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="每块最大问题数">
              <el-input-number
                v-model="configForm.qgMaxQuestions"
                :min="1"
                :max="20"
              />
            </el-form-item>
            <el-form-item label="提示词模板">
              <el-input
                v-model="configForm.qgPromptTemplate"
                type="textarea"
                :rows="3"
                placeholder="自定义提示词模板（可选）"
                maxlength="4000"
              />
            </el-form-item>
          </fieldset>
        </el-form>
      </section>

      <div class="config-footer">
        <el-button v-if="currentStep > 0" @click="prev">上一步</el-button>
        <div class="footer-spacer" />
        <el-button @click="goList">取消</el-button>
        <el-button v-if="currentStep < steps.length - 1" type="primary" @click="next">
          下一步
        </el-button>
        <el-button v-else type="primary" :loading="saving" @click="onSave">
          保存配置
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, nextTick, onMounted } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import PageHeader from '@/components/common/PageHeader.vue'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import { userApi } from '@/api/user'
import type { SplittingConfig, AvailableModelItem } from '@/api/types'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))
const kbId = computed(() => Number(route.params.kbId))
const goListPath = computed(() => `/home/spaces/${spaceId.value}/knowledge-bases`)

const steps = [
  { title: '解析策略' },
  { title: '分块策略' },
  { title: '生成策略' },
] as const

const currentStep = ref(0)
const maxReachedStep = ref(0)
const loading = ref(false)
const saving = ref(false)
const kbName = ref('')

const parsingFormRef = ref<FormInstance>()
const splittingFormRef = ref<FormInstance>()
const generationFormRef = ref<FormInstance>()

const configForm = reactive({
  splittingStrategy: 'recursive' as string,
  splittingChunkSize: 2000,
  splittingChunkOverlap: 100,
  splittingMaxChunkSize: 2000,
  splittingMinChunkSize: 500,
  splittingSimilarityThreshold: 0.7,
  splittingBatchSize: 20,
  parsingExtractImages: false,
  parsingExtractTables: true,
  parsingOcrEnabled: false,
  parsingPreserveStructure: true,
  parsingEncoding: 'utf-8',
  qgEnabled: false,
  qgLlmModel: '',
  qgLlmProtocol: '',
  qgLlmTemperature: 0.3,
  qgLlmTopP: 0.9,
  qgLlmMaxTokens: 2048,
  qgMaxQuestions: 5,
  qgPromptTemplate: '',
})

const parsingRules: FormRules = {
  parsingEncoding: [{ required: true, message: '请输入文件编码', trigger: 'blur' }],
}

const splittingRules: FormRules = {
  splittingStrategy: [{ required: true, message: '请选择切分策略', trigger: 'change' }],
}

const generationRules: FormRules = {}

const llmModels = ref<AvailableModelItem[]>([])
const llmProtocols = ref<string[]>([])

// === 未保存离开提示 ===
const dirty = ref(false)
const saved = ref(false)
watch(configForm, () => {
  dirty.value = true
}, { deep: true })

async function fetchAvailableModels() {
  try {
    const data = await userApi.getAvailableModelDetails()
    llmModels.value = data.llm || []
    llmProtocols.value = [...new Set((data.llm || []).map((m) => m.protocol).filter(Boolean))]
  } catch {
    // ignore
  }
}

async function onLoad() {
  loading.value = true
  try {
    const [data] = await Promise.all([
      knowledgeBaseApi.getConfig(spaceId.value, kbId.value),
      fetchAvailableModels(),
    ])
    kbName.value = data.name
    const cfg = data.config

    const sp = cfg?.splitting
    configForm.splittingStrategy = sp?.strategy || 'recursive'
    configForm.splittingChunkSize = (sp as { chunk_size?: number })?.chunk_size ?? 1000
    configForm.splittingChunkOverlap = (sp as { chunk_overlap?: number })?.chunk_overlap ?? 100
    configForm.splittingMaxChunkSize = (sp as { max_chunk_size?: number })?.max_chunk_size ?? 2000
    configForm.splittingMinChunkSize = (sp as { min_chunk_size?: number })?.min_chunk_size ?? 100
    configForm.splittingSimilarityThreshold = (sp as { similarity_threshold?: number })?.similarity_threshold ?? 0.7
    configForm.splittingBatchSize = (sp as { batch_size?: number })?.batch_size ?? 20

    const ps = cfg?.parsing
    configForm.parsingExtractImages = ps?.extract_images ?? false
    configForm.parsingExtractTables = ps?.extract_tables ?? true
    configForm.parsingOcrEnabled = ps?.ocr_enabled ?? false
    configForm.parsingPreserveStructure = ps?.preserve_structure ?? true
    configForm.parsingEncoding = ps?.encoding || 'utf-8'

    const qg = cfg?.question_generation
    configForm.qgEnabled = qg?.enabled ?? false
    configForm.qgLlmModel = qg?.llm?.model || ''
    configForm.qgLlmProtocol = qg?.llm?.protocol || ''
    configForm.qgLlmTemperature = qg?.llm?.temperature ?? 0.3
    configForm.qgLlmTopP = qg?.llm?.top_p ?? 0.9
    configForm.qgLlmMaxTokens = qg?.llm?.max_tokens ?? 2048
    configForm.qgMaxQuestions = qg?.max_questions_per_chunk ?? 5
    configForm.qgPromptTemplate = qg?.prompt_template || ''

    // 回填会触发 watch 置 dirty，此处重置
    await nextTick()
    dirty.value = false
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '获取配置失败')
    router.replace(goListPath.value)
  } finally {
    loading.value = false
  }
}

function buildSplittingConfig(): SplittingConfig {
  const s = configForm.splittingStrategy
  if (s === 'recursive') {
    return { strategy: 'recursive', chunk_size: configForm.splittingChunkSize, chunk_overlap: configForm.splittingChunkOverlap }
  }
  if (s === 'fixed_size') {
    return { strategy: 'fixed_size', chunk_size: configForm.splittingChunkSize, chunk_overlap: configForm.splittingChunkOverlap }
  }
  if (s === 'markdown') {
    return { strategy: 'markdown', max_chunk_size: configForm.splittingMaxChunkSize, min_chunk_size: configForm.splittingMinChunkSize }
  }
  return { strategy: 'semantic', max_chunk_size: configForm.splittingMaxChunkSize, similarity_threshold: configForm.splittingSimilarityThreshold, batch_size: configForm.splittingBatchSize }
}

async function next() {
  const formRef = [parsingFormRef, splittingFormRef, generationFormRef][currentStep.value]?.value
  if (formRef) {
    try {
      await formRef.validate()
    } catch {
      return
    }
  }
  if (currentStep.value < steps.length - 1) {
    currentStep.value++
    maxReachedStep.value = Math.max(maxReachedStep.value, currentStep.value)
  }
}

function prev() {
  if (currentStep.value > 0) currentStep.value--
}

function goToStep(i: number) {
  if (i <= maxReachedStep.value) currentStep.value = i
}

function goList() {
  router.push(goListPath.value)
}

async function onSave() {
  saving.value = true
  try {
    await knowledgeBaseApi.updateConfig(spaceId.value, kbId.value, {
      splitting: buildSplittingConfig(),
      parsing: {
        extract_images: configForm.parsingExtractImages,
        extract_tables: configForm.parsingExtractTables,
        ocr_enabled: configForm.parsingOcrEnabled,
        preserve_structure: configForm.parsingPreserveStructure,
        encoding: configForm.parsingEncoding || undefined,
      },
      question_generation: {
        enabled: configForm.qgEnabled,
        llm: configForm.qgEnabled
          ? {
              model: configForm.qgLlmModel || undefined,
              protocol: configForm.qgLlmProtocol || undefined,
              temperature: configForm.qgLlmTemperature,
              top_p: configForm.qgLlmTopP,
              max_tokens: configForm.qgLlmMaxTokens,
            }
          : undefined,
        max_questions_per_chunk: configForm.qgEnabled ? configForm.qgMaxQuestions : undefined,
        prompt_template: configForm.qgEnabled ? configForm.qgPromptTemplate || undefined : undefined,
      },
    })
    saved.value = true
    ElMessage.success('配置已保存')
    router.push(goListPath.value)
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '保存配置失败')
  } finally {
    saving.value = false
  }
}

onBeforeRouteLeave(async () => {
  if (!dirty.value || saved.value) return true
  try {
    await ElMessageBox.confirm('配置尚未保存，确定离开？', '提示', {
      type: 'warning',
      confirmButtonText: '离开',
      cancelButtonText: '继续编辑',
    })
    return true
  } catch {
    return false
  }
})

onMounted(() => {
  if (!spaceId.value || !kbId.value) {
    ElMessage.error('参数缺失')
    router.replace(spaceId.value ? goListPath.value : '/home')
    return
  }
  onLoad()
})
</script>

<style scoped>
.kb-config-page {
  padding-top: var(--space-2);
  max-width: 880px;
  margin: 0 auto;
}

.config-card {
  max-width: 880px;
}

.steps-bar {
  margin-bottom: var(--space-6);
}

.step-section {
  padding: var(--space-2) var(--space-4) var(--space-4);
}

.step-title {
  margin: 0 0 var(--space-1);
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.step-desc {
  margin: 0 0 var(--space-5);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.qg-fieldset {
  border: none;
  padding: 0;
  margin: 0;
}

.config-footer {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-6);
  padding-top: var(--space-5);
  border-top: 1px solid var(--color-border-light);
}

.footer-spacer {
  flex: 1;
}

.kb-name-tag {
  font-size: var(--text-md);
  color: var(--color-text-muted);
  font-weight: var(--weight-regular);
}

:deep(.el-step.clickable) {
  cursor: pointer;
}
</style>
