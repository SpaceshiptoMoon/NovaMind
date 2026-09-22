<template>
  <div class="wiki-browser">
    <div class="kb-layout">
      <KbSidebar :nav-items="kbNavItems" />

      <div class="kb-content">
        <!-- 顶部状态条 -->
        <div v-if="ingestActive" class="ingest-banner">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>Wiki 生成中（{{ ingestStatusText }}），页面可能不完整…</span>
        </div>
        <div v-else-if="ingestStatus?.status === 'failed'" class="ingest-banner is-failed">
          <el-icon><WarningFilled /></el-icon>
          <span>最近一次 Wiki 生成失败：{{ ingestStatus.error_message || '未知原因' }}</span>
        </div>

        <!-- 视图切换：浏览 / 图谱 / 问题。三个视图的内容直接放进对应 tab-pane，
             显隐完全交给 el-tabs 内部管理（图谱 pane 用 lazy 惰性挂载）。不要改回
             「tabs + 兄弟容器 v-show」写法——兄弟容器处于父级 dynamicChildren，
             实测反复触发 comment 占位符锚点失配（insertBefore(null)），patch 中断
             后 vdom 与 DOM 永久失同步：点左侧页面列表无反应、多视图同时可见 -->
        <el-tabs v-model="activeView" class="wiki-view-tabs" @tab-change="onActiveViewChange">
          <el-tab-pane label="浏览" name="browse">
            <!-- 浏览视图（原有布局） -->
            <div class="wiki-layout">
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

              <!-- 右侧：页面内容（唯一滚动列；内部限宽阅读列，宽屏两侧留白） -->
              <main ref="articleRef" class="wiki-content">
                <div class="article-column">
                <template v-if="currentPage">
                  <div class="page-header">
                    <div class="page-header-main">
                      <h2 class="page-title-main">{{ currentPage.title }}</h2>
                      <div class="page-meta">
                        <span class="page-type-badge" :data-type="currentPage.page_type">{{
                          typeLabel(currentPage.page_type)
                        }}</span>
                        <span class="meta-item">v{{ currentPage.version }}</span>
                        <span class="meta-item">{{
                          sourceLabel(currentPage.last_edit_source)
                        }}</span>
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
                </div>
              </main>

              <!-- 右侧：本页目录（批 3 接入数据，滚动高亮当前小节） -->
              <aside v-if="tocItems.length" class="wiki-toc">
                <div class="toc-header">本页目录</div>
                <button
                  v-for="item in tocItems"
                  :key="item.id"
                  type="button"
                  class="toc-item"
                  :class="[`is-l${item.level}`, { 'is-active': item.id === activeHeadingId }]"
                  @click="scrollToHeading(item.id)"
                >
                  {{ item.text }}
                </button>
              </aside>
            </div>
          </el-tab-pane>

          <el-tab-pane label="图谱" name="graph" lazy>
            <div class="graph-wrap">
              <WikiGraphPanel
                :space-id="spaceId"
                :kb-id="kbId"
                :initial-center="selectedSlug || undefined"
                @select="selectPageFromPanel"
              />
            </div>
          </el-tab-pane>

          <el-tab-pane
            :label="`问题${pendingIssueCount ? `（${pendingIssueCount}）` : ''}`"
            name="issues"
          >
            <div class="issues-wrap">
              <div class="issues-toolbar">
                <el-radio-group
                  v-model="issueFilter"
                  size="small"
                  :disabled="issuesLoading"
                  @change="loadIssues"
                >
                  <el-radio-button value="pending">待处理</el-radio-button>
                  <el-radio-button value="resolved">已解决</el-radio-button>
                  <el-radio-button value="ignored">已忽略</el-radio-button>
                </el-radio-group>
                <el-button
                  size="small"
                  :loading="lintRunning"
                  :disabled="issuesLoading"
                  @click="runLint"
                >
                  运行质量检查
                </el-button>
              </div>

              <!-- lint 检出问题（派生，非持久化） -->
              <div v-if="lintIssues.length" class="lint-section">
                <h4 class="lint-heading">质量检查（{{ lintIssues.length }} 项）</h4>
                <div v-for="(issue, index) in lintIssues" :key="`l${index}`" class="issue-row">
                  <el-tag size="small" type="warning">{{ lintTypeLabel(issue.issue_type) }}</el-tag>
                  <span class="issue-slug" @click="selectPageFromPanel(issue.slug)">{{
                    issue.slug
                  }}</span>
                  <span class="issue-desc">{{ issue.description }}</span>
                </div>
              </div>

              <!-- 持久化问题列表 -->
              <h4 class="lint-heading">问题登记（{{ issues.length }} 项）</h4>
              <div v-for="issue in issues" :key="issue.id" class="issue-row">
                <el-tag size="small">{{ issueTypeLabel(issue.issue_type) }}</el-tag>
                <span class="issue-slug" @click="selectPageFromPanel(issue.slug)">{{
                  issue.slug
                }}</span>
                <span class="issue-desc">{{ issue.description }}</span>
                <span class="issue-meta">{{ issue.reported_by }}</span>
                <el-button
                  v-if="issue.status === 'pending'"
                  size="small"
                  text
                  type="success"
                  :loading="updatingIssueId === issue.id"
                  @click="setIssueStatus(issue, 'resolved')"
                >
                  解决
                </el-button>
                <el-button
                  v-if="issue.status === 'pending'"
                  size="small"
                  text
                  :loading="updatingIssueId === issue.id"
                  @click="setIssueStatus(issue, 'ignored')"
                >
                  忽略
                </el-button>
              </div>
              <el-empty v-if="!issues.length && !lintIssues.length" description="没有问题" />
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
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
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Loading, MoreFilled, Search, WarningFilled } from '@element-plus/icons-vue'
import { wikiApi } from '@/api/knowledge'
import { renderMarkdownWithToc } from '@/utils/markdown'
import { diffLines as computeDiff, diffStats as diffStatsOf } from '@/utils/wikiDiff'
import { KbSidebar, buildKbNavItems } from '@/components/knowledge'
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

const kbNavItems = computed(() =>
  buildKbNavItems({
    spaceId: spaceId.value,
    kbId: kbId.value,
    currentRouteName: route.name,
  }),
)

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
  respyOnBrowse()
}

// 图谱/问题视图里点 slug → 切回浏览视图并定位页面
function selectPageFromPanel(slug: string) {
  activeView.value = 'browse'
  void selectPage(slug)
}

// ---- 问题登记 ----
const issues = ref<WikiIssue[]>([])
// 列表加载态与竞态序号（切 tab / 行操作后重载共用）
const issuesLoading = ref(false)
let issuesLoadSeq = 0
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
  // 竞态保护：快速切换过滤 tab 时只采纳最后一次请求的结果
  const seq = ++issuesLoadSeq
  issuesLoading.value = true
  try {
    const data = await wikiApi.listIssues(spaceId.value, kbId.value, issueFilter.value)
    if (seq === issuesLoadSeq) {
      issues.value = data
    }
  } catch {
    if (seq === issuesLoadSeq) {
      issues.value = []
    }
  } finally {
    if (seq === issuesLoadSeq) {
      issuesLoading.value = false
    }
  }
}

// 行级在途标记：解决/忽略按钮的 loading（仅该行转圈，不锁整列表）
const updatingIssueId = ref('')

async function setIssueStatus(issue: WikiIssue, status: string) {
  if (updatingIssueId.value) return // 已有在途操作，防重复提交
  updatingIssueId.value = issue.id
  try {
    await wikiApi.updateIssueStatus(spaceId.value, kbId.value, issue.id, status)
    await loadIssues()
  } catch {
    ElMessage.error('状态更新失败')
  } finally {
    updatingIssueId.value = ''
  }
}

// ---- lint 检查 ----
const lintIssues = ref<WikiLintIssue[]>([])
const lintRunning = ref(false)

async function runLint() {
  if (lintRunning.value) return // 防重复点击
  lintRunning.value = true
  try {
    const data = await wikiApi.lint(spaceId.value, kbId.value)
    lintIssues.value = data.issues
    if (!data.issues.length) {
      ElMessage.success(`检查完成（${data.checked_pages} 页），未发现问题`)
    }
  } catch {
    ElMessage.error('质量检查失败')
  } finally {
    lintRunning.value = false
  }
}

// ============ [[slug|title]] 链接预处理 + 本页目录 ============
// html 与 toc 从同一产物派生，保证标题 id 与目录项一一对应
const tocData = computed(() => {
  if (!currentPage.value) return { html: '', toc: [] }
  const md = currentPage.value.content.replace(
    /\[\[([^\]|]+)\|([^\]]+)\]\]/g,
    '<a class="wiki-link" data-slug="$1">$2</a>',
  )
  return renderMarkdownWithToc(md)
})
const renderedContent = computed(() => tocData.value.html)
const tocItems = computed(() => tocData.value.toc)

const articleRef = ref<HTMLElement | null>(null)
const activeHeadingId = ref('')

// ---- scroll-spy：IntersectionObserver 监听正文滚动容器 ----
// root 必须指向 .wiki-article（.wiki-content）而非缺省 window；
// suppressSpy 抑制点击目录后平滑滚动路过各小节时的闪烁高亮
const visibleHeadings = new Set<string>()
let spy: IntersectionObserver | null = null
let suppressSpy = false
let suppressTimer: number | null = null

function setupTocSpy() {
  spy?.disconnect()
  const root = articleRef.value
  if (!root || !tocItems.value.length) {
    activeHeadingId.value = ''
    return
  }
  spy = new IntersectionObserver(
    (entries) => {
      if (suppressSpy) return
      for (const entry of entries) {
        const id = (entry.target as HTMLElement).id
        if (entry.isIntersecting) visibleHeadings.add(id)
        else visibleHeadings.delete(id)
      }
      // 文档序最靠前的可见标题即当前小节
      const first = tocItems.value.find((t) => visibleHeadings.has(t.id))
      if (first) activeHeadingId.value = first.id
    },
    // 顶部 band（避开页头下沿到视口 70% 处）进出即触发
    { root, rootMargin: '-56px 0px -70% 0px', threshold: 0 },
  )
  root
    .querySelectorAll<HTMLElement>('.page-body h2[id], .page-body h3[id]')
    .forEach((el) => spy!.observe(el))
}

watch(
  renderedContent,
  () => {
    // v-html 整体替换后旧标题节点全部失效，必须等 nextTick 重建 observer
    void nextTick(() => {
      visibleHeadings.clear()
      activeHeadingId.value = ''
      setupTocSpy()
    })
  },
  { flush: 'post' },
)

function scrollToHeading(id: string) {
  const el = articleRef.value?.querySelector(`#${CSS.escape(id)}`)
  if (!el) return
  suppressSpy = true
  activeHeadingId.value = id
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  if (suppressTimer !== null) window.clearTimeout(suppressTimer)
  suppressTimer = window.setTimeout(() => {
    suppressSpy = false
    suppressTimer = null
  }, 800)
}

// 图谱/问题页签切回浏览时 DOM 从 display:none 恢复，需重验可见性
function respyOnBrowse() {
  if (activeView.value === 'browse') void nextTick(setupTocSpy)
}

function onContentClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  // 标题 hover 的 # 锚点：拦截默认行为（避免 vue-router hash 入栈），走平滑滚动
  if (target.closest('a.heading-anchor')) {
    event.preventDefault()
    const heading = target.closest('h2[id], h3[id]') as HTMLElement | null
    if (heading?.id) scrollToHeading(heading.id)
    return
  }
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

onBeforeUnmount(() => {
  stopPolling()
  spy?.disconnect()
  if (suppressTimer !== null) window.clearTimeout(suppressTimer)
})
</script>

<style scoped>
.wiki-browser {
  height: 100%;
}

/* 与 DocumentView/SearchView 等 KB 子页面一致的侧栏 + 内容布局 */
.kb-layout {
  display: flex;
  height: 100%;
  min-height: 0;
}

/* 内容区不再整体滚动——滚动权下放到各页签内部的列（正文列/问题列表/页面树），
   这是三栏 sticky（页面树/TOC 不随正文滚走）与图谱页签高度的基础 */
.kb-content {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  overflow: hidden;
}

/* 高度传递链：kb-content(flex col, overflow hidden)
   → tabs(flex:1, min-height:0, flex col)
   → header(flex-shrink:0) + content(flex:1, min-height:0)
   → pane(height:100%) → 各视图容器(height:100%)。
   任何一层漏掉 min-height:0 / height 链即塌陷回整页滚动 */
.wiki-view-tabs {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
}

.wiki-view-tabs :deep(.el-tabs__header) {
  flex-shrink: 0;
  margin: 0 0 var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
}

.wiki-view-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none; /* EP 默认灰色底线，换成自绘发丝线 */
}

.wiki-view-tabs :deep(.el-tabs__item) {
  height: 40px;
  margin-right: var(--space-5);
  padding: 0 var(--space-2);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  line-height: 40px;
  transition: color var(--transition-fast);
}

.wiki-view-tabs :deep(.el-tabs__item:hover) {
  color: var(--color-text);
}

.wiki-view-tabs :deep(.el-tabs__item.is-active) {
  color: var(--color-text);
  font-weight: var(--weight-semibold);
}

.wiki-view-tabs :deep(.el-tabs__active-bar) {
  height: 2px;
  border-radius: 1px;
  background: var(--color-btn-primary);
}

.wiki-view-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.wiki-view-tabs :deep(.el-tab-pane) {
  height: 100%;
}

.ingest-banner {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  /* 生成中：info 语义（带进行感），原写法变量恒存在导致 fallback 死代码 */
  background: var(--color-info-subtle);
  color: var(--color-info);
  font-size: var(--text-sm);
}

.ingest-banner.is-failed {
  color: var(--color-danger);
  background: var(--color-danger-subtle);
  border-color: var(--color-danger-subtle);
}

.wiki-layout {
  display: flex;
  height: 100%;
  gap: var(--space-4);
  min-height: 0;
}

/* 图谱 / 问题视图撑满 pane 高度；内容各自滚动 */
.graph-wrap,
.issues-wrap {
  display: flex;
  height: 100%;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 0;
}

/* 问题视图工具栏：radio 组与按钮垂直居中，检查按钮靠右 */
.issues-toolbar {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  background: var(--color-bg-card);
}

/* 左侧页面树：扁平 Linear 风（去卡壳），自身独立滚动 = 天然 sticky */
.wiki-sidebar {
  width: 256px;
  flex-shrink: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: var(--space-2);
}

.sidebar-search {
  padding: 0 var(--space-2) var(--space-3);
}

.sidebar-group {
  margin-bottom: var(--space-4);
}

.group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-1) var(--space-2);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.group-header small {
  color: var(--color-text-faint);
  font-size: var(--text-xs);
}

/* KbSidebar 同款页面项：扁平 + hover 浅底 + active 左侧指示条 */
.page-item {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  text-align: left;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.page-item::before {
  content: '';
  position: absolute;
  top: 20%;
  bottom: 20%;
  left: 0;
  width: 2px;
  border-radius: 1px;
  background: var(--color-btn-primary);
  opacity: 0;
  transition: opacity var(--transition-fast);
}

.page-item:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.page-item.is-active {
  background: var(--color-bg-hover);
  color: var(--color-text);
  font-weight: var(--weight-medium);
}

.page-item.is-active::before {
  opacity: 1;
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
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  background: var(--color-bg-hover);
}

/* 五种页面类型徽章（与 WikiGraphPanel 节点色系一致，light/dark 成对） */
.page-type-badge[data-type='entity'] {
  color: var(--color-primary);
  background: var(--color-primary-subtle);
}

.page-type-badge[data-type='concept'] {
  color: var(--color-success);
  background: var(--color-success-subtle);
}

.page-type-badge[data-type='summary'] {
  color: var(--color-warning);
  background: var(--color-warning-subtle);
}

.page-type-badge[data-type='synthesis'] {
  color: var(--color-danger);
  background: var(--color-danger-subtle);
}

.page-type-badge[data-type='comparison'] {
  color: var(--color-info);
  background: var(--color-info-subtle);
}

.empty-hint {
  padding: var(--space-3);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

/* 中列：唯一滚动容器（正文独立滚动，左右两列因此天然固定） */
.wiki-content {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card);
  scroll-behavior: smooth;
}

/* 限宽阅读列：宽屏居中留白，长行可读性（GitBook/Notion 惯例 ~760px） */
.article-column {
  width: 100%;
  max-width: 760px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-10);
}

/* 右侧本页目录：与页面树同款扁平语言 */
.wiki-toc {
  display: flex;
  width: 224px;
  flex-shrink: 0;
  flex-direction: column;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: var(--space-2);
}

.toc-header {
  padding: var(--space-1) var(--space-2) var(--space-3);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.toc-item {
  position: relative;
  padding: var(--space-1) var(--space-2);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  font-size: var(--text-sm);
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.toc-item.is-l3 {
  padding-left: var(--space-5);
}

.toc-item:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.toc-item.is-active {
  background: var(--color-bg-hover);
  color: var(--color-text);
  font-weight: var(--weight-medium);
}

.toc-item.is-active::before {
  content: '';
  position: absolute;
  top: 20%;
  bottom: 20%;
  left: 0;
  width: 2px;
  border-radius: 1px;
  background: var(--color-btn-primary);
}

.wiki-empty {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  min-height: 40vh;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: var(--space-4);
  margin-bottom: var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
}

.page-title-main {
  margin: 0 0 var(--space-2);
  font-size: var(--text-3xl);
  letter-spacing: var(--tracking-tight);
  text-wrap: balance;
}

.page-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.meta-item {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.page-body {
  line-height: 1.8;
}

/* 标题锚点：hover 标题时显示 # 链接 + 跳转不贴顶 */
.page-body :deep(h2),
.page-body :deep(h3) {
  position: relative;
  scroll-margin-top: var(--space-4);
}

.page-body :deep(.heading-anchor) {
  margin-left: var(--space-2);
  color: var(--color-text-faint);
  font-weight: var(--weight-normal);
  text-decoration: none;
  opacity: 0;
  transition: opacity var(--transition-fast);
  cursor: pointer;
}

.page-body :deep(h2:hover .heading-anchor),
.page-body :deep(h3:hover .heading-anchor) {
  opacity: 1;
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
  margin-top: var(--space-6);
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
  background: var(--color-bg-hover);
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
  max-height: 60vh;
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

/* ≥1400px 三栏齐全；窄于此隐藏 TOC，正文列自动居中（GitBook 1430px 同思路） */
@media (max-width: 1399px) {
  .wiki-toc {
    display: none;
  }
}

@media (max-width: 1200px) {
  .article-column {
    padding: var(--space-6) var(--space-5);
  }
}

/* 窄屏：树列改为顶部横块 */
@media (max-width: 960px) {
  .wiki-layout {
    flex-direction: column;
  }

  .wiki-sidebar {
    width: 100%;
    max-height: 40vh;
    flex-shrink: 1;
  }

  .wiki-content {
    min-height: 0;
  }
}
</style>
