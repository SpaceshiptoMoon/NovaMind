<template>
  <!-- 分段面包屑：返回键（圆形 hover 位）+ 实体名链段 + 当前段灰底强调 -->
  <nav class="crumb-nav" aria-label="面包屑">
    <button
      v-if="backLabel"
      class="crumb-back"
      :title="backLabel"
      :aria-label="backLabel"
      @click="$emit('back')"
    >
      <el-icon :size="14"><ArrowLeft /></el-icon>
    </button>

    <template v-for="(item, i) in items" :key="`${item.label}-${i}`">
      <el-icon v-if="i > 0" :size="12" class="crumb-sep"><ArrowRight /></el-icon>
      <component
        :is="i < items.length - 1 && item.to ? 'button' : 'span'"
        class="crumb-item"
        :class="i < items.length - 1 && item.to ? 'crumb-item--link' : 'crumb-item--current'"
        :aria-current="i === items.length - 1 ? 'page' : undefined"
        @click="i < items.length - 1 && item.to && $emit('navigate', item.to)"
      >
        {{ item.label }}
      </component>
    </template>
  </nav>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { useSpaceStore } from '@/stores/space'

export interface CrumbItem {
  label: string
  to?: string
}

// 面包屑链段必传（最后一项为当前页，渲染为灰底当前态）；backLabel 不传则不渲染返回键
defineProps<{
  items: CrumbItem[]
  backLabel?: string
}>()

defineEmits<{
  back: []
  navigate: [to: string]
}>()

const route = useRoute()
const spaceStore = useSpaceStore()

const spaceId = computed(() => String(route.params.id ?? ''))

// 空间名由 store 预热（调用方渲染 items 时通常已取到 currentSpace）
onMounted(async () => {
  if (spaceId.value && !spaceStore.currentSpace) {
    try {
      await spaceStore.fetchSpace(Number(spaceId.value))
    } catch {
      // ignore breadcrumb fetch failure
    }
  }
})
</script>

<style scoped>
.crumb-nav {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  min-width: 0;
}

/* 返回键：28px 圆形操作位（与顶栏右侧按键同语言） */
.crumb-back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin-right: var(--space-2);
  border: none;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast),
    box-shadow var(--transition-base);
}

.crumb-back:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
  box-shadow: var(--shadow-xs);
}

.crumb-item {
  display: inline-flex;
  align-items: center;
  max-width: 220px;
  padding: 4px 10px;
  border: none;
  border-radius: var(--radius-full);
  background: transparent;
  font-family: var(--font-body);
  font-size: var(--text-sm);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.crumb-item--link {
  color: var(--color-text-muted);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.crumb-item--link:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

/* 当前段：灰底强调（不可点） */
.crumb-item--current {
  color: var(--color-text);
  font-weight: var(--weight-medium);
  background: var(--color-bg-hover);
}

.crumb-sep {
  color: var(--color-text-faint);
  flex-shrink: 0;
}
</style>
