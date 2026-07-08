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
          :class="{ clickable: true }"
          @click="goToStep(i)"
        />
      </el-steps>

      <!-- ─── 数据类型 ─── -->
      <section v-show="currentStep === 0" class="step-section">
        <div class="step-heading">
          <span class="step-icon">📦</span>
          <div>
            <h3 class="step-title">数据类型</h3>
            <p class="step-desc">选择该知识库支持的数据模态，决定可上传的文件类型和解析管道。</p>
          </div>
        </div>

        <el-checkbox-group v-model="configForm.kbSpaceTypes" class="modality-checkboxes">
          <el-checkbox label="text">
            <span class="modality-label">📄 文本</span>
            <span class="modality-desc">PDF / Word / TXT / MD / CSV / HTML / JSON</span>
          </el-checkbox>
          <el-checkbox label="image">
            <span class="modality-label">🖼 图片</span>
            <span class="modality-desc">JPG / PNG / GIF / WebP</span>
          </el-checkbox>
          <el-checkbox label="video">
            <span class="modality-label">🎬 视频</span>
            <span class="modality-desc">MP4 / MOV / AVI / MKV / WebM</span>
          </el-checkbox>
          <el-checkbox label="audio">
            <span class="modality-label">🎵 音频</span>
            <span class="modality-desc">MP3 / WAV / FLAC / AAC / OGG / M4A</span>
          </el-checkbox>
        </el-checkbox-group>
      </section>

      <!-- ─── Step 2: 模型配置 ─── -->
      <section v-show="currentStep === 1" class="step-section">
        <div class="step-heading">
          <span class="step-icon">⚙️</span>
          <div>
            <h3 class="step-title">模型配置</h3>
            <p class="step-desc">根据数据类型配置对应的 AI 模型。</p>
          </div>
        </div>

        <!-- Embedding（继承自空间，只读） -->
        <div class="info-cards">
          <div class="info-card">
            <div class="info-card-icon embed-icon">📝</div>
            <div class="info-card-body">
              <span class="info-card-label">文本 Embedding 模型</span>
              <span class="info-card-value">{{ embeddingInfo.text_model || '未配置' }}</span>
              <span v-if="embeddingInfo.text_dimension" class="info-card-dim">维度：{{ embeddingInfo.text_dimension }}</span>
            </div>
            <el-tag size="small" type="info" effect="plain">继承自空间</el-tag>
          </div>
          <div v-if="showMmEmbeddingCard" class="info-card">
            <div class="info-card-icon embed-icon">🖼️</div>
            <div class="info-card-body">
              <span class="info-card-label">多模态 Embedding 模型</span>
              <span class="info-card-value">{{ embeddingInfo.mm_model || '未配置' }}</span>
              <span v-if="embeddingInfo.mm_dimension" class="info-card-dim">维度：{{ embeddingInfo.mm_dimension }}</span>
            </div>
            <el-tag size="small" type="info" effect="plain">继承自空间</el-tag>
          </div>
        </div>

        <!-- LLM -->
        <div class="sub-section">
          <h4 class="sub-title">🤖 默认 LLM 模型</h4>
          <p class="sub-desc">用于问题生成等任务，留空使用系统默认。</p>
          <el-form :model="configForm" label-width="100px" class="config-form">
            <el-form-item label="LLM 模型">
              <el-select v-model="configForm.qgLlmModel" placeholder="系统默认" clearable filterable style="width: 100%">
                <el-option v-for="m in llmModels" :key="m.model" :label="m.model" :value="m.model" />
              </el-select>
            </el-form-item>
          </el-form>
        </div>

        <!-- VLM（image 或 video 勾选时显示） -->
        <div v-if="hasImage || hasVideo" class="sub-section">
          <h4 class="sub-title">👁️ 视觉模型 (VLM)</h4>
          <p class="sub-desc">用于图片描述和视频帧理解，留空使用系统默认。</p>
          <el-form :model="configForm" label-width="100px" class="config-form">
            <el-form-item label="VLM 模型">
              <el-select v-model="configForm.parsingVlmModel" placeholder="系统默认" clearable filterable style="width: 100%">
                <el-option v-for="m in vlmModels" :key="m.model" :label="m.model" :value="m.model" />
              </el-select>
            </el-form-item>
          </el-form>
        </div>

        <!-- ASR（audio 勾选时显示） -->
        <div v-if="hasAudio" class="sub-section">
          <h4 class="sub-title">🎵 语音转写模型 (ASR)</h4>
          <el-form label-width="100px" class="config-form" style="max-width: 560px">
            <el-form-item label="ASR 模型">
              <el-select v-model="configForm.audioAsrModel" placeholder="默认 (whisper-1)" clearable filterable style="width: 100%">
                <el-option v-for="m in asrModels" :key="m.model" :label="m.model" :value="m.model" />
              </el-select>
              <span class="form-hint">语音转文字，留空使用默认</span>
            </el-form-item>
          </el-form>
        </div>
      </section>

      <!-- ─── Step 3: 解析策略 ─── -->
      <section v-show="currentStep === 2" class="step-section">
        <div class="step-heading">
          <span class="step-icon">📄</span>
          <div>
            <h3 class="step-title">解析策略</h3>
            <p class="step-desc">配置文档解析行为与转写后的切分方式。</p>
          </div>
        </div>

        <!-- 文本解析 -->
        <div class="sub-section">
          <h4 class="sub-title">📝 文本解析</h4>
          <el-form :model="configForm" label-width="110px" class="config-form">
            <el-row :gutter="24">
              <el-col :span="12">
                <el-form-item label="提取图片">
                  <el-switch v-model="configForm.parsingExtractImages" />
                  <span class="form-hint">从文档中提取嵌入的图片</span>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="提取表格">
                  <el-switch v-model="configForm.parsingExtractTables" />
                  <span class="form-hint">识别并提取表格数据</span>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="启用 OCR">
                  <el-switch v-model="configForm.parsingOcrEnabled" />
                  <span class="form-hint">对图片中的文字进行识别</span>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="保留结构">
                  <el-switch v-model="configForm.parsingPreserveStructure" />
                  <span class="form-hint">保留标题、段落等层级结构</span>
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="文件编码">
              <el-input v-model="configForm.parsingEncoding" placeholder="utf-8" style="max-width: 260px" />
            </el-form-item>
          </el-form>
        </div>

        <!-- 图片解析（image 勾选时显示） -->
        <div v-if="hasImage" class="sub-section">
          <h4 class="sub-title">🖼 图片解析</h4>
          <el-form :model="configForm" label-width="140px" class="config-form">
            <el-form-item label="VLM 图片描述">
              <el-switch v-model="configForm.parsingVlmDescription" />
              <span class="form-hint">调用视觉模型生成图片文本描述，使图片可被文本检索</span>
            </el-form-item>
          </el-form>
        </div>

        <!-- 视频解析（video 勾选时显示） -->
        <div v-if="hasVideo" class="sub-section">
          <h4 class="sub-title">🎬 视频解析</h4>
          <el-form label-width="110px" class="config-form" style="max-width: 560px">
            <el-form-item label="抽帧间隔(秒)">
              <el-slider v-model="configForm.videoFrameInterval" :min="1" :max="60" show-input :show-input-controls="false" />
            </el-form-item>
            <el-form-item label="最大帧数">
              <el-input-number v-model="configForm.videoMaxFrames" :min="1" :max="200" style="width: 100%" />
            </el-form-item>
          </el-form>
        </div>

        <!-- 音频转写参数（audio 勾选时显示） -->
        <div v-if="hasAudio" class="sub-section">
          <h4 class="sub-title">🎵 音频转写参数</h4>
          <el-form label-width="100px" class="config-form" style="max-width: 560px">
            <el-form-item label="转写语言">
              <el-select v-model="configForm.audioAsrLanguage" placeholder="自动检测" clearable style="width: 100%">
                <el-option label="自动检测" value="" />
                <el-option label="中文" value="zh" />
                <el-option label="英文" value="en" />
                <el-option label="日文" value="ja" />
                <el-option label="韩文" value="ko" />
              </el-select>
              <span class="form-hint">指定语言可提升识别准确率，留空自动检测</span>
            </el-form-item>
          </el-form>
        </div>

      </section>

      <!-- ─── Step 4: 切分策略 ─── -->
      <section v-show="currentStep === 3" class="step-section">
        <div class="step-heading">
          <span class="step-icon">✂️</span>
          <div>
            <h3 class="step-title">切分策略</h3>
            <p class="step-desc">配置文本与转写内容的切分方式，决定检索粒度。</p>
          </div>
        </div>

        <!-- 文本切分 -->
        <div class="sub-section">
          <h4 class="sub-title">📝 文本切分</h4>
          <el-form :model="configForm" label-width="110px" class="config-form">
          <el-form-item label="切分策略" prop="splittingStrategy">
            <el-select v-model="configForm.splittingStrategy" style="width: 100%">
              <el-option label="递归字符切分" value="recursive">
                <span>递归字符切分</span>
                <span class="option-desc">按段落 → 句号 → 换行 → 空格逐级切分</span>
              </el-option>
              <el-option label="固定大小切分" value="fixed_size">
                <span>固定大小切分</span>
                <span class="option-desc">按固定字符数截断</span>
              </el-option>
              <el-option label="Markdown 结构切分" value="markdown">
                <span>Markdown 结构切分</span>
                <span class="option-desc">按 # ~ ###### 标题层级切分</span>
              </el-option>
              <el-option label="语义切分" value="semantic">
                <span>语义切分</span>
                <span class="option-desc">基于向量相似度识别语义边界</span>
              </el-option>
            </el-select>
          </el-form-item>

          <template v-if="configForm.splittingStrategy === 'recursive' || configForm.splittingStrategy === 'fixed_size'">
            <el-row :gutter="24">
              <el-col :span="12">
                <el-form-item label="分块大小">
                  <el-input-number v-model="configForm.splittingChunkSize" :min="500" :max="4000" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="重叠字符数">
                  <el-input-number v-model="configForm.splittingChunkOverlap" :min="0" :max="500" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
          </template>
          <el-form-item v-if="configForm.splittingStrategy === 'recursive'" label="最小分块大小">
            <el-input-number v-model="configForm.splittingMinChunkSize" :min="0" :max="2000" style="width: 260px" />
            <span class="form-hint">小于此大小的分块将合并到相邻块</span>
          </el-form-item>

          <template v-if="configForm.splittingStrategy === 'markdown'">
            <el-row :gutter="24">
              <el-col :span="12">
                <el-form-item label="最大分块大小">
                  <el-input-number v-model="configForm.splittingMaxChunkSize" :min="100" :max="8000" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="最小分块大小">
                  <el-input-number v-model="configForm.splittingMinChunkSize" :min="10" :max="1000" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
          </template>

          <template v-if="configForm.splittingStrategy === 'semantic'">
            <el-row :gutter="24">
              <el-col :span="12">
                <el-form-item label="最大分块大小">
                  <el-input-number v-model="configForm.splittingMaxChunkSize" :min="100" :max="8000" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="批处理大小">
                  <el-input-number v-model="configForm.splittingBatchSize" :min="1" :max="100" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="相似度阈值">
              <el-slider v-model="configForm.splittingSimilarityThreshold" :min="0" :max="1" :step="0.05" show-input :show-input-controls="false" style="max-width: 480px" />
              <span class="form-hint">相邻句子相似度低于此值时视为语义边界</span>
            </el-form-item>
          </template>
        </el-form>
        </div>

        <!-- 音频切片（audio 勾选时显示） -->
        <div v-if="hasAudio" class="sub-section">
          <h4 class="sub-title">🎵 音频切片</h4>
          <el-form label-width="120px" class="config-form" style="max-width: 560px">
            <el-form-item label="切片策略">
              <el-radio-group v-model="configForm.audioChunkStrategy">
                <el-radio value="sentence">按句子切分</el-radio>
                <el-radio value="fixed">固定字符数</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="configForm.audioChunkStrategy === 'fixed'" label="固定字符数">
              <el-input-number v-model="configForm.audioChunkSize" :min="100" :max="4000" style="width: 100%" />
            </el-form-item>
          </el-form>
        </div>

        <!-- 视频切片（video 勾选时显示） -->
        <div v-if="hasVideo" class="sub-section">
          <h4 class="sub-title">🎬 视频切片</h4>
          <el-form label-width="120px" class="config-form" style="max-width: 560px">
            <el-form-item label="聚合最大字符数">
              <el-input-number v-model="configForm.videoChunkSize" :min="100" :max="4000" style="width: 100%" />
              <span class="form-hint">将连续帧的描述文本合并，不超过此字符数</span>
            </el-form-item>
          </el-form>
        </div>

        <!-- 图片切分（image 勾选时显示） -->
        <div v-if="hasImage" class="sub-section">
          <h4 class="sub-title">🖼 图片切分</h4>
          <el-form label-width="120px" class="config-form" style="max-width: 560px">
            <el-form-item label="切分方式">
              <el-radio-group v-model="configForm.imageChunkStrategy">
                <el-radio value="single">单图单块</el-radio>
                <el-radio value="batch">按描述合并</el-radio>
              </el-radio-group>
              <span class="form-hint">单图单块：每张图片独立为一个分块；按描述合并：多张图片VLM描述按字符数聚合</span>
            </el-form-item>
            <el-form-item v-if="configForm.imageChunkStrategy === 'batch'" label="聚合最大字符数">
              <el-input-number v-model="configForm.imageChunkSize" :min="100" :max="4000" style="width: 100%" />
            </el-form-item>
          </el-form>
        </div>
      </section>

      <!-- ─── Step 5: 生成策略 ─── -->
      <section v-show="currentStep === 4" class="step-section">
        <div class="step-heading">
          <span class="step-icon">✨</span>
          <div>
            <h3 class="step-title">生成策略</h3>
            <p class="step-desc">为每个分块生成假设性问题（HyDE），提升问题匹配的召回率。</p>
          </div>
        </div>

        <el-form :model="configForm" label-width="120px" class="config-form">
          <el-form-item label="启用问题生成">
            <el-switch v-model="configForm.qgEnabled" />
            <span class="form-hint">{{ configForm.qgEnabled ? '已开启，处理文档时将自动生成假设问题' : '关闭后将跳过问题生成步骤' }}</span>
          </el-form-item>
          <fieldset :disabled="!configForm.qgEnabled" class="qg-fieldset">
            <el-row :gutter="24">
              <el-col :span="12">
                <el-form-item label="每块最大问题数">
                  <el-input-number v-model="configForm.qgMaxQuestions" :min="1" :max="20" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="提示词模板">
              <el-input v-model="configForm.qgPromptTemplate" type="textarea" :rows="3" placeholder="自定义提示词模板（可选）" maxlength="4000" />
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
import { ref, reactive, computed, watch, nextTick, onMounted } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/common/PageHeader.vue'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import { spaceApi } from '@/api/space'
import { userApi } from '@/api/user'
import { normalizeSpaceTypes, hasModality } from '@/utils/document'
import type { SplittingConfig, AvailableModelItem } from '@/api/types'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))
const kbId = computed(() => Number(route.params.kbId))
const goListPath = computed(() => `/home/spaces/${spaceId.value}/knowledge-bases`)

const spaceTypes = ref<string[]>(['text'])
const kbSpaceTypes = ref<string[]>(['text'])
// 这些 computed 绑定 configForm.kbSpaceTypes，Step 1 勾选时实时响应
const hasText = computed(() => configForm.kbSpaceTypes.length === 0 || hasModality(configForm.kbSpaceTypes, 'text'))
const hasImage = computed(() => hasModality(configForm.kbSpaceTypes, 'image'))
const hasVideo = computed(() => hasModality(configForm.kbSpaceTypes, 'video'))
const hasAudio = computed(() => hasModality(configForm.kbSpaceTypes, 'audio'))
// 多模态 Embedding 卡片：取决于 Space（Embedding 由空间统一管理）
const showMmEmbeddingCard = computed(() => hasModality(spaceTypes.value, 'image'))

const embeddingInfo = reactive({
  text_model: '',
  text_dimension: null as number | null,
  mm_model: '',
  mm_dimension: null as number | null,
})

const loading = ref(false)
const saving = ref(false)
const kbName = ref('')

const steps = [
  { title: '数据类型' },
  { title: '模型配置' },
  { title: '解析策略' },
  { title: '切分策略' },
  { title: '生成策略' },
]
const currentStep = ref(0)

const configForm = reactive({
  kbSpaceTypes: ['text'] as string[],
  qgLlmModel: '',
  qgLlmTemperature: 0.3,
  qgLlmTopP: 0.9,
  qgLlmMaxTokens: 2048,
  // 文本解析
  parsingExtractImages: false,
  parsingExtractTables: true,
  parsingOcrEnabled: false,
  parsingPreserveStructure: true,
  parsingEncoding: 'utf-8',
  parsingVlmDescription: false,
  parsingVlmModel: '',
  // 视频
  videoFrameInterval: 5,
  videoMaxFrames: 60,
  videoChunkSize: 1500,
  // 音频
  audioAsrModel: '',
  audioAsrLanguage: '',
  audioChunkStrategy: 'sentence' as 'sentence' | 'fixed',
  audioChunkSize: 1000,
  // 图片切分
  imageChunkStrategy: 'single' as 'single' | 'batch',
  imageChunkSize: 2000,
  // 分块
  splittingStrategy: 'recursive' as string,
  splittingChunkSize: 2000,
  splittingChunkOverlap: 100,
  splittingMaxChunkSize: 2000,
  splittingMinChunkSize: 500,
  splittingSimilarityThreshold: 0.7,
  splittingBatchSize: 20,
  // 生成
  qgEnabled: false,
  qgMaxQuestions: 5,
  qgPromptTemplate: '',
})

const llmModels = ref<AvailableModelItem[]>([])
const vlmModels = ref<AvailableModelItem[]>([])
const asrModels = ref<AvailableModelItem[]>([])

const dirty = ref(false)
const saved = ref(false)
watch(configForm, () => { dirty.value = true }, { deep: true })

async function fetchAvailableModels() {
  try {
    const data = await userApi.getAvailableModelDetails()
    llmModels.value = data.llm || []
    vlmModels.value = data.vlm || []
    asrModels.value = data.asr || []
  } catch { /* ignore */ }
}

async function onLoad() {
  loading.value = true
  try {
    const [data, space] = await Promise.all([
      knowledgeBaseApi.getConfig(spaceId.value, kbId.value),
      spaceApi.getSpace(spaceId.value).catch(() => null),
      fetchAvailableModels(),
    ])
    kbName.value = data.name
    const cfg = data.config

    // KB 模态
    if (cfg?.space_type && Array.isArray(cfg.space_type) && cfg.space_type.length > 0) {
      kbSpaceTypes.value = cfg.space_type
    } else if (space) {
      kbSpaceTypes.value = normalizeSpaceTypes(space.config)
    } else {
      kbSpaceTypes.value = ['text']
    }
    configForm.kbSpaceTypes = [...kbSpaceTypes.value]

    // 空间 Embedding 信息
    if (space) {
      spaceTypes.value = normalizeSpaceTypes(space.config)
      embeddingInfo.text_model = space.config?.embedding?.model || ''
      embeddingInfo.text_dimension = space.config?.embedding?.dimension ?? null
      embeddingInfo.mm_model = space.config?.multimodal_embedding?.model || ''
      embeddingInfo.mm_dimension = space.config?.multimodal_embedding?.dimension ?? null
    } else {
      spaceTypes.value = ['text']
    }

    // 切分配置
    const sp = cfg?.splitting
    configForm.splittingStrategy = sp?.strategy || 'recursive'
    configForm.splittingChunkSize = (sp as { chunk_size?: number })?.chunk_size ?? 1000
    configForm.splittingChunkOverlap = (sp as { chunk_overlap?: number })?.chunk_overlap ?? 100
    configForm.splittingMaxChunkSize = (sp as { max_chunk_size?: number })?.max_chunk_size ?? 2000
    configForm.splittingMinChunkSize = (sp as { min_chunk_size?: number })?.min_chunk_size
      ?? (configForm.splittingStrategy === 'recursive' ? 500 : 100)
    configForm.splittingSimilarityThreshold = (sp as { similarity_threshold?: number })?.similarity_threshold ?? 0.7
    configForm.splittingBatchSize = (sp as { batch_size?: number })?.batch_size ?? 20

    // 音频切片策略从 splitting.audio 读取
    const audioSp = (sp as { audio?: { strategy?: string; chunk_size?: number } })?.audio
    if (audioSp) {
      configForm.audioChunkStrategy = (audioSp.strategy as 'sentence' | 'fixed') || 'sentence'
      configForm.audioChunkSize = audioSp.chunk_size ?? 1000
    }

    // 解析配置
    const ps = cfg?.parsing as Record<string, unknown> | undefined
    configForm.parsingExtractImages = (ps?.extract_images as boolean) ?? false
    configForm.parsingExtractTables = (ps?.extract_tables as boolean) ?? true
    configForm.parsingOcrEnabled = (ps?.ocr_enabled as boolean) ?? false
    configForm.parsingPreserveStructure = (ps?.preserve_structure as boolean) ?? true
    configForm.parsingEncoding = (ps?.encoding as string) || 'utf-8'
    configForm.parsingVlmDescription = (ps?.vlm_description_enabled as boolean) ?? false
    configForm.parsingVlmModel = (ps?.vlm_model as string) || ''

    const vc = (ps?.video as Record<string, unknown>) || {}
    configForm.videoFrameInterval = (vc?.frame_interval as number) ?? 5
    configForm.videoMaxFrames = (vc?.max_frames as number) ?? 60

    const ac = (ps?.audio as Record<string, unknown>) || {}
    configForm.audioAsrModel = (ac?.asr_model as string) || ''
    configForm.audioAsrLanguage = (ac?.language as string) || ''

    // 图片切片策略从 splitting.image 读取
    const imageSp = (sp as { image?: { strategy?: string; chunk_size?: number } })?.image
    if (imageSp) {
      configForm.imageChunkStrategy = (imageSp.strategy as 'single' | 'batch') || 'single'
      configForm.imageChunkSize = imageSp.chunk_size ?? 2000
    }

    // 视频切片策略从 splitting.video 读取
    const videoSp = (sp as { video?: { strategy?: string; chunk_size?: number } })?.video
    if (videoSp) {
      configForm.videoChunkSize = videoSp.chunk_size ?? 1500
    }

    // 问题生成
    const qg = cfg?.question_generation
    configForm.qgEnabled = qg?.enabled ?? false
    configForm.qgLlmModel = qg?.llm?.model || ''
    configForm.qgLlmTemperature = qg?.llm?.temperature ?? 0.3
    configForm.qgLlmTopP = qg?.llm?.top_p ?? 0.9
    configForm.qgLlmMaxTokens = qg?.llm?.max_tokens ?? 2048
    configForm.qgMaxQuestions = qg?.max_questions_per_chunk ?? 5
    configForm.qgPromptTemplate = qg?.prompt_template || ''

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
  const base: SplittingConfig = {
    strategy: s as SplittingConfig['strategy'],
  }
  if (s === 'recursive') {
    base.chunk_size = configForm.splittingChunkSize
    base.chunk_overlap = configForm.splittingChunkOverlap
    base.min_chunk_size = configForm.splittingMinChunkSize
  } else if (s === 'fixed_size') {
    base.chunk_size = configForm.splittingChunkSize
    base.chunk_overlap = configForm.splittingChunkOverlap
  } else if (s === 'markdown') {
    base.max_chunk_size = configForm.splittingMaxChunkSize
    base.min_chunk_size = configForm.splittingMinChunkSize
  } else {
    base.max_chunk_size = configForm.splittingMaxChunkSize
    base.similarity_threshold = configForm.splittingSimilarityThreshold
    base.batch_size = configForm.splittingBatchSize
  }
  if (hasImage.value) {
    base.image = {
      strategy: configForm.imageChunkStrategy,
      ...(configForm.imageChunkStrategy === 'batch' ? { chunk_size: configForm.imageChunkSize } : {}),
    }
  }
  if (hasAudio.value) {
    base.audio = {
      strategy: configForm.audioChunkStrategy,
      ...(configForm.audioChunkStrategy === 'fixed' ? { chunk_size: configForm.audioChunkSize } : {}),
    }
  }
  if (hasVideo.value) {
    base.video = {
      strategy: 'fixed' as const,
      chunk_size: configForm.videoChunkSize,
    }
  }
  return base
}

function goToStep(i: number) { currentStep.value = i }
function goList() { router.push(goListPath.value) }

async function onSave() {
  saving.value = true
  try {
    await knowledgeBaseApi.updateConfig(spaceId.value, kbId.value, {
      space_type: configForm.kbSpaceTypes.length > 0 ? configForm.kbSpaceTypes : ['text'],
      splitting: buildSplittingConfig(),
      parsing: {
        extract_images: configForm.parsingExtractImages,
        extract_tables: configForm.parsingExtractTables,
        ocr_enabled: configForm.parsingOcrEnabled,
        preserve_structure: configForm.parsingPreserveStructure,
        encoding: configForm.parsingEncoding || undefined,
        ...(hasImage.value || hasVideo.value ? {
          vlm_description_enabled: configForm.parsingVlmDescription,
          vlm_model: configForm.parsingVlmModel || null,
        } : {}),
        ...(hasVideo.value ? {
          video: { frame_interval: configForm.videoFrameInterval, max_frames: configForm.videoMaxFrames },
        } : {}),
        ...(hasAudio.value ? {
          audio: {
            asr_model: configForm.audioAsrModel || null,
            language: configForm.audioAsrLanguage || null,
          },
        } : {}),
      },
      question_generation: {
        enabled: configForm.qgEnabled,
        llm: {
          model: configForm.qgLlmModel || undefined,
          temperature: configForm.qgLlmTemperature,
          top_p: configForm.qgLlmTopP,
          max_tokens: configForm.qgLlmMaxTokens,
        },
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
    await ElMessageBox.confirm('配置尚未保存，确定离开？', '提示', { type: 'warning', confirmButtonText: '离开', cancelButtonText: '继续编辑' })
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
.kb-config-page { padding-top: var(--space-2); max-width: 900px; margin: 0 auto; }
.config-card { max-width: 900px; }
.steps-bar { margin-bottom: var(--space-6); padding: 0 var(--space-2); }
:deep(.el-step.clickable) { cursor: pointer; }

.step-section { padding: var(--space-2) var(--space-2) var(--space-4); }
.step-heading {
  display: flex; align-items: flex-start; gap: var(--space-3);
  margin-bottom: var(--space-5); padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
}
.step-icon { font-size: 28px; line-height: 1; flex-shrink: 0; margin-top: 2px; }
.step-title { margin: 0 0 var(--space-1); font-size: var(--text-lg); font-weight: var(--weight-semibold); color: var(--color-text); font-family: var(--font-display); }
.step-desc { margin: 0; font-size: var(--text-sm); color: var(--color-text-muted); line-height: 1.5; }

.sub-section {
  margin-bottom: var(--space-5); padding: var(--space-4);
  background: var(--color-bg-card-elevated); border: 1px solid var(--color-border-light); border-radius: var(--radius-lg);
}
.sub-section:last-child { margin-bottom: 0; }
.sub-title { font-size: var(--text-base); font-weight: var(--weight-semibold); color: var(--color-text); margin: 0 0 var(--space-1); }
.sub-desc { margin: 0 0 var(--space-4); font-size: var(--text-sm); color: var(--color-text-muted); }

.info-cards { display: flex; flex-direction: column; gap: var(--space-3); margin-bottom: var(--space-5); }
.info-card {
  display: flex; align-items: center; gap: var(--space-4); padding: var(--space-4);
  background: var(--color-bg-card-elevated); border: 1px solid var(--color-border-light); border-radius: var(--radius-lg);
}
.info-card-icon { width: 44px; height: 44px; border-radius: var(--radius-md); display: flex; align-items: center; justify-content: center; font-size: 22px; flex-shrink: 0; }
.embed-icon { background: var(--color-primary-subtle); }
.info-card-body { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.info-card-label { font-size: var(--text-xs); color: var(--color-text-muted); }
.info-card-value { font-size: var(--text-sm); font-weight: var(--weight-semibold); color: var(--color-text); font-family: var(--font-mono); }
.info-card-dim { font-size: var(--text-xs); color: var(--color-text-muted); }

.config-form { margin-top: var(--space-1); }
.form-hint { font-size: var(--text-xs); color: var(--color-text-muted); margin-left: var(--space-2); }
.option-desc { float: right; color: var(--color-text-muted); font-size: 12px; line-height: 32px; }

.qg-fieldset {
  border: none; padding: var(--space-4); margin: var(--space-2) 0 0;
  border-radius: var(--radius-lg); background: var(--color-bg-card-elevated); border: 1px solid var(--color-border-light);
}
.qg-fieldset[disabled] { opacity: 0.45; }

.config-footer {
  display: flex; align-items: center; gap: var(--space-3);
  margin-top: var(--space-6); padding-top: var(--space-5); border-top: 1px solid var(--color-border-light);
}
.footer-spacer { flex: 1; }
.kb-name-tag { font-size: var(--text-md); color: var(--color-text-muted); font-weight: var(--weight-regular); }
.modality-checkboxes { display: flex; flex-direction: column; gap: var(--space-2); }
.modality-checkboxes :deep(.el-checkbox) {
  padding: var(--space-2) var(--space-3); border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light); transition: border-color 0.2s, background-color 0.2s;
}
.modality-checkboxes :deep(.el-checkbox:hover) { border-color: var(--color-primary); background-color: var(--color-primary-subtle); }
.modality-checkboxes :deep(.el-checkbox.is-checked) { border-color: var(--color-primary); background-color: var(--color-primary-subtle); }
.modality-label { font-size: var(--text-sm); font-weight: var(--weight-semibold); }
.modality-desc { display: block; font-size: var(--text-xs); color: var(--color-text-muted); margin-top: 2px; }
</style>
