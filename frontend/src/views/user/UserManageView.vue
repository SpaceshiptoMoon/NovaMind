<template>
  <div class="user-manage-view">
    <!-- 页头：eyebrow + 大标题 + 描述，右上主操作（ModelConfigView 同款模式） -->
    <div class="page-header">
      <div>
        <p class="eyebrow">User Management</p>
        <h2>用户管理</h2>
        <p class="desc">
          管理平台用户的账号、状态、应用权限与系统角色；超级管理员账号对所有操作免疫
        </p>
      </div>
      <div class="header-actions">
        <el-button
          v-if="permStore.hasPermission('user.manage')"
          type="primary"
          @click="showCreateDialog"
        >
          <el-icon><Plus /></el-icon>
          新建用户
        </el-button>
        <el-button @click="fetchUsers">刷新</el-button>
      </div>
    </div>

    <!-- 统计卡条：点击切换状态筛选 -->
    <div class="stat-grid">
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': statusFilter === '' }"
        @click="setStatusFilter('')"
      >
        <span class="stat-value">{{ users.length }}</span>
        <span class="stat-label">全部用户</span>
      </button>
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': statusFilter === 1 }"
        @click="setStatusFilter(1)"
      >
        <span class="stat-value">{{ countByStatus(1) }}</span>
        <span class="stat-label">已启用</span>
      </button>
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': statusFilter === 0 }"
        @click="setStatusFilter(0)"
      >
        <span class="stat-value">{{ countByStatus(0) }}</span>
        <span class="stat-label">已禁用</span>
      </button>
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': statusFilter === 2 }"
        @click="setStatusFilter(2)"
      >
        <span class="stat-value">{{ countByStatus(2) }}</span>
        <span class="stat-label">已封禁</span>
      </button>
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': statusFilter === 'admin' }"
        @click="setStatusFilter('admin')"
      >
        <span class="stat-value">{{ adminCount }}</span>
        <span class="stat-label">管理员</span>
      </button>
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': statusFilter === 'super' }"
        @click="setStatusFilter('super')"
      >
        <span class="stat-value">{{ superCount }}</span>
        <span class="stat-label">超级管理员</span>
      </button>
    </div>

    <div class="section-card">
      <!-- 工具行：左搜索右统计 -->
      <div class="toolbar">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索用户名、邮箱"
          clearable
          :prefix-icon="Search"
          class="toolbar-search"
        />
        <span class="toolbar-meta">共 {{ filteredUsers.length }} 人</span>
      </div>

      <!-- 用户表格 -->
      <el-table :data="pagedUsers" v-loading="loading">
        <el-table-column label="用户" min-width="220">
          <template #default="{ row }">
            <div class="user-cell">
              <span
                class="user-avatar"
                :class="{ super: row.is_super_admin, admin: row.is_admin && !row.is_super_admin }"
              >
                {{ row.username.slice(0, 1).toUpperCase() }}
              </span>
              <div class="user-cell-text">
                <span class="user-name">
                  {{ row.username }}
                  <span v-if="row.id === userStore.user?.id" class="self-chip">我</span>
                </span>
                <span class="user-email">{{ row.email }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="phone" label="手机号" min-width="130">
          <template #default="{ row }">
            <span class="muted-cell">{{ row.phone || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <span class="role-chip" :class="roleClass(row)">{{ roleText(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <span class="status-dot-row">
              <span class="status-dot" :class="statusDotClass(row.status)" />
              {{ getStatusText(row.status) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="注册时间" width="110">
          <template #default="{ row }">
            <span class="muted-cell">{{ formatDateShort(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column width="60" align="center">
          <template #default="{ row }">
            <el-dropdown
              trigger="click"
              @command="
                (cmd: string | number | object) => handleCommand(String(cmd) as UserCommand, row)
              "
            >
              <button
                type="button"
                class="row-more"
                :aria-label="`用户 ${row.username} 的更多操作`"
              >
                <el-icon><MoreFilled /></el-icon>
                <!-- el-dropdown 需要内部元素承载 focus -->
                <span class="row-more-hit" />
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="detail">查看详情</el-dropdown-item>
                  <el-dropdown-item command="edit" v-if="permStore.hasPermission('user.manage')">
                    编辑
                  </el-dropdown-item>
                  <el-dropdown-item
                    command="appAccess"
                    v-if="permStore.hasPermission('user.manage')"
                  >
                    应用权限
                  </el-dropdown-item>
                  <el-dropdown-item
                    command="role"
                    v-if="permStore.hasPermission('role.manage')"
                    :disabled="row.is_super_admin"
                  >
                    设为角色
                  </el-dropdown-item>
                  <el-dropdown-item
                    command="toggleStatus"
                    v-if="permStore.hasPermission('user.manage')"
                    :disabled="row.is_super_admin"
                    divided
                  >
                    {{ row.status === 1 ? '停用账号' : '启用账号' }}
                  </el-dropdown-item>
                  <el-dropdown-item
                    command="forceLogout"
                    v-if="permStore.hasPermission('user.manage')"
                    :disabled="row.is_super_admin"
                  >
                    强制下线
                  </el-dropdown-item>
                  <el-dropdown-item
                    command="resetPassword"
                    v-if="permStore.hasPermission('user.manage')"
                    :disabled="row.is_super_admin"
                  >
                    重置密码
                  </el-dropdown-item>
                  <el-dropdown-item
                    command="delete"
                    v-if="
                      (!row.is_admin || canDeleteAdmin) && permStore.hasPermission('user.manage')
                    "
                    :disabled="row.is_super_admin"
                    class="danger-item"
                  >
                    删除用户
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
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
    </div>

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
        <el-button type="primary" :loading="submitLoading" @click="handleSubmit"> 确定 </el-button>
      </template>
    </el-dialog>

    <!-- 查看用户详情 Drawer -->
    <el-drawer v-model="detailVisible" title="用户详情" size="400px" destroy-on-close>
      <div v-if="detailLoading" style="text-align: center; padding: 40px">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      </div>
      <div v-else-if="detailUser" class="detail-content">
        <div class="detail-hero">
          <span class="user-avatar large" :class="avatarClass(detailUser)">
            {{ detailUser.username.slice(0, 1).toUpperCase() }}
          </span>
          <div>
            <div class="detail-name">{{ detailUser.username }}</div>
            <span class="role-chip" :class="roleClass(detailUser)">{{ roleText(detailUser) }}</span>
          </div>
        </div>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="用户ID">{{ detailUser.id }}</el-descriptions-item>
          <el-descriptions-item label="邮箱">{{ detailUser.email }}</el-descriptions-item>
          <el-descriptions-item label="手机号">{{ detailUser.phone || '—' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <span class="status-dot-row">
              <span class="status-dot" :class="statusDotClass(detailUser.status)" />
              {{ getStatusText(detailUser.status) }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="注册时间">{{
            formatDate(detailUser.created_at)
          }}</el-descriptions-item>
          <el-descriptions-item label="最后登录">
            {{ detailUser.last_login_at ? formatDate(detailUser.last_login_at) : '从未登录' }}
          </el-descriptions-item>
          <el-descriptions-item label="更新时间">
            {{ detailUser.updated_at ? formatDate(detailUser.updated_at) : '—' }}
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
      <p class="dialog-tip">
        为用户 <strong>{{ resetPwdUser?.username }}</strong> 设置新密码
      </p>
      <el-form
        ref="resetPwdFormRef"
        :model="resetPwdData"
        :rules="resetPwdRules"
        label-width="90px"
      >
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

    <!-- 应用权限弹窗（勾选=可用，取消勾选=禁用；deny-list） -->
    <el-dialog
      v-model="appAccessVisible"
      title="应用权限"
      width="440px"
      append-to-body
      destroy-on-close
    >
      <p class="dialog-tip">
        为用户 <strong>{{ appAccessUser?.username }}</strong> 配置可用应用（取消勾选即禁用该应用）
      </p>
      <div v-if="appAccessLoading" style="text-align: center; padding: 40px">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      </div>
      <template v-else>
        <el-checkbox-group v-model="appAccessEnabled" class="app-access-group">
          <el-checkbox v-for="code in APP_CODES" :key="code" :value="code">
            {{ APP_CODE_LABELS[code] }}
          </el-checkbox>
        </el-checkbox-group>
        <p class="dialog-note">知识空间不在此列——其内容由空间成员角色控制。</p>
      </template>
      <template #footer>
        <el-button @click="appAccessVisible = false">取消</el-button>
        <el-button type="primary" :loading="appAccessSubmitLoading" @click="handleAppAccessSubmit">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 设置角色弹窗 -->
    <el-dialog
      v-model="roleDialogVisible"
      title="设置角色"
      width="440px"
      append-to-body
      destroy-on-close
    >
      <p class="dialog-tip">
        为用户 <strong>{{ roleDialogUser?.username }}</strong> 分配系统角色
      </p>
      <div v-if="roleDialogLoading" style="text-align: center; padding: 40px">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      </div>
      <el-select v-else v-model="roleDialogSelectedId" placeholder="选择角色" style="width: 100%">
        <el-option
          v-for="r in roleDialogRoles"
          :key="r.id"
          :label="`${r.name} (${r.code})`"
          :value="r.id"
        />
      </el-select>
      <template #footer>
        <el-button @click="roleDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="roleDialogSubmitLoading" @click="handleRoleSubmit">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 用户管理页（管理员）。
 *
 * 对应路由 /home/admin/users（需 user.manage 权限），循环拉取全量用户后前端筛选分页，
 * 承载创建/编辑、停用启用、强制下线、重置密码、删除、应用权限（deny-list）与角色分配
 * 七类管理操作；超级管理员账号对所有操作免疫。
 * 页面模式：统计卡条点击即状态筛选；行操作低频项收敛进「更多」下拉，表格只留一列操作入口。
 * 关键交互：应用权限弹窗以「勾选=可用」展示，提交时换算为后端 disabled_apps 被禁集合。
 */

import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Loading, Search, MoreFilled } from '@element-plus/icons-vue'
import { userApi } from '@/api/user'
import { useUserStore } from '@/stores/user'
import { usePermissionStore } from '@/stores/permission'
import type { User, Role, AppCodeType } from '@/api/types'
import { APP_CODES, APP_CODE_LABELS } from '@/api/types'
import type { FormInstance, FormRules } from 'element-plus'

const userStore = useUserStore()
const permStore = usePermissionStore()

const loading = ref(false)
const submitLoading = ref(false)
const users = ref<User[]>([])
const searchKeyword = ref('')
// ''=全部；1/0/2=状态；'admin'/'super'=角色维度（统计卡点击联动）
const statusFilter = ref<'' | 0 | 1 | 2 | 'admin' | 'super'>('')

// 分页
const currentPage = ref(1)
const pageSize = 10

const canDeleteAdmin = computed(() => permStore.hasPermission('user.manage'))

function countByStatus(status: number): number {
  return users.value.filter((u) => u.status === status).length
}

const adminCount = computed(() => users.value.filter((u) => u.is_admin).length)
const superCount = computed(() => users.value.filter((u) => u.is_super_admin).length)

function setStatusFilter(next: '' | 0 | 1 | 2 | 'admin' | 'super') {
  statusFilter.value = statusFilter.value === next ? '' : next
  currentPage.value = 1
}

// 筛选 + 分页
const filteredUsers = computed(() => {
  let list = users.value
  if (searchKeyword.value) {
    const keyword = searchKeyword.value.toLowerCase()
    list = list.filter(
      (u) => u.username.toLowerCase().includes(keyword) || u.email.toLowerCase().includes(keyword),
    )
  }
  switch (statusFilter.value) {
    case '':
      break
    case 'admin':
      list = list.filter((u) => u.is_admin)
      break
    case 'super':
      list = list.filter((u) => u.is_super_admin)
      break
    default:
      list = list.filter((u) => u.status === statusFilter.value)
  }
  return list
})

const pagedUsers = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredUsers.value.slice(start, start + pageSize)
})

// 状态映射
const statusTextMap: Record<number, string> = {
  0: '已禁用',
  1: '已启用',
  2: '已封禁',
}

function getStatusText(status: number): string {
  return statusTextMap[status] || '未知'
}

function statusDotClass(status: number): string {
  switch (status) {
    case 1:
      return 'ok'
    case 2:
      return 'warn'
    case 0:
      return 'off'
    default:
      return 'off'
  }
}

function formatDate(date: string | null): string {
  if (!date) return '-'
  try {
    const d = new Date(date)
    return (
      d.toLocaleDateString('zh-CN') +
      ' ' +
      d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    )
  } catch {
    return '-'
  }
}

function formatDateShort(date: string | null): string {
  if (!date) return '—'
  try {
    return new Date(date).toLocaleDateString('zh-CN')
  } catch {
    return '—'
  }
}

// 角色展示统一走 neutral chip：super 深底反白、admin 描边、普通灰
function roleText(u: User): string {
  if (u.is_super_admin) return '超级管理员'
  return u.is_admin ? '管理员' : '用户'
}

function roleClass(u: User): string {
  if (u.is_super_admin) return 'super'
  return u.is_admin ? 'admin' : 'member'
}

function avatarClass(u: User): string {
  if (u.is_super_admin) return 'super'
  return u.is_admin && !u.is_super_admin ? 'admin' : ''
}

// 行操作收敛进下拉
type UserCommand =
  | 'detail'
  | 'edit'
  | 'appAccess'
  | 'role'
  | 'toggleStatus'
  | 'forceLogout'
  | 'resetPassword'
  | 'delete'

/** el-dropdown command 直连处理：command 值与行对象由 emit 依次给出（any[] 重载，运行时校验兜底）。 */
function handleCommand(...args: unknown[]) {
  const [cmd, user] = args as [UserCommand, User]
  switch (cmd) {
    case 'detail':
      handleViewDetail(user)
      break
    case 'edit':
      showEditDialog(user)
      break
    case 'appAccess':
      showAppAccessDialog(user)
      break
    case 'role':
      showRoleDialog(user)
      break
    case 'toggleStatus':
      handleToggleStatus(user)
      break
    case 'forceLogout':
      handleForceLogout(user)
      break
    case 'resetPassword':
      showResetPasswordDialog(user)
      break
    case 'delete':
      handleDelete(user)
      break
  }
}

// 循环拉取全部用户（API 单页 limit 上限 100），前端搜索/筛选/分页
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
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' },
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
    {
      pattern: passwordRegex,
      message: '密码需8-30字符，含大小写字母、数字和特殊字符',
      trigger: 'blur',
    },
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
  phone: [{ pattern: /^1[3-9]\d{9}$/, message: '请输入有效的手机号', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    {
      pattern: passwordRegex,
      message: '密码需8-30字符，含大小写字母、数字和特殊字符',
      trigger: 'blur',
    },
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

// ===================== 应用权限（deny-list） =====================
const appAccessVisible = ref(false)
const appAccessLoading = ref(false)
const appAccessSubmitLoading = ref(false)
const appAccessUser = ref<User | null>(null)
// 勾选集合 = 可用应用（提交时转换为被禁集合：全集 - 勾选）
const appAccessEnabled = ref<AppCodeType[]>([])

/** 加载用户当前可用应用（disabled_apps 取反为勾选集）并打开应用权限弹窗。 */
async function showAppAccessDialog(user: User) {
  appAccessUser.value = user
  appAccessVisible.value = true
  appAccessLoading.value = true
  appAccessEnabled.value = []
  try {
    const access = await userApi.getUserAppAccess(user.id)
    const disabled = new Set(access.disabled_apps)
    appAccessEnabled.value = APP_CODES.filter((c) => !disabled.has(c))
  } catch (error: unknown) {
    const err = error as { response?: { data?: { message?: string } } }
    ElMessage.error(err.response?.data?.message || '获取应用权限失败')
    appAccessVisible.value = false
  } finally {
    appAccessLoading.value = false
  }
}

/** 勾选集换算回 disabled_apps（全集 - 勾选）后提交。 */
async function handleAppAccessSubmit() {
  if (!appAccessUser.value) return
  appAccessSubmitLoading.value = true
  try {
    // 勾选=可用 → 被禁集合 = 全集 - 勾选
    const enabled = new Set(appAccessEnabled.value)
    const disabled = APP_CODES.filter((c) => !enabled.has(c))
    await userApi.updateUserAppAccess(appAccessUser.value.id, { disabled_apps: disabled })
    ElMessage.success(`用户 "${appAccessUser.value.username}" 应用权限已更新`)
    appAccessVisible.value = false
  } catch (error: unknown) {
    const err = error as { response?: { data?: { message?: string } } }
    ElMessage.error(err.response?.data?.message || '保存应用权限失败')
  } finally {
    appAccessSubmitLoading.value = false
  }
}

// ===================== 设置角色 =====================
const roleDialogVisible = ref(false)
const roleDialogLoading = ref(false)
const roleDialogSubmitLoading = ref(false)
const roleDialogUser = ref<User | null>(null)
const roleDialogSelectedId = ref<number | null>(null)
const roleDialogRoles = ref<Role[]>([])

/** 拉取角色列表并回显：管理员回显 admin 角色，否则回显 viewer 兜底。 */
async function showRoleDialog(user: User) {
  roleDialogUser.value = user
  roleDialogVisible.value = true
  roleDialogLoading.value = true
  roleDialogSelectedId.value = null
  try {
    const roles = await userApi.getRoles()
    roleDialogRoles.value = roles
    // 回显当前角色
    const current = roles.find((r) => r.code === 'admin')
    roleDialogSelectedId.value =
      user.is_admin && current ? current.id : (roles.find((r) => r.code === 'viewer')?.id ?? null)
  } catch (error: unknown) {
    const err = error as { response?: { data?: { message?: string } } }
    ElMessage.error(err.response?.data?.message || '获取角色列表失败')
    roleDialogVisible.value = false
  } finally {
    roleDialogLoading.value = false
  }
}

async function handleRoleSubmit() {
  if (!roleDialogUser.value || !roleDialogSelectedId.value) {
    ElMessage.warning('请选择角色')
    return
  }
  roleDialogSubmitLoading.value = true
  try {
    await userApi.assignUserRole(roleDialogUser.value.id, {
      role_id: roleDialogSelectedId.value,
    })
    ElMessage.success(`用户 "${roleDialogUser.value.username}" 角色已更新`)
    roleDialogVisible.value = false
    fetchUsers()
  } catch (error: unknown) {
    const err = error as { response?: { data?: { message?: string } } }
    ElMessage.error(err.response?.data?.message || '设置角色失败')
  } finally {
    roleDialogSubmitLoading.value = false
  }
}

onMounted(() => {
  fetchUsers()
})
</script>

<style scoped>
.user-manage-view {
  width: 100%;
  padding: var(--space-5) var(--space-6);
}

/* ===== 页头（ModelConfigView 同款） ===== */
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

/* ===== 统计卡条（点击筛选，active 描边） ===== */
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

/* 用户单元格：头像字块 + 名字/邮箱两行 */
.user-cell {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.user-avatar {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  background: var(--color-primary-subtle);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
}

.user-avatar.super {
  background: var(--color-btn-primary);
  color: #fff;
}

.user-avatar.admin {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.user-cell-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.user-name {
  font-weight: var(--weight-medium);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.self-chip {
  flex-shrink: 0;
  font-size: 10px;
  line-height: 1;
  padding: 2px 5px;
  border-radius: var(--radius-sm);
  background: var(--color-primary-subtle);
  color: var(--color-text-secondary);
  font-weight: var(--weight-normal);
}

.user-email {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.muted-cell {
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

/* 角色 chip：全 neutral 分档，不用彩色 tag */
.role-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  line-height: 1.6;
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.role-chip.admin {
  background: var(--color-primary-subtle);
  color: var(--color-text);
  border: 1px solid var(--color-border);
}

.role-chip.super {
  background: var(--color-btn-primary);
  color: #fff;
}

/* 状态：色点 + 文本（语义色只点在 8px 色点上） */
.status-dot-row {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.status-dot.ok {
  background: var(--color-success);
}

.status-dot.warn {
  background: var(--color-warning);
}

.status-dot.off {
  background: var(--color-text-faint);
}

/* 行操作：更多按钮 */
.row-more {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 0;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.row-more:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.row-more:focus-visible {
  outline: 2px solid var(--color-border-focus);
  outline-offset: 1px;
}

.row-more-hit {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--space-4);
}

/* ===== 弹窗/抽屉 ===== */
.detail-content {
  padding: 0 var(--space-4);
}

.detail-hero {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.user-avatar.large {
  width: 48px;
  height: 48px;
  font-size: var(--text-lg);
  border-radius: var(--radius-lg);
}

.detail-name {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  margin-bottom: var(--space-1);
}

.dialog-tip {
  margin: 0 0 var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.app-access-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3) 0;
}

.dialog-note {
  margin: var(--space-2) 0 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

/* 下拉内危险项红色（el-dropdown 渲染在 body，需 :global） */
:global(.danger-item) {
  color: var(--color-danger) !important;
}

:global(.danger-item:hover) {
  background: var(--color-danger-subtle) !important;
}

/* 窄屏：统计卡降列 + 容器收窄 */
@media (max-width: 960px) {
  .stat-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .user-manage-view {
    padding: var(--space-4);
  }

  .section-card {
    padding: var(--space-4);
  }
}
</style>
