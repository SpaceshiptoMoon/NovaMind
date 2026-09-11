<template>
  <div class="knowledge-base-view">
    <!-- 知识库卡片网格（ima 竖卡：色块缩略区 + 名称 + 描述 + 元信息条） -->
    <div v-loading="loading" class="kb-grid">
      <div
        v-for="(kb, index) in knowledgeBases"
        :key="kb.id"
        class="kb-card"
        @click="goToDocuments(kb.id)"
      >
        <!-- 缩略区：首字 + 状态角标 -->
        <div class="kb-card-cover" :style="{ ...getCoverBg(index), color: getCoverFg(index) }">
          <span class="kb-cover-initial">{{ kb.name.charAt(0) }}</span>
          <span class="kb-status-label">{{ kb.status === 1 ? '活跃' : '已归档' }}</span>
        </div>

        <!-- 主体 -->
        <div class="kb-card-body">
          <h4 class="kb-name">{{ kb.name }}</h4>
          <p class="kb-desc">{{ kb.config?.description || '暂无描述' }}</p>

          <!-- 元信息条 + hover 操作 -->
          <div class="kb-card-footer">
            <span class="meta-item">
              <el-icon :size="13"><Document /></el-icon>
              {{ kb.stats?.document_count ?? 0 }} 文档
            </span>
            <div class="kb-actions" @click.stop>
              <el-tooltip content="编辑" placement="top">
                <el-button size="small" circle text aria-label="编辑" @click="showEditDialog(kb)">
                  <el-icon><Edit /></el-icon>
                </el-button>
              </el-tooltip>
              <el-tooltip content="配置" placement="top">
                <el-button size="small" circle text aria-label="配置" @click="goConfig(kb)">
                  <el-icon><Setting /></el-icon>
                </el-button>
              </el-tooltip>
              <el-tooltip v-if="kb.status === 1" content="归档" placement="top">
                <el-button size="small" circle text aria-label="归档" @click="handleArchive(kb)">
                  <el-icon><FolderOpened /></el-icon>
                </el-button>
              </el-tooltip>
              <el-tooltip v-else content="激活" placement="top">
                <el-button size="small" circle text aria-label="激活" @click="handleUnarchive(kb)">
                  <el-icon><FolderAdd /></el-icon>
                </el-button>
              </el-tooltip>
              <el-tooltip content="删除" placement="top">
                <el-button size="small" circle text aria-label="删除" @click="handleDeleteSingle(kb)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </el-tooltip>
            </div>
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <EmptyState
        v-if="!loading && knowledgeBases.length === 0"
        variant="default"
        headline="暂无知识库"
        description="创建知识库，上传文档，开始构建你的知识体系"
      >
        <el-button type="primary" @click="handleQuickCreateKb">
          新建知识库
        </el-button>
      </EmptyState>
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
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Edit, Setting, FolderOpened, FolderAdd, Delete } from '@element-plus/icons-vue'
import { knowledgeBaseApi } from '@/api/knowledge'
import type { KnowledgeBase } from '@/api/types'
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

// KB 缩略区柔和底色（ima 文件卡片同款思路：低饱和浅色底 + 深色首字）
const coverPalette = [
  { bg: '#EEF2FF', fg: '#4F46E5' }, // 靛
  { bg: '#ECFEFF', fg: '#0E7490' }, // 青
  { bg: '#F0FDF4', fg: '#15803D' }, // 绿
  { bg: '#FFF7ED', fg: '#C2410C' }, // 橙
  { bg: '#FDF4FF', fg: '#7E22CE' }, // 紫
  { bg: '#FEF2F2', fg: '#B91C1C' }, // 红
  { bg: '#F8FAFC', fg: '#475569' }, // 灰蓝
]

function getCoverBg(index: number): { background: string } {
  const c = coverPalette[index % coverPalette.length] ?? coverPalette[0]
  return { background: c?.bg ?? '#F8FAFC' }
}

function getCoverFg(index: number): string {
  return coverPalette[index % coverPalette.length]?.fg ?? '#475569'
}

// === 跳转配置向导页 ===

function goConfig(kb: KnowledgeBase) {
  router.push({ name: 'KbConfig', params: { id: spaceId.value, kbId: kb.id } })
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

// === 单个删除 ===

async function handleDeleteSingle(kb: KnowledgeBase) {
  try {
    await ElMessageBox.confirm(
      `确定要删除知识库「${kb.name}」吗？此操作将删除该知识库下的所有文档，且不可恢复。`,
      '删除知识库',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'error',
      },
    )
  } catch {
    return
  }

  try {
    await knowledgeBaseApi.deleteKnowledgeBase(spaceId.value, kb.id)
    ElMessage.success(`已删除知识库「${kb.name}」`)
    fetchKnowledgeBases()
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '删除失败')
  }
}

function goToDocuments(kbId: number) {
  router.push(`/home/spaces/${spaceId.value}/knowledge-bases/${kbId}/documents`)
}

async function handleQuickCreateKb() {
  try {
    const { value } = await ElMessageBox.prompt('请输入知识库名称', '新建知识库', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputPattern: /\S/,
      inputErrorMessage: '名称不能为空',
    })
    if (value) {
      await knowledgeBaseApi.createKnowledgeBase(spaceId.value, { name: value.trim() })
      ElMessage.success('知识库创建成功')
      fetchKnowledgeBases()
    }
  } catch {
    // 用户取消
  }
}

onMounted(() => {
  fetchKnowledgeBases()
})
</script>

<style scoped>
.knowledge-base-view {
  padding-top: var(--space-2);
}

.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-4);
}

/* 空状态需横跨所有列，否则只占一个单元格、图标视觉偏左不居中 */
.kb-grid > :deep(.empty-state) {
  grid-column: 1 / -1;
}

/* ima 竖卡：缩略区在上 + 主体在下 */
.kb-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  overflow: hidden;
  box-shadow: var(--shadow-xs);
  cursor: pointer;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast),
    transform var(--transition-base);
}

.kb-card:hover {
  border-color: var(--color-border);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

/* 缩略区：低饱和色底 + 大号首字 + 状态角标 */
.kb-card-cover {
  position: relative;
  height: 96px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.kb-cover-initial {
  font-family: var(--font-display);
  font-size: 34px;
  font-weight: var(--weight-bold);
  line-height: 1;
  user-select: none;
}

.kb-status-label {
  position: absolute;
  top: 10px;
  right: 10px;
  font-size: 11px;
  font-weight: var(--weight-medium);
  color: rgba(255, 255, 255, 0.95);
  background: rgba(0, 0, 0, 0.28);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  backdrop-filter: blur(4px);
}

/* 主体 */
.kb-card-body {
  padding: var(--space-3) var(--space-4) var(--space-2);
}

.kb-name {
  margin: 0 0 4px;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-desc {
  margin: 0 0 var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: var(--leading-normal);
  min-height: calc(var(--leading-normal) * 2 * var(--text-xs));
}

/* 底部：元信息 + hover 操作 */
.kb-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--color-border-light);
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.kb-actions {
  display: flex;
  align-items: center;
  gap: 0;
  opacity: 0;
  transition: opacity var(--transition-base);
}

.kb-card:hover .kb-actions {
  opacity: 1;
}
</style>
