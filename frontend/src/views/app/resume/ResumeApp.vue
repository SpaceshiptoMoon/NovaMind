<template>
  <div class="resume-app">
    <!-- 顶部导航 -->
    <div class="top-bar">
      <span class="back-btn" @click="router.push('/home/apps')">
        <el-icon><ArrowLeft /></el-icon> 应用中心
      </span>
      <h2>简历挖掘</h2>
      <span class="top-spacer" />
      <el-button text size="small" @click="router.push('/home/apps/resume/history')">历史记录</el-button>
    </div>

    <!-- ========== Step 0: 上传 ========== -->
    <div v-if="step === 0" class="upload-page">
      <div class="upload-container">
        <!-- 拖拽上传区 -->
        <div class="upload-zone-card">
          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            accept=".pdf,.docx,.doc,.txt,.md"
            :on-change="(f: UploadFile) => selectedFile = f.raw ?? null"
            :on-remove="() => selectedFile = null"
            class="upload-dragger"
          >
            <div class="upload-icon-circle">
              <el-icon :size="32" color="var(--color-primary)"><UploadFilled /></el-icon>
            </div>
            <div class="upload-text">
              <span class="upload-main-text">拖拽简历文件到此处，或 <em>点击选择</em></span>
              <span class="upload-sub-text">支持 PDF / DOCX / TXT / MD，最大 100MB</span>
            </div>
          </el-upload>
        </div>

        <!-- JD 折叠面板 -->
        <div class="collapsible" :class="{ 'is-expanded': jdExpanded }">
          <div class="collapsible-header" @click="jdExpanded = !jdExpanded">
            <span>岗位 JD 描述</span>
            <span class="collapsible-tag">可选</span>
            <el-icon class="collapsible-arrow"><ArrowRight /></el-icon>
          </div>
          <div v-if="jdExpanded" class="collapsible-body">
            <el-input
              v-model="jdText"
              type="textarea"
              :rows="5"
              placeholder="粘贴目标岗位的 JD 描述。有 JD 时追问会侧重岗位相关技术，无 JD 则纯按简历内容全面挖掘。"
            />
          </div>
        </div>

        <!-- 配置行 -->
        <div class="config-row">
          <div class="config-item">
            <label>追问广度</label>
            <el-input-number v-model="formConfig.breadth" :min="1" :max="5" size="small" controls-position="right" />
            <span class="config-label">衍生子话题数</span>
          </div>
          <div class="config-item">
            <label>追问深度</label>
            <el-input-number v-model="formConfig.depth" :min="1" :max="5" size="small" controls-position="right" />
            <span class="config-label">每个话题追问轮数</span>
          </div>
          <div class="config-item">
            <label>LLM 模型</label>
            <el-select v-model="selectedModel" size="small" placeholder="默认模型" clearable>
              <el-option v-for="(_, name) in availableModels" :key="name" :label="name" :value="name" />
            </el-select>
          </div>
        </div>

        <!-- 开始按钮 -->
        <div class="upload-action">
          <el-button
            type="primary"
            size="large"
            :loading="uploading"
            :disabled="!selectedFile"
            @click="doUpload"
          >
            {{ uploading ? '上传中...' : '开始解析' }}
          </el-button>
        </div>
      </div>
    </div>

    <!-- ========== Step 1: 报告 ========== -->
    <div v-if="step === 1" class="report-page">
      <!-- 加载态 -->
      <div v-if="session?.status !== 5 || !reportContent" class="loading-state">
        <div class="loading-card">
          <div class="pipeline-steps">
            <div
              v-for="(s, i) in pipelineSteps"
              :key="i"
              class="pipeline-step"
              :class="{
                'is-active': currentStepIndex === i,
                'is-done': currentStepIndex > i,
                'is-pending': currentStepIndex < i,
              }"
            >
              <div class="step-dot">
                <el-icon v-if="currentStepIndex > i" :size="14"><Check /></el-icon>
              </div>
              <span class="step-label">{{ s.label }}</span>
            </div>
          </div>
          <div class="loading-bottom">
            <el-icon class="is-loading" :size="20" color="var(--color-primary)"><Loading /></el-icon>
            <p class="loading-text">{{ statusText }}</p>
            <p v-if="session?.status === 4" class="loading-hint">全自动追问中，预计 2-5 分钟，请耐心等待...</p>
          </div>
        </div>
      </div>

      <!-- 报告三栏布局 -->
      <div v-else class="report-layout">
        <!-- 左侧栏 -->
        <aside class="report-aside">
          <div v-if="pi.name || pi.email" class="candidate-card">
            <div class="candidate-avatar">{{ pi.name?.charAt(0) || '?' }}</div>
            <div class="candidate-name">{{ pi.name }}</div>
            <div v-if="pi.email" class="candidate-email">{{ pi.email }}</div>
            <div v-if="pi.phone" class="candidate-phone">{{ pi.phone }}</div>
            <div v-if="pi.summary" class="candidate-summary">{{ pi.summary }}</div>
          </div>

          <div v-if="session.structured_resume?.work_experience?.length" class="aside-section">
            <h4>工作经历</h4>
            <div v-for="w in session.structured_resume.work_experience" :key="w.company" class="timeline-item">
              <div class="timeline-dot" />
              <div class="timeline-content">
                <div class="timeline-title">{{ w.company }}</div>
                <div class="timeline-sub">{{ w.position }}</div>
                <div class="timeline-date">{{ w.start_date }} ~ {{ w.end_date }}</div>
              </div>
            </div>
          </div>

          <div v-if="session.structured_resume?.project_experience?.length" class="aside-section">
            <h4>项目经历</h4>
            <div v-for="p in session.structured_resume.project_experience" :key="p.name" class="timeline-item">
              <div class="timeline-dot" />
              <div class="timeline-content">
                <div class="timeline-title">{{ p.name }}</div>
                <div class="timeline-sub">{{ p.role }}</div>
                <div class="timeline-tags">
                  <el-tag v-for="t in [...p.tech_stack?.languages?.slice(0, 2) ?? [], ...p.tech_stack?.middleware?.slice(0, 1) ?? []]" :key="t" size="small" type="info" effect="plain">{{ t }}</el-tag>
                </div>
              </div>
            </div>
          </div>

          <div v-if="allSkills.length" class="aside-section">
            <h4>技能</h4>
            <div class="skill-cloud">
              <el-tag v-for="s in allSkills.slice(0, 15)" :key="s" size="small" effect="plain" round>{{ s }}</el-tag>
            </div>
          </div>
        </aside>

        <!-- 中栏：报告主体 -->
        <main class="report-main">
          <div class="report-content markdown-body" v-html="renderedMd" />
        </main>

        <!-- 右侧栏：TOC 目录 -->
        <aside v-if="tocItems.length" class="report-toc">
          <h4>目录</h4>
          <nav class="toc-nav">
            <a
              v-for="item in tocItems"
              :key="item.id"
              :href="'#' + item.id"
              class="toc-link"
              :class="{ 'is-active': activeTocId === item.id, 'toc-h3': item.level === 3 }"
              @click.prevent="scrollToHeading(item.id)"
            >
              {{ item.text }}
            </a>
          </nav>
        </aside>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { UploadFilled, ArrowLeft, ArrowRight, Loading, Download, Check } from '@element-plus/icons-vue'
import { ElMessage, type UploadFile } from 'element-plus'
import { marked } from 'marked'
import { appApi, type ResumeSession } from '@/api/app'

const router = useRouter()
const route = useRoute()

// ==================== 状态 ====================
const step = ref(0)
const uploading = ref(false)
const selectedFile = ref<File | null>(null)
const jdText = ref('')
const jdExpanded = ref(false)
const formConfig = ref({ breadth: 3, depth: 3 })
const selectedModel = ref('')
const availableModels = ref<Record<string, { max_tokens: number; temperature: number; top_p: number }>>({})
const session = ref<ResumeSession | null>(null)
const reportContent = ref('')
const activeTocId = ref('')
let pollingTimer: ReturnType<typeof setTimeout> | null = null

// ==================== 计算属性 ====================
const pi = computed(() => session.value?.structured_resume?.personal_info ?? { name: '', email: '', phone: '', summary: '' })

const allSkills = computed(() => {
  const groups = session.value?.structured_resume?.skills?.skill_groups ?? []
  return groups.flatMap(g => g.items.map(i => `${i.name}${i.proficiency ? '(' + i.proficiency + ')' : ''}`))
})

function enhanceReportHtml(html: string): string {
  // 将 Q/A/评分段落包装成可区分的容器
  return html
    // 匹配 **Q1:** question → qa-question
    .replace(/<p><strong>(Q\d+:)<\/strong>(.*?)<\/p>/gi,
      '<div class="qa-question"><span class="qa-tag qa-tag-q">$1</span>$2</div>')
    // 匹配 **A:** answer → qa-answer
    .replace(/<p><strong>(A:)<\/strong>(.*?)<\/p>/gi,
      '<div class="qa-answer"><span class="qa-tag qa-tag-a">$1</span>$2</div>')
    // 匹配 *深度评分: 0.7* → qa-score
    .replace(/<p><em>(深度评分:\s*[\d.]+)<\/em><\/p>/gi,
      '<div class="qa-score">$1</div>')
}

const renderedMd = computed(() => {
  if (!reportContent.value) return ''
  const raw = marked.parse(reportContent.value) as string
  return enhanceReportHtml(raw)
})

const statusText = computed(() => {
  const s = session.value?.status
  if (s === 1) return '正在解析简历...'
  if (s === 2) return '正在生成分析报告...'
  if (s === 4) return '正在进行深度追问...'
  return '正在处理...'
})

const pipelineSteps = [
  { label: '解析简历', status: 1 },
  { label: '分析报告', status: 2 },
  { label: '深度追问', status: 4 },
  { label: '评估完成', status: 5 },
]

const currentStepIndex = computed(() => {
  const s = session.value?.status ?? 0
  if (s <= 0) return -1
  if (s === 1) return 0
  if (s === 2) return 1
  if (s === 4) return 2
  if (s === 5) return 3
  return -1
})

// ==================== TOC 目录 ====================
interface TocItem { id: string; text: string; level: number }
const tocItems = ref<TocItem[]>([])

function extractToc(html: string) {
  const regex = /<h([23])[^>]*id="([^"]*)"[^>]*>(.*?)<\/h[23]>/gi
  const items: TocItem[] = []
  let match
  while ((match = regex.exec(html)) !== null) {
    items.push({ level: parseInt(match[1]), id: match[2], text: match[3].replace(/<[^>]+>/g, '') })
  }
  return items
}

watch(renderedMd, (html) => {
  if (html) {
    tocItems.value = extractToc(html)
    nextTick(() => setupScrollSpy())
  } else {
    tocItems.value = []
  }
})

function scrollToHeading(id: string) {
  const el = document.getElementById(id)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    activeTocId.value = id
  }
}

function setupScrollSpy() {
  const main = document.querySelector('.report-main')
  if (!main) return
  main.addEventListener('scroll', updateActiveToc)
}

function updateActiveToc() {
  const main = document.querySelector('.report-main')
  if (!main || !tocItems.value.length) return
  const scrollTop = main.scrollTop
  let active = tocItems.value[0]?.id ?? ''
  for (const item of tocItems.value) {
    const el = document.getElementById(item.id)
    if (el && el.offsetTop - main.offsetTop - 100 <= scrollTop) {
      active = item.id
    }
  }
  activeTocId.value = active
}

// ==================== 生命周期 ====================
onMounted(async () => {
  try {
    const data = await appApi.getModels()
    availableModels.value = data.models || {}
  } catch { /* 忽略 */ }

  const sid = route.params.sessionId as string
  if (sid) {
    try {
      session.value = await appApi.getSession(sid)
      selectedModel.value = (session.value.config as Record<string, string>)?.llm_model || ''
      if (session.value.status === 5) {
        step.value = 1
        fetchReport()
      } else if (session.value.status >= 1 && session.value.status < 5) {
        step.value = 1
        startPolling()
      }
    } catch {
      ElMessage.error('加载会话失败')
    }
  }
})

// ==================== 操作 ====================
async function doUpload() {
  if (!selectedFile.value) return
  uploading.value = true
  try {
    await appApi.uploadResume(selectedFile.value, jdText.value, formConfig.value, selectedModel.value)
    uploading.value = false
    ElMessage.success('已提交解析，后台处理中，可在历史记录中查看进度')
    router.push('/home/apps/resume/history')
  } catch (e: unknown) {
    uploading.value = false
    ElMessage.error('上传失败: ' + (e instanceof Error ? e.message : '未知错误'))
  }
}

function startPolling() {
  if (!session.value) return
  pollSession()
}

async function pollSession() {
  if (!session.value) return
  try {
    const updated = await appApi.getSession(session.value.id)
    session.value = updated
    if (updated.status === 5) {
      ElMessage.success('分析完成')
      fetchReport()
      return
    }
    if (updated.status === 0) {
      ElMessage.error('简历解析失败，请重试')
      return
    }
    pollingTimer = setTimeout(pollSession, 3000)
  } catch {
    pollingTimer = setTimeout(pollSession, 5000)
  }
}

async function fetchReport() {
  if (!session.value) return
  try {
    reportContent.value = await appApi.getReportContent(session.value.id)
  } catch {
    ElMessage.error('获取报告失败')
  }
}

async function doDownload() {
  if (!session.value) return
  try {
    await appApi.downloadReport(session.value.id)
  } catch {
    ElMessage.error('下载失败')
  }
}

function stopPolling() {
  if (pollingTimer) {
    clearTimeout(pollingTimer)
    pollingTimer = null
  }
}

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.resume-app {
  min-height: 100%;
}

/* ========== 顶部栏 ========== */
.top-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
  background: var(--color-bg-card);
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  cursor: pointer;
  transition: color var(--transition-fast);
}

.back-btn:hover { color: var(--color-primary); }

.top-bar h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--weight-bold);
  color: var(--color-text);
}

.top-spacer { flex: 1; }

/* ========== 上传页 ========== */
.upload-page {
  display: flex;
  justify-content: center;
  padding: var(--space-10) var(--space-5);
}

.upload-container {
  width: 100%;
  max-width: 640px;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.upload-zone-card {
  background: var(--color-bg-card);
  border: 2px dashed var(--color-border);
  border-radius: var(--radius-xl);
  padding: var(--space-6);
  transition: border-color var(--transition-base);
}

.upload-zone-card:hover {
  border-color: var(--color-primary);
}

.upload-dragger :deep(.el-upload) {
  width: 100%;
}

.upload-dragger :deep(.el-upload-dragger) {
  border: none;
  background: transparent;
  padding: var(--space-8) 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4);
}

.upload-icon-circle {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--color-primary-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
}

.upload-text {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
}

.upload-main-text {
  font-size: var(--text-md);
  color: var(--color-text-secondary);
}

.upload-main-text em {
  color: var(--color-primary);
  font-style: normal;
  font-weight: var(--weight-medium);
}

.upload-sub-text {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

/* 折叠面板 */
.collapsible {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.collapsible-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  transition: background var(--transition-fast);
}

.collapsible-header:hover {
  background: var(--color-bg-hover);
}

.collapsible-tag {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
  font-weight: var(--weight-normal);
}

.collapsible-arrow {
  margin-left: auto;
  font-size: 12px;
  color: var(--color-text-faint);
  transition: transform var(--transition-base);
}

.collapsible.is-expanded .collapsible-arrow {
  transform: rotate(90deg);
}

.collapsible-body {
  padding: 0 var(--space-4) var(--space-4);
}

/* 配置行 */
.config-row {
  display: flex;
  gap: var(--space-6);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
}

.config-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.config-item label {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.config-label {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

.upload-action {
  display: flex;
  justify-content: center;
  padding-top: var(--space-2);
}

.upload-action .el-button {
  min-width: 200px;
}

/* ========== 报告页 ========== */
.report-page {
  position: relative;
  min-height: calc(100vh - 120px);
}

/* 加载态 */
.loading-state {
  display: flex;
  justify-content: center;
  padding: var(--space-10);
}

.loading-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  padding: var(--space-8) var(--space-10);
  box-shadow: var(--shadow-sm);
  text-align: center;
  max-width: 480px;
  width: 100%;
}

.pipeline-steps {
  display: flex;
  justify-content: center;
  gap: var(--space-6);
  margin-bottom: var(--space-8);
}

.pipeline-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
}

.step-dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--color-border);
  background: var(--color-bg-card);
  color: white;
  font-size: 12px;
  transition: all var(--transition-base);
}

.pipeline-step.is-done .step-dot {
  background: var(--color-success);
  border-color: var(--color-success);
}

.pipeline-step.is-active .step-dot {
  background: var(--color-primary);
  border-color: var(--color-primary);
  box-shadow: 0 0 0 4px var(--color-primary-subtle);
}

.pipeline-step.is-pending .step-dot {
  background: var(--color-bg-hover);
}

.step-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
}

.pipeline-step.is-active .step-label {
  color: var(--color-primary);
  font-weight: var(--weight-medium);
}

.pipeline-step.is-done .step-label {
  color: var(--color-text-secondary);
}

.loading-bottom {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
}

.loading-text {
  font-size: var(--text-md);
  color: var(--color-text);
  font-weight: var(--weight-medium);
  margin: 0;
}

.loading-hint {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
  margin: 0;
}

/* 三栏布局 */
.report-layout {
  display: flex;
  gap: 0;
  min-height: calc(100vh - 120px);
}

/* 左侧栏 */
.report-aside {
  width: 260px;
  flex-shrink: 0;
  padding: 24px 16px;
  border-right: 1px solid #F0EDEA;
  overflow-y: auto;
  max-height: calc(100vh - 120px);
  position: sticky;
  top: 60px;
  background: #FAFAF8;
}

.candidate-card {
  text-align: center;
  padding-bottom: 20px;
  margin-bottom: 20px;
  border-bottom: 1px solid #F0EDEA;
}

.candidate-avatar {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, #E8F0FE, #D2E3FC);
  color: var(--color-primary);
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 12px;
  box-shadow: 0 2px 8px rgba(66,133,244,0.15);
}

.candidate-name {
  font-size: 16px;
  font-weight: 600;
  color: #111;
  margin-bottom: 4px;
}

.candidate-email,
.candidate-phone {
  font-size: 12px;
  color: #8C8C8C;
  line-height: 1.6;
}

.candidate-summary {
  font-size: 12px;
  color: #5C5C5C;
  line-height: 1.6;
  margin-top: 8px;
  text-align: left;
  background: #F5F3F0;
  padding: 8px 10px;
  border-radius: 6px;
}

.aside-section {
  margin-bottom: 20px;
}

.aside-section h4 {
  margin: 0 0 10px;
  font-size: 11px;
  font-weight: 600;
  color: #8C8C8C;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* 时间线 */
.timeline-item {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
  position: relative;
}

.timeline-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-primary);
  margin-top: 5px;
  flex-shrink: 0;
}

.timeline-content {
  flex: 1;
  min-width: 0;
}

.timeline-title {
  font-size: 13px;
  font-weight: 500;
  color: #333;
}

.timeline-sub {
  font-size: 12px;
  color: #666;
}

.timeline-date {
  font-size: 11px;
  color: #AAA;
}

.timeline-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.skill-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

/* 中栏：报告 */
.report-main {
  flex: 1;
  min-width: 0;
  padding: 32px 48px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  position: sticky;
  top: 60px;
  background: #FFFFFF;
}

.report-content {
  max-width: 780px;
  margin: 0 auto;
}

/* 右侧栏：TOC */
.report-toc {
  width: 200px;
  flex-shrink: 0;
  padding: 24px 12px;
  border-left: 1px solid #F0EDEA;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  position: sticky;
  top: 60px;
  background: #FAFAF8;
}

.report-toc h4 {
  margin: 0 0 12px;
  font-size: 11px;
  font-weight: 600;
  color: #8C8C8C;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.toc-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.toc-link {
  display: block;
  font-size: 12px;
  color: #8C8C8C;
  text-decoration: none;
  padding: 4px 8px;
  border-radius: 4px;
  border-left: 2px solid transparent;
  transition: all 0.15s;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.5;
}

.toc-link:hover {
  color: #333;
  background: #F0EDEA;
}

.toc-link.is-active {
  color: var(--color-primary);
  border-left-color: var(--color-primary);
  background: rgba(66,133,244,0.06);
  font-weight: 500;
}

.toc-link.toc-h3 {
  padding-left: 20px;
}


/* ========== Markdown 渲染样式 ========== */
.markdown-body {
  font-family: var(--font-body);
  font-size: 15px;
  line-height: 1.85;
  color: #2C2C2C;
  word-break: break-word;
}

/* ---------- 标题层级 ---------- */
.markdown-body :deep(h1) {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 8px;
  letter-spacing: -0.02em;
  color: #111;
  line-height: 1.3;
}

.markdown-body :deep(h2) {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  margin: 40px 0 16px;
  padding-bottom: 8px;
  padding-left: 12px;
  border-left: 3px solid var(--color-primary);
  border-bottom: 1px solid #E8E5E1;
  color: #111;
  line-height: 1.4;
}

.markdown-body :deep(h3) {
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 600;
  margin: 32px 0 12px;
  color: #222;
  line-height: 1.4;
}

.markdown-body :deep(h4) {
  font-size: 15px;
  font-weight: 600;
  margin: 24px 0 8px;
  color: #444;
  line-height: 1.5;
}

.markdown-body :deep(h5) {
  font-size: 14px;
  font-weight: 600;
  margin: 20px 0 6px;
  color: #555;
  line-height: 1.5;
}

/* ---------- 段落 ---------- */
.markdown-body :deep(p) {
  margin: 8px 0;
}

/* ---------- 加粗 / 斜体 ---------- */
.markdown-body :deep(strong) {
  color: #111;
  font-weight: 600;
}

.markdown-body :deep(em) {
  color: var(--color-primary);
  font-style: italic;
}

/* ---------- Q&A 对话样式 ---------- */
.markdown-body :deep(.qa-question) {
  background: linear-gradient(135deg, #EEF3FF, #E8F0FE);
  border-left: 3px solid var(--color-primary);
  border-radius: 0 8px 8px 0;
  padding: 12px 16px;
  margin: 14px 0 6px;
  font-size: 14px;
  line-height: 1.7;
  color: #1A1A1A;
}

.markdown-body :deep(.qa-answer) {
  background: #F8F7F5;
  border-left: 3px solid #D5D0CB;
  border-radius: 0 8px 8px 0;
  padding: 12px 16px;
  margin: 0 0 6px;
  font-size: 14px;
  line-height: 1.7;
  color: #333;
}

.markdown-body :deep(.qa-tag) {
  display: inline-block;
  font-weight: 700;
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 4px;
  margin-right: 8px;
  vertical-align: baseline;
}

.markdown-body :deep(.qa-tag-q) {
  background: var(--color-primary);
  color: #FFF;
}

.markdown-body :deep(.qa-tag-a) {
  background: #D5D0CB;
  color: #555;
}

.markdown-body :deep(.qa-score) {
  margin: 0 0 16px;
  padding-left: 16px;
  font-size: 12px;
  color: #AAA;
  font-style: italic;
  border-left: 2px solid #EEE;
}

/* 深度评分旧格式兜底 */

/* ---------- 分隔线 ---------- */
.markdown-body :deep(hr) {
  border: none;
  height: 1px;
  background: linear-gradient(90deg, transparent, #D5D0CB, transparent);
  margin: 36px 0;
}

/* ---------- 列表 ---------- */
.markdown-body :deep(ul) {
  padding-left: 20px;
  margin: 8px 0;
}

.markdown-body :deep(ol) {
  padding-left: 20px;
  margin: 8px 0;
}

.markdown-body :deep(li) {
  margin: 4px 0;
  line-height: 1.75;
}

.markdown-body :deep(li::marker) {
  color: var(--color-text-muted);
}

/* ---------- 引用块 (callout) ---------- */
.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--color-primary);
  padding: 12px 16px;
  margin: 16px 0;
  background: linear-gradient(135deg, rgba(66,133,244,0.04), rgba(66,133,244,0.02));
  border-radius: 0 8px 8px 0;
  color: #444;
  font-size: 14px;
}

.markdown-body :deep(blockquote p) {
  margin: 4px 0;
}

/* ---------- 表格 ---------- */
.markdown-body :deep(table) {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  margin: 16px 0;
  font-size: 14px;
  border: 1px solid #E8E5E1;
  border-radius: 8px;
  overflow: hidden;
}

.markdown-body :deep(th) {
  background: #F8F6F3;
  font-weight: 600;
  color: #444;
  padding: 10px 14px;
  text-align: left;
  border-bottom: 2px solid #E8E5E1;
  font-size: 13px;
  letter-spacing: 0.02em;
}

.markdown-body :deep(td) {
  padding: 10px 14px;
  text-align: left;
  border-bottom: 1px solid #F0EDEA;
  color: #333;
}

.markdown-body :deep(tr:last-child td) {
  border-bottom: none;
}

.markdown-body :deep(tr:hover td) {
  background: #FAFAF8;
}

/* ---------- 行内代码 ---------- */
.markdown-body :deep(code) {
  font-family: var(--font-mono);
  font-size: 13px;
  background: #F0EDEA;
  padding: 2px 6px;
  border-radius: 4px;
  color: #C7254E;
}

.markdown-body :deep(pre) {
  background: #1E1E1E;
  border-radius: 8px;
  padding: 16px;
  margin: 16px 0;
  overflow-x: auto;
}

.markdown-body :deep(pre code) {
  background: none;
  color: #D4D4D4;
  padding: 0;
}

/* ---------- 链接 ---------- */
.markdown-body :deep(a) {
  color: var(--color-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
  transition: color 0.15s;
}

.markdown-body :deep(a:hover) {
  color: var(--color-primary-hover);
}

/* ---------- 图片 ---------- */
.markdown-body :deep(img) {
  max-width: 100%;
  border-radius: 8px;
  margin: 12px 0;
}
</style>
