<template>
  <div class="login-view">
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      class="login-form"
      @submit.prevent="handleLogin"
    >
      <el-form-item label="用户名" prop="username">
        <el-input
          v-model="form.username"
          placeholder="请输入用户名"
          size="large"
          :prefix-icon="User"
        />
      </el-form-item>

      <el-form-item label="密码" prop="password">
        <el-input
          v-model="form.password"
          type="password"
          placeholder="请输入密码"
          size="large"
          :prefix-icon="Lock"
          show-password
          @keyup.enter="handleLogin"
        />
      </el-form-item>

      <div class="form-options">
        <el-checkbox v-model="rememberMe">记住我</el-checkbox>
        <a class="forgot-link" @click.prevent="handleForgotPassword">忘记密码？</a>
      </div>

      <el-button
        type="primary"
        size="large"
        :loading="loading"
        class="login-btn"
        @click="handleLogin"
      >
        登录
      </el-button>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const formRef = ref()
const loading = ref(false)
const rememberMe = ref(false)

const form = reactive({
  username: '',
  password: '',
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const handleLogin = async () => {
  if (!formRef.value) return

  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return

    loading.value = true
    try {
      await userStore.login(form.username, form.password)
      ElMessage.success('登录成功')
      const redirect = (route.query.redirect as string) || '/'
      router.push(redirect)
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      ElMessage.error(err.response?.data?.message || '登录失败')
    } finally {
      loading.value = false
    }
  })
}

function handleForgotPassword() {
  ElMessage.info('请联系管理员重置密码')
}
</script>

<style scoped>
.login-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.form-options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-5);
}

.forgot-link {
  font-size: var(--text-sm);
  color: var(--color-primary);
  text-decoration: none;
  cursor: pointer;
}

.forgot-link:hover {
  color: var(--color-primary-hover);
}

.login-btn {
  width: 100%;
  height: 44px;
  font-weight: var(--weight-medium);
}
</style>
