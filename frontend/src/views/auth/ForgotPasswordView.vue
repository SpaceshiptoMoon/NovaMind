<template>
  <div class="forgot-password-view">
    <h2 class="forgot-title">找回密码</h2>
    <p class="forgot-desc">输入邮箱地址以接收重置链接</p>
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      @submit.prevent="handleSubmit"
    >
      <el-form-item prop="email">
        <el-input
          v-model="form.email"
          placeholder="邮箱地址"
          size="large"
        />
      </el-form-item>
      <el-button
        type="primary"
        :loading="loading"
        class="submit-btn"
        size="large"
        @click="handleSubmit"
      >
        发送重置链接
      </el-button>
    </el-form>
    <router-link to="/login" class="back-link">← 返回登录</router-link>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { userApi } from '@/api/user'

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
    ElMessage.success('如果该邮箱已注册，您将收到重置链接')
    router.push('/login')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.forgot-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--color-text);
  margin: 0 0 8px;
}

.forgot-desc {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 0 0 20px;
}

.submit-btn {
  width: 100%;
}

.back-link {
  display: inline-block;
  margin-top: 16px;
  font-size: 13px;
  color: var(--color-primary);
  text-decoration: none;
}

.back-link:hover {
  text-decoration: underline;
}
</style>
