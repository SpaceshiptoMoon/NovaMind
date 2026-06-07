<template>
  <div class="forgot-password-view">
    <el-card class="forgot-card" shadow="never">
      <div class="forgot-header">
        <UnicornIcon :size="48" />
        <h2>忘记密码</h2>
        <p class="forgot-desc">请输入注册邮箱，我们将发送密码重置链接</p>
      </div>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="handleSubmit"
      >
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="请输入注册邮箱" prefix-icon="Message" />
        </el-form-item>
        <el-button type="primary" :loading="loading" class="submit-btn" @click="handleSubmit">
          发送重置链接
        </el-button>
      </el-form>
      <div class="forgot-footer">
        <router-link to="/login">← 返回登录</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { userApi } from '@/api/user'
import UnicornIcon from '@/components/common/UnicornIcon.vue'

const router = useRouter()
const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive({
  email: '',
})

const rules: FormRules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' },
  ],
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await userApi.forgotPassword(form.email)
    ElMessage.success('如果该邮箱已注册，您将收到重置链接')
    router.push('/login')
  } catch {
    // 服务端不暴露邮箱是否存在，统一成功提示
    ElMessage.success('如果该邮箱已注册，您将收到重置链接')
    router.push('/login')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.forgot-password-view {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--color-bg-page);
}

.forgot-card {
  width: 420px;
  padding: var(--space-4);
}

.forgot-header {
  text-align: center;
  margin-bottom: var(--space-6);
}

.forgot-header h2 {
  margin: var(--space-3) 0 var(--space-2);
  font-size: var(--text-xl);
  color: var(--color-text);
}

.forgot-desc {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.submit-btn {
  width: 100%;
  margin-top: var(--space-2);
}

.forgot-footer {
  text-align: center;
  margin-top: var(--space-4);
}

.forgot-footer a {
  font-size: var(--text-sm);
  color: var(--color-primary);
  text-decoration: none;
}
</style>
