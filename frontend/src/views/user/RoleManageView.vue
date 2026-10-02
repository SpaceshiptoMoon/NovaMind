<template>
  <div class="role-manage-view">
    <!-- 页头：eyebrow + 大标题 + 描述，右上主操作 -->
    <div class="page-header">
      <div>
        <p class="eyebrow">Role Management</p>
        <h2>角色管理</h2>
        <p class="desc">定义系统角色与其权限集合；系统内置角色只可调整权限，不可编辑或删除</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="showCreateDialog">
          <el-icon><Plus /></el-icon>
          新建角色
        </el-button>
        <el-button @click="fetchRoles">刷新</el-button>
      </div>
    </div>

    <!-- 统计卡条：点击切换类型筛选 -->
    <div class="stat-grid stat-grid-4">
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': systemFilter === '' }"
        @click="setTypeFilter('')"
      >
        <span class="stat-value">{{ roles.length }}</span>
        <span class="stat-label">全部角色</span>
      </button>
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': systemFilter === true }"
        @click="setTypeFilter(true)"
      >
        <span class="stat-value">{{ systemCount }}</span>
        <span class="stat-label">系统角色</span>
      </button>
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': systemFilter === false }"
        @click="setTypeFilter(false)"
      >
        <span class="stat-value">{{ roles.length - systemCount }}</span>
        <span class="stat-label">自定义角色</span>
      </button>
      <button type="button" class="stat-card is-static" @click="gotoUsers">
        <span class="stat-value">{{ userCount }}</span>
        <span class="stat-label">用户数 · 去分配</span>
      </button>
    </div>

    <div class="section-card">
      <!-- 工具行 -->
      <div class="toolbar">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索角色代码、名称"
          clearable
          :prefix-icon="Search"
          class="toolbar-search"
        />
        <span class="toolbar-meta">共 {{ filteredRoles.length }} 个角色</span>
      </div>

      <!-- 角色表格 -->
      <el-table :data="filteredRoles" v-loading="loading">
        <el-table-column label="角色" min-width="240">
          <template #default="{ row }">
            <div class="role-cell">
              <span class="role-cell-name">
                {{ row.name }}
                <span v-if="row.is_system" class="system-chip">系统</span>
              </span>
              <span class="role-cell-code">{{ row.code }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="描述" min-width="200">
          <template #default="{ row }">
            <span class="muted-cell">{{ row.description || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="权限" width="90" align="center">
          <template #default="{ row }">
            <span class="perm-count">{{ row.permissions?.length || 0 }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link size="small" @click="showPermissionDialog(row)">权限配置</el-button>
            <el-button link size="small" @click="showEditDialog(row)" v-if="!row.is_system">
              编辑
            </el-button>
            <el-button
              link
              size="small"
              class="danger-link"
              @click="handleDelete(row)"
              v-if="!row.is_system"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 创建/编辑角色弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑角色' : '新建角色'"
      width="480px"
      append-to-body
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="formData" :rules="formRules" label-width="80px">
        <el-form-item label="角色代码" prop="code" v-if="!isEdit">
          <el-input v-model="formData.code" placeholder="英文，2-50字符，唯一" />
        </el-form-item>
        <el-form-item label="角色代码" v-if="isEdit">
          <el-input v-model="formData.code" disabled />
        </el-form-item>
        <el-form-item label="角色名称" prop="name">
          <el-input v-model="formData.name" placeholder="请输入角色名称" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="formData.description"
            type="textarea"
            :rows="3"
            placeholder="请输入描述（可选）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handleSubmit"> 确定 </el-button>
      </template>
    </el-dialog>

    <!-- 权限配置弹窗 -->
    <el-dialog
      v-model="permDialogVisible"
      :title="`${currentRole?.name} (${currentRole?.code}) - 权限配置`"
      width="600px"
      append-to-body
      destroy-on-close
    >
      <div v-if="permLoading" style="text-align: center; padding: 40px">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      </div>
      <div v-else class="perm-content">
        <p v-if="currentRole?.is_system" class="dialog-note">
          系统角色权限为出厂定义，仅可查看；如需调整请复制为自定义角色。
        </p>
        <el-checkbox-group v-model="selectedPermCodes" class="perm-group">
          <el-row :gutter="10">
            <el-col :span="12" v-for="cat in permissionCategories" :key="cat">
              <template v-if="getCategoryPermissions(cat).length > 0">
                <div class="perm-category">
                  <h4 class="category-title">{{ cat }}</h4>
                  <template v-for="perm in getCategoryPermissions(cat)" :key="perm.code">
                    <el-checkbox :value="perm.code" :disabled="currentRole?.is_system">
                      {{ perm.name }} <span class="perm-code">({{ perm.code }})</span>
                    </el-checkbox>
                  </template>
                </div>
              </template>
            </el-col>
          </el-row>
        </el-checkbox-group>
      </div>
      <template #footer>
        <el-button @click="permDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="permSubmitLoading"
          @click="handlePermSubmit"
          :disabled="currentRole?.is_system"
        >
          保存权限
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 系统角色管理页（管理员）。
 *
 * 对应路由 /home/admin/roles，支持角色的增删改查、关键词/类型筛选与按权限分类分组的
 * 权限勾选配置；系统内置角色（is_system）只允许调整权限，不可编辑或删除。
 * 页面模式与用户管理一致：统计卡条点击筛选，表格主列双行展示（名称+代码）。
 */

import { ref, computed, onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Loading, Search } from '@element-plus/icons-vue'
import { userApi } from '@/api/user'
import type { Role, Permission, CreateRoleRequest } from '@/api/types'
import type { FormInstance, FormRules } from 'element-plus'

const router = useRouter()

const loading = ref(false)
const submitLoading = ref(false)
const roles = ref<Role[]>([])
const searchKeyword = ref('')
const systemFilter = ref<boolean | ''>('')

const systemCount = computed(() => roles.value.filter((r) => r.is_system).length)

function setTypeFilter(next: boolean | '') {
  systemFilter.value = systemFilter.value === next ? '' : next
}

// 用户总数（统计卡展示，供跳转用户管理分配角色）
const userCount = ref(0)

function gotoUsers() {
  router.push('/home/admin/users')
}

// 权限配置相关
const permDialogVisible = ref(false)
const permLoading = ref(false)
const permSubmitLoading = ref(false)
const currentRole = ref<Role | null>(null)
const selectedPermCodes = ref<string[]>([])
const allPermissions = ref<Permission[]>([])

// 创建/编辑相关
const dialogVisible = ref(false)
const isEdit = ref(false)
const formRef = ref<FormInstance>()
const formData = reactive<Partial<CreateRoleRequest>>({
  code: '',
  name: '',
  description: '',
  permission_codes: [],
})

const formRules: FormRules = {
  code: [
    { required: true, message: '请输入角色代码', trigger: 'blur' },
    { min: 2, max: 50, message: '角色代码长度 2-50 字符', trigger: 'blur' },
    { pattern: /^[a-zA-Z0-9_]+$/, message: '角色代码仅支持字母、数字、下划线', trigger: 'blur' },
  ],
  name: [
    { required: true, message: '请输入角色名称', trigger: 'blur' },
    { max: 100, message: '角色名称最多 100 字符', trigger: 'blur' },
  ],
  description: [{ max: 255, message: '描述最多 255 字符', trigger: 'blur' }],
}

// 权限分类映射
const permissionCategoryMap: Record<string, string> = {
  'user.manage': '用户',
  'role.manage': '角色',
  'skill.config': '技能',
  'skill.review': '技能',
  'agent.manage_system': '智能体',
}

const permissionCategories = computed(() => {
  const cats = new Set<string>()
  allPermissions.value.forEach((p) => {
    cats.add(permissionCategoryMap[p.code] || '其他')
  })
  return Array.from(cats).sort()
})

function getCategoryPermissions(category: string): Permission[] {
  return allPermissions.value.filter((p) => (permissionCategoryMap[p.code] || '其他') === category)
}

// 搜索筛选后的角色列表
const filteredRoles = computed(() => {
  let list = roles.value
  if (searchKeyword.value) {
    const keyword = searchKeyword.value.toLowerCase()
    list = list.filter(
      (r) => r.code.toLowerCase().includes(keyword) || r.name.toLowerCase().includes(keyword),
    )
  }
  if (systemFilter.value !== '') {
    list = list.filter((r) => r.is_system === systemFilter.value)
  }
  return list
})

// 获取角色列表
async function fetchRoles() {
  loading.value = true
  try {
    const res = await userApi.getRoles()
    roles.value = res
  } catch (error: unknown) {
    const err = error as { response?: { data?: { message?: string } } }
    ElMessage.error(err.response?.data?.message || '获取角色列表失败')
  } finally {
    loading.value = false
  }
}

// 获取所有权限
async function fetchPermissions() {
  try {
    const res = await userApi.getPermissions()
    allPermissions.value = res
  } catch (error: unknown) {
    const err = error as { response?: { data?: { message?: string } } }
    ElMessage.error(err.response?.data?.message || '获取权限列表失败')
  }
}

// 获取用户总数（统计卡）
async function fetchUserCount() {
  try {
    let count = 0
    let skip = 0
    const limit = 100
    while (true) {
      const batch = await userApi.getUsers({ skip, limit })
      count += batch.length
      if (batch.length < limit) break
      skip += limit
    }
    userCount.value = count
  } catch {
    // 静默：统计卡数字缺失不阻塞角色列表
  }
}

// ===================== 权限配置 =====================
async function showPermissionDialog(role: Role) {
  currentRole.value = role
  // 列表接口已 selectinload(permissions)，直接用行数据，无需再请求详情
  selectedPermCodes.value = role.permissions?.map((p) => p.code) || []
  permDialogVisible.value = true
  permLoading.value = false
}

/** 将已勾选权限码整体提交为该角色的权限集合（全量覆盖语义）。 */
async function handlePermSubmit() {
  if (!currentRole.value) return

  permSubmitLoading.value = true
  try {
    await userApi.updateRole(currentRole.value.id, {
      permission_codes: selectedPermCodes.value,
    })
    ElMessage.success('权限配置保存成功')
    permDialogVisible.value = false
    fetchRoles()
  } catch (error: unknown) {
    const err = error as { response?: { data?: { message?: string } } }
    ElMessage.error(err.response?.data?.message || '保存权限失败')
  } finally {
    permSubmitLoading.value = false
  }
}

// ===================== 创建/编辑 =====================
function showCreateDialog() {
  isEdit.value = false
  formData.code = ''
  formData.name = ''
  formData.description = ''
  formData.permission_codes = []
  dialogVisible.value = true
}

function showEditDialog(role: Role) {
  isEdit.value = true
  currentRole.value = role
  formData.code = role.code
  formData.name = role.name
  formData.description = role.description || ''
  formData.permission_codes = []
  dialogVisible.value = true
}

function resetForm() {
  formRef.value?.resetFields()
}

/** 新建或更新角色：编辑态角色代码不可改，仅更新名称与描述。 */
async function handleSubmit() {
  if (!formRef.value) return

  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return

    submitLoading.value = true
    try {
      if (isEdit.value) {
        await userApi.updateRole(currentRole.value!.id, {
          name: formData.name!,
          description: formData.description || undefined,
        })
        ElMessage.success('角色更新成功')
      } else {
        await userApi.createRole({
          code: formData.code!,
          name: formData.name!,
          description: formData.description || undefined,
          permission_codes: formData.permission_codes || [],
        })
        ElMessage.success('角色创建成功')
      }
      dialogVisible.value = false
      fetchRoles()
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      ElMessage.error(err.response?.data?.message || '操作失败')
    } finally {
      submitLoading.value = false
    }
  })
}

// ===================== 删除 =====================
async function handleDelete(role: Role) {
  try {
    await ElMessageBox.confirm(
      `确定要删除角色 "${role.name} (${role.code})" 吗？此操作不可恢复。`,
      '警告',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'error',
      },
    )
    await userApi.deleteRole(role.id)
    ElMessage.success('角色已删除')
    fetchRoles()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      const err = error as { response?: { data?: { message?: string } } }
      ElMessage.error(err.response?.data?.message || '删除失败')
    }
  }
}

onMounted(() => {
  Promise.all([fetchRoles(), fetchPermissions(), fetchUserCount()])
})
</script>

<style scoped>
.role-manage-view {
  width: 100%;
  padding: var(--space-5) var(--space-6);
}

/* ===== 页头（与用户管理/模型配置同款） ===== */
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

/* ===== 统计卡条 ===== */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
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
  border-color: var(--color-border-focus);
}

.stat-card.is-active {
  border-color: var(--color-border-focus);
  box-shadow: var(--shadow-sm);
}

/* 纯展示/跳转卡不做选中描边 */
.stat-card.is-static {
  cursor: pointer;
}

.stat-value {
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}

.stat-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

/* ===== 列表区 ===== */
.section-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  padding: var(--space-5) var(--space-6);
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-bottom: var(--space-4);
}

.toolbar-search {
  width: 260px;
  max-width: 100%;
}

.toolbar-meta {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

/* 角色单元格：名称 + 系统徽标 / 代码 mono */
.role-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.role-cell-name {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: var(--weight-medium);
  color: var(--color-text);
}

.system-chip {
  flex-shrink: 0;
  font-size: 10px;
  line-height: 1;
  padding: 2px 5px;
  border-radius: var(--radius-sm);
  background: var(--color-primary-subtle);
  color: var(--color-text-secondary);
  font-weight: var(--weight-normal);
}

.role-cell-code {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.muted-cell {
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

.perm-count {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
}

.danger-link {
  color: var(--color-danger);
}

/* ===== 权限配置弹窗 ===== */
.perm-content {
  max-height: 500px;
  overflow-y: auto;
  padding: var(--space-4) 0;
}

.perm-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.perm-category {
  padding: var(--space-3);
  background: var(--color-bg);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
}

.category-title {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--color-border-light);
}

.perm-code {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}

.dialog-note {
  margin: 0 0 var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

/* 窄屏降级 */
@media (max-width: 960px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .role-manage-view {
    padding: var(--space-4);
  }

  .section-card {
    padding: var(--space-4);
  }
}
</style>
