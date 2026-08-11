<template>
  <div class="model-config-view">
    <div class="page-header">
      <h2>模型配置</h2>
      <p class="desc">管理您的 LLM、Embedding、Rerank、VLM、ASR 语音识别模型配置</p>
    </div>

    <el-tabs v-model="activeTab" @tab-change="handleTabChange">
      <el-tab-pane label="LLM 模型" name="llm" />
      <el-tab-pane label="Embedding 模型" name="embedding" />
      <el-tab-pane label="Rerank 模型" name="rerank" />
      <el-tab-pane label="VLM 视觉模型" name="vlm" />
      <el-tab-pane label="ASR 语音识别" name="asr" />
      <el-tab-pane label="搜索引擎" name="search" />
    </el-tabs>

    <!-- 模型配置区（非搜索引擎 Tab） -->
    <template v-if="activeTab !== 'search'">
      <div class="toolbar">
        <el-button type="primary" @click="showCreateDialog">新增配置</el-button>
        <el-button @click="fetchConfigs">刷新</el-button>
      </div>

      <!-- 用户配置 -->
      <div class="config-section">
        <h3>我的配置</h3>
        <el-table :data="userConfigs" v-loading="loading" stripe>
          <el-table-column prop="model" label="模型名称" />
          <el-table-column prop="protocol" label="通信协议" width="120" />
          <el-table-column prop="base_url" label="Base URL" show-overflow-tooltip />
          <el-table-column prop="api_key" label="API Key" show-overflow-tooltip />
          <el-table-column label="扩展配置" width="120">
            <template #default="{ row }">
              <span v-if="row.extra_config">{{ JSON.stringify(row.extra_config) }}</span>
              <span v-else class="text-muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="showEditDialog(row)"
                >编辑</el-button
              >
              <el-button link type="danger" size="small" @click="handleDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 创建/编辑对话框 -->
      <el-dialog
        v-model="dialogVisible"
        :title="isEditing ? '编辑配置' : '新增配置'"
        width="560px"
        destroy-on-close
      >
        <el-form ref="formRef" :model="form" :rules="formRules" label-width="100px">
          <el-form-item label="通信协议" prop="protocol">
            <el-select v-model="form.protocol" placeholder="选择协议">
              <el-option
                v-for="p in availableProtocols"
                :key="p.value"
                :label="p.label"
                :value="p.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="模型名称" prop="model">
            <el-input v-model="form.model" placeholder="例如 gpt-4o, glm-4" />
          </el-form-item>
          <el-form-item label="Base URL" prop="base_url">
            <el-input v-model="form.base_url" placeholder="https://api.openai.com/v1" />
          </el-form-item>
          <el-form-item label="API Key" prop="api_key">
            <el-input v-model="form.api_key" type="password" show-password placeholder="sk-..." />
          </el-form-item>
          <el-form-item label="扩展配置">
            <el-input
              v-model="extraConfigStr"
              type="textarea"
              :rows="3"
              placeholder='{"dimension": 1024}'
            />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="info" :loading="testLoading" @click="handleTestForm">测试连接</el-button>
          <el-button type="primary" :loading="submitLoading" @click="handleSubmit">
            {{ isEditing ? '保存' : '创建' }}
          </el-button>
        </template>
      </el-dialog>

      <!-- 测试结果 -->
      <el-dialog v-model="testResultVisible" title="连接测试结果" width="400px">
        <el-result
          v-if="testResult"
          :icon="testResult.success ? 'success' : 'error'"
          :title="testResult.message"
        >
          <template #sub-title>
            <p v-if="testResult.latency_ms">延迟: {{ testResult.latency_ms.toFixed(1) }} ms</p>
            <p v-if="testResult.detected_dimension">
              检测到向量维度: {{ testResult.detected_dimension }}
            </p>
          </template>
        </el-result>
      </el-dialog>
    </template>

    <!-- 搜索引擎配置区 -->
    <template v-else>
      <div class="toolbar">
        <el-button type="primary" @click="showCreateSearchDialog">新增搜索引擎</el-button>
        <el-button @click="fetchSearchConfigs">刷新</el-button>
      </div>

      <div class="config-section">
        <h3>我的搜索引擎配置</h3>
        <p class="desc search-hint">
          配置联网搜索服务商凭证，工作台 AI 聊天「联网搜索」将按首选 provider
          检索；未配置或失败时回退全局默认。
        </p>
        <el-table :data="searchConfigs" v-loading="searchLoading" stripe>
          <el-table-column label="服务商" width="160">
            <template #default="{ row }: { row: SearchEngineConfig }">
              <el-tag v-if="row.is_primary" type="success" size="small" class="primary-tag"
                >首选</el-tag
              >
              <span>{{ SEARCH_PROVIDER_LABELS[row.provider] || row.provider }}</span>
            </template>
          </el-table-column>
          <el-table-column label="API Key" show-overflow-tooltip>
            <template #default="{ row }: { row: SearchEngineConfig }">
              <span v-if="row.api_key">{{ row.api_key }}</span>
              <span v-else class="text-muted">未设置（免费）</span>
            </template>
          </el-table-column>
          <el-table-column label="扩展配置" width="200" show-overflow-tooltip>
            <template #default="{ row }: { row: SearchEngineConfig }">
              <span v-if="row.extra_config">{{ JSON.stringify(row.extra_config) }}</span>
              <span v-else class="text-muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }: { row: SearchEngineConfig }">
              <el-button
                link
                type="primary"
                size="small"
                :disabled="row.is_primary"
                @click="handleSetSearchPrimary(row)"
                >设为默认</el-button
              >
              <el-button link type="primary" size="small" @click="showEditSearchDialog(row)"
                >编辑</el-button
              >
              <el-button link type="danger" size="small" @click="handleDeleteSearch(row)"
                >删除</el-button
              >
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 搜索引擎 创建/编辑对话框 -->
      <el-dialog
        v-model="searchDialogVisible"
        :title="searchIsEditing ? '编辑搜索引擎' : '新增搜索引擎'"
        width="560px"
        destroy-on-close
      >
        <el-form
          ref="searchFormRef"
          :model="searchForm"
          :rules="searchFormRules"
          label-width="100px"
        >
          <el-form-item label="服务商" prop="provider">
            <el-select
              v-model="searchForm.provider"
              :disabled="searchIsEditing"
              placeholder="选择搜索服务商"
            >
              <el-option
                v-for="opt in SEARCH_PROVIDER_OPTIONS"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="API Key" prop="api_key">
            <el-input
              v-model="searchForm.api_key"
              type="password"
              show-password
              :placeholder="searchApiKeyPlaceholder"
            />
            <div class="form-tip" v-if="searchIsEditing">留空表示不修改原 Key</div>
            <div class="form-tip" v-else-if="searchForm.provider === 'duckduckgo'">
              DuckDuckGo 免费无需 Key
            </div>
          </el-form-item>
          <el-form-item label="扩展配置">
            <el-input
              v-model="searchExtraConfigStr"
              type="textarea"
              :rows="3"
              placeholder='{"max_results": 10, "search_depth": "basic"}'
            />
          </el-form-item>
          <el-form-item label="设为首选">
            <el-switch v-model="searchForm.is_primary" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="searchDialogVisible = false">取消</el-button>
          <el-button type="info" :loading="searchTestLoading" @click="handleTestSearchForm"
            >测试连接</el-button
          >
          <el-button type="primary" :loading="searchSubmitLoading" @click="handleSubmitSearch">
            {{ searchIsEditing ? '保存' : '创建' }}
          </el-button>
        </template>
      </el-dialog>

      <!-- 搜索测试结果 -->
      <el-dialog v-model="searchTestResultVisible" title="搜索测试结果" width="420px">
        <el-result
          v-if="searchTestResult"
          :icon="searchTestResult.success ? 'success' : 'error'"
          :title="searchTestResult.message"
        >
          <template #sub-title>
            <p v-if="searchTestResult.latency_ms != null">
              延迟: {{ searchTestResult.latency_ms.toFixed(1) }} ms
            </p>
            <p v-if="searchTestResult.results_count != null">
              返回结果数: {{ searchTestResult.results_count }}
            </p>
          </template>
        </el-result>
      </el-dialog>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { userApi } from '@/api/user'
import type {
  ModelConfig,
  ModelConfigTestResponse,
  SearchEngineConfig,
  SearchEngineTestResponse,
  SearchProvider,
} from '@/api/types'

type TabName = 'llm' | 'embedding' | 'rerank' | 'vlm' | 'asr' | 'search'
const activeTab = ref<TabName>('llm')
const loading = ref(false)
const submitLoading = ref(false)
const testLoading = ref(false)
const dialogVisible = ref(false)
const testResultVisible = ref(false)
const isEditing = ref(false)
const editingId = ref<number | null>(null)

const userConfigList = ref<ModelConfig[]>([])

const formRef = ref<FormInstance>()
const extraConfigStr = ref('')

const form = ref({
  protocol: 'openai',
  model: '',
  base_url: '',
  api_key: '',
})

const formRules = computed<FormRules>(() => ({
  protocol: [{ required: true, message: '请选择通信协议', trigger: 'change' }],
  model: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
  api_key:
    form.value.protocol === 'local'
      ? []
      : [{ required: true, message: '请输入 API Key', trigger: 'blur' }],
}))

const userConfigs = computed(() =>
  userConfigList.value.filter((c) => c.model_type === activeTab.value),
)

// 各模型类型支持的协议（与后端 factory 一致）
const PROTOCOL_OPTIONS: Record<string, { value: string; label: string }[]> = {
  llm: [
    { value: 'openai', label: 'OpenAI' },
    { value: 'anthropic', label: 'Anthropic' },
    { value: 'ollama', label: 'Ollama' },
    { value: 'transformers', label: 'Transformers' },
  ],
  embedding: [
    { value: 'openai', label: 'OpenAI' },
    { value: 'ollama', label: 'Ollama' },
    { value: 'transformers', label: 'Transformers' },
  ],
  rerank: [
    { value: 'openai', label: 'OpenAI' },
    { value: 'transformers', label: 'Transformers' },
  ],
  vlm: [
    { value: 'openai', label: 'OpenAI' },
    { value: 'anthropic', label: 'Anthropic' },
    { value: 'ollama', label: 'Ollama' },
  ],
  asr: [
    { value: 'local', label: '本地 (faster-whisper)' },
    { value: 'openai', label: 'OpenAI (Whisper)' },
    { value: 'dashscope', label: 'DashScope (Paraformer)' },
  ],
}

const availableProtocols = computed(() => PROTOCOL_OPTIONS[activeTab.value] || [])

async function fetchConfigs() {
  loading.value = true
  try {
    const data = await userApi.getModelConfigs()
    userConfigList.value = data.items
  } catch {
    userConfigList.value = []
  } finally {
    loading.value = false
  }
}

function handleTabChange() {
  // 切到搜索引擎 Tab 时懒加载搜索配置（模型配置已全量缓存）
  if (activeTab.value === 'search' && searchConfigs.value.length === 0 && !searchLoaded.value) {
    fetchSearchConfigs()
  }
}

function showCreateDialog() {
  isEditing.value = false
  editingId.value = null
  const defaultProtocol = availableProtocols.value[0]?.value || 'openai'
  form.value = { protocol: defaultProtocol, model: '', base_url: '', api_key: '' }
  extraConfigStr.value = ''
  dialogVisible.value = true
}

function showEditDialog(row: ModelConfig) {
  isEditing.value = true
  editingId.value = row.id
  form.value = {
    protocol: row.protocol,
    model: row.model,
    base_url: row.base_url || '',
    api_key: '',
  }
  extraConfigStr.value = row.extra_config ? JSON.stringify(row.extra_config, null, 2) : ''
  dialogVisible.value = true
}

async function handleSubmit() {
  await formRef.value?.validate()
  submitLoading.value = true
  try {
    let extraConfig = null
    if (extraConfigStr.value.trim()) {
      try {
        extraConfig = JSON.parse(extraConfigStr.value)
      } catch {
        ElMessage.error('扩展配置 JSON 格式错误')
        return
      }
    }

    const payload = {
      ...form.value,
      model_type: activeTab.value as 'llm' | 'embedding' | 'rerank' | 'vlm' | 'asr',
      extra_config: extraConfig,
    }

    if (isEditing.value && editingId.value) {
      await userApi.updateModelConfig(editingId.value, payload)
      ElMessage.success('配置已更新')
    } else {
      await userApi.createModelConfig(payload)
      ElMessage.success('配置已创建')
    }
    dialogVisible.value = false
    fetchConfigs()
  } finally {
    submitLoading.value = false
  }
}

async function handleTestForm() {
  testLoading.value = true
  try {
    const result = await userApi.testModelConfig({
      model_type: activeTab.value as 'llm' | 'embedding' | 'rerank' | 'vlm' | 'asr',
      ...form.value,
      api_key: form.value.api_key || '',
    })
    showTestResult(result)
  } catch (e) {
    showTestResult({
      success: false,
      message: e instanceof Error ? e.message : '测试失败',
      latency_ms: null,
      detected_dimension: null,
    })
  } finally {
    testLoading.value = false
  }
}

const testResult = ref<ModelConfigTestResponse | null>(null)
function showTestResult(result: ModelConfigTestResponse) {
  testResult.value = result
  testResultVisible.value = true
}

async function handleDelete(row: ModelConfig) {
  try {
    await ElMessageBox.confirm(`确定删除配置 "${row.model}"？`, '删除确认', { type: 'warning' })
    await userApi.deleteModelConfig(row.id)
    ElMessage.success('配置已删除')
    fetchConfigs()
  } catch (e) {
    if (e !== 'cancel') {
      const msg = (e as { message?: string })?.message || '删除失败'
      ElMessage.error(msg)
    }
  }
}

// ===================== 搜索引擎配置 =====================

const SEARCH_PROVIDER_OPTIONS: { value: SearchProvider; label: string }[] = [
  { value: 'tavily', label: 'Tavily' },
  { value: 'serpapi', label: 'SerpAPI' },
  { value: 'duckduckgo', label: 'DuckDuckGo（免费）' },
]

const SEARCH_PROVIDER_LABELS: Record<SearchProvider, string> = {
  tavily: 'Tavily',
  serpapi: 'SerpAPI',
  duckduckgo: 'DuckDuckGo',
}

const searchConfigs = ref<SearchEngineConfig[]>([])
const searchLoading = ref(false)
const searchLoaded = ref(false)
const searchDialogVisible = ref(false)
const searchIsEditing = ref(false)
const searchEditingId = ref<number | null>(null)
const searchSubmitLoading = ref(false)
const searchTestLoading = ref(false)
const searchTestResultVisible = ref(false)
const searchTestResult = ref<SearchEngineTestResponse | null>(null)
const searchFormRef = ref<FormInstance>()
const searchExtraConfigStr = ref('')

const searchForm = ref({
  provider: 'tavily' as SearchProvider,
  api_key: '',
  is_primary: false,
})

const searchFormRules = computed<FormRules>(() => ({
  provider: [{ required: true, message: '请选择搜索服务商', trigger: 'change' }],
  api_key:
    searchForm.value.provider === 'duckduckgo'
      ? []
      : [
          { required: true, message: '请输入 API Key', trigger: 'blur' },
          ...(searchIsEditing.value
            ? []
            : [{ required: true, message: '请输入 API Key', trigger: 'blur' }]),
        ],
}))

const searchApiKeyPlaceholder = computed(() => {
  if (searchForm.value.provider === 'duckduckgo') return 'DuckDuckGo 免费，无需 Key'
  return 'tvly-... / serpapi-...'
})

async function fetchSearchConfigs() {
  searchLoading.value = true
  try {
    const data = await userApi.getSearchEngineConfigs()
    searchConfigs.value = data.items
    searchLoaded.value = true
  } catch {
    searchConfigs.value = []
  } finally {
    searchLoading.value = false
  }
}

function showCreateSearchDialog() {
  searchIsEditing.value = false
  searchEditingId.value = null
  searchForm.value = { provider: 'tavily', api_key: '', is_primary: false }
  searchExtraConfigStr.value = ''
  searchDialogVisible.value = true
}

function showEditSearchDialog(row: SearchEngineConfig) {
  searchIsEditing.value = true
  searchEditingId.value = row.id
  searchForm.value = {
    provider: row.provider,
    api_key: '', // 留空 = 不改
    is_primary: row.is_primary,
  }
  searchExtraConfigStr.value = row.extra_config ? JSON.stringify(row.extra_config, null, 2) : ''
  searchDialogVisible.value = true
}

function parseSearchExtraConfig(): Record<string, unknown> | undefined {
  if (!searchExtraConfigStr.value.trim()) return undefined
  try {
    return JSON.parse(searchExtraConfigStr.value)
  } catch {
    ElMessage.error('扩展配置 JSON 格式错误')
    throw new Error('invalid json')
  }
}

async function handleSubmitSearch() {
  await searchFormRef.value?.validate()
  searchSubmitLoading.value = true
  try {
    const extraConfig = parseSearchExtraConfig()
    if (searchIsEditing.value && searchEditingId.value) {
      // 编辑：api_key 留空 = 不改；payload 不含 provider
      await userApi.updateSearchEngineConfig(searchEditingId.value, {
        api_key: searchForm.value.api_key || undefined,
        extra_config: extraConfig,
        is_primary: searchForm.value.is_primary,
      })
      ElMessage.success('搜索引擎配置已更新')
    } else {
      await userApi.createSearchEngineConfig({
        provider: searchForm.value.provider,
        api_key: searchForm.value.api_key || undefined,
        extra_config: extraConfig,
        is_primary: searchForm.value.is_primary,
      })
      ElMessage.success('搜索引擎配置已创建')
    }
    searchDialogVisible.value = false
    fetchSearchConfigs()
  } catch (e) {
    if (e instanceof Error && e.message === 'invalid json') return
    ElMessage.error(e instanceof Error ? e.message : '操作失败')
  } finally {
    searchSubmitLoading.value = false
  }
}

async function handleTestSearchForm() {
  // 新建态：直接用表单值测试；编辑态：api_key 留空时无法测原 Key，提示用户填写
  if (
    !searchIsEditing.value &&
    searchForm.value.provider !== 'duckduckgo' &&
    !searchForm.value.api_key
  ) {
    ElMessage.warning('请先填写 API Key')
    return
  }
  searchTestLoading.value = true
  try {
    const extraConfig = parseSearchExtraConfig()
    const result = await userApi.testSearchEngineConfig({
      provider: searchForm.value.provider,
      api_key: searchForm.value.api_key || undefined,
      extra_config: extraConfig,
    })
    searchTestResult.value = result
    searchTestResultVisible.value = true
  } catch (e) {
    searchTestResult.value = {
      success: false,
      message: e instanceof Error ? e.message : '测试失败',
      latency_ms: null,
      results_count: 0,
    }
    searchTestResultVisible.value = true
  } finally {
    searchTestLoading.value = false
  }
}

async function handleSetSearchPrimary(row: SearchEngineConfig) {
  try {
    await userApi.setSearchEnginePrimary(row.id)
    ElMessage.success(`已将 ${SEARCH_PROVIDER_LABELS[row.provider]} 设为默认搜索引擎`)
    fetchSearchConfigs()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '设置失败')
  }
}

async function handleDeleteSearch(row: SearchEngineConfig) {
  try {
    await ElMessageBox.confirm(
      `确定删除搜索引擎配置 "${SEARCH_PROVIDER_LABELS[row.provider]}"？`,
      '删除确认',
      { type: 'warning' },
    )
    await userApi.deleteSearchEngineConfig(row.id)
    ElMessage.success('配置已删除')
    fetchSearchConfigs()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error((e as { message?: string })?.message || '删除失败')
    }
  }
}

onMounted(() => {
  fetchConfigs()
})
</script>

<style scoped>
.model-config-view {
  max-width: 1000px;
}

.page-header {
  margin-bottom: var(--space-5);
}

.page-header h2 {
  margin: 0 0 var(--space-1);
  font-size: var(--text-xl);
}

.page-header .desc {
  color: var(--color-text-muted);
  font-size: var(--text-base);
  margin: 0;
}

.toolbar {
  margin-bottom: var(--space-4);
}

.config-section {
  margin-bottom: var(--space-6);
}

.config-section h3 {
  font-size: var(--text-md);
  margin: 0 0 var(--space-3);
  color: var(--color-text-secondary);
}

.text-muted {
  color: var(--color-text-faint);
}

.search-hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
}

.primary-tag {
  margin-right: var(--space-1);
}

.form-tip {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  line-height: 1.4;
  margin-top: var(--space-1);
}
</style>
