<template>
  <div class="home-view">
    <div class="home-inner">
      <!-- 品牌 + 问候 -->
      <div class="welcome-section">
        <div class="brand-logo">
          <UnicornIcon :size="52" />
        </div>
        <h1 class="greeting">问而知，知而行</h1>
        <p class="greeting-sub">Ask. Know. Act.</p>
      </div>

      <!-- 建议提示卡片 -->
      <div class="suggest-grid">
        <button
          v-for="(item, i) in suggestions"
          :key="i"
          class="suggest-card"
          @click="handleSuggest(item.action)"
        >
          <span class="suggest-icon">{{ item.icon }}</span>
          <span class="suggest-text">{{ item.text }}</span>
        </button>
      </div>

      <!-- 底部输入框 -->
      <div class="home-input-area">
        <div class="home-input-box" @click="router.push('/home/workspace/chat')">
          <span class="home-input-placeholder">问我任何问题，或输入 / 使用知识库</span>
          <span class="home-input-send">
            <el-icon :size="15"><Promotion /></el-icon>
          </span>
        </div>
      </div>

      <!-- 功能导航 -->
      <div class="nav-row">
        <button class="nav-chip" @click="router.push('/home/spaces')">
          <NavIcon name="spaces" :size="14" />
          <span>知识空间</span>
        </button>
        <button class="nav-chip" @click="goToResearch">
          <NavIcon name="research" :size="14" />
          <span>深度研究</span>
        </button>
        <button class="nav-chip" @click="router.push('/home/workspace/agents')">
          <NavIcon name="agents" :size="14" />
          <span>智能体</span>
        </button>
        <button class="nav-chip" @click="router.push('/home/apps')">
          <NavIcon name="apps" :size="14" />
          <span>应用</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Promotion } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useSpaceStore } from '@/stores/space'
import UnicornIcon from '@/components/common/UnicornIcon.vue'
import NavIcon from '@/components/common/NavIcon.vue'

const router = useRouter()
const spaceStore = useSpaceStore()

const suggestions = [
  { icon: '💡', text: '帮我分析一段代码的逻辑', action: '/home/workspace/chat' },
  { icon: '📝', text: '总结这个文档的核心观点', action: '/home/workspace/chat' },
  { icon: '🔍', text: '从知识库中检索相关资料', action: '/home/spaces' },
  { icon: '📊', text: '生成一份研究报告', action: 'research' },
]

function handleSuggest(action: string) {
  if (action === 'research') {
    goToResearch()
  } else {
    router.push(action)
  }
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
</script>

<style scoped>
/* ========================================
   Layout — centered like Claude / ChatGPT
   ======================================== */
.home-view {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 120px);
  padding: var(--space-6);
}

.home-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  max-width: 720px;
  animation: fadeIn 0.6s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ========================================
   Welcome Section
   ======================================== */
.welcome-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: var(--space-8);
}

.brand-logo {
  width: 64px;
  height: 64px;
  border-radius: var(--radius-xl);
  background: linear-gradient(135deg, #E8F0FE, #FEF1EE);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-5);
  box-shadow: 0 4px 16px rgba(66, 133, 244, 0.1);
}

.greeting {
  font-family: var(--font-display);
  font-size: 32px;
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin: 0 0 var(--space-2);
  letter-spacing: 0.04em;
}

.greeting-sub {
  font-family: var(--font-display);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text-faint);
  letter-spacing: 0.18em;
  text-transform: uppercase;
  margin: 0;
}

/* ========================================
   Suggestion Cards — 2x2 grid like Claude
   ======================================== */
.suggest-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
  width: 100%;
  margin-bottom: var(--space-8);
}

.suggest-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
  cursor: pointer;
  transition: all var(--transition-base);
  text-align: left;
  font-family: var(--font-body);
}

.suggest-card:hover {
  border-color: var(--color-border);
  box-shadow: var(--shadow-sm);
}

.suggest-icon {
  font-size: 18px;
  flex-shrink: 0;
}

.suggest-text {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-normal);
}

.suggest-card:hover .suggest-text {
  color: var(--color-text);
}

/* ========================================
   Input Box — like ChatGPT / Claude
   ======================================== */
.home-input-area {
  width: 100%;
  margin-bottom: var(--space-6);
}

.home-input-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-4) var(--space-4) var(--space-5);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card);
  cursor: pointer;
  transition: all var(--transition-base);
  box-shadow: var(--shadow-xs);
}

.home-input-box:hover {
  border-color: var(--color-border);
  box-shadow: var(--shadow-sm);
}

.home-input-placeholder {
  font-size: var(--text-base);
  color: var(--color-text-faint);
}

.home-input-send {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  background: var(--color-primary);
  color: #FFFFFF;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 2px 6px rgba(66, 133, 244, 0.2);
}

/* ========================================
   Navigation Chips
   ======================================== */
.nav-row {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  justify-content: center;
}

.nav-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: transparent;
  font-family: var(--font-body);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.nav-chip:hover {
  border-color: var(--color-border);
  color: var(--color-text-secondary);
  background: var(--color-bg-card);
}

/* ========================================
   Responsive
   ======================================== */
@media (max-width: 600px) {
  .greeting {
    font-size: 24px;
  }

  .suggest-grid {
    grid-template-columns: 1fr;
  }
}
</style>
