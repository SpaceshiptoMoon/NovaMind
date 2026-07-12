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
          v-for="(step, index) in steps"
          :key="step.title"
          :title="step.title"
          class="clickable"
          @click="goToStep(index)"
        />
      </el-steps>

      <section v-show="currentStep === 0" class="step-section">
        <div class="step-heading">
          <span class="step-icon">01</span>
          <div>
            <h3 class="step-title">数据类型</h3>
            <p class="step-desc">选择这个知识库需要支持的数据模态。</p>
          </div>
        </div>

        <el-checkbox-group v-model="configForm.kbSpaceTypes" class="modality-checkboxes">
          <el-checkbox label="text">
            <span class="modality-label">文本</span>
            <span class="modality-desc">PDF / DOCX / Excel / PPT / EPUB / Markdown / HTML / TXT / JSON</span>
          </el-checkbox>
          <el-checkbox label="image">
            <span class="modality-label">图片</span>
            <span class="modality-desc">OCR / VLM 图像理解</span>
          </el-checkbox>
          <el-checkbox label="video">
            <span class="modality-label">视频</span>
            <span class="modality-desc">抽帧、视觉描述、视频切分</span>
          </el-checkbox>
          <el-checkbox label="audio">
            <span class="modality-label">音频</span>
            <span class="modality-desc">ASR、语言指定、音频切分</span>
          </el-checkbox>
        </el-checkbox-group>
      </section>

      <section v-show="currentStep === 1" class="step-section">
        <div class="step-heading">
          <span class="step-icon">02</span>
          <div>
            <h3 class="step-title">模型配置</h3>
            <p class="step-desc">查看继承自空间的模型，并配置知识库专用模型。</p>
          </div>
        </div>

        <div class="info-cards">
          <div class="info-card">
            <div class="info-card-icon embed-icon">E</div>
            <div class="info-card-body">
              <span class="info-card-label">文本 Embedding</span>
              <span class="info-card-value">{{ embeddingInfo.textModel || '未配置' }}</span>
              <span v-if="embeddingInfo.textDimension" class="info-card-dim">维度 {{ embeddingInfo.textDimension }}</span>
            </div>
            <el-tag size="small" type="info" effect="plain">继承自空间</el-tag>
          </div>

          <div v-if="showMmEmbeddingCard" class="info-card">
            <div class="info-card-icon embed-icon">MM</div>
            <div class="info-card-body">
              <span class="info-card-label">多模态 Embedding</span>
              <span class="info-card-value">{{ embeddingInfo.mmModel || '未配置' }}</span>
              <span v-if="embeddingInfo.mmDimension" class="info-card-dim">维度 {{ embeddingInfo.mmDimension }}</span>
            </div>
            <el-tag size="small" type="info" effect="plain">继承自空间</el-tag>
          </div>
        </div>

        <div class="sub-section">
          <h4 class="sub-title">问题生成 LLM</h4>
          <p class="sub-desc">用于问题生成，留空时使用系统默认模型。</p>
          <el-form :model="configForm" label-width="120px" class="config-form">
            <el-form-item label="LLM 模型">
              <el-select v-model="configForm.qgLlmModel" clearable filterable placeholder="系统默认" style="width: 100%">
                <el-option v-for="model in llmModels" :key="model.model" :label="model.model" :value="model.model" />
              </el-select>
            </el-form-item>
          </el-form>
        </div>

        <div v-if="hasImage" class="sub-section">
          <h4 class="sub-title">图片 VLM</h4>
          <p class="sub-desc">仅在图片解析策略选择 VLM 时生效。</p>
          <el-form :model="configForm" label-width="120px" class="config-form">
            <el-form-item label="VLM 模型">
              <el-select v-model="configForm.imageVlmModel" clearable filterable placeholder="系统默认" style="width: 100%">
                <el-option v-for="model in vlmModels" :key="model.model" :label="model.model" :value="model.model" />
              </el-select>
            </el-form-item>
          </el-form>
        </div>

        <div v-if="hasVideo" class="sub-section">
          <h4 class="sub-title">视频 VLM</h4>
          <p class="sub-desc">用于视频抽帧后的视觉描述，留空时使用系统默认模型。</p>
          <el-form :model="configForm" label-width="120px" class="config-form">
            <el-form-item label="VLM 模型">
              <el-select v-model="configForm.videoVlmModel" clearable filterable placeholder="系统默认" style="width: 100%">
                <el-option v-for="model in vlmModels" :key="model.model" :label="model.model" :value="model.model" />
              </el-select>
            </el-form-item>
          </el-form>
        </div>

        <div v-if="hasAudio" class="sub-section">
          <h4 class="sub-title">音频 ASR</h4>
          <p class="sub-desc">用于音频转写，留空时使用默认 ASR 模型。</p>
          <el-form :model="configForm" label-width="120px" class="config-form">
            <el-form-item label="ASR 模型">
              <el-select v-model="configForm.audioAsrModel" clearable filterable placeholder="默认 whisper-1" style="width: 100%">
                <el-option v-for="model in asrModels" :key="model.model" :label="model.model" :value="model.model" />
              </el-select>
            </el-form-item>
          </el-form>
        </div>
      </section>

      <section v-show="currentStep === 2" class="step-section">
        <div class="step-heading">
          <span class="step-icon">03</span>
          <div>
            <h3 class="step-title">解析策略</h3>
            <p class="step-desc">按文档类型和模态分别配置解析方式。</p>
          </div>
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

      <section v-show="currentStep === 3" class="step-section">
        <div class="step-heading">
          <span class="step-icon">04</span>
          <div>
            <h3 class="step-title">切分策略</h3>
            <p class="step-desc">保留文本主切分，并支持音频、视频额外切分配置。</p>
          </div>
        </div>

        <KbSplittingSection :config-form="configForm" :has-audio="hasAudio" :has-video="hasVideo" />
      </section>

      <section v-show="currentStep === 4" class="step-section">
        <div class="step-heading">
          <span class="step-icon">05</span>
          <div>
            <h3 class="step-title">问题生成</h3>
            <p class="step-desc">为切分后的 chunk 生成辅助问题。</p>
          </div>
        </div>

        <KbQuestionGenerationSection :config-form="configForm" />
      </section>

      <div class="config-footer">
        <el-button @click="goList">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存配置</el-button>
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
  KbMultimodalParsingSection,
  KbQuestionGenerationSection,
  KbSplittingSection,
  KbTextParsingSection,
} from '@/components/knowledge'
import type { AudioChunkStrategy, ImageStrategy, TextStrategy } from '@/components/knowledge'
import { spaceApi } from '@/api/space'
import { userApi } from '@/api/user'
import { hasModality, normalizeSpaceTypes } from '@/components/knowledge'
import type {
  AvailableModelItem,
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
  { title: '数据类型' },
  { title: '模型配置' },
  { title: '解析策略' },
  { title: '切分策略' },
  { title: '问题生成' },
]

const currentStep = ref(0)
const loading = ref(false)
const saving = ref(false)
const dirty = ref(false)
const saved = ref(false)
const kbName = ref('')
const spaceTypes = ref<string[]>(['text'])

const llmModels = ref<AvailableModelItem[]>([])
const vlmModels = ref<AvailableModelItem[]>([])
const asrModels = ref<AvailableModelItem[]>([])

const embeddingInfo = reactive({
  textModel: '',
  textDimension: null as number | null,
  mmModel: '',
  mmDimension: null as number | null,
})

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
const showMmEmbeddingCard = computed(() => hasModality(spaceTypes.value, 'image'))

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

async function onLoad() {
  loading.value = true
  try {
    const [kbConfigResponse, space] = await Promise.all([
      knowledgeBaseApi.getConfig(spaceId.value, kbId.value),
      spaceApi.getSpace(spaceId.value).catch(() => null),
      fetchAvailableModels(),
    ])

    kbName.value = kbConfigResponse.name
    const kbConfig = kbConfigResponse.config

    if (kbConfig?.space_type && kbConfig.space_type.length > 0) {
      configForm.kbSpaceTypes = [...kbConfig.space_type]
    } else if (space) {
      configForm.kbSpaceTypes = normalizeSpaceTypes(space.config)
    } else {
      configForm.kbSpaceTypes = ['text']
    }

    if (space) {
      spaceTypes.value = normalizeSpaceTypes(space.config)
      embeddingInfo.textModel = space.config?.embedding?.model || ''
      embeddingInfo.textDimension = space.config?.embedding?.dimension ?? null
      embeddingInfo.mmModel = space.config?.multimodal_embedding?.model || ''
      embeddingInfo.mmDimension = space.config?.multimodal_embedding?.dimension ?? null
    } else {
      spaceTypes.value = ['text']
    }

    const splitting = kbConfig?.splitting
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

    const parsing = kbConfig?.parsing as ParsingConfig | undefined
    loadTextParsingConfig(parsing?.text)

    configForm.imageStrategy = parsing?.image?.strategy || 'ocr'
    configForm.imageVlmModel = parsing?.image?.vlm_model || ''

    configForm.videoFrameInterval = parsing?.video?.frame_interval ?? 5
    configForm.videoMaxFrames = parsing?.video?.max_frames ?? 60
    configForm.videoVlmDescriptionEnabled = parsing?.video?.vlm_description_enabled ?? false
    configForm.videoVlmModel = parsing?.video?.vlm_model || ''

    configForm.audioAsrModel = parsing?.audio?.asr_model || ''
    configForm.audioAsrLanguage = parsing?.audio?.language || ''

    const qg = kbConfig?.question_generation
    configForm.qgEnabled = qg?.enabled ?? false
    configForm.qgLlmModel = qg?.llm?.model || ''
    configForm.qgLlmTemperature = qg?.llm?.temperature ?? 0.3
    configForm.qgLlmTopP = qg?.llm?.top_p ?? 0.9
    configForm.qgLlmMaxTokens = qg?.llm?.max_tokens ?? 2048
    configForm.qgMaxQuestions = qg?.max_questions_per_chunk ?? 5
    configForm.qgPromptTemplate = qg?.prompt_template || ''

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
  max-width: 1120px;
  margin: 0 auto;
  padding-top: var(--space-2);
  --kb-accent: #b14d22;
  --kb-accent-soft: rgba(177, 77, 34, 0.1);
  --kb-ink: #1f2937;
  --kb-muted: #667085;
  --kb-card: linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(250, 246, 239, 0.92));
  --kb-rule: rgba(31, 41, 55, 0.09);
}

.config-card {
  max-width: 1120px;
  border: 1px solid rgba(31, 41, 55, 0.08);
  border-radius: 28px;
  background:
    radial-gradient(circle at top right, rgba(177, 77, 34, 0.1), transparent 26%),
    linear-gradient(180deg, #fffefb 0%, #fff9f2 100%);
  box-shadow: 0 28px 80px rgba(15, 23, 42, 0.08);
}

.steps-bar {
  margin-bottom: var(--space-6);
  padding: 24px 24px 8px;
  border-bottom: 1px solid var(--kb-rule);
  background: linear-gradient(180deg, rgba(177, 77, 34, 0.05), rgba(177, 77, 34, 0.01));
}

:deep(.el-step.clickable) {
  cursor: pointer;
}

:deep(.steps-bar .el-step__title) {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.01em;
}

:deep(.steps-bar .el-step__title.is-process),
:deep(.steps-bar .el-step__title.is-success) {
  color: var(--kb-ink);
}

:deep(.steps-bar .el-step__head.is-process .el-step__icon),
:deep(.steps-bar .el-step__head.is-success .el-step__icon) {
  background: var(--kb-accent);
  border-color: var(--kb-accent);
  color: #fff;
}

:deep(.steps-bar .el-step__head.is-process .el-step__line-inner),
:deep(.steps-bar .el-step__head.is-success .el-step__line-inner) {
  border-color: var(--kb-accent);
}

:deep(.steps-bar .el-step__head.is-wait .el-step__icon) {
  background: #fff;
  border-color: rgba(31, 41, 55, 0.16);
  color: var(--kb-muted);
}

.step-section {
  padding: 24px 24px 28px;
}

.step-heading {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 24px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--kb-rule);
}

.step-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 40px;
  height: 40px;
  border-radius: 999px;
  background: var(--kb-accent-soft);
  color: var(--kb-accent);
  font-size: 14px;
  font-weight: var(--weight-semibold);
  flex-shrink: 0;
  box-shadow: inset 0 0 0 1px rgba(177, 77, 34, 0.12);
}

.step-title {
  margin: 0 0 var(--space-1);
  font-size: 26px;
  font-weight: 700;
  color: var(--kb-ink);
  font-family: var(--font-display);
  letter-spacing: -0.02em;
}

.step-desc {
  margin: 0;
  max-width: 720px;
  font-size: 14px;
  color: var(--kb-muted);
  line-height: 1.7;
}

.sub-section {
  margin-bottom: var(--space-5);
  padding: 22px 22px 20px;
  border: 1px solid rgba(31, 41, 55, 0.08);
  border-radius: 22px;
  background: var(--kb-card);
  box-shadow: 0 14px 36px rgba(15, 23, 42, 0.04);
}

.sub-section:last-child {
  margin-bottom: 0;
}

.sub-title {
  margin: 0 0 var(--space-1);
  font-size: 18px;
  font-weight: 700;
  color: var(--kb-ink);
}

.sub-desc {
  margin: 0 0 var(--space-4);
  font-size: 13px;
  color: var(--kb-muted);
  line-height: 1.7;
}

.info-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}

.info-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4);
  border: 1px solid rgba(31, 41, 55, 0.08);
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(248, 243, 235, 0.94));
}

.info-card-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: var(--weight-semibold);
  flex-shrink: 0;
}

.embed-icon {
  background: var(--kb-accent-soft);
  color: var(--kb-accent);
}

.info-card-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.info-card-label {
  font-size: var(--text-xs);
  color: var(--kb-muted);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.info-card-value {
  font-size: 15px;
  font-weight: 700;
  color: var(--kb-ink);
  font-family: var(--font-mono);
}

.info-card-dim {
  font-size: var(--text-xs);
  color: var(--kb-muted);
}

.config-form {
  margin-top: var(--space-1);
}

.text-strategy-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--space-3);
  margin-top: var(--space-2);
}

.text-strategy-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid rgba(31, 41, 55, 0.08);
  border-radius: 16px;
  background: linear-gradient(180deg, #fff, #fbf8f3);
}

.text-strategy-label {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--kb-ink);
}

.qg-fieldset {
  margin: var(--space-2) 0 0;
  padding: var(--space-4);
  border: 1px solid rgba(31, 41, 55, 0.08);
  border-radius: 20px;
  background: linear-gradient(180deg, #fff, #fcfaf6);
}

.qg-fieldset[disabled] {
  opacity: 0.45;
}

.config-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-6);
  padding: 22px 24px 24px;
  border-top: 1px solid var(--kb-rule);
  background: linear-gradient(180deg, rgba(255, 249, 241, 0.15), rgba(255, 255, 255, 0.8));
}

.kb-name-tag {
  font-size: var(--text-md);
  color: var(--kb-muted);
  font-weight: var(--weight-regular);
}

.modality-checkboxes {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-2);
}

.modality-checkboxes :deep(.el-checkbox) {
  align-items: flex-start;
  min-height: 110px;
  margin-right: 0;
  padding: 16px 16px 14px;
  border-radius: 20px;
  border: 1px solid rgba(31, 41, 55, 0.08);
  background: linear-gradient(180deg, #fff, #fcf8f2);
  transition: border-color 0.2s, background-color 0.2s, transform 0.2s, box-shadow 0.2s;
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.04);
}

.modality-checkboxes :deep(.el-checkbox:hover) {
  border-color: rgba(177, 77, 34, 0.42);
  background: #fff8ef;
  transform: translateY(-2px);
  box-shadow: 0 16px 34px rgba(177, 77, 34, 0.1);
}

.modality-checkboxes :deep(.el-checkbox.is-checked) {
  border-color: rgba(177, 77, 34, 0.42);
  background: linear-gradient(180deg, rgba(255, 244, 229, 0.96), rgba(255, 249, 241, 0.96));
  box-shadow: 0 16px 34px rgba(177, 77, 34, 0.1);
}

.modality-checkboxes :deep(.el-checkbox__label) {
  display: flex;
  flex-direction: column;
  line-height: 1.5;
}

.modality-label {
  font-size: 16px;
  font-weight: 700;
  color: var(--kb-ink);
}

.modality-desc {
  display: block;
  margin-top: 8px;
  font-size: 12px;
  color: var(--kb-muted);
  line-height: 1.65;
}

:deep(.config-form .el-form-item__label) {
  color: var(--kb-muted);
  font-weight: 700;
}

:deep(.config-form .el-input__wrapper),
:deep(.config-form .el-select__wrapper),
:deep(.config-form .el-textarea__inner),
:deep(.config-form .el-input-number) {
  border-radius: 14px;
}

:deep(.config-footer .el-button) {
  min-width: 120px;
  border-radius: 999px;
  font-weight: 700;
}

:deep(.config-footer .el-button--primary) {
  border-color: var(--kb-accent);
  background: var(--kb-accent);
}

@media (max-width: 768px) {
  .kb-config-page {
    max-width: 100%;
  }

  .config-card {
    border-radius: 20px;
  }

  .steps-bar,
  .step-section,
  .config-footer {
    padding-left: 16px;
    padding-right: 16px;
  }

  .step-title {
    font-size: 22px;
  }

  .modality-checkboxes,
  .info-cards {
    grid-template-columns: 1fr;
  }
}
</style>
