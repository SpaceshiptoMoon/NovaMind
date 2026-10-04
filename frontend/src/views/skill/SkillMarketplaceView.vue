<template>
  <div class="skill-marketplace">
    <PageHeader title="技能广场">
      <el-button
        v-if="permStore.hasPermission('skill.config')"
        @click="router.push('/home/workspace/skills/admin')"
      >
        <el-icon><Setting /></el-icon>
        审核管理
      </el-button>
      <el-upload
        v-if="permStore.hasPermission('skill.config')"
        :show-file-list="false"
        :before-upload="handleUpload"
        accept=".zip"
      >
        <SkillFormatTooltip>
          <el-button type="primary" :loading="skillStore.uploading">
            <el-icon><Upload /></el-icon>
            上传技能
          </el-button>
        </SkillFormatTooltip>
      </el-upload>
      <!-- 空态 CTA 复用同一条上传通道（隐藏 input + 程序化触发） -->
      <input
        ref="uploadInputRef"
        type="file"
        accept=".zip"
        class="hidden-upload-input"
        @change="onHiddenInputChange"
      />
    </PageHeader>

    <!-- Tab 切换 -->
    <div class="tab-bar">
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'marketplace' }"
        @click="switchTab('marketplace')"
      >
        广场
      </button>
      <button class="tab-btn" :class="{ active: activeTab === 'mine' }" @click="switchTab('mine')">
        我的技能
      </button>
    </div>

    <!-- 搜索和过滤（仅广场模式） -->
    <div v-if="activeTab === 'marketplace'" class="filter-bar">
      <div class="search-section">
        <el-input
          v-model="searchKeyword"
          :placeholder="aiSearchMode ? '用自然语言描述你想要的技能...' : '搜索技能...'"
          clearable
          class="search-input"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        >
          <template #prefix
            ><el-icon><Search /></el-icon
          ></template>
        </el-input>
        <el-tooltip
          :content="aiSearchMode ? '切换到普通搜索' : '切换到 AI 智能搜索'"
          placement="top"
        >
          <button
            type="button"
            class="ai-toggle"
            :class="{ active: aiSearchMode }"
            :aria-label="aiSearchMode ? '切换到普通搜索' : '切换到 AI 智能搜索'"
            @click="toggleAISearch"
          >
            <el-icon><MagicStick /></el-icon>
          </button>
        </el-tooltip>
        <el-button v-if="aiSearchMode" type="primary" @click="handleSearch">AI 搜索</el-button>
      </div>
      <el-select
        v-model="selectedCategory"
        placeholder="全部分类"
        clearable
        style="width: 150px"
        @change="handleSearch"
      >
        <el-option v-for="cat in skillStore.categories" :key="cat" :label="cat" :value="cat" />
      </el-select>
      <el-select
        v-model="selectedTags"
        placeholder="标签筛选"
        clearable
        multiple
        collapse-tags
        collapse-tags-tooltip
        style="width: 200px"
        @change="handleSearch"
      >
        <el-option v-for="tag in skillStore.availableTags" :key="tag" :label="tag" :value="tag" />
      </el-select>
      <el-select v-model="sortBy" style="width: 130px" @change="handleSearch">
        <el-option label="最新" value="newest" />
        <el-option label="最热门" value="popular" />
        <el-option label="最高评分" value="rating" />
        <el-option label="名称" value="name" />
      </el-select>
    </div>

    <!-- AI 搜索解释横幅 -->
    <div v-if="aiSearchMode && skillStore.aiSearchExplanation" class="ai-explanation-banner">
      <el-alert
        :title="skillStore.aiSearchExplanation"
        type="info"
        show-icon
        :closable="true"
        @close="clearAISearch"
      />
    </div>

    <!-- 技能卡片网格 -->
    <div v-loading="currentLoading" class="skill-grid">
      <div
        v-for="skill in currentSkills"
        :key="skill.id"
        class="skill-card"
        @click="goToDetail(skill.id)"
      >
        <div class="card-header">
          <span class="card-icon" aria-hidden="true">
            <el-icon><MagicStick /></el-icon>
          </span>
          <el-tag v-if="skill.skill_source === 'builtin'" type="warning" size="small">内置</el-tag>
          <el-tag v-else type="info" size="small">{{ skill.category || '通用' }}</el-tag>
        </div>
        <h3 class="card-title">{{ skill.display_name }}</h3>
        <p class="card-desc">{{ skill.description }}</p>
        <div class="card-footer">
          <div class="card-stats">
            <span class="stat"
              ><el-icon><Download /></el-icon> {{ skill.install_count }}</span
            >
            <span class="stat"
              ><el-icon><Star /></el-icon> {{ skill.rating_avg.toFixed(1) }}</span
            >
          </div>
          <div v-if="skill.tags?.length" class="card-tags">
            <el-tag v-for="tag in skill.tags.slice(0, 3)" :key="tag" size="small" type="info">{{
              tag
            }}</el-tag>
          </div>
        </div>
        <div v-if="skill.author_name" class="card-author">by {{ skill.author_name }}</div>
      </div>

      <EmptyState
        v-if="!currentLoading && currentSkills.length === 0"
        :variant="activeTab === 'mine' ? 'default' : 'search'"
        :headline="activeTab === 'mine' ? '你还没有上传技能' : '没有找到匹配的技能'"
        :description="
          activeTab === 'mine'
            ? '将技能打包为 .zip（内含 SKILL.md）上传，即可在广场发布分享给团队成员'
            : searchKeyword || selectedCategory || selectedTags.length
              ? '换个关键词或清除筛选条件再试试'
              : '广场暂无已发布技能，上传第一个技能让大家用起来'
        "
      >
        <el-button
          v-if="permStore.hasPermission('skill.config') && activeTab === 'mine'"
          @click="triggerUpload"
        >
          <el-icon><Upload /></el-icon>
          上传技能
        </el-button>
        <el-button
          v-if="
            permStore.hasPermission('skill.config') &&
            activeTab === 'marketplace' &&
            !searchKeyword &&
            !selectedCategory &&
            !selectedTags.length
          "
          type="primary"
          @click="triggerUpload"
        >
          <el-icon><Upload /></el-icon>
          上传第一个技能
        </el-button>
      </EmptyState>
    </div>

    <!-- 分页 -->
    <div v-if="currentTotal > pageSize" class="pagination-area">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="currentTotal"
        layout="prev, pager, next"
        @current-change="handlePageChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 技能广场页（/home/workspace/skills）
 *
 * 对应路由 WorkspaceSkills，广场/我的技能双 Tab 浏览，支持普通搜索、AI 智能搜索、
 * 分类/标签/排序过滤与 zip 技能包上传（上传与审核入口需 skill.config 权限）。
 */

import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Upload, Search, Download, Star, Setting, MagicStick } from '@element-plus/icons-vue'
import { useSkillStore } from '@/stores/skill'
import { usePermissionStore } from '@/stores/permission'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import SkillFormatTooltip from '@/components/skill/SkillFormatTooltip.vue'

const router = useRouter()
const skillStore = useSkillStore()
const permStore = usePermissionStore()

const activeTab = ref<'marketplace' | 'mine'>('marketplace')
const searchKeyword = ref('')
const selectedCategory = ref('')
const selectedTags = ref<string[]>([])
const sortBy = ref('newest')
const currentPage = ref(1)
const pageSize = 20
const aiSearchMode = ref(false)
const uploadInputRef = ref<HTMLInputElement | null>(null)

const currentSkills = computed(() => {
  if (activeTab.value === 'mine') return skillStore.mySkills
  // AI 搜索模式以 parsedQuery 为准（而非 results.length），
  // 否则零结果时会错误回落显示广场列表而非空状态
  return aiSearchMode.value && skillStore.aiSearchParsedQuery
    ? skillStore.aiSearchResults
    : skillStore.marketplaceSkills
})
const currentTotal = computed(() => {
  if (activeTab.value === 'mine') return skillStore.mySkillsTotal
  return aiSearchMode.value && skillStore.aiSearchParsedQuery
    ? skillStore.aiSearchTotal
    : skillStore.marketplaceTotal
})
const currentLoading = computed(() => {
  if (activeTab.value === 'mine') return false
  return aiSearchMode.value ? skillStore.aiSearchLoading : skillStore.marketplaceLoading
})

onMounted(() => {
  Promise.all([
    skillStore.fetchMarketplace({ sort: sortBy.value, limit: pageSize, offset: 0 }),
    skillStore.fetchCategories(),
    skillStore.fetchTags(),
  ])
})

function switchTab(tab: 'marketplace' | 'mine') {
  activeTab.value = tab
  currentPage.value = 1
  if (tab === 'mine') {
    skillStore.fetchMySkills({ limit: pageSize, offset: 0 })
  } else {
    handleSearch()
  }
}

function toggleAISearch() {
  aiSearchMode.value = !aiSearchMode.value
  if (!aiSearchMode.value) {
    clearAISearch()
  }
  searchKeyword.value = ''
}

function clearAISearch() {
  aiSearchMode.value = false
  skillStore.aiSearchResults = []
  skillStore.aiSearchTotal = 0
  skillStore.aiSearchExplanation = ''
  skillStore.aiSearchParsedQuery = null
}

/** 执行搜索：AI 模式走自然语言解析搜索，否则按关键字/分类/标签/排序走广场列表 */
function handleSearch() {
  currentPage.value = 1
  if (aiSearchMode.value && searchKeyword.value) {
    skillStore.aiSearch({
      query: searchKeyword.value,
      limit: pageSize,
      offset: 0,
    })
  } else {
    // AI 模式下清空关键词应回落普通列表（parsedQuery 置空让 currentSkills 切回 marketplace）
    if (aiSearchMode.value && !searchKeyword.value) {
      skillStore.aiSearchParsedQuery = null
    }
    skillStore.fetchMarketplace({
      keyword: searchKeyword.value || undefined,
      category: selectedCategory.value || undefined,
      tags: selectedTags.value.length > 0 ? selectedTags.value.join(',') : undefined,
      sort: sortBy.value,
      limit: pageSize,
      offset: 0,
    })
  }
}

function handlePageChange(page: number) {
  const offset = (page - 1) * pageSize
  if (activeTab.value === 'mine') {
    skillStore.fetchMySkills({ limit: pageSize, offset })
  } else if (aiSearchMode.value && skillStore.aiSearchParsedQuery) {
    skillStore.aiSearch({
      query: searchKeyword.value,
      limit: pageSize,
      offset,
    })
  } else {
    skillStore.fetchMarketplace({
      keyword: searchKeyword.value || undefined,
      category: selectedCategory.value || undefined,
      tags: selectedTags.value.length > 0 ? selectedTags.value.join(',') : undefined,
      sort: sortBy.value,
      limit: pageSize,
      offset,
    })
  }
}

function goToDetail(skillId: number) {
  const query = activeTab.value === 'mine' ? '?from=mine' : ''
  router.push(`/home/workspace/skills/${skillId}${query}`)
}

/** el-upload before-upload 钩子：手动调 API 上传 zip 并刷新当前列表，返回 false 阻止默认上传 */
async function handleUpload(file: File) {
  if (!file.name.endsWith('.zip')) {
    ElMessage.error('请上传 .zip 格式的文件')
    return false
  }
  try {
    const result = await skillStore.uploadSkill(file)
    ElMessage.success(`技能 "${result.display_name}" 上传成功`)
    if (activeTab.value === 'mine') {
      skillStore.fetchMySkills({ limit: pageSize, offset: 0 })
    } else {
      skillStore.fetchMarketplace({ sort: sortBy.value, limit: pageSize, offset: 0 })
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '上传失败')
  }
  return false
}

/** 空态 CTA 复用页头同一上传通道：程序化触发隐藏的文件选择框 */
function triggerUpload() {
  uploadInputRef.value?.click()
}

/** 隐藏 input 的 change 处理：交给 handleUpload 后清空 value 以便重选同一文件 */
async function onHiddenInputChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) await handleUpload(file)
  input.value = ''
}
</script>

<style scoped>
.skill-marketplace {
  position: absolute;
  inset: 0;
  padding: var(--space-6);
  overflow-y: auto;
}

/* ===== Tab Bar ===== */
.tab-bar {
  display: flex;
  gap: 0;
  margin-bottom: var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
}

.tab-btn {
  padding: var(--space-2) var(--space-5);
  border: none;
  background: transparent;
  font-family: var(--font-body);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
  position: relative;
  font-weight: var(--weight-medium);
}

.tab-btn:hover {
  color: var(--color-text-secondary);
}

.tab-btn.active {
  color: var(--color-primary);
}

.tab-btn.active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  background: var(--color-primary);
  border-radius: 2px 2px 0 0;
}

.filter-bar {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-6);
  align-items: center;
  flex-wrap: wrap;
}

.search-section {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  /* 窄视口下输入框收缩、按钮换行进首屏（评审 P3-1），不靠容器横向滚动兜底 */
  flex-wrap: wrap;
  /* flex 子项内容宽可撑破 wrap 容器（min-width:auto），显式收敛保证 320px 不溢出 */
  min-width: 0;
  max-width: 100%;
}

.search-input {
  width: 320px;
  max-width: 100%;
}

/* AI 搜索模式开关：中性芯片（激活=墨水蓝淡底），与搜索按钮解耦 */
.ai-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-base);
}

.ai-toggle:hover {
  border-color: var(--color-border);
  color: var(--color-text-secondary);
}

.ai-toggle.active {
  background: var(--color-primary-muted);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.hidden-upload-input {
  display: none;
}

.ai-explanation-banner {
  margin-bottom: var(--space-4);
}

/* ===== Card Grid ===== */
.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(280px, 100%), 1fr));
  gap: var(--space-4);
  min-height: 200px;
}

.skill-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  padding: var(--space-5);
  cursor: pointer;
  transition: all var(--transition-base);
}

.skill-card:hover {
  border-color: var(--color-border);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-3);
}

.card-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  font-size: var(--text-lg);
}

.card-icon .el-icon {
  font-size: 18px;
}

.card-title {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  margin: 0 0 var(--space-2);
  color: var(--color-text);
}

.card-desc {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  line-height: var(--leading-normal);
  margin: 0 0 var(--space-4);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
}

.card-stats {
  display: flex;
  gap: var(--space-3);
  flex-shrink: 0;
}

.stat {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.card-tags {
  display: flex;
  gap: var(--space-1);
  flex-wrap: nowrap;
  overflow: hidden;
  /* footer 剩余宽度内收敛：卡片极窄时放不下的 tag 直接裁掉，不撑破卡片 */
  min-width: 0;
}

.card-tags .el-tag {
  flex-shrink: 0;
}

.card-author {
  margin-top: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

.pagination-area {
  display: flex;
  justify-content: center;
  margin-top: var(--space-6);
}
</style>
