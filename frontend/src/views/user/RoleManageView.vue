<template>
  <div class="role-manage-view">
    <el-card class="manage-card">
      <template #header>
        <div class="card-header">
          <span>角色管理</span>
          <el-button type="primary" @click="showCreateDialog">
            <el-icon><Plus /></el-icon>
            新建角色
          </el-button>
        </div>
      </template>

      <!-- 搜索栏 -->
      <div class="search-bar">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索角色代码、名称"
          clearable
          style="width: 240px"
        />
        <el-select v-model="systemFilter" placeholder="全部类型" clearable style="width: 140px">
          <el-option label="系统角色" :value="true" />
          <el-option label="自定义角色" :value="false" />
        </el-select>
      </div>

      <!-- 角色表格 -->
      <el-table :data="filteredRoles" v-loading="loading" stripe>
        <el-table-column prop="code" label="角色代码" min-width="120" />
        <el-table-column prop="name" label="角色名称" min-width="150" />
        <el-table-column prop="description" label="描述" min-width="200">
          <template #default="{ row }">
            {{ row.description || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_system ? 'warning' : 'info'" size="small">
              {{ row.is_system ? '系统角色' : '自定义' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="权限数量" width="100">
          <template #default="{ row }">
            {{ row.permissions?.length || 0 }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="showPermissionDialog(row)">
              权限配置
            </el-button>
            <el-button type="primary" link size="small" @click="showEditDialog(row)" v-if="!row.is_system">
              编辑
            </el-button>
            <el-button type="danger" link size="small" @click="handleDelete(row)" v-if="!row.is_system">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

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
        <el-button type="primary" :loading="submitLoading" @click="handleSubmit">
          确定
        </el-button>
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
        <el-checkbox-group v-model="selectedPermCodes" class="perm-group">
          <el-row :gutter="10">
            <el-col :span="12" v-for="cat in permissionCategories" :key="cat">
              <template v-if="getCategoryPermissions(cat).length > 0">
                <div class="perm-category">
                  <h4 class="category-title">{{ cat }}</h4>
                  <template v-for="perm in getCategoryPermissions(cat)" :key="perm.code">
                    <el-checkbox
                      :label="perm.code"
                      :disabled="currentRole?.is_system"
                    >
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
        <el-button type="primary" :loading="permSubmitLoading" @click="handlePermSubmit" :disabled="currentRole?.is_system">
          保存权限
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Loading } from '@element-plus/icons-vue'
import { userApi } from '@/api/user'
import type { Role, Permission, CreateRoleRequest } from '@/api/types'
import type { FormInstance, FormRules } from 'element-plus'

const loading = ref(false)
const submitLoading = ref(false)
const roles = ref<Role[]>([])
const permissions = ref<Permission[]>([])
const searchKeyword = ref('')
const systemFilter = ref<boolean | ''>('')

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
  description: [
    { max: 255, message: '描述最多 255 字符', trigger: 'blur' },
  ],
}

// 权限分类映射
const permissionCategoryMap: Record<string, string> = {
  'user.read': '用户',
  'user.write': '用户',
  'user.delete': '用户',
  'role.manage': '角色',
  'space.manage': '知识空间',
  'kb.manage': '知识库',
  'doc.manage': '文档',
  'skill.config': '技能',
  'skill.review': '技能',
  'agent.manage': '智能体',
  'admin.panel': '管理面板',
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
      (r) =>
        r.code.toLowerCase().includes(keyword) ||
        r.name.toLowerCase().includes(keyword)
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
    permissions.value = res
  } catch (error: unknown) {
    const err = error as { response?: { data?: { message?: string } } }
    ElMessage.error(err.response?.data?.message || '获取权限列表失败')
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
    await ElMessageBox.confirm(`确定要删除角色 "${role.name} (${role.code})" 吗？此操作不可恢复。`, '警告', {
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
      type: 'error',
    })
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
  Promise.all([fetchRoles(), fetchPermissions()])
})
</script>

<style scoped>
.role-manage-view {
  padding: var(--space-5);
}

.manage-card {
  border-radius: var(--radius-xl);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.search-bar {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

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

.category-title::before {
  content: '';
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-primary);
  margin-right: var(--space-2);
  vertical-align: middle;
}

:deep(.el-checkbox__label) {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
}

:deep(.el-checkbox__label.el-checkbox__label--disabled) {
  color: var(--color-text-placeholder);
}

.perm-code {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-family: monospace;
}

:deep(.el-dialog__footer) {
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--color-border-light);
}
</style>