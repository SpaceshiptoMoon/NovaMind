<template>
  <div class="api-key-view">
    <div class="page-header">
      <div>
        <p class="eyebrow">Agent Access</p>
        <h2>API 密钥</h2>
        <p class="desc">
          外部 Agent（Claude Code MCP 等）访问 NovaMind 知识库的凭证。
          密钥继承您的完整权限链，吊销即时生效。
        </p>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="openCreateDialog">创建密钥</el-button>
        <el-button @click="loadKeys">刷新</el-button>
      </div>
    </div>

    <div class="section-card">
      <el-table :data="keys" v-loading="loading">
        <el-table-column prop="name" label="名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="key_prefix" label="密钥前缀" min-width="180">
          <template #default="{ row }">
            <span class="mono-text">{{ row.key_prefix }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">
              {{ row.status === 'active' ? '有效' : '已吊销' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="160">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="last_used_at" label="最后使用" min-width="160">
          <template #default="{ row }">
            <span v-if="row.last_used_at">{{ formatDate(row.last_used_at) }}</span>
            <span v-else class="text-muted">从未使用</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'active'"
              size="small"
              type="danger"
              plain
              :loading="revokingId === row.id"
              @click="confirmRevoke(row)"
            >
              吊销
            </el-button>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="还没有 API 密钥。创建一个，让 Claude Code 等 Agent 检索您的知识库。" />
        </template>
      </el-table>
    </div>

    <!-- 创建对话框 -->
    <el-dialog v-model="createVisible" title="创建 API 密钥" width="440px">
      <el-form @submit.prevent>
        <el-form-item label="密钥名称" required>
          <el-input
            v-model="createName"
            placeholder="如 claude-code-mcp"
            maxlength="100"
            show-word-limit
            @keyup.enter="createKey"
          />
        </el-form-item>
        <p class="form-hint">名称用于在列表中识别密钥，与权限无关——密钥始终继承您的完整权限。</p>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" :disabled="!createName.trim()" @click="createKey">
          创建
        </el-button>
      </template>
    </el-dialog>

    <!-- 明文一次性展示对话框 -->
    <el-dialog v-model="plaintextVisible" title="密钥已创建" width="520px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" show-icon class="plaintext-warning">
        <p>这是密钥明文的<b>唯一一次展示</b>，关闭后不可再查询。请立即复制保存。</p>
      </el-alert>
      <div class="plaintext-row">
        <code class="plaintext-value">{{ createdPlainKey }}</code>
        <el-button type="primary" size="small" @click="copyPlainKey">复制</el-button>
      </div>
      <template #footer>
        <el-button type="primary" @click="plaintextVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiKeyApi } from '@/api/agent'
import type { ApiKeyItem } from '@/api/types'

const keys = ref<ApiKeyItem[]>([])
const loading = ref(false)
const revokingId = ref<number | null>(null)

const createVisible = ref(false)
const creating = ref(false)
const createName = ref('')

const plaintextVisible = ref(false)
const createdPlainKey = ref('')

async function loadKeys() {
  loading.value = true
  try {
    const data = await apiKeyApi.listKeys()
    keys.value = data.keys
  } catch {
    ElMessage.error('密钥列表加载失败')
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  createName.value = ''
  createVisible.value = true
}

async function createKey() {
  const name = createName.value.trim()
  if (!name || creating.value) return
  creating.value = true
  try {
    const created = await apiKeyApi.createKey(name)
    createVisible.value = false
    createdPlainKey.value = created.api_key
    plaintextVisible.value = true
    await loadKeys()
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '创建失败')
  } finally {
    creating.value = false
  }
}

async function copyPlainKey() {
  try {
    await navigator.clipboard.writeText(createdPlainKey.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动选择复制')
  }
}

async function confirmRevoke(key: ApiKeyItem) {
  try {
    await ElMessageBox.confirm(
      `吊销「${key.name}」后，使用该密钥的外部 Agent 将立即失去访问能力。确认吊销？`,
      '吊销确认',
      { confirmButtonText: '吊销', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  revokingId.value = key.id
  try {
    await apiKeyApi.revokeKey(key.id)
    ElMessage.success('已吊销')
    await loadKeys()
  } catch {
    ElMessage.error('吊销失败')
  } finally {
    revokingId.value = null
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

onMounted(loadKeys)
</script>

<style scoped>
.api-key-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.eyebrow {
  margin: 0 0 var(--space-1);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.page-header h2 {
  margin: 0 0 var(--space-2);
  font-size: var(--text-xl);
  font-weight: var(--weight-semibold);
}

.desc {
  margin: 0;
  max-width: 560px;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.section-card {
  padding: var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
}

.mono-text {
  font-family: var(--font-mono, monospace);
  font-size: var(--text-sm);
}

.text-muted {
  color: var(--color-text-muted);
}

.form-hint {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  line-height: 1.6;
}

.plaintext-warning {
  margin-bottom: var(--space-3);
}

.plaintext-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.plaintext-value {
  flex: 1;
  min-width: 0;
  padding: var(--space-2) var(--space-3);
  overflow-x: auto;
  background: var(--color-bg-subtle, var(--color-bg));
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  font-family: var(--font-mono, monospace);
  font-size: var(--text-sm);
  word-break: break-all;
  white-space: nowrap;
}

@media (max-width: 720px) {
  .page-header {
    flex-direction: column;
  }
}
</style>
