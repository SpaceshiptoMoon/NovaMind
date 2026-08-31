<template>
  <div class="space-join-view">
    <div class="join-card">
      <el-skeleton v-if="loading" :rows="2" animated style="width: 320px" />

      <el-result
        v-else-if="success"
        icon="success"
        title="已成功加入空间"
        :sub-title="`空间 ID：${spaceId}`"
      >
        <template #extra>
          <el-button type="primary" @click="goToSpace">进入空间</el-button>
          <el-button @click="goHome">返回首页</el-button>
        </template>
      </el-result>

      <el-result
        v-else
        icon="warning"
        title="无法加入空间"
        :sub-title="errorText"
      >
        <template #extra>
          <el-button type="primary" @click="goHome">返回首页</el-button>
        </template>
      </el-result>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { memberApi } from '@/api/member'
import { useSpaceStore } from '@/stores/space'

const route = useRoute()
const router = useRouter()
const spaceStore = useSpaceStore()

const spaceId = Number(route.params.id)
const token = (route.query.token as string) || ''

const loading = ref(true)
const success = ref(false)
const errorText = ref('邀请链接无效或已过期')

async function join() {
  if (!spaceId || !token) {
    loading.value = false
    errorText.value = '邀请链接缺少必要参数'
    return
  }

  try {
    await memberApi.joinSpace(spaceId, { invite_token: token })
    // 加入成功后刷新空间列表，使新空间出现在下拉中
    try {
      await spaceStore.fetchSpaces()
    } catch {
      // 列表刷新失败不阻塞加入流程
    }
    success.value = true
  } catch {
    // 拦截器已统一弹错；此处只展示结果卡片
    errorText.value = '邀请链接无效或已过期，请联系空间管理员重新邀请'
  } finally {
    loading.value = false
  }
}

function goToSpace() {
  router.push(`/home/spaces/${spaceId}/knowledge-bases`)
}

function goHome() {
  router.push('/home')
}

onMounted(join)
</script>

<style scoped>
.space-join-view {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  padding: 24px;
}

.join-card {
  width: 100%;
  max-width: 480px;
  background: var(--el-bg-color, #fff);
  border-radius: 12px;
  box-shadow: var(--el-box-shadow-light, 0 2px 12px rgba(0, 0, 0, 0.08));
  padding: 32px 24px;
}
</style>