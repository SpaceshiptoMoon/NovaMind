<template>
  <div class="user-profile-view">
    <div class="page-header">
      <div>
        <p class="eyebrow">Account Profile</p>
        <h2>个人信息</h2>
        <p class="desc">查看账号基本信息与状态；编辑资料与修改密码入口在右上角</p>
      </div>
      <div class="header-actions">
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

    <div class="config-section">
      <div class="section-card" v-loading="loading">
        <h3>基本信息</h3>
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
      </div>
    </div>

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
      <el-form
        ref="passwordFormRef"
        :model="passwordForm"
        :rules="passwordRules"
        label-width="100px"
      >
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
/**
 * 个人信息页。
 *
 * 对应路由 /home/profile，展示当前登录用户的基本信息与账号状态，
 * 提供编辑资料（用户名/邮箱/手机号）与修改密码两个入口弹窗，改密成功后延迟自动登出。
 */

import { ref, reactive, computed, onMounted } from 'vue'
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

// 页面完全依赖 store 渲染，而 store 只在登录瞬间填充；缓存缺失（如他处清理了
// localStorage）时会整页「-」——挂载时缺失则拉一次自愈（评审 P3）
onMounted(() => {
  if (!userStore.user) {
    loading.value = true
    userStore
      .fetchProfile()
      .catch(() => {})
      .finally(() => {
        loading.value = false
      })
  }
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
  phone: [{ pattern: /^1[3-9]\d{9}$/, message: '请输入有效的手机号', trigger: 'blur' }],
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
        // 空串必须显式提交 null 而非吞成 undefined：undefined 会被后端
        // exclude_unset 丢弃成「未提交」，用户显式清空却得到假成功（评审 P3）
        phone: editForm.phone.trim() === '' ? null : editForm.phone,
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

const validateNewPassword = (_rule: unknown, value: string, callback: (error?: Error) => void) => {
  if (value && value === passwordForm.old_password) {
    callback(new Error('新密码不能与当前密码相同'))
  } else {
    callback()
  }
}

const validateConfirmPassword = (
  _rule: unknown,
  value: string,
  callback: (error?: Error) => void,
) => {
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
    {
      pattern: passwordRegex,
      message: '密码需8-30字符，含大小写字母、数字和特殊字符',
      trigger: 'blur',
    },
    { validator: validateNewPassword, trigger: 'blur' },
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

/**
 * 提交新密码；成功后提示并延时 1.5s 登出，让用户重新以新密码登录。
 *
 * 必须走 change-password（验旧密）而非管理端 updateUser 通道：后者对超管
 * 一刀切 403，且不验证旧密码——任何人拿到已登录会话即可改密（评审 P1）。
 */
async function handlePasswordSubmit() {
  if (!passwordFormRef.value) return

  await passwordFormRef.value.validate(async (valid) => {
    if (!valid) return

    submitLoading.value = true
    try {
      await userApi.changePassword(passwordForm.old_password, passwordForm.new_password)
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
/* 根容器：与 UserManageView 等系统页统一（width:100% 必须显式声明——本页处于
   flex column 容器，cross-axis 的 margin:auto 会让子项退化为 fit-content 宽） */
.user-profile-view {
  width: 100%;
  padding: var(--space-5) var(--space-6);
}

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
  flex-wrap: wrap;
  gap: var(--space-2);
  flex-shrink: 0;
}

/* ===== 信息区卡片 ===== */
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

.info-row {
  display: flex;
  align-items: center;
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--color-border-light);
}

.info-row:last-child {
  border-bottom: none;
}

.info-label {
  width: 100px;
  color: var(--color-text-muted);
  font-size: var(--text-base);
}

.info-value {
  flex: 1;
  color: var(--color-text);
  font-size: var(--text-base);
}

@media (max-width: 720px) {
  .page-header {
    flex-direction: column;
    align-items: stretch;
    padding: var(--space-4);
  }

  .header-actions {
    justify-content: flex-end;
  }

  .info-label {
    width: 84px;
  }
}

/* 弹窗固定 440px 在 320px 视口下页脚按钮会裁到视口外（评审三轮 P3）：
   scoped 内 :global 收口两个 el-dialog 的宽度上限 */
.user-profile-view :global(.el-dialog) {
  max-width: calc(100vw - 24px);
}
</style>
