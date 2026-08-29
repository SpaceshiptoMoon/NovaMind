<template>
  <div class="register-view">
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      class="register-form"
      @submit.prevent="handleRegister"
    >
      <el-form-item label="用户名" prop="username">
        <el-input
          v-model="form.username"
          placeholder="请输入用户名（3-50字符，字母数字下划线）"
          size="large"
          :prefix-icon="User"
        />
      </el-form-item>

      <el-form-item label="邮箱" prop="email">
        <el-input
          v-model="form.email"
          placeholder="请输入邮箱"
          size="large"
          :prefix-icon="Message"
        />
      </el-form-item>

      <el-form-item label="手机号" prop="phone">
        <el-input
          v-model="form.phone"
          placeholder="请输入手机号（可选）"
          size="large"
          :prefix-icon="Phone"
        />
      </el-form-item>

      <el-form-item label="密码" prop="password">
        <el-input
          v-model="form.password"
          type="password"
          placeholder="请输入密码（8-30字符，含大小写/数字/特殊字符）"
          size="large"
          :prefix-icon="Lock"
          show-password
        />
      </el-form-item>

      <el-form-item label="确认密码" prop="confirmPassword">
        <el-input
          v-model="form.confirmPassword"
          type="password"
          placeholder="再次输入密码"
          size="large"
          :prefix-icon="Lock"
          show-password
          @keyup.enter="handleRegister"
        />
      </el-form-item>

      <el-button
        type="primary"
        size="large"
        :loading="loading"
        class="register-btn"
        @click="handleRegister"
      >
        注册并登录
      </el-button>
    </el-form>

    <div class="login-link">
      已有账号？<el-button type="text" size="small" @click="goLogin">去登录</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Message, Phone, Lock } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import type { RegisterRequest } from '@/api/types'

const router = useRouter()
const userStore = useUserStore()

const formRef = ref()
const loading = ref(false)

const form = reactive({
  username: '',
  email: '',
  phone: '',
  password: '',
  confirmPassword: '',
})

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度 3-50 字符', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string, callback: (e?: Error) => void) => {
        if (/^([a-zA-Z0-9]([a-zA-Z0-9_]*[a-zA-Z0-9])?)$/.test(value) && !value.includes('__')) {
          callback()
        } else {
          callback(new Error('用户名仅支持字母、数字、下划线，不能以下划线开头/结尾或连续'))
        }
      },
      trigger: 'blur',
    },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' },
  ],
  phone: [
    {
      validator: (_rule: unknown, value: string, callback: (e?: Error) => void) => {
        if (!value || /^1[3-9]\d{9}$/.test(value)) {
          callback()
        } else {
          callback(new Error('请输入有效的手机号'))
        }
      },
      trigger: 'blur',
    },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 30, message: '密码长度 8-30 字符', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string, callback: (e?: Error) => void) => {
        if (!value) return callback()
        const missing: string[] = []
        if (!/[A-Z]/.test(value)) missing.push('大写字母')
        if (!/[a-z]/.test(value)) missing.push('小写字母')
        if (!/\d/.test(value)) missing.push('数字')
        if (!/[!@#$%^&*(),.?":{}|<>]/.test(value)) missing.push('特殊字符')
        if (missing.length > 0) {
          callback(new Error(`密码必须包含至少一个${missing.join('、')}`))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: (_rule: unknown, value: string, callback: (e?: Error) => void) => {
        if (value !== form.password) {
          callback(new Error('两次输入的密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

function extractErrorMessage(error: unknown): string {
  const err = error as {
    response?: { data?: { error?: { message?: string; details?: Array<{ field?: string; message?: string }> } } }
  }
  const apiError = err?.response?.data?.error
  if (apiError?.details?.length) {
    return apiError.details.map((d) => d.message).filter(Boolean).join('；')
  }
  return apiError?.message || '注册失败'
}

const handleRegister = async () => {
  if (!formRef.value) return

  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return

    loading.value = true
    try {
      const { confirmPassword: _omit, ...registerData } = form
      const payload: RegisterRequest = registerData.phone
        ? registerData
        : { ...registerData, phone: undefined }
      const data = await userStore.register(payload)

      ElMessage.success('注册成功，正在进入...')

      if (data.must_change_password) {
        router.push('/home/change-password?forced=1')
      } else {
        router.push('/home')
      }
    } catch (error: unknown) {
      ElMessage.error(extractErrorMessage(error))
    } finally {
      loading.value = false
    }
  })
}

function goLogin() {
  router.push('/login')
}
</script>

<style scoped>
.register-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.register-btn {
  width: 100%;
  height: 44px;
  font-weight: var(--weight-medium);
  margin-top: var(--space-3);
}

.login-link {
  text-align: center;
  margin-top: var(--space-5);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.login-link a {
  color: var(--color-primary);
  text-decoration: none;
  margin-left: var(--space-1);
  font-weight: var(--weight-medium);
  cursor: pointer;
}

.login-link a:hover {
  color: var(--color-primary-hover);
}
</style>