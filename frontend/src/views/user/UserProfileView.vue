<template>
  <div class="user-profile-view">
    <el-card class="profile-card">
      <template #header>
        <span>个人信息</span>
      </template>

      <div class="profile-content" v-loading="loading">
        <!-- 基本信息 -->
        <div class="info-section">
          <div class="info-row">
            <span class="info-label">用户名</span>
            <span class="info-value">{{ userStore.user?.username || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">邮箱</span>
            <span class="info-value">{{ userStore.user?.email || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">手机号</span>
            <span class="info-value">{{ userStore.user?.phone || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">角色</span>
            <el-tag :type="userStore.isAdmin ? 'danger' : 'info'" size="small">
              {{ userStore.isAdmin ? '管理员' : '普通用户' }}
            </el-tag>
          </div>
          <div class="info-row">
            <span class="info-label">状态</span>
            <el-tag :type="statusTag.type" size="small">{{ statusTag.text }}</el-tag>
          </div>
          <div class="info-row">
            <span class="info-label">注册时间</span>
            <span class="info-value">{{ formatDate(userStore.user?.created_at) }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">最后登录</span>
            <span class="info-value">{{ formatDate(userStore.user?.last_login_at) }}</span>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="action-buttons">
          <el-button type="primary" @click="showEditDialog">
            <el-icon><Edit /></el-icon>
            编辑信息
          </el-button>
          <el-button @click="showPasswordDialog">
            <el-icon><Lock /></el-icon>
            修改密码
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 编辑信息弹窗 -->
    <el-dialog v-model="editDialogVisible" title="编辑信息" width="440px">
      <el-form ref="editFormRef" :model="editForm" :rules="editRules" label-width="80px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="editForm.username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="editForm.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="手机号" prop="phone">
          <el-input v-model="editForm.phone" placeholder="请输入手机号（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handleEditSubmit">
          确定
        </el-button>
      </template>
    </el-dialog>

    <!-- 修改密码弹窗 -->
    <el-dialog v-model="passwordDialogVisible" title="修改密码" width="440px">
      <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-width="100px">
        <el-form-item label="当前密码" prop="old_password">
          <el-input
            v-model="passwordForm.old_password"
            type="password"
            placeholder="请输入当前密码"
            show-password
          />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input
            v-model="passwordForm.new_password"
            type="password"
            placeholder="8-30字符，含大小写/数字/特殊字符"
            show-password
          />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm_password">
          <el-input
            v-model="passwordForm.confirm_password"
            type="password"
            placeholder="请再次输入新密码"
            show-password
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handlePasswordSubmit">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Edit, Lock } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { userApi } from '@/api/user'
import type { FormInstance, FormRules } from 'element-plus'

const userStore = useUserStore()

const loading = ref(false)
const submitLoading = ref(false)

// 状态映射
const statusMap: Record<number, { text: string; type: string }> = {
  0: { text: '已禁用', type: 'danger' },
  1: { text: '已启用', type: 'success' },
  2: { text: '已封禁', type: 'warning' },
}

const statusTag = computed(() => {
  const status = userStore.user?.status ?? 1
  return statusMap[status] || { text: '未知', type: 'info' }
})

// 格式化日期
function formatDate(date: string | null | undefined): string {
  if (!date) return '-'
  try {
    const d = new Date(date)
    return d.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '-'
  }
}

// ===================== 编辑信息 =====================
const editDialogVisible = ref(false)
const editFormRef = ref<FormInstance>()
const editForm = reactive({
  username: '',
  email: '',
  phone: '',
})

const editRules: FormRules = {
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
}

function showEditDialog() {
  editForm.username = userStore.user?.username || ''
  editForm.email = userStore.user?.email || ''
  editForm.phone = userStore.user?.phone || ''
  editDialogVisible.value = true
}

async function handleEditSubmit() {
  if (!editFormRef.value) return

  await editFormRef.value.validate(async (valid) => {
    if (!valid) return

    submitLoading.value = true
    try {
      await userStore.updateProfile({
        username: editForm.username,
        email: editForm.email,
        phone: editForm.phone || undefined,
      })
      ElMessage.success('信息更新成功')
      editDialogVisible.value = false
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      ElMessage.error(err.response?.data?.message || '更新失败')
    } finally {
      submitLoading.value = false
    }
  })
}

// ===================== 修改密码 =====================
const passwordDialogVisible = ref(false)
const passwordFormRef = ref<FormInstance>()
const passwordForm = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

const passwordRegex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>]).{8,30}$/

const validateConfirmPassword = (_rule: unknown, value: string, callback: (error?: Error) => void) => {
  if (value !== passwordForm.new_password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const passwordRules: FormRules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { pattern: passwordRegex, message: '密码需8-30字符，含大小写字母、数字和特殊字符', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
}

function showPasswordDialog() {
  passwordForm.old_password = ''
  passwordForm.new_password = ''
  passwordForm.confirm_password = ''
  passwordDialogVisible.value = true
}

async function handlePasswordSubmit() {
  if (!passwordFormRef.value) return

  await passwordFormRef.value.validate(async (valid) => {
    if (!valid) return

    submitLoading.value = true
    try {
      await userApi.updateUser(userStore.user!.id, {
        password: passwordForm.new_password,
      })
      ElMessage.success('密码修改成功，请重新登录')
      passwordDialogVisible.value = false
      // 修改密码后自动登出
      setTimeout(() => {
        userStore.logout()
      }, 1500)
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      ElMessage.error(err.response?.data?.message || '修改失败')
    } finally {
      submitLoading.value = false
    }
  })
}
</script>

<style scoped>
.user-profile-view {
  padding: 20px;
  max-width: 800px;
  margin: 0 auto;
}

.profile-card {
  border-radius: 10px;
}

.profile-content {
  padding: 10px 0;
}

.info-section {
  margin-bottom: 24px;
}

.info-row {
  display: flex;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid var(--color-border-light);
}

.info-row:last-child {
  border-bottom: none;
}

.info-label {
  width: 100px;
  color: #5C5C5C;
  font-size: 14px;
}

.info-value {
  flex: 1;
  color: #1A1A1A;
  font-size: 14px;
}

.action-buttons {
  display: flex;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid #E5E2DE;
}
</style>
