<template>
  <div class="skill-marketplace">
    <PageHeader title="技能广场">
      <el-button v-if="userStore.user?.is_admin" @click="router.push('/home/workspace/skills/admin')">
        <el-icon><Setting /></el-icon>
        审核管理
      </el-button>
      <el-upload
        :show-file-list="false"
        :before-upload="handleUpload"
        accept=".zip"
      >
        <el-button type="primary" :loading="skillStore.uploading">
          <el-icon><Upload /></el-icon>
          上传技能
        </el-button>
      </el-upload>
    </PageHeader>

    <!-- Tab 切换 -->
    <div class="tab-bar">
      <button class="tab-btn" :class="{ active: activeTab === 'marketplace' }" @click="switchTab('marketplace')">广场</button>
      <button class="tab-btn" :class="{ active: activeTab === 'mine' }" @click="switchTab('mine')">我的技能</button>
    </div>

    <!-- 搜索和过滤（仅广场模式） -->
    <div v-if="activeTab === 'marketplace'" class="filter-bar">
      <el-input
        v-model="searchKeyword"
        placeholder="搜索技能..."
        clearable
        style="width: 300px"
        @keyup.enter="handleSearch"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="selectedCategory" placeholder="全部分类" clearable style="width: 150px" @change="handleSearch">
        <el-option v-for="cat in skillStore.categories" :key="cat" :label="cat" :value="cat" />
      </el-select>
      <el-select v-model="sortBy" style="width: 130px" @change="handleSearch">
        <el-option label="最新" value="newest" />
        <el-option label="最热门" value="popular" />
        <el-option label="最高评分" value="rating" />
        <el-option label="名称" value="name" />
      </el-select>
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
          <span class="card-icon">{{ skill.icon || '⚡' }}</span>
          <el-tag v-if="skill.skill_source === 'builtin'" type="warning" size="small">内置</el-tag>
          <el-tag v-else type="info" size="small">{{ skill.category || '通用' }}</el-tag>
        </div>
        <h3 class="card-title">{{ skill.display_name }}</h3>
        <p class="card-desc">{{ skill.description }}</p>
        <div class="card-footer">
          <div class="card-stats">
            <span class="stat"><el-icon><Download /></el-icon> {{ skill.install_count }}</span>
            <span class="stat"><el-icon><Star /></el-icon> {{ skill.rating_avg.toFixed(1) }}</span>
          </div>
          <div v-if="skill.tags?.length" class="card-tags">
            <el-tag v-for="tag in skill.tags.slice(0, 3)" :key="tag" size="small" type="info">{{ tag }}</el-tag>
          </div>
        </div>
        <div v-if="skill.author_name" class="card-author">by {{ skill.author_name }}</div>
      </div>

      <el-empty v-if="!currentLoading && currentSkills.length === 0" :description="activeTab === 'mine' ? '你还没有上传技能' : '暂无技能'" />
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
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Upload, Search, Download, Star, Setting } from '@element-plus/icons-vue'
import { useSkillStore } from '@/stores/skill'
import { useUserStore } from '@/stores/user'
import PageHeader from '@/components/common/PageHeader.vue'

const router = useRouter()
const skillStore = useSkillStore()
const userStore = useUserStore()

const activeTab = ref<'marketplace' | 'mine'>('marketplace')
const searchKeyword = ref('')
const selectedCategory = ref('')
const sortBy = ref('newest')
const currentPage = ref(1)
const pageSize = 20

const currentSkills = computed(() =>
  activeTab.value === 'mine' ? skillStore.mySkills : skillStore.marketplaceSkills,
)
const currentTotal = computed(() =>
  activeTab.value === 'mine' ? skillStore.mySkillsTotal : skillStore.marketplaceTotal,
)
const currentLoading = computed(() => skillStore.marketplaceLoading)

onMounted(() => {
  skillStore.fetchMarketplace({ sort: sortBy.value, limit: pageSize, offset: 0 })
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

function handleSearch() {
  currentPage.value = 1
  skillStore.fetchMarketplace({
    keyword: searchKeyword.value || undefined,
    category: selectedCategory.value || undefined,
    sort: sortBy.value,
    limit: pageSize,
    offset: 0,
  })
}

function handlePageChange(page: number) {
  const offset = (page - 1) * pageSize
  if (activeTab.value === 'mine') {
    skillStore.fetchMySkills({ limit: pageSize, offset })
  } else {
    skillStore.fetchMarketplace({
      keyword: searchKeyword.value || undefined,
      category: selectedCategory.value || undefined,
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
  } catch (e: any) {
    ElMessage.error(e?.message || '上传失败')
  }
  return false
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
}

/* ===== Card Grid ===== */
.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
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
  font-size: var(--text-3xl);
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
