<template>
  <div class="kb-config-page">
    <PageHeader title="知识库配置" show-back :back-to="goListPath">
      <template #title-suffix>
        <span v-if="kbName" class="kb-name-tag">{{ kbName }}</span>
      </template>
    </PageHeader>

    <el-card v-loading="loading" shadow="never" class="config-shell">
      <section class="editor-section editor-section-first">
        <div class="section-heading">
          <div>
            <h3 class="section-title">选择知识库要启用的数据类型</h3>
          </div>
          <p class="section-desc">
            选择这个知识库需要处理的内容类型。
          </p>
        </div>

        <el-checkbox-group v-model="configForm.kbSpaceTypes" class="modality-grid">
          <el-checkbox label="text">
            <span class="modality-title">文本</span>
            <span class="modality-desc">PDF、DOCX、Excel、PPT、Markdown、HTML、TXT、JSON</span>
          </el-checkbox>
          <el-checkbox label="image">
            <span class="modality-title">图片</span>
            <span class="modality-desc">OCR 或 VLM 识图，支持图像语义检索。</span>
          </el-checkbox>
          <el-checkbox label="video">
            <span class="modality-title">视频</span>
            <span class="modality-desc">抽帧、视觉描述与视频文本切分。</span>
          </el-checkbox>
          <el-checkbox label="audio">
            <span class="modality-title">音频</span>
            <span class="modality-desc">ASR 转写、语言指定与音频专属切分。</span>
          </el-checkbox>
        </el-checkbox-group>
      </section>

      <div class="section-nav">
        <button
          v-for="(step, index) in steps"
          :key="step.title"
          type="button"
          class="nav-pill"
          :class="{ 'is-active': currentStep === index }"
          @click="goToStep(index)"
        >
          <span class="nav-index">0{{ index + 1 }}</span>
          <span class="nav-copy">
            <strong>{{ step.title }}</strong>
            <small>{{ step.desc }}</small>
          </span>
        </button>
      </div>

      <section v-show="currentStep === 1" class="editor-section">
        <div class="section-heading">
          <div>
            <h3 class="section-title">配置主切分策略和模态覆盖参数</h3>
          </div>
          <p class="section-desc">
            不同策略只显示会生效的参数。
          </p>
        </div>

        <KbSplittingSection :config-form="configForm" :has-audio="hasAudio" :has-video="hasVideo" />
      </section>

      <section v-show="currentStep === 0" class="editor-section">
        <div class="section-heading">
          <div>
            <h3 class="section-title">按文档类型和模态配置解析方式</h3>
          </div>
          <p class="section-desc">
            已按后端约束自动收口无效字段。
          </p>
        </div>

        <KbTextParsingSection v-if="hasText" :config-form="configForm" />
        <KbMultimodalParsingSection
          :config-form="configForm"
          :has-image="hasImage"
          :has-video="hasVideo"
          :has-audio="hasAudio"
          :vlm-models="vlmModels"
          :asr-models="asrModels"
        />
      </section>

      <section v-show="currentStep === 2" class="editor-section">
        <div class="section-heading">
          <div>
            <h3 class="section-title">设置问题生成开关和 LLM 参数</h3>
          </div>
          <p class="section-desc">
            开启后用于生成辅助问题，增强检索召回。
          </p>
        </div>

        <KbQuestionGenerationSection :config-form="configForm" :llm-models="llmModels" />
      </section>

      <div class="config-footer">
        <div class="footer-actions">
          <el-button @click="goList">取消</el-button>
          <el-button type="primary" :loading="saving" @click="onSave">保存配置</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/common/PageHeader.vue'
import { knowledgeBaseApi } from '@/api/knowledge'
import {
  applyTextParsingConfig,
  buildTextParsingConfigFromForm,
  hasModality,
  KbMultimodalParsingSection,
  KbQuestionGenerationSection,
  KbSplittingSection,
  KbTextParsingSection,
  normalizeSpaceTypes,
} from '@/components/knowledge'
import type { AudioChunkStrategy, ImageStrategy, TextStrategy } from '@/components/knowledge'
import { spaceApi } from '@/api/space'
import { userApi } from '@/api/user'
import type {
  AvailableModelItem,
  KnowledgeBaseConfigResponse,
  KnowledgeBaseConfigUpdateRequest,
  ParsingConfig,
  PdfParserName,
  SplittingConfig,
  TextParsingConfig,
} from '@/api/types'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))
const kbId = computed(() => Number(route.params.kbId))
const goListPath = computed(() => `/home/spaces/${spaceId.value}/knowledge-bases`)

const steps = [
  { title: '解析策略', desc: 'parsing' },
  { title: '切分策略', desc: 'splitting' },
  { title: '问题生成', desc: 'question_generation' },
]

const currentStep = ref(0)
const loading = ref(false)
const saving = ref(false)
const dirty = ref(false)
const saved = ref(false)
const kbName = ref('')

const llmModels = ref<AvailableModelItem[]>([])
const vlmModels = ref<AvailableModelItem[]>([])
const asrModels = ref<AvailableModelItem[]>([])

const configForm = reactive({
  kbSpaceTypes: ['text'] as string[],

  pdfStrategy: 'default' as TextStrategy,
  deepdocParser: 'layout' as PdfParserName,
  pdfOcrEnabled: false,
  docxStrategy: 'default' as TextStrategy,
  excelStrategy: 'default' as TextStrategy,
  pptStrategy: 'default' as TextStrategy,
  epubStrategy: 'default' as TextStrategy,
  markdownStrategy: 'default' as TextStrategy,
  htmlStrategy: 'default' as TextStrategy,
  txtStrategy: 'default' as TextStrategy,
  jsonStrategy: 'default' as TextStrategy,

  imageStrategy: 'ocr' as ImageStrategy,
  imageVlmModel: '',

  videoFrameInterval: 5,
  videoMaxFrames: 60,
  videoVlmDescriptionEnabled: false,
  videoVlmModel: '',

  audioAsrModel: '',
  audioAsrLanguage: '',

  splittingStrategy: 'recursive',
  splittingChunkSize: 1000,
  splittingChunkOverlap: 100,
  splittingMinChunkSize: 500,
  splittingMaxChunkSize: 2000,
  splittingSimilarityThreshold: 0.7,
  splittingBatchSize: 20,
  audioChunkStrategy: 'sentence' as AudioChunkStrategy,
  audioChunkSize: 1000,
  videoChunkSize: 1500,

  qgEnabled: false,
  qgLlmModel: '',
  qgLlmTemperature: 0.3,
  qgLlmTopP: 0.9,
  qgLlmMaxTokens: 2048,
  qgMaxQuestions: 5,
  qgPromptTemplate: '',
})

const hasText = computed(() => configForm.kbSpaceTypes.length === 0 || hasModality(configForm.kbSpaceTypes, 'text'))
const hasImage = computed(() => hasModality(configForm.kbSpaceTypes, 'image'))
const hasVideo = computed(() => hasModality(configForm.kbSpaceTypes, 'video'))
const hasAudio = computed(() => hasModality(configForm.kbSpaceTypes, 'audio'))

watch(
  configForm,
  () => {
    dirty.value = true
  },
  { deep: true },
)

watch(hasImage, (value) => {
  if (!value) {
    configForm.imageStrategy = 'ocr'
    configForm.imageVlmModel = ''
  }
})

watch(hasVideo, (value) => {
  if (!value) {
    configForm.videoVlmDescriptionEnabled = false
    configForm.videoVlmModel = ''
  }
})

watch(hasAudio, (value) => {
  if (!value) {
    configForm.audioAsrModel = ''
    configForm.audioAsrLanguage = ''
    configForm.audioChunkStrategy = 'sentence'
    configForm.audioChunkSize = 1000
  }
})

watch(
  () => configForm.imageStrategy,
  (value) => {
    if (value !== 'vlm') {
      configForm.imageVlmModel = ''
    }
  },
)

watch(
  () => configForm.videoVlmDescriptionEnabled,
  (value) => {
    if (!value) {
      configForm.videoVlmModel = ''
    }
  },
)

function goToStep(index: number) {
  currentStep.value = index
}

function goList() {
  router.push(goListPath.value)
}

async function fetchAvailableModels() {
  try {
    const data = await userApi.getAvailableModelDetails()
    llmModels.value = data.llm || []
    vlmModels.value = data.vlm || []
    asrModels.value = data.asr || []
  } catch {
    // keep page usable even if model discovery fails
  }
}

function loadTextParsingConfig(textConfig?: TextParsingConfig) {
  applyTextParsingConfig(configForm, textConfig)
}

function applyKbResponse(response: KnowledgeBaseConfigResponse) {
  kbName.value = response.name

  const kbConfig = response.config
  const splitting = kbConfig?.splitting
  const parsing = kbConfig?.parsing as ParsingConfig | undefined
  const qg = kbConfig?.question_generation

  configForm.splittingStrategy = splitting?.strategy || 'recursive'
  configForm.splittingChunkSize = splitting?.chunk_size ?? 1000
  configForm.splittingChunkOverlap = splitting?.chunk_overlap ?? 100
  configForm.splittingMinChunkSize = splitting?.min_chunk_size ?? 500
  configForm.splittingMaxChunkSize = splitting?.max_chunk_size ?? 2000
  configForm.splittingSimilarityThreshold = splitting?.similarity_threshold ?? 0.7
  configForm.splittingBatchSize = splitting?.batch_size ?? 20
  configForm.audioChunkStrategy = splitting?.audio?.strategy || 'sentence'
  configForm.audioChunkSize = splitting?.audio?.chunk_size ?? 1000
  configForm.videoChunkSize = splitting?.video?.chunk_size ?? 1500

  loadTextParsingConfig(parsing?.text)
  configForm.imageStrategy = parsing?.image?.strategy || 'ocr'
  configForm.imageVlmModel = parsing?.image?.vlm_model || ''
  configForm.videoFrameInterval = parsing?.video?.frame_interval ?? 5
  configForm.videoMaxFrames = parsing?.video?.max_frames ?? 60
  configForm.videoVlmDescriptionEnabled = parsing?.video?.vlm_description_enabled ?? false
  configForm.videoVlmModel = parsing?.video?.vlm_model || ''
  configForm.audioAsrModel = parsing?.audio?.asr_model || ''
  configForm.audioAsrLanguage = parsing?.audio?.language || ''

  configForm.qgEnabled = qg?.enabled ?? false
  configForm.qgLlmModel = qg?.llm?.model || ''
  configForm.qgLlmTemperature = qg?.llm?.temperature ?? 0.3
  configForm.qgLlmTopP = qg?.llm?.top_p ?? 0.9
  configForm.qgLlmMaxTokens = qg?.llm?.max_tokens ?? 2048
  configForm.qgMaxQuestions = qg?.max_questions_per_chunk ?? 5
  configForm.qgPromptTemplate = qg?.prompt_template || ''
}

async function onLoad() {
  loading.value = true
  try {
    const [kbConfigResponse, space] = await Promise.all([
      knowledgeBaseApi.getConfig(spaceId.value, kbId.value),
      spaceApi.getSpace(spaceId.value).catch(() => null),
      fetchAvailableModels(),
    ])

    applyKbResponse(kbConfigResponse)

    if (kbConfigResponse.config?.space_type && kbConfigResponse.config.space_type.length > 0) {
      configForm.kbSpaceTypes = [...kbConfigResponse.config.space_type]
    } else if (space) {
      configForm.kbSpaceTypes = normalizeSpaceTypes(space.config)
    } else {
      configForm.kbSpaceTypes = ['text']
    }

    dirty.value = false
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '获取知识库配置失败')
    router.replace(goListPath.value)
  } finally {
    loading.value = false
  }
}

function buildTextParsingConfig(): TextParsingConfig {
  return buildTextParsingConfigFromForm(configForm)
}

function buildSplittingConfig(): SplittingConfig {
  const splitting: SplittingConfig = {
    strategy: configForm.splittingStrategy as SplittingConfig['strategy'],
  }

  if (configForm.splittingStrategy === 'recursive') {
    splitting.chunk_size = configForm.splittingChunkSize
    splitting.chunk_overlap = configForm.splittingChunkOverlap
    splitting.min_chunk_size = configForm.splittingMinChunkSize
  } else if (configForm.splittingStrategy === 'fixed_size') {
    splitting.chunk_size = configForm.splittingChunkSize
    splitting.chunk_overlap = configForm.splittingChunkOverlap
  } else if (configForm.splittingStrategy === 'markdown') {
    splitting.max_chunk_size = configForm.splittingMaxChunkSize
    splitting.min_chunk_size = configForm.splittingMinChunkSize
  } else if (configForm.splittingStrategy === 'semantic') {
    splitting.max_chunk_size = configForm.splittingMaxChunkSize
    splitting.similarity_threshold = configForm.splittingSimilarityThreshold
    splitting.batch_size = configForm.splittingBatchSize
  }

  if (hasAudio.value) {
    splitting.audio = {
      strategy: configForm.audioChunkStrategy,
      chunk_size: configForm.audioChunkStrategy === 'fixed' ? configForm.audioChunkSize : undefined,
    }
  }

  if (hasVideo.value) {
    splitting.video = {
      strategy: 'fixed',
      chunk_size: configForm.videoChunkSize,
    }
  }

  return splitting
}

function buildParsingConfig(): ParsingConfig {
  const parsing: ParsingConfig = {}

  if (hasText.value) {
    parsing.text = buildTextParsingConfig()
  }

  if (hasImage.value) {
    parsing.image = {
      strategy: configForm.imageStrategy,
      vlm_model: configForm.imageStrategy === 'vlm' ? (configForm.imageVlmModel || undefined) : undefined,
    }
  }

  if (hasVideo.value) {
    parsing.video = {
      frame_interval: configForm.videoFrameInterval,
      max_frames: configForm.videoMaxFrames,
      vlm_description_enabled: configForm.videoVlmDescriptionEnabled,
      vlm_model: configForm.videoVlmDescriptionEnabled ? (configForm.videoVlmModel || undefined) : undefined,
    }
  }

  if (hasAudio.value) {
    parsing.audio = {
      asr_model: configForm.audioAsrModel || undefined,
      language: configForm.audioAsrLanguage || undefined,
    }
  }

  return parsing
}

function buildPayload(): KnowledgeBaseConfigUpdateRequest {
  return {
    space_type: configForm.kbSpaceTypes.length > 0 ? configForm.kbSpaceTypes : ['text'],
    splitting: buildSplittingConfig(),
    parsing: buildParsingConfig(),
    question_generation: {
      enabled: configForm.qgEnabled,
      llm: {
        model: configForm.qgLlmModel || undefined,
        temperature: configForm.qgLlmTemperature,
        top_p: configForm.qgLlmTopP,
        max_tokens: configForm.qgLlmMaxTokens,
      },
      max_questions_per_chunk: configForm.qgEnabled ? configForm.qgMaxQuestions : undefined,
      prompt_template: configForm.qgEnabled ? (configForm.qgPromptTemplate || undefined) : undefined,
    },
  }
}

async function onSave() {
  if (configForm.kbSpaceTypes.length === 0) {
    ElMessage.warning('请至少选择一种知识库数据类型')
    currentStep.value = 0
    return
  }

  saving.value = true
  try {
    await knowledgeBaseApi.updateConfig(spaceId.value, kbId.value, buildPayload())
    saved.value = true
    ElMessage.success('知识库配置已保存')
    router.push(goListPath.value)
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '保存配置失败')
  } finally {
    saving.value = false
  }
}

onBeforeRouteLeave(async () => {
  if (!dirty.value || saved.value) {
    return true
  }

  try {
    await ElMessageBox.confirm('当前配置还没有保存，确认离开吗？', '提示', {
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
    ElMessage.error('缺少必要参数')
    router.replace(spaceId.value ? goListPath.value : '/home')
    return
  }
  onLoad()
})
</script>

<style scoped>
.kb-config-page {
  padding-top: var(--space-2);
}

.config-shell {
  border: 1px solid var(--color-border-light);
  border-radius: 24px;
  background:
    radial-gradient(circle at top right, rgba(99, 102, 241, 0.1), transparent 28%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(250, 249, 255, 0.96));
  box-shadow: var(--shadow-lg);
}

.editor-section-first {
  padding-top: var(--space-8);
  padding-bottom: var(--space-6);
  border-bottom: 1px solid var(--color-border-light);
}

.section-nav {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  padding: var(--space-6) var(--space-6) 0;
}

.nav-pill {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 14px 16px;
  border: 1px solid var(--color-border-light);
  border-radius: 18px;
  background: var(--color-bg-card);
  text-align: left;
  cursor: pointer;
  transition: transform var(--transition-fast), box-shadow var(--transition-fast), border-color var(--transition-fast);
}

.nav-pill:hover {
  transform: translateY(-1px);
  border-color: rgba(99, 102, 241, 0.28);
  box-shadow: var(--shadow-sm);
}

.nav-pill.is-active {
  border-color: rgba(99, 102, 241, 0.4);
  background: linear-gradient(180deg, rgba(238, 242, 255, 0.92), rgba(255, 255, 255, 0.98));
  box-shadow: var(--shadow-md);
}

.nav-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 14px;
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  font-size: var(--text-sm);
  font-weight: var(--weight-bold);
  flex-shrink: 0;
}

.nav-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-copy strong {
  color: var(--color-text);
  font-size: var(--text-sm);
}

.nav-copy small {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.editor-section {
  padding: var(--space-8) var(--space-6);
}

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-5);
  margin-bottom: var(--space-6);
  padding-bottom: var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
}

.section-title {
  margin: 0;
  font-size: 26px;
}

.section-desc {
  max-width: 320px;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
}

.modality-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-3);
}

.modality-grid :deep(.el-checkbox) {
  align-items: flex-start;
  min-height: 120px;
  margin-right: 0;
  padding: 18px;
  border: 1px solid var(--color-border-light);
  border-radius: 20px;
  background: linear-gradient(180deg, #fff, rgba(250, 249, 255, 0.96));
  transition: transform var(--transition-fast), box-shadow var(--transition-fast), border-color var(--transition-fast);
}

.modality-grid :deep(.el-checkbox:hover) {
  transform: translateY(-2px);
  border-color: rgba(99, 102, 241, 0.26);
  box-shadow: var(--shadow-sm);
}

.modality-grid :deep(.el-checkbox.is-checked) {
  border-color: rgba(99, 102, 241, 0.35);
  background: linear-gradient(180deg, rgba(238, 242, 255, 0.95), rgba(255, 255, 255, 0.98));
  box-shadow: var(--shadow-md);
}

.modality-grid :deep(.el-checkbox__label) {
  display: flex;
  flex-direction: column;
  line-height: 1.6;
  min-width: 0;
  width: 100%;
}

.modality-title {
  color: var(--color-text);
  font-size: var(--text-md);
  font-weight: var(--weight-bold);
}

.modality-desc {
  margin-top: 8px;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  white-space: normal;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.config-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-6);
  border-top: 1px solid var(--color-border-light);
  background: linear-gradient(180deg, rgba(250, 249, 255, 0.4), rgba(255, 255, 255, 0.95));
}

.footer-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.kb-name-tag {
  color: var(--color-text-muted);
  font-size: var(--text-md);
  font-weight: var(--weight-normal);
}

:deep(.config-footer .el-button) {
  min-width: 120px;
  border-radius: var(--radius-full);
  font-weight: var(--weight-semibold);
}

:deep(.config-footer .el-button--primary) {
  box-shadow: 0 10px 24px rgba(99, 102, 241, 0.18);
}

@media (max-width: 1024px) {
  .section-nav {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .section-heading,
  .config-footer {
    flex-direction: column;
    align-items: stretch;
  }

  .section-desc {
    max-width: none;
  }
}

@media (max-width: 768px) {
  .config-shell {
    border-radius: 20px;
  }

  .editor-section,
  .config-footer {
    padding-left: var(--space-4);
    padding-right: var(--space-4);
  }

  .section-nav {
    grid-template-columns: 1fr;
    padding-left: var(--space-4);
    padding-right: var(--space-4);
  }

  .section-title {
    font-size: 22px;
  }

  .footer-actions {
    justify-content: flex-end;
  }
}
</style>
