<template>
  <div class="reset-password-view">
    <el-card class="reset-card" shadow="never">
      <div class="reset-header">
        <UnicornIcon :size="48" />
        <h2>重置密码</h2>
        <p class="reset-desc">请输入新密码</p>
      </div>
      <el-form
        v-if="validToken"
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="handleSubmit"
      >
        <el-form-item label="新密码" prop="newPassword">
          <el-input
            v-model="form.newPassword"
            type="password"
            placeholder="8-30位，需包含大小写字母、数字和特殊字符"
            show-password
          />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input
            v-model="form.confirmPassword"
            type="password"
            placeholder="再次输入新密码"
            show-password
          />
        </el-form-item>
        <el-button type="primary" :loading="loading" class="submit-btn" @click="handleSubmit">
          重置密码
        </el-button>
      </el-form>
      <div v-else class="reset-invalid">
        <el-result icon="error" title="链接无效" sub-title="重置链接已过期或无效，请重新申请">
          <template #extra>
            <el-button type="primary" @click="router.push('/forgot-password')">重新申请</el-button>
          </template>
        </el-result>
      </div>
      <div v-if="validToken" class="reset-footer">
        <router-link to="/login">← 返回登录</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { userApi } from '@/api/user'
import UnicornIcon from '@/components/common/UnicornIcon.vue'

const router = useRouter()
const route = useRoute()
const formRef = ref<FormInstance>()
const loading = ref(false)
const validToken = ref(true)

const form = reactive({
  newPassword: '',
  confirmPassword: '',
})

const rules: FormRules = {
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, max: 30, message: '密码长度为8-30位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string, callback: (err?: Error) => void) => {
        if (value !== form.newPassword) {
          callback(new Error('两次输入的密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

onMounted(() => {
  const token = route.query.token as string
  if (!token) {
    validToken.value = false
  }
})

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  const token = route.query.token as string
  if (!token) {
    validToken.value = false
    return
  }

  loading.value = true
  try {
    await userApi.resetPassword(token, form.newPassword)
    ElMessage.success('密码重置成功，请使用新密码登录')
    router.push('/login')
  } catch {
    validToken.value = false
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.reset-password-view {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--color-bg-page);
}

.reset-card {
  width: 420px;
  padding: var(--space-4);
}

.reset-header {
  text-align: center;
  margin-bottom: var(--space-6);
}

.reset-header h2 {
  margin: var(--space-3) 0 var(--space-2);
  font-size: var(--text-xl);
  color: var(--color-text);
}

.reset-desc {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.submit-btn {
  width: 100%;
  margin-top: var(--space-2);
}

.reset-footer {
  text-align: center;
  margin-top: var(--space-4);
}

.reset-footer a {
  font-size: var(--text-sm);
  color: var(--color-primary);
  text-decoration: none;
}
</style>
