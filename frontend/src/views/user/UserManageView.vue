<template>
  <div class="user-manage-view">
    <el-card class="manage-card">
      <template #header>
        <div class="card-header">
          <span>用户管理</span>
          <el-button type="primary" @click="showCreateDialog">
            <el-icon><Plus /></el-icon>
            新建用户
          </el-button>
        </div>
      </template>

      <!-- 搜索栏 -->
      <div class="search-bar">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索用户名、邮箱"
          clearable
          style="width: 240px"
        />
        <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 140px">
          <el-option label="已启用" :value="1" />
          <el-option label="已禁用" :value="0" />
          <el-option label="已封禁" :value="2" />
        </el-select>
      </div>

      <!-- 用户表格 -->
      <el-table :data="pagedUsers" v-loading="loading" stripe>
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column prop="email" label="邮箱" min-width="180" />
        <el-table-column prop="phone" label="手机号" min-width="120">
          <template #default="{ row }">
            {{ row.phone || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_admin ? 'danger' : 'info'" size="small">
              {{ row.is_admin ? '管理员' : '用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="注册时间" width="160">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="handleViewDetail(row)">
              查看
            </el-button>
            <el-button type="primary" link size="small" @click="showEditDialog(row)">
              编辑
            </el-button>
            <el-button
              :type="row.status === 1 ? 'warning' : 'success'"
              link
              size="small"
              @click="handleToggleStatus(row)"
            >
              {{ row.status === 1 ? '停用' : '启用' }}
            </el-button>
            <el-button type="info" link size="small" @click="handleForceLogout(row)">
              下线
            </el-button>
            <el-button type="danger" link size="small" @click="showResetPasswordDialog(row)">
              重置密码
            </el-button>
            <el-button
              v-if="!row.is_admin || canDeleteAdmin"
              type="danger"
              link
              size="small"
              @click="handleDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="filteredUsers.length"
          layout="total, prev, pager, next"
          background
        />
      </div>
    </el-card>

    <!-- 创建/编辑用户弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑用户' : '新建用户'"
      width="480px"
      append-to-body
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="formData" :rules="formRules" label-width="80px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="formData.username" placeholder="3-50字符" :disabled="isEdit" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="formData.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="手机号" prop="phone">
          <el-input v-model="formData.phone" placeholder="请输入手机号（可选）" />
        </el-form-item>
        <el-form-item v-if="!isEdit" label="密码" prop="password">
          <el-input
            v-model="formData.password"
            type="password"
            placeholder="8-30字符，含大小写/数字/特殊字符"
            show-password
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

    <!-- 查看用户详情 Drawer -->
    <el-drawer v-model="detailVisible" title="用户详情" size="400px" destroy-on-close>
      <div v-if="detailLoading" style="text-align: center; padding: 40px">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      </div>
      <div v-else-if="detailUser" class="detail-content">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="用户ID">{{ detailUser.id }}</el-descriptions-item>
          <el-descriptions-item label="用户名">{{ detailUser.username }}</el-descriptions-item>
          <el-descriptions-item label="邮箱">{{ detailUser.email }}</el-descriptions-item>
          <el-descriptions-item label="手机号">{{ detailUser.phone || '-' }}</el-descriptions-item>
          <el-descriptions-item label="角色">
            <el-tag :type="detailUser.is_admin ? 'danger' : 'info'" size="small">
              {{ detailUser.is_admin ? '管理员' : '普通用户' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="getStatusType(detailUser.status)" size="small">
              {{ getStatusText(detailUser.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="注册时间">{{ formatDate(detailUser.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="最后登录">
            {{ detailUser.last_login_at ? formatDate(detailUser.last_login_at) : '从未登录' }}
          </el-descriptions-item>
          <el-descriptions-item label="更新时间">
            {{ detailUser.updated_at ? formatDate(detailUser.updated_at) : '-' }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </el-drawer>

    <!-- 重置密码弹窗 -->
    <el-dialog
      v-model="resetPwdVisible"
      title="重置密码"
      width="420px"
      append-to-body
      destroy-on-close
      @closed="resetPwdForm"
    >
      <p class="reset-tip">为用户 <strong>{{ resetPwdUser?.username }}</strong> 设置新密码</p>
      <el-form ref="resetPwdFormRef" :model="resetPwdData" :rules="resetPwdRules" label-width="90px">
        <el-form-item label="新密码" prop="newPassword">
          <el-input
            v-model="resetPwdData.newPassword"
            type="password"
            placeholder="8-30字符，含大小写/数字/特殊字符"
            show-password
          />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input
            v-model="resetPwdData.confirmPassword"
            type="password"
            placeholder="再次输入新密码"
            show-password
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetPwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetPwdLoading" @click="handleResetPassword">
          确定重置
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Loading } from '@element-plus/icons-vue'
import { userApi } from '@/api/user'
import { useUserStore } from '@/stores/user'
import type { User } from '@/api/types'
import type { FormInstance, FormRules } from 'element-plus'

const userStore = useUserStore()

const loading = ref(false)
const submitLoading = ref(false)
const users = ref<User[]>([])
const searchKeyword = ref('')
const statusFilter = ref<number | ''>('')

// 分页
const currentPage = ref(1)
const pageSize = 10

// 当前用户是管理员
const canDeleteAdmin = computed(() => userStore.isAdmin)

// 搜索 + 状态筛选后的用户列表
const filteredUsers = computed(() => {
  let list = users.value
  if (searchKeyword.value) {
    const keyword = searchKeyword.value.toLowerCase()
    list = list.filter(
      (u) =>
        u.username.toLowerCase().includes(keyword) ||
        u.email.toLowerCase().includes(keyword)
    )
  }
  if (statusFilter.value !== '') {
    list = list.filter((u) => u.status === statusFilter.value)
  }
  return list
})

// 当前页数据
const pagedUsers = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredUsers.value.slice(start, start + pageSize)
})

// 状态映射
const statusMap: Record<number, { text: string; type: string }> = {
  0: { text: '已禁用', type: 'danger' },
  1: { text: '已启用', type: 'success' },
  2: { text: '已封禁', type: 'warning' },
}

function getStatusText(status: number): string {
  return statusMap[status]?.text || '未知'
}

function getStatusType(status: number): string {
  return statusMap[status]?.type || 'info'
}

function formatDate(date: string | null): string {
  if (!date) return '-'
  try {
    const d = new Date(date)
    return d.toLocaleDateString('zh-CN') + ' ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return '-'
  }
}

// 获取用户列表
async function fetchUsers() {
  loading.value = true
  try {
    const allUsers: User[] = []
    let skip = 0
    const limit = 100
    // API 限制 limit 最大 100，循环拉取全部
    while (true) {
      const batch = await userApi.getUsers({ skip, limit })
      allUsers.push(...batch)
      if (batch.length < limit) break
      skip += limit
    }
    users.value = allUsers
  } catch (error: unknown) {
    const err = error as { response?: { data?: { message?: string } } }
    ElMessage.error(err.response?.data?.message || '获取用户列表失败')
  } finally {
    loading.value = false
  }
}

// ===================== 查看详情 =====================
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailUser = ref<User | null>(null)

async function handleViewDetail(user: User) {
  detailVisible.value = true
  detailLoading.value = true
  detailUser.value = null
  try {
    const response = await userApi.getUser(user.id)
    detailUser.value = response
  } catch {
    ElMessage.error('获取用户详情失败')
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

// ===================== 强制下线 =====================
async function handleForceLogout(user: User) {
  try {
    await ElMessageBox.confirm(
      `确定要将用户 "${user.username}" 强制下线吗？该用户的所有会话将被注销。`,
      '强制下线',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
    await userApi.logoutAll(user.id)
    ElMessage.success(`用户 "${user.username}" 已被强制下线`)
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      const err = error as { response?: { data?: { message?: string } } }
      ElMessage.error(err.response?.data?.message || '操作失败')
    }
  }
}

// ===================== 重置密码 =====================
const resetPwdVisible = ref(false)
const resetPwdLoading = ref(false)
const resetPwdUser = ref<User | null>(null)
const resetPwdFormRef = ref<FormInstance>()
const resetPwdData = reactive({
  newPassword: '',
  confirmPassword: '',
})

const passwordRegex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>]).{8,30}$/

const resetPwdRules: FormRules = {
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { pattern: passwordRegex, message: '密码需8-30字符，含大小写字母、数字和特殊字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
        if (value !== resetPwdData.newPassword) {
          callback(new Error('两次输入的密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

function showResetPasswordDialog(user: User) {
  resetPwdUser.value = user
  resetPwdData.newPassword = ''
  resetPwdData.confirmPassword = ''
  resetPwdVisible.value = true
}

function resetPwdForm() {
  resetPwdFormRef.value?.resetFields()
}

async function handleResetPassword() {
  if (!resetPwdFormRef.value || !resetPwdUser.value) return

  await resetPwdFormRef.value.validate(async (valid) => {
    if (!valid) return

    resetPwdLoading.value = true
    try {
      await userApi.updateUser(resetPwdUser.value!.id, {
        password: resetPwdData.newPassword,
      })
      ElMessage.success(`用户 "${resetPwdUser.value!.username}" 密码已重置`)
      resetPwdVisible.value = false
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      ElMessage.error(err.response?.data?.message || '重置密码失败')
    } finally {
      resetPwdLoading.value = false
    }
  })
}

// ===================== 创建/编辑 =====================
const dialogVisible = ref(false)
const isEdit = ref(false)
const editUserId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const formData = reactive({
  username: '',
  email: '',
  phone: '',
  password: '',
})

const formRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度 3-50 字符', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' },
  ],
  phone: [
    { pattern: /^1[3-9]\d{9}$/, message: '请输入有效的手机号', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { pattern: passwordRegex, message: '密码需8-30字符，含大小写字母、数字和特殊字符', trigger: 'blur' },
  ],
}

function showCreateDialog() {
  isEdit.value = false
  editUserId.value = null
  formData.username = ''
  formData.email = ''
  formData.phone = ''
  formData.password = ''
  dialogVisible.value = true
}

function showEditDialog(user: User) {
  isEdit.value = true
  editUserId.value = user.id
  formData.username = user.username
  formData.email = user.email
  formData.phone = user.phone || ''
  formData.password = ''
  dialogVisible.value = true
}

function resetForm() {
  formRef.value?.resetFields()
}

async function handleSubmit() {
  if (!formRef.value) return

  await formRef.value.validate(async (valid) => {
    if (!valid) return

    submitLoading.value = true
    try {
      if (isEdit.value && editUserId.value) {
        await userApi.updateUser(editUserId.value, {
          email: formData.email,
          phone: formData.phone || undefined,
        })
        ElMessage.success('用户更新成功')
      } else {
        await userApi.createUser({
          username: formData.username,
          email: formData.email,
          password: formData.password,
          phone: formData.phone || undefined,
        })
        ElMessage.success('用户创建成功')
      }
      dialogVisible.value = false
      fetchUsers()
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      ElMessage.error(err.response?.data?.message || '操作失败')
    } finally {
      submitLoading.value = false
    }
  })
}

// ===================== 停用/启用 =====================
async function handleToggleStatus(user: User) {
  const action = user.status === 1 ? '停用' : '启用'
  try {
    await ElMessageBox.confirm(`确定要${action}用户 "${user.username}" 吗？`, '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await userApi.toggleUserStatus(user.id)
    ElMessage.success(`用户已${action}`)
    fetchUsers()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      const err = error as { response?: { data?: { message?: string } } }
      ElMessage.error(err.response?.data?.message || '操作失败')
    }
  }
}

// ===================== 删除 =====================
async function handleDelete(user: User) {
  if (user.id === userStore.user?.id) {
    ElMessage.warning('不能删除自己的账户')
    return
  }

  try {
    await ElMessageBox.confirm(`确定要删除用户 "${user.username}" 吗？此操作不可恢复。`, '警告', {
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
      type: 'error',
    })
    await userApi.deleteUser(user.id)
    ElMessage.success('用户已删除')
    fetchUsers()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      const err = error as { response?: { data?: { message?: string } } }
      ElMessage.error(err.response?.data?.message || '删除失败')
    }
  }
}

onMounted(() => {
  fetchUsers()
})
</script>

<style scoped>
.user-manage-view {
  padding: 20px;
}

.manage-card {
  border-radius: 10px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.search-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.detail-content {
  padding: 0 16px;
}

.reset-tip {
  margin: 0 0 16px;
  font-size: 14px;
  color: var(--color-text-secondary);
}

:deep(.el-table) {
  margin-top: 0;
}
</style>
