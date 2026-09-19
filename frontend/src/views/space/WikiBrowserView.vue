<template>
  <div class="wiki-browser">
    <!-- 顶部状态条 -->
    <div v-if="ingestActive" class="ingest-banner">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>Wiki 生成中（{{ ingestStatusText }}），页面可能不完整…</span>
    </div>
    <div v-else-if="ingestStatus?.status === 'failed'" class="ingest-banner is-failed">
      <el-icon><WarningFilled /></el-icon>
      <span>最近一次 Wiki 生成失败：{{ ingestStatus.error_message || '未知原因' }}</span>
    </div>

    <!-- 视图切换：浏览 / 图谱 / 问题 -->
    <el-tabs v-model="activeView" class="wiki-view-tabs" @tab-change="onActiveViewChange">
      <el-tab-pane label="浏览" name="browse" />
      <el-tab-pane label="图谱" name="graph" />
      <el-tab-pane
        :label="`问题${pendingIssueCount ? `（${pendingIssueCount}）` : ''}`"
        name="issues"
      />
    </el-tabs>

    <!-- 图谱视图 -->
    <div v-show="activeView === 'graph'" class="graph-wrap">
      <WikiGraphPanel
        :space-id="spaceId"
        :kb-id="kbId"
        :initial-center="selectedSlug || undefined"
        @select="selectPageFromPanel"
      />
    </div>

    <!-- 问题视图 -->
    <div v-show="activeView === 'issues'" class="issues-wrap">
      <div class="issues-toolbar">
        <el-radio-group v-model="issueFilter" size="small" @change="loadIssues">
          <el-radio-button value="pending">待处理</el-radio-button>
          <el-radio-button value="resolved">已解决</el-radio-button>
          <el-radio-button value="ignored">已忽略</el-radio-button>
        </el-radio-group>
        <el-button size="small" @click="runLint">运行质量检查</el-button>
      </div>

      <!-- lint 检出问题（派生，非持久化） -->
      <div v-if="lintIssues.length" class="lint-section">
        <h4 class="lint-heading">质量检查（{{ lintIssues.length }} 项）</h4>
        <div v-for="(issue, index) in lintIssues" :key="`l${index}`" class="issue-row">
          <el-tag size="small" type="warning">{{ lintTypeLabel(issue.issue_type) }}</el-tag>
          <span class="issue-slug" @click="selectPageFromPanel(issue.slug)">{{ issue.slug }}</span>
          <span class="issue-desc">{{ issue.description }}</span>
        </div>
      </div>

      <!-- 持久化问题列表 -->
      <h4 class="lint-heading">问题登记（{{ issues.length }} 项）</h4>
      <div v-for="issue in issues" :key="issue.id" class="issue-row">
        <el-tag size="small">{{ issueTypeLabel(issue.issue_type) }}</el-tag>
        <span class="issue-slug" @click="selectPageFromPanel(issue.slug)">{{ issue.slug }}</span>
        <span class="issue-desc">{{ issue.description }}</span>
        <span class="issue-meta">{{ issue.reported_by }}</span>
        <el-button
          v-if="issue.status === 'pending'"
          size="small"
          text
          type="success"
          @click="setIssueStatus(issue, 'resolved')"
        >
          解决
        </el-button>
        <el-button
          v-if="issue.status === 'pending'"
          size="small"
          text
          @click="setIssueStatus(issue, 'ignored')"
        >
          忽略
        </el-button>
      </div>
      <el-empty v-if="!issues.length && !lintIssues.length" description="没有问题" />
    </div>

    <!-- 浏览视图（原有布局） -->
    <div v-show="activeView === 'browse'" class="wiki-layout">
      <!-- 左侧：页面列表 -->
      <aside class="wiki-sidebar">
        <div class="sidebar-search">
          <el-input
            v-model="searchQuery"
            placeholder="搜索页面…"
            clearable
            :prefix-icon="Search"
            @input="onSearchInput"
          />
        </div>

        <div v-if="searchQuery" class="sidebar-group">
          <div class="group-header">
            <span>搜索结果（{{ searchResults.length }}）</span>
          </div>
          <button
            v-for="item in searchResults"
            :key="item.slug"
            type="button"
            class="page-item"
            :class="{ 'is-active': item.slug === selectedSlug }"
            @click="selectPage(item.slug)"
          >
            <span class="page-title">{{ item.title }}</span>
            <span class="page-type-badge" :data-type="item.page_type">{{
              typeLabel(item.page_type)
            }}</span>
          </button>
          <p v-if="!searchResults.length" class="empty-hint">无匹配页面</p>
        </div>

        <template v-else>
          <div v-for="group in indexGroups" :key="group.page_type" class="sidebar-group">
            <div class="group-header">
              <span>{{ typeLabel(group.page_type) }}</span>
              <small>{{ group.total }}</small>
            </div>
            <button
              v-for="item in group.items"
              :key="item.slug"
              type="button"
              class="page-item"
              :class="{ 'is-active': item.slug === selectedSlug }"
              @click="selectPage(item.slug)"
            >
              <span class="page-title">{{ item.title }}</span>
            </button>
          </div>
          <p v-if="!hasAnyPage" class="empty-hint">
            暂无 Wiki 页面。开启配置中的「Wiki 自动生成」并上传文档后自动创建。
          </p>
        </template>
      </aside>

      <!-- 右侧：页面内容 -->
      <main class="wiki-content">
        <template v-if="currentPage">
          <div class="page-header">
            <div class="page-header-main">
              <h2 class="page-title-main">{{ currentPage.title }}</h2>
              <div class="page-meta">
                <span class="page-type-badge" :data-type="currentPage.page_type">{{
                  typeLabel(currentPage.page_type)
                }}</span>
                <span class="meta-item">v{{ currentPage.version }}</span>
                <span class="meta-item">{{ sourceLabel(currentPage.last_edit_source) }}</span>
                <span class="meta-item">{{ formatDate(currentPage.updated_at) }}</span>
              </div>
            </div>
            <div class="page-actions">
              <el-button size="small" @click="openEditor">编辑</el-button>
              <el-button size="small" @click="openHistory">历史</el-button>
              <el-dropdown trigger="click" @command="onPageCommand">
                <el-button size="small" text>
                  <el-icon><MoreFilled /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="sources">查看来源</el-dropdown-item>
                    <el-dropdown-item command="delete" divided>删除页面</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>

          <!-- 正文：[[slug|title]] 链接预处理后渲染 -->
          <div
            class="page-body markdown-body"
            v-html="renderedContent"
            @click="onContentClick"
          ></div>

          <!-- 来源折叠面板 -->
          <el-collapse v-if="sources.length" class="sources-panel">
            <el-collapse-item title="来源文档">
              <div v-for="source in sources" :key="source.document_id" class="source-row">
                <el-icon><Document /></el-icon>
                <template v-if="!source.deleted">
                  <RouterLink
                    :to="`/home/spaces/${spaceId}/documents/${source.document_id}`"
                    class="source-link"
                  >
                    {{ source.filename }}
                  </RouterLink>
                </template>
                <span v-else class="source-deleted">{{ source.filename }}（已删除）</span>
              </div>
            </el-collapse-item>
          </el-collapse>
        </template>

        <template v-else>
          <div class="wiki-empty">
            <el-empty
              :description="
                hasAnyPage || searchQuery ? '选择左侧页面查看' : '此知识库还没有 Wiki 页面'
              "
            />
          </div>
        </template>
      </main>
    </div>

    <!-- 编辑抽屉 -->
    <el-drawer v-model="editorVisible" title="编辑页面" size="60%" :close-on-click-modal="false">
      <el-form label-width="90px">
        <el-form-item label="标题">
          <el-input v-model="editorForm.title" maxlength="512" />
        </el-form-item>
        <el-form-item label="摘要">
          <el-input v-model="editorForm.summary" type="textarea" :rows="2" maxlength="2000" />
        </el-form-item>
        <el-form-item label="正文">
          <el-input
            v-model="editorForm.content"
            type="textarea"
            :rows="18"
            placeholder="Markdown；[[slug|名称]] 表示站内链接"
          />
        </el-form-item>
        <el-form-item label="版本乐观锁">
          <el-input-number v-model="editorForm.version" :min="0" disabled />
          <span class="form-hint">保存时校验，他人更新后返回 409</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEditor">保存</el-button>
      </template>
    </el-drawer>

    <!-- 历史抽屉 -->
    <el-drawer v-model="historyVisible" title="版本历史" size="55%">
      <div v-if="revisions.length">
        <div v-for="revision in revisions" :key="revision.version" class="revision-row">
          <div class="revision-info">
            <strong>v{{ revision.version }}</strong>
            <span class="revision-source" :data-source="revision.edit_source">{{
              sourceLabel(revision.edit_source)
            }}</span>
            <span class="revision-title">{{ revision.title }}</span>
            <small class="revision-time">{{ formatDate(revision.edited_at) }}</small>
          </div>
          <div class="revision-actions">
            <el-button size="small" text @click="viewRevisionDiff(revision.version)"
              >对比</el-button
            >
            <el-button
              size="small"
              text
              type="warning"
              :disabled="revision.version === currentPage?.version"
              @click="confirmRevert(revision.version)"
            >
              回滚到此版
            </el-button>
          </div>
        </div>
      </div>
      <el-empty v-else description="暂无历史版本" />

      <!-- diff 视图 -->
      <template v-if="diffLines.length">
        <el-divider />
        <h4 class="diff-heading">
          v{{ diffBaseVersion }} → v{{ diffTargetVersion }}
          <el-tag size="small" type="success" class="diff-tag">+{{ diffStats.added }}</el-tag>
          <el-tag size="small" type="danger" class="diff-tag">-{{ diffStats.removed }}</el-tag>
        </h4>
        <div class="diff-view">
          <div
            v-for="(line, index) in diffLines"
            :key="index"
            class="diff-line"
            :class="`is-${line.type}`"
          >
            <span class="diff-marker">{{
              line.type === 'added' ? '+' : line.type === 'removed' ? '-' : ' '
            }}</span>
            <span class="diff-text">{{ line.text || ' ' }}</span>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Loading, MoreFilled, Search, WarningFilled } from '@element-plus/icons-vue'
import { wikiApi } from '@/api/knowledge'
import { renderMarkdown } from '@/utils/markdown'
import { diffLines as computeDiff, diffStats as diffStatsOf } from '@/utils/wikiDiff'
import WikiGraphPanel from '@/components/knowledge/WikiGraphPanel.vue'
import type {
  WikiIngestStatusResponse,
  WikiIndexGroup,
  WikiIssue,
  WikiLintIssue,
  WikiPage,
  WikiPageSourceDocument,
  WikiRevisionSummary,
} from '@/api/types'

const route = useRoute()
const router = useRouter()
const spaceId = computed(() => Number(route.params.id))
const kbId = computed(() => Number(route.params.kbId))

// ============ 列表 / 索引 ============
const indexGroups = ref<WikiIndexGroup[]>([])
const hasAnyPage = computed(() => indexGroups.value.some((g) => g.total > 0))
const searchQuery = ref('')
const searchResults = ref<
  Array<{ slug: string; title: string; page_type: string; summary: string }>
>([])
const selectedSlug = ref('')
const currentPage = ref<WikiPage | null>(null)
const sources = ref<WikiPageSourceDocument[]>([])

// ============ 生成状态轮询 ============
const ingestStatus = ref<WikiIngestStatusResponse | null>(null)
const ingestActive = computed(
  () => ingestStatus.value?.status === 'pending' || ingestStatus.value?.status === 'running',
)
const ingestStatusText = computed(() => {
  const progress = ingestStatus.value?.step_progress
  if (!progress) return '准备中'
  const steps = ['extract', 'cite', 'reduce', 'finalize']
  const labels: Record<string, string> = {
    extract: '候选抽取',
    cite: '引文标注',
    reduce: '页面生成',
    finalize: '收尾',
  }
  for (const step of steps) {
    if (progress[step]?.status === 'running') return labels[step]
  }
  return '处理中'
})
let pollTimer: number | null = null

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    try {
      ingestStatus.value = await wikiApi.getIngestStatus(spaceId.value, kbId.value)
      // 从生成中 → 终态时刷新索引
      if (!ingestActive.value) {
        stopPolling()
        await loadIndex()
      }
    } catch {
      // 轮询失败静默（DB 是事实源，下次轮询自愈）
    }
  }, 5000)
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

// ============ 类型标签 ============
const TYPE_LABELS: Record<string, string> = {
  entity: '实体',
  concept: '概念',
  summary: '摘要',
  synthesis: '综合',
  comparison: '对比',
}
function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type
}
const SOURCE_LABELS: Record<string, string> = {
  pipeline: '自动生成',
  user: '人工编辑',
  agent: '智能体',
  revert: '回滚',
}
function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? '自动生成'
}

// ============ 视图切换（浏览/图谱/问题） ============
const activeView = ref<'browse' | 'graph' | 'issues'>('browse')

// 问题页签首次切入时拉取列表（角标计数依赖 pending 列表）
let issuesLoaded = false

function onActiveViewChange(view: string | number) {
  if (view === 'issues' && !issuesLoaded) {
    issuesLoaded = true
    void loadIssues()
  }
}

// 图谱/问题视图里点 slug → 切回浏览视图并定位页面
function selectPageFromPanel(slug: string) {
  activeView.value = 'browse'
  void selectPage(slug)
}

// ---- 问题登记 ----
const issues = ref<WikiIssue[]>([])
const issueFilter = ref('pending')
const pendingIssueCount = computed(() => issues.value.filter((i) => i.status === 'pending').length)

const ISSUE_TYPE_LABELS: Record<string, string> = {
  mixed_entities: '实体混淆',
  contradictory_facts: '事实矛盾',
  out_of_date: '内容过期',
  dead_link: '死链',
  orphan: '孤儿页',
  other: '其他',
}
function issueTypeLabel(type: string): string {
  return ISSUE_TYPE_LABELS[type] ?? type
}
const LINT_TYPE_LABELS: Record<string, string> = {
  dead_link: '死链',
  orphan: '孤儿页',
  empty_content: '空页面',
}
function lintTypeLabel(type: string): string {
  return LINT_TYPE_LABELS[type] ?? type
}

async function loadIssues() {
  try {
    issues.value = await wikiApi.listIssues(spaceId.value, kbId.value, issueFilter.value)
  } catch {
    issues.value = []
  }
}

async function setIssueStatus(issue: WikiIssue, status: string) {
  try {
    await wikiApi.updateIssueStatus(spaceId.value, kbId.value, issue.id, status)
    await loadIssues()
  } catch {
    ElMessage.error('状态更新失败')
  }
}

// ---- lint 检查 ----
const lintIssues = ref<WikiLintIssue[]>([])

async function runLint() {
  try {
    const data = await wikiApi.lint(spaceId.value, kbId.value)
    lintIssues.value = data.issues
    if (!data.issues.length) {
      ElMessage.success(`检查完成（${data.checked_pages} 页），未发现问题`)
    }
  } catch {
    ElMessage.error('质量检查失败')
  }
}

// ============ [[slug|title]] 链接预处理 ============
const renderedContent = computed(() => {
  if (!currentPage.value) return ''
  const md = currentPage.value.content.replace(
    /\[\[([^\]|]+)\|([^\]]+)\]\]/g,
    '<a class="wiki-link" data-slug="$1">$2</a>',
  )
  return renderMarkdown(md)
})

function onContentClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  const link = target.closest('a.wiki-link') as HTMLElement | null
  if (link) {
    event.preventDefault()
    selectPage(link.dataset.slug || '')
  }
}

// ============ 数据加载 ============
async function loadIndex() {
  try {
    const data = await wikiApi.getIndex(spaceId.value, kbId.value, 100)
    indexGroups.value = data.groups
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '加载 Wiki 索引失败')
  }
}

async function selectPage(slug: string) {
  if (!slug) return
  selectedSlug.value = slug
  sources.value = []
  try {
    currentPage.value = await wikiApi.getPage(spaceId.value, kbId.value, slug)
    // 来源异步加载，不阻塞正文渲染
    wikiApi
      .getPageSources(spaceId.value, kbId.value, slug)
      .then((data) => {
        sources.value = data.source_documents
      })
      .catch(() => {
        sources.value = []
      })
    // URL 同步（不触发路由跳转）
    router.replace({ query: { ...route.query, page: slug } })
  } catch {
    ElMessage.error('页面加载失败')
    currentPage.value = null
  }
}

// ============ 搜索（防抖） ============
let searchTimer: number | null = null
function onSearchInput() {
  if (searchTimer !== null) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    searchTimer = null
    doSearch()
  }, 400)
}

async function doSearch() {
  const q = searchQuery.value.trim()
  if (!q) {
    searchResults.value = []
    return
  }
  try {
    const data = await wikiApi.search(spaceId.value, kbId.value, q)
    searchResults.value = data.items
  } catch {
    searchResults.value = []
  }
}

// ============ 编辑 ============
const editorVisible = ref(false)
const saving = ref(false)
const editorForm = reactive({ title: '', summary: '', content: '', version: 0 })

function openEditor() {
  if (!currentPage.value) return
  editorForm.title = currentPage.value.title
  editorForm.summary = currentPage.value.summary
  editorForm.content = currentPage.value.content
  editorForm.version = currentPage.value.version
  editorVisible.value = true
}

async function saveEditor() {
  if (!currentPage.value) return
  saving.value = true
  try {
    const updated = await wikiApi.updatePage(spaceId.value, kbId.value, currentPage.value.slug, {
      title: editorForm.title,
      summary: editorForm.summary,
      content: editorForm.content,
      version: editorForm.version,
    })
    currentPage.value = updated
    editorVisible.value = false
    ElMessage.success('保存成功')
    await loadIndex()
  } catch (error: unknown) {
    const err = error as { response?: { status?: number } }
    if (err.response?.status === 409) {
      ElMessage.error('页面已被他人更新，请关闭后重新打开编辑')
    } else {
      ElMessage.error('保存失败')
    }
  } finally {
    saving.value = false
  }
}

// ============ 历史 / diff / 回滚 ============
const historyVisible = ref(false)
const revisions = ref<WikiRevisionSummary[]>([])
const diffBaseVersion = ref<number>()
const diffTargetVersion = ref<number>()
const diffLinesList = ref<ReturnType<typeof computeDiff>>([])
const diffLines = computed(() => diffLinesList.value)
const diffStats = computed(() => diffStatsOf(diffLines.value))

function openHistory() {
  if (!currentPage.value) return
  historyVisible.value = true
  wikiApi
    .listRevisions(spaceId.value, kbId.value, currentPage.value.slug)
    .then((data) => {
      revisions.value = data.revisions
    })
    .catch(() => {
      revisions.value = []
    })
}

async function viewRevisionDiff(version: number) {
  if (!currentPage.value) return
  try {
    const [oldRevision, currentContent] = await Promise.all([
      wikiApi.getRevision(spaceId.value, kbId.value, currentPage.value.slug, version),
      wikiApi.getPage(spaceId.value, kbId.value, currentPage.value.slug),
    ])
    diffBaseVersion.value = version
    diffTargetVersion.value = currentPage.value.version
    diffLinesList.value = computeDiff(oldRevision.content, currentContent.content)
  } catch {
    ElMessage.error('版本内容加载失败')
  }
}

async function confirmRevert(version: number) {
  if (!currentPage.value) return
  try {
    await ElMessageBox.confirm(`确认回滚到 v${version}？将以此版本内容创建新版本。`, '回滚确认', {
      confirmButtonText: '回滚',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    const result = await wikiApi.revert(spaceId.value, kbId.value, currentPage.value.slug, version)
    ElMessage.success(`已回滚（新版本 v${result.new_version}）`)
    historyVisible.value = false
    await selectPage(currentPage.value.slug)
    await loadIndex()
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '回滚失败')
  }
}

// ============ 页面操作 ============
async function onPageCommand(command: string | number | object) {
  if (command === 'sources') {
    if (!currentPage.value) return
    const data = await wikiApi
      .getPageSources(spaceId.value, kbId.value, currentPage.value.slug)
      .catch(() => null)
    if (data) {
      const detail = data.source_documents
        .map((s) => `${s.filename}${s.deleted ? '（已删除）' : ''}`)
        .join('\n')
      ElMessageBox.alert(detail || '无来源文档', '来源文档', { confirmButtonText: '关闭' })
    }
  } else if (command === 'delete') {
    await confirmDelete()
  }
}

async function confirmDelete() {
  if (!currentPage.value) return
  const slug = currentPage.value.slug
  try {
    await ElMessageBox.confirm(
      `确认删除页面「${currentPage.value.title}」？历史版本将一并不可见。`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await wikiApi.deletePage(spaceId.value, kbId.value, slug)
    ElMessage.success('已删除')
    currentPage.value = null
    selectedSlug.value = ''
    await loadIndex()
  } catch {
    ElMessage.error('删除失败')
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

// ============ 初始化 ============
onMounted(async () => {
  await loadIndex()
  // URL ?page=slug 直达
  const initialSlug = route.query.page as string | undefined
  if (initialSlug) {
    await selectPage(initialSlug)
  } else if (hasAnyPage.value) {
    const firstGroup = indexGroups.value.find((g) => g.items.length > 0)
    const firstItem = firstGroup?.items[0]
    if (firstGroup && firstItem) {
      await selectPage(firstItem.slug)
    }
  }
  // 生成状态：有进行中任务才启动轮询
  try {
    ingestStatus.value = await wikiApi.getIngestStatus(spaceId.value, kbId.value)
    if (ingestActive.value) startPolling()
  } catch {
    // ignore
  }
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.wiki-browser {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.ingest-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  margin-bottom: 12px;
  border-radius: var(--radius-xl);
  background: var(--color-bg-card-elevated, #f0f9eb);
  color: var(--el-color-primary);
  font-size: var(--text-sm);
}

.ingest-banner.is-failed {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}

.wiki-layout {
  display: flex;
  flex: 1;
  gap: 16px;
  min-height: 0;
}

/* 图谱 / 问题视图与浏览视图共用剩余高度；三视图互斥显示 */
.graph-wrap,
.issues-wrap {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

/* 问题视图工具栏：radio 组与按钮垂直居中，检查按钮靠右 */
.issues-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  background: var(--color-bg-card);
}

.wiki-sidebar {
  width: 280px;
  flex-shrink: 0;
  overflow-y: auto;
  padding: 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card);
}

.sidebar-search {
  margin-bottom: 12px;
}

.sidebar-group {
  margin-bottom: 16px;
}

.group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.page-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: var(--radius-lg);
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}

.page-item:hover {
  background: var(--color-bg-hover, rgba(0, 0, 0, 0.04));
}

.page-item.is-active {
  background: var(--el-color-primary-light-9);
}

.page-title {
  overflow: hidden;
  font-size: var(--text-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page-type-badge {
  flex-shrink: 0;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: var(--text-xs);
  background: var(--color-bg-hover, rgba(0, 0, 0, 0.05));
}

.page-type-badge[data-type='entity'] {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.page-type-badge[data-type='concept'] {
  color: var(--el-color-success);
  background: var(--el-color-success-light-9);
}

.page-type-badge[data-type='summary'] {
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
}

.empty-hint {
  padding: 12px;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.wiki-content {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  overflow-y: auto;
  padding: 24px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card);
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.page-title-main {
  margin: 0 0 8px;
  font-size: var(--text-2xl, 24px);
}

.page-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.page-body {
  flex: 1;
  line-height: 1.8;
}

.page-body :deep(.wiki-link) {
  color: var(--el-color-primary);
  text-decoration: none;
  border-bottom: 1px dashed var(--el-color-primary-light-5);
  cursor: pointer;
}

.page-body :deep(.wiki-link:hover) {
  border-bottom-style: solid;
}

.sources-panel {
  margin-top: 24px;
}

.source-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: var(--text-sm);
}

.source-link {
  color: var(--el-color-primary);
  text-decoration: none;
}

.source-deleted {
  color: var(--color-text-muted);
  text-decoration: line-through;
}

.wiki-empty {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
}

.form-hint {
  margin-left: 12px;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.revision-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-border-light);
}

.revision-info {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.revision-source {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: var(--text-xs);
  background: var(--color-bg-hover, rgba(0, 0, 0, 0.05));
}

.revision-title {
  overflow: hidden;
  font-size: var(--text-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.revision-time {
  color: var(--color-text-muted);
}

.diff-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 10px;
}

.diff-tag {
  font-family: monospace;
}

.diff-view {
  max-height: 40vh;
  padding: 10px;
  overflow-y: auto;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card-elevated);
  font-family: var(--font-mono, monospace);
  font-size: var(--text-xs);
}

.diff-line {
  display: flex;
  gap: 8px;
  padding: 1px 4px;
}

.diff-line.is-added {
  background: var(--el-color-success-light-9);
  color: var(--el-color-success);
}

.diff-line.is-removed {
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
}

.diff-marker {
  flex-shrink: 0;
  width: 14px;
  user-select: none;
}

.diff-text {
  white-space: pre-wrap;
  word-break: break-all;
}

@media (max-width: 768px) {
  .wiki-layout {
    flex-direction: column;
  }

  .wiki-sidebar {
    width: 100%;
    max-height: 40vh;
  }
}
</style>
