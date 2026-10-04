<template>
  <div class="app-view">
    <PageHeader title="应用中心">
      <span class="app-count">共 {{ apps.length }} 个应用</span>
    </PageHeader>

    <div class="app-grid">
      <div v-for="app in apps" :key="app.id" class="app-card" @click="navigateTo(app)">
        <div class="card-head">
          <span class="card-icon" aria-hidden="true">
            <el-icon :size="20"><component :is="app.iconComponent" /></el-icon>
          </span>
          <el-icon class="card-arrow" aria-hidden="true"><ArrowRight /></el-icon>
        </div>
        <h3 class="card-title">{{ app.name }}</h3>
        <p class="card-desc">{{ app.description }}</p>
      </div>

      <EmptyState
        v-if="apps.length === 0"
        headline="暂无可用应用"
        description="当前账号未被授权任何应用，请联系管理员开通"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 应用中心页（/home/apps）
 *
 * 对应路由 Apps，按应用级门禁（appCode）过滤后展示可用应用卡片，点击跳转对应应用。
 * 卡片网格用 auto-fill 自适应列数，后续新增应用只需在 allApps 追加条目。
 */

import { type Component, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Document, ArrowRight } from '@element-plus/icons-vue'
import { usePermissionStore } from '@/stores/permission'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'

interface AppCard {
  id: string
  name: string
  description: string
  route_path: string
  iconComponent: Component
  /** 应用门禁代码（AppCode） */
  appCode: string
}

const router = useRouter()
const permStore = usePermissionStore()

const allApps: AppCard[] = [
  {
    id: 'resume_mining',
    name: '简历挖掘',
    description: '上传简历，AI 自动解析结构化数据，生成面试准备报告并进行项目经验深度追问',
    route_path: '/home/apps/resume',
    iconComponent: Document,
    appCode: 'app',
  },
]

// 应用级权限过滤（被禁应用不渲染卡片；门禁强制执行在后端）
const apps = computed(() => allApps.filter((a) => permStore.hasApp(a.appCode)))

function navigateTo(app: AppCard) {
  router.push(app.route_path)
}
</script>

<style scoped>
.app-view {
  position: absolute;
  inset: 0;
  padding: var(--space-6);
  overflow-y: auto;
}

.app-count {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

/* 卡片网格：auto-fill 自适应列数（300px 下限防窄视口溢出），应用增多自动换行 */
.app-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(300px, 100%), 1fr));
  gap: var(--space-4);
}

.app-card {
  display: flex;
  flex-direction: column;
  padding: var(--space-5);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  cursor: pointer;
  transition: all var(--transition-base);
}

.app-card:hover {
  border-color: var(--color-border);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-3);
}

/* 中性芯片图标：与技能广场 card-icon 同语言，颜色全部走 token */
.card-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}

.card-arrow {
  font-size: 16px;
  color: var(--color-text-faint);
  transition: all var(--transition-fast);
}

.app-card:hover .card-arrow {
  transform: translateX(3px);
  color: var(--color-primary);
}

.card-title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.card-desc {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  line-height: var(--leading-normal);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
