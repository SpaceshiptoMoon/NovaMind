<template>
  <div class="knowledge-base-view">
    <!-- 批量操作栏 -->
    <div v-if="selectedIds.length > 0" class="batch-bar">
      <span class="batch-count">已选 {{ selectedIds.length }} 项</span>
      <el-button size="small" @click="clearSelection">取消选择</el-button>
      <el-button type="danger" size="small" @click="handleBatchDelete">
        批量删除
      </el-button>
    </div>

    <!-- 知识库卡片网格 -->
    <div v-loading="loading" class="kb-grid">
      <div
        v-for="(kb, index) in knowledgeBases"
        :key="kb.id"
        class="kb-card"
        :class="{ selected: selectedIds.includes(kb.id) }"
      >
        <!-- 顶部彩色条 -->
        <div class="kb-card-accent" :style="{ background: getColor(index) }" />

        <div class="kb-card-body" @click="goToDocuments(kb.id)">
          <!-- 头部：名称 + 状态 -->
          <div class="kb-card-header">
            <div class="kb-card-title-row">
              <div class="kb-color-dot" :style="{ background: getColor(index) }" />
              <h4 class="kb-name">{{ kb.name }}</h4>
            </div>
            <el-tag :type="kb.status === 1 ? 'success' : 'info'" size="small" class="kb-status-tag">
              {{ kb.status === 1 ? '活跃' : '已归档' }}
            </el-tag>
          </div>

          <!-- 描述 -->
          <p class="kb-desc">{{ kb.config?.description || '暂无描述' }}</p>

          <!-- 元信息 -->
          <div class="kb-meta">
            <span class="meta-item">
              <el-icon :size="14"><Document /></el-icon>
              {{ kb.stats?.document_count ?? 0 }} 文档
            </span>
          </div>
        </div>

        <!-- 操作按钮（hover 显示） -->
        <div class="kb-actions">
          <el-tooltip content="编辑" placement="top">
            <el-button size="small" circle @click.stop="showEditDialog(kb)">
              <el-icon><Edit /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip content="配置" placement="top">
            <el-button size="small" circle @click.stop="showConfigDialog(kb)">
              <el-icon><Setting /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip v-if="kb.status === 1" content="归档" placement="top">
            <el-button size="small" circle type="warning" plain @click.stop="handleArchive(kb)">
              <el-icon><FolderOpened /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip v-else content="激活" placement="top">
            <el-button size="small" circle type="success" plain @click.stop="handleUnarchive(kb)">
              <el-icon><FolderAdd /></el-icon>
            </el-button>
          </el-tooltip>
        </div>
      </div>

      <!-- 空状态 -->
      <EmptyState
        v-if="!loading && knowledgeBases.length === 0"
        variant="default"
        title="暂无知识库"
        description="点击右上角「新建知识库」创建第一个知识库"
      />
    </div>

    <!-- 编辑知识库弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      title="编辑知识库"
      width="480px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="formData" :rules="formRules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="formData.name" placeholder="请输入知识库名称" maxlength="100" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="formData.description"
            type="textarea"
            :rows="3"
            placeholder="请输入知识库描述（可选）"
            maxlength="500"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handleSubmit">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 知识库配置弹窗 -->
    <el-dialog
      v-model="configDialogVisible"
      title="知识库配置"
      width="640px"
      destroy-on-close
    >
      <div v-loading="configLoading">
        <el-form label-width="110px">
          <!-- 分块配置 -->
          <el-divider content-position="left">分块配置</el-divider>
          <el-form-item label="切分策略">
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

          <!-- 解析配置 -->
          <el-divider content-position="left">解析配置</el-divider>
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
          </el-row>
          <el-row :gutter="20">
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
          <el-form-item label="文件编码">
            <el-input v-model="configForm.parsingEncoding" placeholder="utf-8" />
          </el-form-item>

          <!-- 问题生成配置 -->
          <el-divider content-position="left">问题生成配置</el-divider>
          <el-form-item label="启用问题生成">
            <el-switch v-model="configForm.qgEnabled" />
          </el-form-item>
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
                <el-input
                  v-model.number="configForm.qgLlmTemperature"
                  type="number"
                  :min="0"
                  :max="2"
                  :step="0.1"
                  style="width: 100%"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="Top P">
                <el-input
                  v-model.number="configForm.qgLlmTopP"
                  type="number"
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
        </el-form>
      </div>
      <template #footer>
        <el-button @click="configDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="configSaving" @click="handleSaveConfig">
          保存配置
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Edit, Setting, FolderOpened, FolderAdd } from '@element-plus/icons-vue'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import { userApi } from '@/api/user'
import type { KnowledgeBase, SplittingConfig, AvailableModelItem } from '@/api/types'
import type { FormInstance, FormRules } from 'element-plus'
import EmptyState from '@/components/common/EmptyState.vue'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))

const loading = ref(false)
const submitLoading = ref(false)
const dialogVisible = ref(false)
const editKbId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const knowledgeBases = ref<KnowledgeBase[]>([])
const selectedIds = ref<number[]>([])

const formData = reactive({
  name: '',
  description: '',
})

const formRules: FormRules = {
  name: [
    { required: true, message: '请输入知识库名称', trigger: 'blur' },
    { min: 1, max: 100, message: '名称长度 1-100 字符', trigger: 'blur' },
  ],
}

// === 色板 ===

const colorPalette = [
  '#2563EB',
  '#10B981',
  '#EF4444',
  '#7C3AED',
  '#F59E0B',
  '#0EA5E9',
  '#F97316',
  '#14B8A6',
]

function getColor(index: number): string {
  return colorPalette[index % colorPalette.length]
}

// === 配置弹窗 ===

const configDialogVisible = ref(false)
const configLoading = ref(false)
const configSaving = ref(false)
const configKbId = ref<number | null>(null)

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

const llmModels = ref<AvailableModelItem[]>([])
const llmProtocols = ref<string[]>([])

async function fetchAvailableModels() {
  try {
    const data = await userApi.getAvailableModelDetails()
    llmModels.value = data.llm || []
    llmProtocols.value = [...new Set((data.llm || []).map((m) => m.protocol).filter(Boolean))]
  } catch {
    // ignore
  }
}

async function showConfigDialog(kb: KnowledgeBase) {
  configKbId.value = kb.id
  configDialogVisible.value = true
  configLoading.value = true

  try {
    const [data] = await Promise.all([
      knowledgeBaseApi.getConfig(spaceId.value, kb.id),
      fetchAvailableModels(),
    ])
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
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '获取配置失败')
  } finally {
    configLoading.value = false
  }
}

function buildSplittingConfig(): SplittingConfig {
  const s = configForm.splittingStrategy
  if (s === 'recursive') {
    return { strategy: 'recursive', chunk_size: configForm.splittingChunkSize, chunk_overlap: configForm.splittingChunkOverlap, min_chunk_size: configForm.splittingMinChunkSize }
  }
  if (s === 'fixed_size') {
    return { strategy: 'fixed_size', chunk_size: configForm.splittingChunkSize, chunk_overlap: configForm.splittingChunkOverlap }
  }
  if (s === 'markdown') {
    return { strategy: 'markdown', max_chunk_size: configForm.splittingMaxChunkSize, min_chunk_size: configForm.splittingMinChunkSize }
  }
  return { strategy: 'semantic', max_chunk_size: configForm.splittingMaxChunkSize, similarity_threshold: configForm.splittingSimilarityThreshold, batch_size: configForm.splittingBatchSize }
}

async function handleSaveConfig() {
  if (!configKbId.value) return

  configSaving.value = true
  try {
    await knowledgeBaseApi.updateConfig(spaceId.value, configKbId.value, {
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
    ElMessage.success('配置已保存')
    configDialogVisible.value = false
    fetchKnowledgeBases()
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '保存配置失败')
  } finally {
    configSaving.value = false
  }
}

// === 选择 ===

function toggleSelect(kbId: number, checked: boolean) {
  if (checked) {
    if (!selectedIds.value.includes(kbId)) {
      selectedIds.value.push(kbId)
    }
  } else {
    selectedIds.value = selectedIds.value.filter((id) => id !== kbId)
  }
}

function clearSelection() {
  selectedIds.value = []
}

// === 知识库列表 ===

async function fetchKnowledgeBases() {
  loading.value = true
  try {
    const data = await knowledgeBaseApi.getKnowledgeBases(spaceId.value)
    knowledgeBases.value = data.items || []
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '获取知识库列表失败')
  } finally {
    loading.value = false
  }
}

// === 编辑 ===

function showEditDialog(kb: KnowledgeBase) {
  editKbId.value = kb.id
  formData.name = kb.name
  formData.description = kb.config?.description || ''
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!formRef.value || !editKbId.value) return

  await formRef.value.validate(async (valid) => {
    if (!valid) return

    submitLoading.value = true
    try {
      await knowledgeBaseApi.updateKnowledgeBase(spaceId.value, editKbId.value!, {
        name: formData.name,
        config: formData.description ? { description: formData.description } : undefined,
      })
      ElMessage.success('知识库更新成功')
      dialogVisible.value = false
      fetchKnowledgeBases()
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: { message?: string } } } }
      ElMessage.error(err.response?.data?.error?.message || '操作失败')
    } finally {
      submitLoading.value = false
    }
  })
}

// === 归档/激活 ===

async function handleArchive(kb: KnowledgeBase) {
  try {
    await ElMessageBox.confirm(`确定要归档知识库 "${kb.name}" 吗？`, '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await knowledgeBaseApi.updateKnowledgeBase(spaceId.value, kb.id, { status: 2 })
    ElMessage.success('知识库已归档')
    fetchKnowledgeBases()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      const err = error as { response?: { data?: { error?: { message?: string } } } }
      ElMessage.error(err.response?.data?.error?.message || '操作失败')
    }
  }
}

async function handleUnarchive(kb: KnowledgeBase) {
  try {
    await knowledgeBaseApi.updateKnowledgeBase(spaceId.value, kb.id, { status: 1 })
    ElMessage.success('知识库已激活')
    fetchKnowledgeBases()
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '操作失败')
  }
}

// === 批量删除 ===

async function handleBatchDelete() {
  if (selectedIds.value.length === 0) return

  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedIds.value.length} 个知识库吗？此操作将删除所有关联文档，且不可恢复。`,
      '批量删除',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'error',
      },
    )
  } catch {
    return
  }

  const ids = [...selectedIds.value]
  let failCount = 0

  for (const id of ids) {
    try {
      await knowledgeBaseApi.deleteKnowledgeBase(spaceId.value, id)
    } catch {
      failCount++
    }
  }

  selectedIds.value = []

  if (failCount === 0) {
    ElMessage.success(`已删除 ${ids.length} 个知识库`)
  } else {
    ElMessage.warning(`${ids.length - failCount} 个删除成功，${failCount} 个删除失败`)
  }

  fetchKnowledgeBases()
}

function goToDocuments(kbId: number) {
  router.push(`/home/spaces/${spaceId.value}/knowledge-bases/${kbId}/documents`)
}

onMounted(() => {
  fetchKnowledgeBases()
})
</script>

<style scoped>
.knowledge-base-view {
  padding-top: var(--space-2);
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--color-danger-subtle);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-danger-subtle);
}

.batch-count {
  font-size: var(--text-sm);
  color: var(--color-danger);
  font-weight: var(--weight-medium);
}

.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-4);
}

.kb-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  overflow: hidden;
  transition: all var(--transition-base);
  display: flex;
  flex-direction: row;
}

.kb-card:hover {
  border-color: var(--color-border);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.kb-card.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
}

.kb-card-accent {
  width: 3px;
  flex-shrink: 0;
}

.kb-card-body {
  padding: var(--space-4) var(--space-5);
  cursor: pointer;
  flex: 1;
  min-width: 0;
}

.kb-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-3);
}

.kb-card-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  flex: 1;
}

.kb-color-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.kb-name {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color var(--transition-fast);
}

.kb-card:hover .kb-name {
  color: var(--color-primary);
}

.kb-status-tag {
  flex-shrink: 0;
  margin-left: var(--space-2);
}

.kb-desc {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: var(--leading-relaxed);
}

.kb-meta {
  display: flex;
  gap: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.meta-item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.kb-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border-top: 1px solid var(--color-border-light);
  opacity: 0;
  transition: opacity var(--transition-base);
}

.kb-card:hover .kb-actions {
  opacity: 1;
}
</style>
