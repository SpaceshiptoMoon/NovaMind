<template>
  <nav class="ops-sub-nav" aria-label="知识运营子导航">
    <router-link
      v-for="item in items"
      :key="item.name"
      :to="item.to"
      class="ops-tab"
      :class="{ 'ops-tab--active': isActive(item.name) }"
    >
      {{ item.label }}
      <span v-if="badgeCount(item) > 0" class="ops-badge">{{ badgeCount(item) }}</span>
    </router-link>
  </nav>
</template>

<script setup lang="ts">
/**
 * 知识运营区子导航：四页签（工作台/缺口与失败/待办队列/资产健康）+ 待办徽标。
 *
 * 徽标数据由父壳（SpaceOpsView）轻量拉取后传入；徽标只在 >0 时显示——
 * 空徽标不占位（与 wiki 类型筛选 chips 同款空组折叠语义）。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const props = defineProps<{
  /** 徽标数：缺口待办数 / 队列 open 建议数 */
  badges?: { gaps?: number; queue?: number }
}>()

const route = useRoute()

const items = computed(() => [
  { name: 'SpaceOpsOverview', to: 'overview', label: '工作台' },
  { name: 'SpaceOpsGaps', to: 'gaps', label: '缺口与失败', badge: props.badges?.gaps ?? 0 },
  { name: 'SpaceOpsQueue', to: 'queue', label: '待办队列', badge: props.badges?.queue ?? 0 },
  { name: 'SpaceOpsHealth', to: 'health', label: '资产健康', badge: 0 },
])

function isActive(name: string): boolean {
  return route.name === name
}

function badgeCount(item: { badge?: number }): number {
  return item.badge ?? 0
}
</script>

<style scoped>
.ops-sub-nav {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--color-border-light);
}

.ops-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  font-size: 13px;
  color: var(--color-text-secondary);
  text-decoration: none;
  border-radius: 0;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition:
    color 0.15s,
    border-color 0.15s;
}

.ops-tab:hover {
  color: var(--color-text);
}

.ops-tab--active {
  color: var(--color-text);
  font-weight: 600;
  border-bottom-color: var(--color-primary);
}

.ops-badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--color-danger);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  line-height: 18px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
</style>
