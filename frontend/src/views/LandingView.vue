<template>
  <div class="landing-page">
    <!-- 导航栏 -->
    <header class="landing-header">
      <div class="landing-nav">
        <div class="landing-brand" @click="scrollToTop">
          <UnicornIcon :size="32" />
          <span class="landing-brand-name">NovaMind</span>
        </div>
        <div class="landing-nav-right">
          <router-link v-if="!hasToken" to="/login" class="nav-link">登录</router-link>
          <router-link v-if="!hasToken" to="/login" class="nav-cta">免费开始</router-link>
          <router-link v-if="hasToken" to="/home" class="nav-cta">进入控制台</router-link>
        </div>
      </div>
    </header>

    <!-- Hero -->
    <section class="hero">
      <div class="hero-inner">
        <div class="hero-badge">AI-Powered Knowledge Platform</div>
        <h1 class="hero-title">
          问而知，知而行
        </h1>
        <p class="hero-subtitle">Ask. Know. Act.</p>
        <p class="hero-desc">用对话唤醒沉睡的知识 — 集知识管理、AI 对话、深度研究于一体的智能平台</p>
        <div class="hero-actions">
          <router-link v-if="!hasToken" to="/login" class="hero-btn hero-btn-primary">开始使用</router-link>
          <router-link v-else to="/home" class="hero-btn hero-btn-primary">进入控制台</router-link>
          <a class="hero-btn hero-btn-ghost" @click="scrollToFeatures">了解更多</a>
        </div>
      </div>
      <!-- 装饰光晕 -->
      <div class="hero-glow hero-glow-1"></div>
      <div class="hero-glow hero-glow-2"></div>
    </section>

    <!-- 功能展示 -->
    <section ref="featuresRef" class="features">
      <div class="features-inner">
        <h2 class="section-title">一个平台，四种能力</h2>
        <p class="section-desc">从文档上传到智能问答，从知识检索到深度研究</p>

        <div class="feature-cards">
          <div class="feature-card feature-card-main">
            <div class="feature-card-icon feature-icon-blue">
              <NavIcon name="spaces" :size="28" />
            </div>
            <h3>知识空间</h3>
            <p>多租户知识管理，支持 PDF、Word 等多种文档格式。自动分段、向量化、精准检索，构建团队专属知识体系。</p>
          </div>

          <div class="feature-card">
            <div class="feature-card-icon feature-icon-coral">
              <NavIcon name="chat" :size="24" />
            </div>
            <h3>AI 对话</h3>
            <p>基于 RAG 的智能问答，从你的知识库中提取精准答案，每条回复可溯源至原文。</p>
          </div>

          <div class="feature-card">
            <div class="feature-card-icon feature-icon-violet">
              <NavIcon name="research" :size="24" />
            </div>
            <h3>深度研究</h3>
            <p>AI 自动搜索、分析、整合信息，生成结构化研究报告，让深度研究效率提升十倍。</p>
          </div>

          <div class="feature-card">
            <div class="feature-card-icon feature-icon-teal">
              <NavIcon name="agents" :size="24" />
            </div>
            <h3>智能体</h3>
            <p>创建和管理 AI 智能体，自动化复杂任务，让 AI 按照你的流程工作。</p>
          </div>
        </div>
      </div>
    </section>

    <!-- 底部 CTA -->
    <section class="cta-section">
      <div class="cta-inner">
        <h2 class="cta-title">准备好唤醒你的知识了吗？</h2>
        <p class="cta-desc">几分钟内即可上手，无需复杂配置</p>
        <div class="cta-actions">
          <router-link v-if="!hasToken" to="/login" class="hero-btn hero-btn-primary">免费开始使用</router-link>
          <router-link v-else to="/home" class="hero-btn hero-btn-primary">进入控制台</router-link>
        </div>
      </div>
    </section>

    <!-- 页脚 -->
    <footer class="landing-footer">
      <div class="footer-inner">
        <div class="footer-brand">
          <UnicornIcon :size="24" />
          <span>NovaMind</span>
        </div>
        <p class="footer-copy">&copy; {{ new Date().getFullYear() }} NovaMind</p>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { tokenManager } from '@/api'
import UnicornIcon from '@/components/common/UnicornIcon.vue'
import NavIcon from '@/components/common/NavIcon.vue'

const featuresRef = ref<HTMLElement>()
const hasToken = computed(() => !!tokenManager.getToken())

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function scrollToFeatures() {
  featuresRef.value?.scrollIntoView({ behavior: 'smooth' })
}
</script>

<style scoped>
/* ========================================
   Landing Page — full-width, no MainLayout
   ======================================== */
.landing-page {
  min-height: 100vh;
  background: var(--color-bg);
  overflow-x: hidden;
}

/* ========================================
   Header
   ======================================== */
.landing-header {
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  background: rgba(245, 243, 240, 0.85);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--color-border-light);
}

.landing-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 1100px;
  margin: 0 auto;
  padding: var(--space-3) var(--space-6);
  height: 56px;
}

.landing-brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
}

.landing-brand-name {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--weight-bold);
  color: var(--color-text);
}

.landing-nav-right {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.nav-link {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  transition: color var(--transition-fast);
}

.nav-link:hover {
  color: var(--color-text);
}

.nav-cta {
  display: inline-flex;
  align-items: center;
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-full);
  background: var(--color-primary);
  color: #FFFFFF;
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  text-decoration: none;
  transition: all var(--transition-base);
  box-shadow: 0 2px 8px rgba(66, 133, 244, 0.2);
}

.nav-cta:hover {
  background: var(--color-primary-hover);
  color: #FFFFFF;
  box-shadow: 0 4px 12px rgba(66, 133, 244, 0.3);
  transform: translateY(-1px);
}

/* ========================================
   Hero Section
   ======================================== */
.hero {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 56px);
  padding: var(--space-10) var(--space-6);
  overflow: hidden;
}

.hero-inner {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  max-width: 680px;
  animation: heroIn 0.8s ease;
}

@keyframes heroIn {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.hero-badge {
  display: inline-block;
  padding: var(--space-1) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  color: var(--color-text-muted);
  letter-spacing: 0.04em;
  margin-bottom: var(--space-6);
}

.hero-title {
  font-family: var(--font-display);
  font-size: 56px;
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin: 0 0 var(--space-2);
  letter-spacing: 0.06em;
  line-height: var(--leading-tight);
}

.hero-subtitle {
  font-family: var(--font-display);
  font-size: var(--text-md);
  font-weight: var(--weight-medium);
  color: var(--color-text-faint);
  letter-spacing: 0.2em;
  text-transform: uppercase;
  margin: 0 0 var(--space-5);
}

.hero-desc {
  font-size: var(--text-md);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin: 0 0 var(--space-8);
  max-width: 520px;
}

.hero-actions {
  display: flex;
  gap: var(--space-3);
  align-items: center;
}

.hero-btn {
  display: inline-flex;
  align-items: center;
  padding: var(--space-3) var(--space-6);
  border-radius: var(--radius-full);
  font-family: var(--font-body);
  font-size: var(--text-base);
  font-weight: var(--weight-medium);
  text-decoration: none;
  cursor: pointer;
  transition: all var(--transition-base);
}

.hero-btn-primary {
  background: var(--color-primary);
  color: #FFFFFF;
  box-shadow: 0 4px 16px rgba(66, 133, 244, 0.25);
}

.hero-btn-primary:hover {
  background: var(--color-primary-hover);
  color: #FFFFFF;
  box-shadow: 0 6px 20px rgba(66, 133, 244, 0.35);
  transform: translateY(-1px);
}

.hero-btn-ghost {
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  background: transparent;
}

.hero-btn-ghost:hover {
  border-color: var(--color-text-muted);
  color: var(--color-text);
}

/* Glow */
.hero-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(100px);
  pointer-events: none;
}

.hero-glow-1 {
  width: 500px;
  height: 500px;
  background: radial-gradient(circle, rgba(66, 133, 244, 0.12), transparent 70%);
  top: 5%;
  right: -10%;
  animation: floatGlow 20s ease-in-out infinite;
}

.hero-glow-2 {
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, rgba(234, 67, 53, 0.08), transparent 70%);
  bottom: 10%;
  left: -8%;
  animation: floatGlow 25s ease-in-out infinite reverse;
}

@keyframes floatGlow {
  0%, 100% { transform: translate(0, 0); }
  33% { transform: translate(20px, -15px); }
  66% { transform: translate(-15px, 10px); }
}

/* ========================================
   Features Section
   ======================================== */
.features {
  padding: var(--space-10) var(--space-6);
  background: var(--color-bg-card);
  border-top: 1px solid var(--color-border-light);
  border-bottom: 1px solid var(--color-border-light);
}

.features-inner {
  max-width: 1000px;
  margin: 0 auto;
}

.section-title {
  font-family: var(--font-display);
  font-size: var(--text-3xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  text-align: center;
  margin: 0 0 var(--space-2);
}

.section-desc {
  font-size: var(--text-base);
  color: var(--color-text-muted);
  text-align: center;
  margin: 0 0 var(--space-10);
}

.feature-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}

.feature-card {
  padding: var(--space-6);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  background: var(--color-bg);
  transition: all var(--transition-base);
}

.feature-card:hover {
  border-color: var(--color-border);
  box-shadow: var(--shadow-md);
}

.feature-card-main {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.feature-card-icon {
  width: 52px;
  height: 52px;
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-4);
}

.feature-icon-blue { background: var(--color-info-subtle); color: var(--color-info); }
.feature-icon-coral { background: var(--color-danger-subtle); color: var(--color-danger); }
.feature-icon-violet { background: var(--color-accent-subtle); color: var(--color-accent); }
.feature-icon-teal { background: var(--color-success-subtle); color: var(--color-success); }

.feature-card h3 {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  margin: 0 0 var(--space-2);
}

.feature-card p {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin: 0;
}

/* ========================================
   CTA Section
   ======================================== */
.cta-section {
  padding: var(--space-10) var(--space-6);
}

.cta-inner {
  max-width: 560px;
  margin: 0 auto;
  text-align: center;
}

.cta-title {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin: 0 0 var(--space-2);
}

.cta-desc {
  font-size: var(--text-base);
  color: var(--color-text-muted);
  margin: 0 0 var(--space-6);
}

.cta-actions {
  display: flex;
  justify-content: center;
}

/* ========================================
   Footer
   ======================================== */
.landing-footer {
  padding: var(--space-6);
  border-top: 1px solid var(--color-border-light);
}

.footer-inner {
  max-width: 1000px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.footer-brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--font-display);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.footer-copy {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
  margin: 0;
}

/* ========================================
   Responsive
   ======================================== */
@media (max-width: 700px) {
  .hero-title {
    font-size: 36px;
  }

  .feature-cards {
    grid-template-columns: 1fr;
  }

  .feature-card-main {
    grid-column: auto;
  }

  .hero-actions {
    flex-direction: column;
    width: 100%;
  }

  .hero-btn {
    width: 100%;
    justify-content: center;
  }

  .footer-inner {
    flex-direction: column;
    gap: var(--space-2);
  }
}
</style>
