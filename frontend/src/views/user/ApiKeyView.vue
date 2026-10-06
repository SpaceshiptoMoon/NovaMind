<template>
  <div class="api-key-view">
    <div class="page-header">
      <div>
        <p class="eyebrow">Agent Access</p>
        <h2>API 密钥</h2>
        <p class="desc">外部 Agent（Claude Code、MCP 客户端等）访问知识库的凭证——继承您的完整权限链，吊销即时生效</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="openCreateDialog">
          <el-icon class="btn-icon"><Plus /></el-icon>
          创建密钥
        </el-button>
        <el-button @click="loadKeys" :loading="loading">
          <el-icon class="btn-icon"><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
    </div>

    <!-- 数量统计卡：点击切换过滤（有效/已吊销/全部） -->
    <div class="stat-grid">
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': filter === 'active' }"
        @click="filter = 'active'"
      >
        <span class="stat-value">{{ activeCount }}</span>
        <span class="stat-label">有效</span>
      </button>
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': filter === 'revoked' }"
        @click="filter = 'revoked'"
      >
        <span class="stat-value">{{ revokedCount }}</span>
        <span class="stat-label">已吊销</span>
      </button>
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': filter === 'all' }"
        @click="filter = 'all'"
      >
        <span class="stat-value">{{ keys.length }}</span>
        <span class="stat-label">全部</span>
      </button>
    </div>

    <div class="config-section">
      <div class="section-card">
        <h3>{{ sectionTitle }}</h3>
        <el-table :data="visibleKeys" v-loading="loading">
          <el-table-column prop="name" label="名称" min-width="170" show-overflow-tooltip>
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
          <el-table-column prop="created_at" label="创建时间" min-width="150">
            <template #default="{ row }">
              <span class="time-text">{{ formatDate(row.created_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="last_used_at" label="最后使用" min-width="150">
            <template #default="{ row }">
              <span v-if="row.last_used_at" class="time-text">{{ formatDate(row.last_used_at) }}</span>
              <span v-else class="time-text is-never">从未使用</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <template v-if="row.status === 'active'">
                <el-button link type="primary" size="small" @click="copyPrefix(row.key_prefix)">复制前缀</el-button>
                <el-button
                  link
                  type="danger"
                  size="small"
                  :loading="revokingId === row.id"
                  @click="confirmRevoke(row)"
                >
                  吊销
                </el-button>
              </template>
              <span v-else class="time-text">—</span>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :description="emptyText">
              <el-button v-if="filter === 'all'" type="primary" @click="openCreateDialog">创建第一个密钥</el-button>
            </el-empty>
          </template>
        </el-table>
      </div>
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
const filter = ref<'active' | 'revoked' | 'all'>('all')

const createVisible = ref(false)
const creating = ref(false)
const createName = ref('')

const plaintextVisible = ref(false)
const createdPlainKey = ref('')

const activeCount = computed(() => keys.value.filter((k) => k.status === 'active').length)
const revokedCount = computed(() => keys.value.length - activeCount.value)
const visibleKeys = computed(() => {
  if (filter.value === 'active') return keys.value.filter((k) => k.status === 'active')
  if (filter.value === 'revoked') return keys.value.filter((k) => k.status !== 'active')
  return keys.value
})
const sectionTitle = computed(() => {
  if (filter.value === 'active') return `有效密钥（${activeCount.value}）`
  if (filter.value === 'revoked') return `已吊销密钥（${revokedCount.value}）`
  return `全部密钥（${keys.value.length}）`
})
const emptyText = computed(() => {
  if (filter.value === 'active') return '没有有效密钥——点击「已吊销」或「全部」查看其余密钥'
  if (filter.value === 'revoked') return '没有已吊销的密钥'
  return '还没有 API 密钥。创建一个，让 Claude Code 等 Agent 检索您的知识库。'
})

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

async function copyPrefix(prefix: string) {
  try {
    await navigator.clipboard.writeText(prefix)
    ElMessage.success('前缀已复制（完整密钥仅在创建时展示一次）')
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
/* ===== 页头卡片（对齐 ModelConfigView 三件套） ===== */
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
  max-width: 560px;
}

.header-actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

.btn-icon {
  margin-right: 4px;
}

/* ===== 三档统计卡（有效/已吊销/全部，点击即过滤） ===== */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-1);
  padding: var(--space-4);
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

/* ===== 表格区卡片 ===== */
.config-section {
  margin-bottom: var(--space-6);
}

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

.key-name {
  font-weight: var(--weight-medium);
  color: var(--color-text);
}

.key-name.is-revoked,
.mono-text.is-revoked {
  color: var(--color-text-faint);
}

.mono-text {
  font-family: var(--font-mono, Menlo, Consolas, monospace);
  font-size: 12.5px;
}

.time-text {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.time-text.is-never {
  /* 占位信息性文本用 muted 不用 faint（评审实测 faint 档 3.36:1 < WCAG AA 4.5:1） */
  color: var(--color-text-muted);
}

/* ===== 对话框 ===== */
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
  font-family: var(--font-mono, Menlo, Consolas, monospace);
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
  font-family: var(--font-mono, Menlo, Consolas, monospace);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  word-break: break-all;
  line-height: 1.6;
}

/* ===== 窄屏降级 ===== */
@media (max-width: 720px) {
  .page-header {
    flex-direction: column;
    align-items: stretch;
    padding: var(--space-4);
  }

  .header-actions {
    justify-content: flex-end;
  }

  .plaintext-row {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
