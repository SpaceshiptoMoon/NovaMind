<template>
  <div class="model-config-view">
    <div class="page-header">
      <div>
        <p class="eyebrow">Model Settings</p>
        <h2>模型配置</h2>
        <p class="desc">管理您的 LLM、Embedding、Rerank、VLM、ASR 语音识别与搜索引擎配置</p>
      </div>
      <div class="header-actions">
        <el-button v-if="activeTab !== 'search'" type="primary" @click="showCreateDialog">
          新增配置
        </el-button>
        <el-button v-else type="primary" @click="showCreateSearchDialog">新增搜索引擎</el-button>
        <el-button v-if="activeTab !== 'search'" @click="fetchConfigs">刷新</el-button>
        <el-button v-else @click="fetchSearchConfigs">刷新</el-button>
      </div>
    </div>

    <!-- 配置数量统计：点击切换类型 -->
    <div class="stat-grid">
      <button
        v-for="card in typeCards"
        :key="card.type"
        type="button"
        class="stat-card"
        :class="{ 'is-active': activeTab === card.type }"
        @click="switchTab(card.type)"
      >
        <span class="stat-value">{{ card.count ?? '—' }}</span>
        <span class="stat-label">{{ card.label }}</span>
      </button>
    </div>

    <el-tabs v-model="activeTab" class="config-tabs" @tab-change="handleTabChange">
      <el-tab-pane label="LLM 模型" name="llm" />
      <el-tab-pane label="Embedding 模型" name="embedding" />
      <el-tab-pane label="Rerank 模型" name="rerank" />
      <el-tab-pane label="VLM 视觉模型" name="vlm" />
      <el-tab-pane label="ASR 语音识别" name="asr" />
      <el-tab-pane label="搜索引擎" name="search" />
    </el-tabs>

    <!-- 模型配置区（非搜索引擎 Tab） -->
    <template v-if="activeTab !== 'search'">
      <!-- 用户配置 -->
      <div class="config-section">
        <div class="section-card">
          <h3>我的配置</h3>
          <el-table :data="userConfigs" v-loading="loading" stripe>
            <el-table-column prop="model" label="模型名称" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="mono-text">{{ row.model }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="protocol" label="协议" width="100">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ row.protocol }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="base_url" label="Base URL" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="mono-text text-muted">{{ row.base_url || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="api_key" label="API Key" width="90" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="mono-text">{{ row.api_key || '未设置' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="扩展配置" width="150" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="row.extra_config" class="mono-text">{{
                  JSON.stringify(row.extra_config)
                }}</span>
                <span v-else class="text-muted">-</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="130" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="showEditDialog(row)"
                  >编辑</el-button
                >
                <el-button link type="danger" size="small" @click="handleDelete(row)"
                  >删除</el-button
                >
              </template>
            </el-table-column>
          </el-table>
        </div>
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
      <div class="config-section">
        <div class="section-card">
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
/**
 * 用户级模型配置页。
 *
 * 对应路由 /home/settings/models，按 Tab 管理 LLM/Embedding/Rerank/VLM/ASR 五类模型凭证
 * 与搜索引擎（Tavily/SerpAPI/DuckDuckGo）配置，均支持新增/编辑/删除/连接测试。
 * 搜索引擎 Tab 懒加载；编辑时 API Key 留空表示不修改原 Key，编辑态 payload 不含 provider。
 */

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

/** 六类配置数量统计卡（search 懒加载，未加载前显示 —） */
const typeCards = computed(() => [
  {
    type: 'llm' as const,
    label: 'LLM 模型',
    count: userConfigList.value.filter((c) => c.model_type === 'llm').length,
  },
  {
    type: 'embedding' as const,
    label: 'Embedding',
    count: userConfigList.value.filter((c) => c.model_type === 'embedding').length,
  },
  {
    type: 'rerank' as const,
    label: 'Rerank',
    count: userConfigList.value.filter((c) => c.model_type === 'rerank').length,
  },
  {
    type: 'vlm' as const,
    label: 'VLM 视觉',
    count: userConfigList.value.filter((c) => c.model_type === 'vlm').length,
  },
  {
    type: 'asr' as const,
    label: 'ASR 语音',
    count: userConfigList.value.filter((c) => c.model_type === 'asr').length,
  },
  {
    type: 'search' as const,
    label: '搜索引擎',
    count: searchLoaded.value ? searchConfigs.value.length : null,
  },
])

/** 统计卡点击切换类型（等价于切 Tab，并触发同样的懒加载逻辑） */
function switchTab(type: TabName) {
  activeTab.value = type
  handleTabChange()
}

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

/** 拉取用户全部模型配置，前端按当前 Tab 的 model_type 过滤展示。 */
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

/** 创建或更新模型配置：扩展配置 textarea 需为合法 JSON，随 Tab 类型落 model_type。 */
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

/** 用表单当前值（未保存的草稿配置）调用后端连通性测试并弹出结果。 */
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

/** 解析扩展配置 textarea；非法 JSON 时提示并抛错，由提交方中断流程。 */
function parseSearchExtraConfig(): Record<string, unknown> | undefined {
  if (!searchExtraConfigStr.value.trim()) return undefined
  try {
    return JSON.parse(searchExtraConfigStr.value)
  } catch {
    ElMessage.error('扩展配置 JSON 格式错误')
    throw new Error('invalid json')
  }
}

/** 创建或更新搜索引擎配置；编辑态 api_key 留空 = 不修改，payload 不回传 provider。 */
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

/** 草稿连通性测试；编辑态 api_key 留空时无法取到原 Key，前置拦截提示填写。 */
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
/* width:100% 必须显式声明：本页处于 flex column 容器，cross-axis 的
   margin:auto 会让子项退化为 fit-content 宽（页面随表格内容伸缩，
   切 Tab 时整页宽度跳动、前后不对齐） */
.model-config-view {
  width: 100%;
  max-width: 1200px;
  padding: var(--space-6) var(--space-6) var(--space-8);
  margin: 0 auto;
}

/* ===== 页头 panel：左文右操作，对齐任务列表页的 dashboard 风格 ===== */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: var(--space-4);
  flex-wrap: wrap;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  padding: var(--space-5) var(--space-6);
  margin-bottom: var(--space-5);
}

.eyebrow {
  margin: 0 0 var(--space-1);
  font-size: 12px;
  font-weight: var(--weight-semibold);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-text-faint);
}

.page-header h2 {
  margin: 0 0 var(--space-1);
  font-size: 22px;
  font-weight: var(--weight-bold);
}

.page-header .desc {
  color: var(--color-text-muted);
  font-size: var(--text-base);
  margin: 0;
}

.header-actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

/* ===== 六类配置数量统计卡 ===== */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-1);
  padding: var(--space-4) var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition:
    border-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.stat-card:hover {
  border-color: var(--color-text-faint);
  box-shadow: var(--shadow-xs);
}

.stat-card.is-active {
  border-color: var(--color-primary);
  box-shadow: inset 0 0 0 1px var(--color-primary);
}

.stat-value {
  font-size: 22px;
  font-weight: var(--weight-bold);
  font-variant-numeric: tabular-nums;
  color: var(--color-text);
  line-height: 1.1;
}

.stat-label {
  font-size: 12px;
  color: var(--color-text-muted);
}

.config-tabs {
  margin-bottom: var(--space-4);
}

.config-section {
  margin-bottom: var(--space-6);
}

/* 配置列表卡片：白底 + 边框 + 圆角，与全站卡片语言一致 */
.section-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  padding: var(--space-5) var(--space-6);
}

.config-section h3 {
  font-size: var(--text-md);
  margin: 0 0 var(--space-3);
  color: var(--color-text-secondary);
}

.text-muted {
  color: var(--color-text-faint);
}

/* 模型名 / Base URL / Key 等技术标识用等宽字体，避免视觉挤压 */
.mono-text {
  font-family: var(--font-mono, Menlo, Consolas, monospace);
  font-size: 12.5px;
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

/* 窄屏：统计卡 6 → 3 → 2 列降级 */
@media (max-width: 960px) {
  .stat-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .page-header {
    padding: var(--space-4);
  }
}
</style>
