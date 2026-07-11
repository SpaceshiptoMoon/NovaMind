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
            <span class="modality-desc">OCR / VLM 图片理解</span>
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
              <el-select
                v-model="configForm.imageVlmModel"
                clearable
                filterable
                placeholder="系统默认"
                style="width: 100%"
              >
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
              <el-select
                v-model="configForm.videoVlmModel"
                clearable
                filterable
                placeholder="系统默认"
                style="width: 100%"
              >
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
              <el-select
                v-model="configForm.audioAsrModel"
                clearable
                filterable
                placeholder="默认 whisper-1"
                style="width: 100%"
              >
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

        <div v-if="hasText" class="sub-section">
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

        <div v-if="hasImage" class="sub-section">
          <h4 class="sub-title">图片解析</h4>
          <p class="sub-desc">OCR 与 VLM 二选一；当策略为 VLM 时才会带上 VLM 模型。</p>

          <el-form :model="configForm" label-width="120px" class="config-form">
            <el-form-item label="解析策略">
              <el-radio-group v-model="configForm.imageStrategy">
                <el-radio value="ocr">ocr</el-radio>
                <el-radio value="vlm">vlm</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="configForm.imageStrategy === 'vlm'" label="VLM 模型">
              <el-select v-model="configForm.imageVlmModel" clearable filterable placeholder="系统默认" style="width: 100%">
                <el-option v-for="model in vlmModels" :key="model.model" :label="model.model" :value="model.model" />
              </el-select>
            </el-form-item>
          </el-form>
        </div>

        <div v-if="hasVideo" class="sub-section">
          <h4 class="sub-title">视频解析</h4>
          <p class="sub-desc">控制抽帧频率、最大抽帧数和视觉描述开关。</p>

          <el-form :model="configForm" label-width="120px" class="config-form">
            <el-form-item label="抽帧间隔">
              <el-slider v-model="configForm.videoFrameInterval" :min="1" :max="60" show-input :show-input-controls="false" />
            </el-form-item>
            <el-form-item label="最大帧数">
              <el-input-number v-model="configForm.videoMaxFrames" :min="1" :max="200" style="width: 100%" />
            </el-form-item>
            <el-form-item label="视觉描述">
              <el-switch v-model="configForm.videoVlmDescriptionEnabled" />
            </el-form-item>
            <el-form-item v-if="configForm.videoVlmDescriptionEnabled" label="VLM 模型">
              <el-select v-model="configForm.videoVlmModel" clearable filterable placeholder="系统默认" style="width: 100%">
                <el-option v-for="model in vlmModels" :key="model.model" :label="model.model" :value="model.model" />
              </el-select>
            </el-form-item>
          </el-form>
        </div>

        <div v-if="hasAudio" class="sub-section">
          <h4 class="sub-title">音频解析</h4>
          <p class="sub-desc">ASR 模型与语言配置互不冲突。</p>

          <el-form :model="configForm" label-width="120px" class="config-form">
            <el-form-item label="ASR 模型">
              <el-select v-model="configForm.audioAsrModel" clearable filterable placeholder="默认 whisper-1" style="width: 100%">
                <el-option v-for="model in asrModels" :key="model.model" :label="model.model" :value="model.model" />
              </el-select>
            </el-form-item>
            <el-form-item label="语言">
              <el-select v-model="configForm.audioAsrLanguage" clearable placeholder="自动检测" style="width: 100%">
                <el-option label="自动检测" value="" />
                <el-option label="中文" value="zh" />
                <el-option label="英文" value="en" />
                <el-option label="日文" value="ja" />
                <el-option label="韩文" value="ko" />
              </el-select>
            </el-form-item>
          </el-form>
        </div>
      </section>

      <section v-show="currentStep === 3" class="step-section">
        <div class="step-heading">
          <span class="step-icon">04</span>
          <div>
            <h3 class="step-title">切分策略</h3>
            <p class="step-desc">保留文本主切分，并支持音频、视频覆盖配置。</p>
          </div>
        </div>

        <div class="sub-section">
          <h4 class="sub-title">文本切分</h4>

          <el-form :model="configForm" label-width="120px" class="config-form">
            <el-form-item label="切分策略">
              <el-select v-model="configForm.splittingStrategy" style="width: 100%">
                <el-option label="recursive" value="recursive" />
                <el-option label="fixed_size" value="fixed_size" />
                <el-option label="markdown" value="markdown" />
                <el-option label="semantic" value="semantic" />
              </el-select>
            </el-form-item>

            <template v-if="configForm.splittingStrategy === 'recursive' || configForm.splittingStrategy === 'fixed_size'">
              <el-row :gutter="24">
                <el-col :span="12">
                  <el-form-item label="chunk_size">
                    <el-input-number v-model="configForm.splittingChunkSize" :min="100" :max="4000" style="width: 100%" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="chunk_overlap">
                    <el-input-number v-model="configForm.splittingChunkOverlap" :min="0" :max="500" style="width: 100%" />
                  </el-form-item>
                </el-col>
              </el-row>
            </template>

            <el-form-item v-if="configForm.splittingStrategy === 'recursive'" label="min_chunk_size">
              <el-input-number v-model="configForm.splittingMinChunkSize" :min="0" :max="2000" style="width: 260px" />
            </el-form-item>

            <template v-if="configForm.splittingStrategy === 'markdown'">
              <el-row :gutter="24">
                <el-col :span="12">
                  <el-form-item label="max_chunk_size">
                    <el-input-number v-model="configForm.splittingMaxChunkSize" :min="100" :max="8000" style="width: 100%" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="min_chunk_size">
                    <el-input-number v-model="configForm.splittingMinChunkSize" :min="0" :max="2000" style="width: 100%" />
                  </el-form-item>
                </el-col>
              </el-row>
            </template>

            <template v-if="configForm.splittingStrategy === 'semantic'">
              <el-row :gutter="24">
                <el-col :span="12">
                  <el-form-item label="max_chunk_size">
                    <el-input-number v-model="configForm.splittingMaxChunkSize" :min="100" :max="8000" style="width: 100%" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="batch_size">
                    <el-input-number v-model="configForm.splittingBatchSize" :min="1" :max="100" style="width: 100%" />
                  </el-form-item>
                </el-col>
              </el-row>
              <el-form-item label="similarity_threshold">
                <el-slider
                  v-model="configForm.splittingSimilarityThreshold"
                  :min="0"
                  :max="1"
                  :step="0.05"
                  show-input
                  :show-input-controls="false"
                  style="max-width: 480px"
                />
              </el-form-item>
            </template>
          </el-form>
        </div>

        <div v-if="hasAudio" class="sub-section">
          <h4 class="sub-title">音频切分</h4>

          <el-form :model="configForm" label-width="120px" class="config-form">
            <el-form-item label="切分策略">
              <el-radio-group v-model="configForm.audioChunkStrategy">
                <el-radio value="sentence">sentence</el-radio>
                <el-radio value="fixed">fixed</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="configForm.audioChunkStrategy === 'fixed'" label="chunk_size">
              <el-input-number v-model="configForm.audioChunkSize" :min="100" :max="4000" style="width: 100%" />
            </el-form-item>
          </el-form>
        </div>

        <div v-if="hasVideo" class="sub-section">
          <h4 class="sub-title">视频切分</h4>

          <el-form :model="configForm" label-width="120px" class="config-form">
            <el-form-item label="chunk_size">
              <el-input-number v-model="configForm.videoChunkSize" :min="100" :max="4000" style="width: 100%" />
            </el-form-item>
          </el-form>
        </div>
      </section>

      <section v-show="currentStep === 4" class="step-section">
        <div class="step-heading">
          <span class="step-icon">05</span>
          <div>
            <h3 class="step-title">问题生成</h3>
            <p class="step-desc">为切分后的 chunk 生成辅助问题。</p>
          </div>
        </div>

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
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/common/PageHeader.vue'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import { spaceApi } from '@/api/space'
import { userApi } from '@/api/user'
import { hasModality, normalizeSpaceTypes } from '@/utils/document'
import type {
  AvailableModelItem,
  KnowledgeBaseConfigUpdateRequest,
  ParsingConfig,
  PdfParserName,
  SplittingConfig,
  TextParsingConfig,
} from '@/api/types'

type TextStrategy = 'default' | 'deepdoc'
type ImageStrategy = 'ocr' | 'vlm'
type AudioChunkStrategy = 'sentence' | 'fixed'

type TextStrategyField =
  | 'docxStrategy'
  | 'excelStrategy'
  | 'pptStrategy'
  | 'epubStrategy'
  | 'markdownStrategy'
  | 'htmlStrategy'
  | 'txtStrategy'
  | 'jsonStrategy'

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

const textStrategyItems: Array<{ key: TextStrategyField; label: string }> = [
  { key: 'docxStrategy', label: 'DOCX' },
  { key: 'excelStrategy', label: 'Excel' },
  { key: 'pptStrategy', label: 'PPT' },
  { key: 'epubStrategy', label: 'EPUB' },
  { key: 'markdownStrategy', label: 'Markdown' },
  { key: 'htmlStrategy', label: 'HTML' },
  { key: 'txtStrategy', label: 'TXT' },
  { key: 'jsonStrategy', label: 'JSON' },
]

const deepdocParserOptions: Array<{ label: string; value: PdfParserName }> = [
  { label: 'layout', value: 'layout' },
  { label: 'plain', value: 'plain' },
  { label: 'vision', value: 'vision' },
  { label: 'docling', value: 'docling' },
  { label: 'mineru', value: 'mineru' },
  { label: 'opendataloader', value: 'opendataloader' },
  { label: 'paddleocr', value: 'paddleocr' },
  { label: 'somark', value: 'somark' },
  { label: 'tcadp', value: 'tcadp' },
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

watch(configForm, () => {
  dirty.value = true
}, { deep: true })

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

watch(() => configForm.imageStrategy, (value) => {
  if (value !== 'vlm') {
    configForm.imageVlmModel = ''
  }
})

watch(() => configForm.videoVlmDescriptionEnabled, (value) => {
  if (!value) {
    configForm.videoVlmModel = ''
  }
})

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

function getTextStrategyValue(value: unknown): TextStrategy {
  return value === 'deepdoc' ? 'deepdoc' : 'default'
}

function loadTextParsingConfig(textConfig?: TextParsingConfig) {
  configForm.pdfStrategy = getTextStrategyValue(textConfig?.pdf?.strategy)
  configForm.deepdocParser = textConfig?.pdf?.parser || 'layout'
  configForm.pdfOcrEnabled = textConfig?.pdf?.ocr_enabled ?? false
  configForm.docxStrategy = getTextStrategyValue(textConfig?.docx?.strategy)
  configForm.excelStrategy = getTextStrategyValue(textConfig?.excel?.strategy)
  configForm.pptStrategy = getTextStrategyValue(textConfig?.ppt?.strategy)
  configForm.epubStrategy = getTextStrategyValue(textConfig?.epub?.strategy)
  configForm.markdownStrategy = getTextStrategyValue(textConfig?.markdown?.strategy)
  configForm.htmlStrategy = getTextStrategyValue(textConfig?.html?.strategy)
  configForm.txtStrategy = getTextStrategyValue(textConfig?.txt?.strategy)
  configForm.jsonStrategy = getTextStrategyValue(textConfig?.json?.strategy)
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
  return {
    pdf: {
      strategy: configForm.pdfStrategy,
      parser: configForm.pdfStrategy === 'deepdoc' ? configForm.deepdocParser : undefined,
      ocr_enabled: configForm.pdfOcrEnabled,
    },
    docx: { strategy: configForm.docxStrategy },
    excel: { strategy: configForm.excelStrategy },
    ppt: { strategy: configForm.pptStrategy },
    epub: { strategy: configForm.epubStrategy },
    markdown: { strategy: configForm.markdownStrategy },
    html: { strategy: configForm.htmlStrategy },
    txt: { strategy: configForm.txtStrategy },
    json: { strategy: configForm.jsonStrategy },
  }
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
  max-width: 960px;
  margin: 0 auto;
  padding-top: var(--space-2);
}

.config-card {
  max-width: 960px;
}

.steps-bar {
  margin-bottom: var(--space-6);
  padding: 0 var(--space-2);
}

:deep(.el-step.clickable) {
  cursor: pointer;
}

.step-section {
  padding: var(--space-2) var(--space-2) var(--space-4);
}

.step-heading {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
}

.step-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 40px;
  height: 40px;
  border-radius: 999px;
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  font-size: 14px;
  font-weight: var(--weight-semibold);
  flex-shrink: 0;
}

.step-title {
  margin: 0 0 var(--space-1);
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  font-family: var(--font-display);
}

.step-desc {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  line-height: 1.5;
}

.sub-section {
  margin-bottom: var(--space-5);
  padding: var(--space-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card-elevated);
}

.sub-section:last-child {
  margin-bottom: 0;
}

.sub-title {
  margin: 0 0 var(--space-1);
  font-size: var(--text-base);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.sub-desc {
  margin: 0 0 var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.info-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}

.info-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card-elevated);
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
  background: var(--color-primary-subtle);
  color: var(--color-primary);
}

.info-card-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.info-card-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.info-card-value {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  font-family: var(--font-mono);
}

.info-card-dim {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
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
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
}

.text-strategy-label {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
}

.qg-fieldset {
  margin: var(--space-2) 0 0;
  padding: var(--space-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card-elevated);
}

.qg-fieldset[disabled] {
  opacity: 0.45;
}

.config-footer {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-6);
  padding-top: var(--space-5);
  border-top: 1px solid var(--color-border-light);
}

.kb-name-tag {
  font-size: var(--text-md);
  color: var(--color-text-muted);
  font-weight: var(--weight-regular);
}

.modality-checkboxes {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.modality-checkboxes :deep(.el-checkbox) {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
  transition: border-color 0.2s, background-color 0.2s;
}

.modality-checkboxes :deep(.el-checkbox:hover) {
  border-color: var(--color-primary);
  background: var(--color-primary-subtle);
}

.modality-checkboxes :deep(.el-checkbox.is-checked) {
  border-color: var(--color-primary);
  background: var(--color-primary-subtle);
}

.modality-label {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
}

.modality-desc {
  display: block;
  margin-top: 2px;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}
</style>
