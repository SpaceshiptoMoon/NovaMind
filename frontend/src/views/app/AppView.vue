<template>
  <div class="app-view">
    <div class="app-header">
      <h1>应用中心</h1>
      <p class="app-desc">AI 驱动的智能工具，提升你的工作效率</p>
    </div>

    <div class="app-grid">
      <div
        v-for="app in apps"
        :key="app.id"
        class="app-card"
        @click="navigateTo(app)"
      >
        <div class="app-icon" :style="{ background: app.bgColor }">
          <el-icon :size="28" :color="app.iconColor">
            <component :is="app.iconComponent" />
          </el-icon>
        </div>
        <div class="app-info">
          <h3>{{ app.name }}</h3>
          <p>{{ app.description }}</p>
        </div>
        <el-icon class="app-arrow"><ArrowRight /></el-icon>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { type Component } from 'vue'
import { useRouter } from 'vue-router'
import { Document, ArrowRight } from '@element-plus/icons-vue'

interface AppCard {
  id: string
  name: string
  description: string
  route_path: string
  iconComponent: Component
  bgColor: string
  iconColor: string
}

const router = useRouter()

const apps: AppCard[] = [
  {
    id: 'resume_mining',
    name: '简历挖掘',
    description: '上传简历，AI 自动解析结构化数据，生成面试准备报告并进行项目经验深度追问',
    route_path: '/home/apps/resume',
    iconComponent: Document,
    bgColor: 'linear-gradient(135deg, #E8F0FE 0%, #D2E3FC 100%)',
    iconColor: '#4285F4',
  },
]

function navigateTo(app: AppCard) {
  router.push(app.route_path)
}
</script>

<style scoped>
.app-view {
  padding: var(--space-10) var(--space-5);
  max-width: 800px;
  margin: 0 auto;
}

.app-header {
  margin-bottom: var(--space-8);
}

.app-header h1 {
  margin: 0 0 var(--space-2);
  font-family: var(--font-display);
  font-size: var(--text-3xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  letter-spacing: var(--tracking-tight);
}

.app-desc {
  margin: 0;
  font-size: var(--text-md);
  color: var(--color-text-muted);
  line-height: var(--leading-normal);
}

.app-grid {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.app-card {
  display: flex;
  align-items: center;
  gap: var(--space-5);
  padding: var(--space-5) var(--space-6);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  cursor: pointer;
  transition: all var(--transition-base);
  box-shadow: var(--shadow-xs);
}

.app-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.app-icon {
  flex-shrink: 0;
  width: 52px;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-lg);
}

.app-info {
  flex: 1;
  min-width: 0;
}

.app-info h3 {
  margin: 0 0 var(--space-1);
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.app-info p {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  line-height: var(--leading-relaxed);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.app-arrow {
  flex-shrink: 0;
  font-size: 18px;
  color: var(--color-text-faint);
  transition: all var(--transition-fast);
}

.app-card:hover .app-arrow {
  transform: translateX(4px);
  color: var(--color-primary);
}
</style>
