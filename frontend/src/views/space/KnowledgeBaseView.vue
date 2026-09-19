<template>
  <div class="knowledge-base-view">
    <!-- 知识库卡片网格（中性横卡：头像 + 名称/描述 + 元信息，与全站 Neutral Minimal 同语言） -->
    <div v-loading="loading" class="kb-grid">
      <div
        v-for="kb in knowledgeBases"
        :key="kb.id"
        class="kb-card"
        @click="goToDocuments(kb.id)"
      >
        <!-- 左：首字头像（中性灰底） -->
        <div class="kb-avatar">{{ kb.name.charAt(0) }}</div>

        <!-- 右：内容列 -->
        <div class="kb-card-body">
          <div class="kb-title-row">
            <h4 class="kb-name">{{ kb.name }}</h4>
            <span v-if="kb.status !== 1" class="kb-archived-tag">已归档</span>
          </div>
          <p class="kb-desc">{{ kb.config?.description || '暂无描述' }}</p>
          <span class="meta-item">
            <el-icon :size="13"><Document /></el-icon>
            {{ kb.stats?.document_count ?? 0 }} 文档
          </span>
        </div>

        <!-- hover 操作（右上角，不与内容挤一行） -->
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
        // 描述为空也要显式传 ""，否则 config 整个不发送，清空操作静默失效
        config: { description: formData.description },
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
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-3);
}

/* 空状态需横跨所有列，否则只占一个单元格、图标视觉偏左不居中 */
.kb-grid > :deep(.empty-state) {
  grid-column: 1 / -1;
}

/* 中性横卡：左头像 + 右内容列，hover 上浮（与智能体/空间侧栏同语言） */
.kb-card {
  position: relative;
  display: flex;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  cursor: pointer;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast),
    transform var(--transition-base);
}

.kb-card:hover {
  border-color: var(--color-border);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

/* 首字头像：中性灰底 */
.kb-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-lg);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: var(--weight-semibold);
  flex-shrink: 0;
  user-select: none;
}

.kb-card-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.kb-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.kb-name {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-archived-tag {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--color-text-muted);
  background: var(--color-bg-hover);
  padding: 1px 8px;
  border-radius: var(--radius-full);
}

.kb-desc {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  line-height: var(--leading-normal);
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-top: 2px;
}

/* hover 操作：右上角，不与内容挤一行 */
.kb-actions {
  position: absolute;
  top: 6px;
  right: 6px;
  display: flex;
  align-items: center;
  opacity: 0;
  transition: opacity var(--transition-base);
}

.kb-card:hover .kb-actions {
  opacity: 1;
}
</style>
