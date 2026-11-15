<template>
  <div class="home-view">
    <div class="home-inner">
      <section class="welcome">
        <UnicornIcon :size="44" />
        <h1 class="welcome-title">欢迎使用 NovaMind</h1>
        <p class="welcome-desc">
          企业知识库：上传文档自动解析与向量化，语义检索、Wiki 沉淀与知识运营都在这里。
        </p>
        <el-button type="primary" size="large" class="welcome-cta" @click="createVisible = true">
          新建第一个知识空间
        </el-button>
      </section>
    </div>

    <SpaceCreateDialog v-model:visible="createVisible" />
  </div>
</template>

<script setup lang="ts">
/**
 * 首页空态引导（/home）。
 *
 * 登录后路由守卫直达最近空间工作台；本页仅在「零空间」时可见——空屏是
 * 行动邀请：一句话说明产品 + 唯一动作「新建第一个知识空间」。
 */
import { ref } from 'vue'
import UnicornIcon from '@/components/common/UnicornIcon.vue'
import { SpaceCreateDialog } from '@/components/workbench'

const createVisible = ref(false)
</script>

<style scoped>
.home-view {
  display: flex;
  justify-content: center;
  min-height: 100%;
  padding: var(--space-10) var(--space-6) var(--space-8);
}

.home-inner {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 640px;
}

.welcome {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-3);
  padding-top: clamp(var(--space-8), 12vh, var(--space-16));
}

.welcome-title {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin: var(--space-2) 0 0;
}

.welcome-desc {
  font-size: var(--text-md);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin: 0 0 var(--space-4);
  max-width: 52em;
}

.welcome-cta {
  min-width: 180px;
}
</style>
