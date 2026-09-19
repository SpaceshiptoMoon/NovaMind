<template>
  <div class="home-view">
    <div class="home-inner">
      <!-- Hero（米哈游招聘站排版层级：左对齐大标题 + 字距副题 + 描述 + 主 CTA） -->
      <section class="hero">
        <h1 class="hero-title">问而知，知而行</h1>
        <p class="hero-subtitle">ASK · KNOW · ACT</p>
        <p class="hero-desc">集知识管理、AI 对话、深度研究于一体的智能平台</p>

        <!-- 主 CTA：输入胶囊（点击进对话） -->
        <div class="hero-input" role="button" tabindex="0" @click="goChat" @keydown.enter="goChat">
          <span class="hero-input-placeholder">问我任何问题，或输入 / 使用知识库</span>
          <span class="hero-input-send">
            <el-icon :size="15"><Promotion /></el-icon>
          </span>
        </div>
      </section>

      <!-- 功能入口（米哈游职业分类卡片同构：图标 + 标题 + 描述 + hover 上浮） -->
      <section class="features">
        <button
          v-for="card in featureCards"
          :key="card.key"
          class="feature-card"
          @click="card.action()"
        >
          <span class="feature-icon">
            <NavIcon :name="card.icon" :size="22" />
          </span>
          <span class="feature-meta">
            <span class="feature-title">{{ card.title }}</span>
            <span class="feature-desc">{{ card.desc }}</span>
          </span>
          <el-icon :size="14" class="feature-arrow"><ArrowRight /></el-icon>
        </button>
      </section>

      <!-- 数据条 -->
      <section class="stats-bar">
        <span class="stat-item"
          ><strong>{{ spaceStore.spaces.length }}</strong> 个知识空间</span
        >
        <span class="stat-divider" />
        <span class="stat-item"
          ><strong>{{ chatStore.sessions.length }}</strong> 段对话</span
        >
        <span class="stat-divider" />
        <span class="stat-item"
          ><strong>{{ agentStore.agents.length }}</strong> 个智能体</span
        >
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Promotion, ArrowRight } from '@element-plus/icons-vue'
import { useSpaceStore } from '@/stores/space'
import { useChatStore } from '@/stores/chat'
import { useAgentStore } from '@/stores/agent'
import { usePermissionStore } from '@/stores/permission'
import NavIcon from '@/components/common/NavIcon.vue'

const router = useRouter()
const spaceStore = useSpaceStore()
const chatStore = useChatStore()
const agentStore = useAgentStore()
const permStore = usePermissionStore()

// 功能卡片（应用门禁过滤；emoji 全部换 NavIcon 统一语言）
const featureCards = [
  {
    key: 'spaces',
    icon: 'spaces',
    title: '知识空间',
    desc: '多租户知识管理，上传文档自动分段、向量化、精准检索',
    action: () => router.push('/home/spaces'),
    app: null,
  },
  {
    key: 'research',
    icon: 'research',
    title: '深度研究',
    desc: '自动规划、多源检索，生成结构化研究报告',
    action: () => goToResearch(),
    app: null,
  },
  {
    key: 'agents',
    icon: 'agents',
    title: '智能体',
    desc: '按你的指令自主调用工具、检索知识库，完成复杂任务',
    action: () => router.push('/home/workspace/agents'),
    app: 'agent' as const,
  },
  {
    key: 'apps',
    icon: 'apps',
    title: '应用',
    desc: '开箱即用的场景化应用，快速获得 AI 能力',
    action: () => router.push('/home/apps'),
    app: 'app' as const,
  },
].filter((card) => card.app === null || permStore.hasApp(card.app))

function goChat() {
  router.push('/home/workspace/chat')
}

function goToResearch() {
  const spaceId = spaceStore.currentSpace?.id || spaceStore.spaces[0]?.id
  if (spaceId) {
    router.push(`/home/workspace/research/${spaceId}`)
  } else {
    ElMessage.info('请先创建一个知识空间')
    router.push('/home/spaces')
  }
}

onMounted(() => {
  // 数据条数据源（已有会话/智能体缓存时静默跳过）
  if (chatStore.sessions.length === 0) chatStore.fetchSessions().catch(() => {})
  if (agentStore.agents.length === 0) agentStore.fetchAgents().catch(() => {})
})
</script>

<style scoped>
/* ========================================
   Layout — 门面页（米哈游招聘站式排版层级）
   ======================================== */
.home-view {
  display: flex;
  justify-content: center;
  min-height: calc(100vh - var(--header-height));
  padding: var(--space-10) var(--space-6) var(--space-8);
}

.home-inner {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 880px;
  animation: fadeIn 0.5s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ========================================
   Hero — 左对齐排版层级
   ======================================== */
.hero {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  margin-bottom: var(--space-9, 36px);
}

.hero-title {
  font-family: var(--font-display);
  font-size: 44px;
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin: 0 0 var(--space-2);
  letter-spacing: var(--tracking-tight);
  line-height: var(--leading-tight);
}

.hero-subtitle {
  font-family: var(--font-display);
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--color-text-muted);
  letter-spacing: 0.28em;
  margin: 0 0 var(--space-4);
}

.hero-desc {
  font-size: var(--text-md);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin: 0 0 var(--space-6);
}

/* 主 CTA：输入胶囊（米哈游胶囊按钮语言） */
.hero-input {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  width: 100%;
  max-width: 560px;
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  cursor: pointer;
  transition: all var(--transition-base);
  box-shadow: var(--shadow-xs);
}

.hero-input:hover {
  border-color: var(--color-text-faint);
  box-shadow: var(--shadow-md);
}

.hero-input-placeholder {
  font-size: var(--text-sm);
  color: var(--color-text-faint);
}

.hero-input-send {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-full);
  background: var(--color-btn-primary);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background var(--transition-fast);
}

.hero-input:hover .hero-input-send {
  background: var(--color-btn-primary-hover);
}

/* ========================================
   Feature Cards — 功能入口网格
   ======================================== */
.features {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
  margin-bottom: var(--space-8);
}

.feature-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-5);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  background: var(--color-bg-card);
  cursor: pointer;
  transition: all var(--transition-base);
  text-align: left;
  font-family: var(--font-body);
}

.feature-card:hover {
  border-color: var(--color-border);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.feature-card:hover .feature-arrow {
  color: var(--color-primary);
  transform: translateX(2px);
}

.feature-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-lg);
  background: var(--color-primary-muted);
  color: var(--color-text);
  flex-shrink: 0;
}

.feature-meta {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.feature-title {
  font-size: var(--text-base);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.feature-desc {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  line-height: var(--leading-normal);
}

.feature-arrow {
  color: var(--color-text-faint);
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

/* ========================================
   Stats Bar — 数据条
   ======================================== */
.stats-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-5);
  padding: var(--space-4);
  border-top: 1px solid var(--color-border-light);
}

.stat-item {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.stat-item strong {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin-right: 4px;
}

.stat-divider {
  width: 1px;
  height: 24px;
  background: var(--color-border-light);
}

/* ========================================
   Responsive
   ======================================== */
@media (max-width: 768px) {
  .home-view {
    padding: var(--space-6) var(--space-4);
  }

  .hero-title {
    font-size: 32px;
  }

  .features {
    grid-template-columns: 1fr;
  }
}
</style>
