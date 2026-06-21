<template>
  <div v-if="sources.length" class="source-list">
    <div class="source-list-header" @click="collapsed = !collapsed">
      <span class="source-list-title">📎 引用来源 · {{ sources.length }} 条</span>
      <el-icon :size="12" class="source-list-arrow" :class="{ collapsed }">
        <ArrowDown />
      </el-icon>
    </div>
    <transition name="source-collapse">
      <div v-show="!collapsed" class="source-list-items">
        <div
          v-for="s in sources"
          :key="s.index"
          class="source-card"
          :class="{ active: activeIndex === s.index }"
          @mouseenter="emit('hover', s.index)"
          @mouseleave="emit('hover', null)"
          @click="emit('select', s)"
        >
          <span class="source-index">{{ s.index }}</span>
          <div class="source-meta">
            <div class="source-name-row">
              <span class="source-name" :title="displayName(s)">{{ displayName(s) }}</span>
              <span class="source-kind" :class="s.kind || 'kb'">{{ s.kind === 'web' ? '联网' : '知识库' }}</span>
            </div>
            <div class="source-sub">
              <span v-if="s.score != null" class="source-score">相关度 {{ formatScore(s.score) }}</span>
              <span v-if="s.page != null" class="source-page">第 {{ s.page }} 页</span>
              <a
                v-if="s.url"
                :href="s.url"
                target="_blank"
                rel="noopener"
                class="source-link"
                @click.stop
              >链接 ↗</a
              >
            </div>
            <div v-if="s.snippet" class="source-snippet">{{ s.snippet }}</div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import type { ChatSource } from '@/api/types'

defineProps<{
  sources: ChatSource[]
  activeIndex?: number | null
}>()

const emit = defineEmits<{
  (e: 'hover', index: number | null): void
  (e: 'select', source: ChatSource): void
}>()

const collapsed = ref(false)

function displayName(s: ChatSource): string {
  return s.document_name || s.url || `来源 ${s.index}`
}

function formatScore(score: number): string {
  return Math.round(score * 100) + '%'
}
</script>

<style scoped>
.source-list {
  margin-top: 10px;
  border: 1px solid var(--color-border-light);
  border-radius: 10px;
  background: var(--color-bg-card-elevated);
  overflow: hidden;
}

.source-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
}

.source-list-header:hover {
  background: var(--color-bg-hover);
}

.source-list-title {
  font-size: 12px;
  color: var(--color-text-secondary);
  font-weight: 500;
}

.source-list-arrow {
  transition: transform 0.2s;
  color: var(--color-text-muted);
}

.source-list-arrow.collapsed {
  transform: rotate(-90deg);
}

.source-list-items {
  padding: 4px 8px 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.source-collapse-enter-active,
.source-collapse-leave-active {
  transition: all 0.2s;
  overflow: hidden;
}

.source-collapse-enter-from,
.source-collapse-leave-to {
  opacity: 0;
}

.source-card {
  display: flex;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid transparent;
  transition: all var(--transition-fast);
  cursor: pointer;
}

.source-card:hover,
.source-card.active {
  background: var(--color-primary-muted);
  border-color: var(--color-primary);
}

.source-index {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.source-card.active .source-index {
  background: var(--color-primary-hover);
}

.source-meta {
  flex: 1;
  min-width: 0;
}

.source-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.source-name {
  font-size: 13px;
  color: var(--color-text);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-kind {
  flex-shrink: 0;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.source-kind.kb {
  background: rgba(99, 102, 241, 0.12);
  color: var(--color-primary);
}

.source-kind.web {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.source-sub {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  margin-top: 3px;
  font-size: 11px;
  color: var(--color-text-muted);
}

.source-link {
  color: var(--color-primary);
}

.source-snippet {
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
