<template>
  <div class="model-config-view">
    <div class="page-header">
      <h2>模型配置</h2>
      <p class="desc">管理您的私有 LLM、Embedding、Rerank 模型配置</p>
    </div>

    <el-tabs v-model="activeTab" @tab-change="handleTabChange">
      <el-tab-pane label="LLM 模型" name="llm" />
      <el-tab-pane label="Embedding 模型" name="embedding" />
      <el-tab-pane label="Rerank 模型" name="rerank" />
    </el-tabs>

    <div class="toolbar">
      <el-button type="primary" @click="showCreateDialog">新增配置</el-button>
      <el-button @click="fetchConfigs">刷新</el-button>
    </div>

    <!-- 系统配置（只读） -->
    <div v-if="systemConfigs.length" class="config-section">
      <h3>系统配置</h3>
      <el-table :data="systemConfigs" stripe>
        <el-table-column prop="model" label="模型名称" />
        <el-table-column prop="protocol" label="通信协议" width="120" />
        <el-table-column prop="base_url" label="Base URL" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default>
            <el-tag type="info" size="small">系统</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 用户私有配置 -->
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
            <el-button link type="primary" size="small" @click="showEditDialog(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 创建/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="isEditing ? '编辑配置' : '新增配置'" width="560px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="100px">
        <el-form-item label="通信协议" prop="protocol">
          <el-select v-model="form.protocol" placeholder="选择协议">
            <el-option label="OpenAI" value="openai" />
            <el-option label="Anthropic" value="anthropic" />
            <el-option label="Ollama" value="ollama" />
            <el-option label="Transformers" value="transformers" />
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
          <el-input v-model="extraConfigStr" type="textarea" :rows="3" placeholder='{"dimension": 1024}' />
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
      <el-result v-if="testResult" :icon="testResult.success ? 'success' : 'error'" :title="testResult.message">
        <template #sub-title>
          <p v-if="testResult.latency_ms">延迟: {{ testResult.latency_ms.toFixed(1) }} ms</p>
          <p v-if="testResult.detected_dimension">检测到向量维度: {{ testResult.detected_dimension }}</p>
        </template>
      </el-result>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { userApi } from '@/api/user'
import type { ModelConfig, ModelConfigTestResponse, AvailableModelItem } from '@/api/types'

const activeTab = ref<'llm' | 'embedding' | 'rerank'>('llm')
const loading = ref(false)
const submitLoading = ref(false)
const testLoading = ref(false)
const dialogVisible = ref(false)
const testResultVisible = ref(false)
const isEditing = ref(false)
const editingId = ref<number | null>(null)

const availableDetail = ref<{ llm: AvailableModelItem[]; embedding: AvailableModelItem[]; rerank: AvailableModelItem[] }>({
  llm: [], embedding: [], rerank: [],
})
const userConfigList = ref<ModelConfig[]>([])

const formRef = ref<FormInstance>()
const extraConfigStr = ref('')

const form = ref({
  protocol: 'openai',
  model: '',
  base_url: '',
  api_key: '',
})

const formRules: FormRules = {
  protocol: [{ required: true, message: '请选择通信协议', trigger: 'change' }],
  model: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
  api_key: [{ required: true, message: '请输入 API Key', trigger: 'blur' }],
}

const systemConfigs = computed(() => availableDetail.value[activeTab.value].filter((c) => c.is_system))
const userConfigs = computed(() => userConfigList.value.filter((c) => c.model_type === activeTab.value))

async function fetchAvailable() {
  try {
    availableDetail.value = await userApi.getAvailableModelDetails()
  } catch {
    // ignore
  }
}

async function fetchConfigs() {
  loading.value = true
  try {
    const data = await userApi.getModelConfigs(activeTab.value)
    userConfigList.value = data.items
  } catch {
    userConfigList.value = []
  } finally {
    loading.value = false
  }
}

function handleTabChange() {
  fetchConfigs()
}

function showCreateDialog() {
  isEditing.value = false
  editingId.value = null
  form.value = { protocol: 'openai', model: '', base_url: '', api_key: '' }
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

    const payload = { ...form.value, model_type: activeTab.value, extra_config: extraConfig }

    if (isEditing.value && editingId.value) {
      await userApi.updateModelConfig(editingId.value, payload)
      ElMessage.success('配置已更新')
    } else {
      await userApi.createModelConfig(payload)
      ElMessage.success('配置已创建')
    }
    dialogVisible.value = false
    fetchConfigs()
    fetchAvailable()
  } finally {
    submitLoading.value = false
  }
}

async function handleTestForm() {
  testLoading.value = true
  try {
    const result = await userApi.testModelConfig({
      model_type: activeTab.value,
      ...form.value,
      api_key: form.value.api_key || '',
    })
    showTestResult(result)
  } catch (e) {
    showTestResult({ success: false, message: e instanceof Error ? e.message : '测试失败', latency_ms: null, detected_dimension: null })
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
    fetchAvailable()
  } catch (e) {
    if (e !== 'cancel') {
      const msg = (e as { message?: string })?.message || '删除失败'
      ElMessage.error(msg)
    }
  }
}

onMounted(() => {
  fetchAvailable()
  fetchConfigs()
})
</script>

<style scoped>
.model-config-view {
  max-width: 1000px;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0 0 4px;
  font-size: 20px;
}

.page-header .desc {
  color: var(--color-text-muted);
  font-size: 14px;
  margin: 0;
}

.toolbar {
  margin-bottom: 16px;
}

.config-section {
  margin-bottom: 24px;
}

.config-section h3 {
  font-size: 15px;
  margin: 0 0 12px;
  color: var(--color-text-secondary);
}

.text-muted {
  color: var(--color-text-faint);
}
</style>
