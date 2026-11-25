<template>
  <div class="kb-register">
    <!-- 分节头：计数 + 新建入口（新建复用 KB 列表页弹窗，?create=1 触发） -->
    <div class="register-head">
      <span class="head-label">知识库 {{ activeKbs.length }}</span>
      <button
        type="button"
        class="head-add"
        title="新建知识库"
        aria-label="新建知识库"
        @click="createKb"
      >
        <el-icon :size="14"><Plus /></el-icon>
      </button>
    </div>

    <!-- 筛选行：仅 KB > 10 时出现（作用域小，客户端即打即现，无请求） -->
    <div v-if="activeKbs.length > 10" class="register-filter">
      <el-input
        v-model="filterText"
        size="small"
        placeholder="筛选知识库"
        clearable
        :prefix-icon="Search"
      />
    </div>

    <!-- 登记册：唯一滚动区，30px 字行纪律 -->
    <div class="register-list">
      <button
        v-for="kb in filteredKbs"
        :key="kb.id"
        type="button"
        class="kb-row"
        :class="{ active: kbIdInRoute === String(kb.id) }"
        :title="kb.name"
        @click="openKb(kb)"
      >
        <span class="kb-avatar" :style="{ background: avatarColor(kb.name) }">{{
          kb.name.charAt(0)
        }}</span>
        <span class="kb-name">{{ kb.name }}</span>
        <span v-if="failedCount(kb) > 0" class="kb-failed">{{ failedCount(kb) }}</span>
      </button>

      <div v-if="activeKbs.length === 0 && !spaceStore.kbLoading" class="register-empty">
        这个空间还没有知识库
        <button type="button" class="empty-action" @click="createKb">新建知识库</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 当前空间 KB 登记册：高频导航对象平铺字行，作用域被当前空间锁死
 * （列表上限 = 单空间 KB 数，无跨空间组合爆炸）。归档库不入册；
 * 失败任务 >0 的库行尾有 warning 小计数（信息而非装饰）。
 *
 * spaceId 由侧栏注入（路由 :id 优先，无空间参数页面回退最近空间）。
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Search } from '@element-plus/icons-vue'
import { useSpaceStore } from '@/stores/space'
import type { KnowledgeBase } from '@/api/types'
import { avatarColor } from './avatar'

const props = defineProps<{ spaceId: number }>()

const route = useRoute()
const router = useRouter()
const spaceStore = useSpaceStore()

const filterText = ref('')

const activeKbs = computed(() => spaceStore.currentSpaceKbs)

const filteredKbs = computed(() => {
  const kw = filterText.value.trim().toLowerCase()
  if (!kw) return activeKbs.value
  return activeKbs.value.filter((kb) => kb.name.toLowerCase().includes(kw))
})

/** 路由中的当前 KB id（路径参数优先，检索页经 query 传） */
const kbIdInRoute = computed(() => {
  const raw = route.params.kbId ?? route.query.kbId
  const first = Array.isArray(raw) ? raw[0] : raw
  return first != null ? String(first) : ''
})

function failedCount(kb: KnowledgeBase): number {
  return kb.stats?.failed_documents ?? 0
}

function openKb(kb: KnowledgeBase) {
  void router.push(`/home/spaces/${props.spaceId}/knowledge-bases/${kb.id}/documents`)
}

/** 新建 KB：跳 KB 列表页并经 ?create=1 打开 KnowledgeBaseView 的创建弹窗 */
function createKb() {
  const sid = props.spaceId
  const current = route.name === 'KnowledgeBases' && String(sid) === String(route.params.id)
  if (current) {
    // 已在 KB 列表页：直接改 query 触发该页弹窗（同页 push 由视图监听 query.create）
    void router.push({ path: `/home/spaces/${sid}/knowledge-bases`, query: { create: '1' } })
  } else {
    void router.push(`/home/spaces/${sid}/knowledge-bases?create=1`)
  }
}
</script>

<style scoped>
/* 按内容自然高度：滚动由外层 sidebar-scroll 整体承接（系统组紧跟内容排） */
.kb-register {
  display: flex;
  flex-direction: column;
}

.register-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 34px;
  padding: 0 var(--space-3) 0 var(--space-3);
}

.head-label {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

.head-add {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  background: none;
  border-radius: var(--radius-sm);
  color: var(--color-text-faint);
  cursor: pointer;
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.head-add:hover {
  color: var(--color-text);
  background: var(--color-bg-hover);
}

.register-filter {
  /* 与行左缘同一条 12px 对齐线 */
  padding: 0 var(--space-3) var(--space-1);
}

/* 登记册列表：自然高度，超长由外层滚动 */
.register-list {
  padding-bottom: var(--space-2);
}

.kb-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  height: 32px;
  padding: 0 var(--space-3);
  border: none;
  background: none;
  color: var(--color-text-secondary);
  cursor: pointer;
  text-align: left;
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.kb-row:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.kb-row.active {
  color: var(--color-primary);
  font-weight: var(--weight-semibold);
}

/* 登记簿墨线：与系统组/KbSidebar 同一语法 */
.kb-row.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--color-primary);
}

.kb-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.kb-name {
  flex: 1;
  min-width: 0;
  font-size: var(--text-sm);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kb-failed {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--color-warning);
  font-weight: var(--weight-medium);
}

.register-empty {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

/* 空屏是行动邀请：邀请语 + 墨黑小按钮 */
.empty-action {
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-btn-primary);
  color: var(--color-btn-primary-text);
  font-size: var(--text-xs);
  padding: var(--space-1) var(--space-3);
  cursor: pointer;
}

.empty-action:hover {
  background: var(--color-btn-primary-hover);
}
</style>
