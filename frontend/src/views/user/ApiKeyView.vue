<template>
  <div class="api-key-view">
    <!-- 页头：eyebrow + 标题 + 描述（左）与操作（右），对齐 DocumentView page-head 语言 -->
    <section class="page-head">
      <div class="page-head__main">
        <p class="page-head__eyebrow">系统设置</p>
        <h1 class="page-head__title">API 密钥</h1>
        <p class="page-head__desc">
          外部 Agent（Claude Code、MCP 客户端等）访问 NovaMind 知识库的凭证——密钥继承您的完整权限链，吊销即时生效。
        </p>
      </div>
      <div class="page-head__actions">
        <el-button @click="loadKeys" :loading="loading">
          <el-icon class="btn-icon"><Refresh /></el-icon>
          刷新
        </el-button>
        <el-button type="primary" @click="openCreateDialog">
          <el-icon class="btn-icon"><Plus /></el-icon>
          创建密钥
        </el-button>
      </div>
    </section>

    <!-- 单行统计条：有效 / 已吊销 / 总数 -->
    <div class="list-toolbar">
      <div class="stats-inline">
        <div class="stats-item">
          <span class="stats-label">有效</span>
          <strong class="stats-value is-success">{{ activeCount }}</strong>
        </div>
        <span class="stats-divider"></span>
        <div class="stats-item">
          <span class="stats-label">已吊销</span>
          <strong class="stats-value">{{ revokedCount }}</strong>
        </div>
        <span class="stats-divider"></span>
        <div class="stats-item">
          <span class="stats-label">全部</span>
          <strong class="stats-value">{{ keys.length }}</strong>
        </div>
      </div>
      <div class="right-actions">
        <el-checkbox v-model="showRevoked" size="small">显示已吊销</el-checkbox>
      </div>
    </div>

    <div class="section-card">
      <el-table :data="visibleKeys" v-loading="loading">
        <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="key-name" :class="{ 'is-revoked': row.status !== 'active' }">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="key_prefix" label="密钥前缀" min-width="150">
          <template #default="{ row }">
            <span class="mono-text" :class="{ 'is-revoked': row.status !== 'active' }">{{ row.key_prefix }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'" effect="plain">
              {{ row.status === 'active' ? '有效' : '已吊销' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="140">
          <template #default="{ row }">
            <span class="time-text">{{ formatDate(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_used_at" label="最后使用" min-width="140">
          <template #default="{ row }">
            <span v-if="row.last_used_at" class="time-text">{{ formatDate(row.last_used_at) }}</span>
            <span v-else class="time-text is-never">从未使用</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
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
            <span v-else class="time-text">—</span>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">
            <el-empty description="还没有 API 密钥">
              <el-button type="primary" @click="openCreateDialog">创建第一个密钥</el-button>
            </el-empty>
            <p class="empty-hint">创建后配置到 Claude Code / MCP 客户端，即可让 Agent 检索您的知识库。</p>
          </div>
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
    <el-dialog v-model="plaintextVisible" title="密钥已创建" width="560px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" show-icon class="plaintext-warning">
        <p>这是密钥明文的<b>唯一一次展示</b>，关闭后不可再查询。请立即复制保存。</p>
      </el-alert>
      <div class="plaintext-row">
        <code class="plaintext-value">{{ createdPlainKey }}</code>
        <el-button type="primary" size="small" @click="copyPlainKey">
          <el-icon class="btn-icon"><CopyDocument /></el-icon>
          复制
        </el-button>
      </div>
      <div class="next-steps">
        <p class="next-steps__title">接下来把它配置到客户端：</p>
        <code class="next-steps__code">claude mcp add --transport http novamind-kb http://&lt;host&gt;:8100/mcp \</code>
        <code class="next-steps__code">  --header "X-API-Key: &lt;刚复制的密钥&gt;"</code>
      </div>
      <template #footer>
        <el-button type="primary" @click="plaintextVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/** API 密钥管理页：外部 Agent 凭证的创建/吊销/列表（agent_api 凭证面） */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, CopyDocument } from '@element-plus/icons-vue'
import { apiKeyApi } from '@/api/agent'
import type { ApiKeyItem } from '@/api/types'

const keys = ref<ApiKeyItem[]>([])
const loading = ref(false)
const revokingId = ref<number | null>(null)
const showRevoked = ref(true)

const createVisible = ref(false)
const creating = ref(false)
const createName = ref('')

const plaintextVisible = ref(false)
const createdPlainKey = ref('')

const activeCount = computed(() => keys.value.filter((k) => k.status === 'active').length)
const revokedCount = computed(() => keys.value.length - activeCount.value)
const visibleKeys = computed(() =>
  showRevoked.value ? keys.value : keys.value.filter((k) => k.status === 'active'),
)

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
  min-width: 0;
}

/* ===== 页头（对齐 DocumentView page-head 设计语言） ===== */
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.page-head__main {
  min-width: 0;
  flex: 1 1 auto;
}

.page-head__eyebrow {
  margin: 0 0 2px;
  font-size: 12px;
  font-weight: var(--weight-semibold);
  letter-spacing: 0.1em;
  color: var(--color-text-faint);
}

.page-head__title {
  margin: 0;
  font-size: var(--text-2xl);
  letter-spacing: var(--tracking-tight);
}

.page-head__desc {
  margin: 4px 0 0;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  max-width: 560px;
}

.page-head__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.btn-icon {
  margin-right: 4px;
}

/* ===== 单行统计条 ===== */
.list-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.stats-inline {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-4);
}

.stats-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.stats-label {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.stats-value {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  letter-spacing: var(--tracking-tight);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.stats-value.is-success {
  color: var(--color-success);
}

.stats-divider {
  align-self: stretch;
  width: 1px;
  background: var(--color-border-light);
}

.right-actions {
  display: flex;
  align-items: center;
}

/* ===== 列表卡片 ===== */
.section-card {
  padding: var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  min-width: 0;
}

.key-name {
  font-weight: var(--weight-medium);
  color: var(--color-text);
}

.key-name.is-revoked,
.mono-text.is-revoked {
  color: var(--color-text-faint);
}

.mono-text {
  font-family: var(--font-mono, monospace);
  font-size: var(--text-sm);
}

.time-text {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.time-text.is-never {
  color: var(--color-text-faint);
}

/* ===== 空态 ===== */
.empty-state {
  padding: var(--space-4) 0;
}

.empty-hint {
  margin: 0;
  text-align: center;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

/* ===== 创建/明文对话框 ===== */
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
  min-width: 0;
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

.next-steps {
  margin-top: var(--space-3);
  padding: var(--space-3);
  background: var(--color-bg-subtle, var(--color-bg));
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.next-steps__title {
  margin: 0 0 2px;
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--color-text-secondary);
}

.next-steps__code {
  font-family: var(--font-mono, monospace);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  word-break: break-all;
  line-height: 1.6;
}

@media (max-width: 720px) {
  .page-head {
    flex-direction: column;
    align-items: stretch;
  }

  .page-head__actions {
    justify-content: flex-end;
  }

  .plaintext-row {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
