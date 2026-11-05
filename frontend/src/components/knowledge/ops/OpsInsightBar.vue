<template>
  <div v-if="items.length" class="ops-insight-bar">
    <div class="insight-label">本周洞察</div>
    <ul class="insight-list">
      <li v-for="(item, i) in items" :key="i" class="insight-item">
        <span v-if="item.tone === 'bad'" class="insight-dot dot-bad" aria-hidden="true" />
        <span v-else class="insight-dot dot-flat" aria-hidden="true" />
        <span class="insight-text">{{ item.text }}</span>
        <router-link v-if="item.to" :to="item.to" class="insight-link">{{
          item.linkLabel
        }}</router-link>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
/**
 * 运营洞察条：规则化洞察句列表（Tableau Pulse 式文案公式的平台内实现）。
 *
 * 句子由父页按「现象（数值+幅度）→ 归因 → 链接详情」公式组装传入；
 * 本组件只管展示层级与跳转，不做任何计算。
 */
interface InsightItem {
  /** 完整洞察句（现象+归因） */
  text: string
  /** 跳转目标（router-link to），缺省无链接 */
  to?: string
  /** 链接文案 */
  linkLabel?: string
  /** bad=红点强调（异常信号），flat=中性 */
  tone?: 'bad' | 'flat'
}

withDefaults(defineProps<{ items: InsightItem[] }>(), { items: () => [] })
</script>

<style scoped>
.ops-insight-bar {
  background: var(--ops-panel);
  border: 1px solid var(--ops-line);
  border-left: 3px solid var(--ops-ink-bar);
  border-radius: 8px;
  padding: 12px 16px;
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.insight-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  flex-shrink: 0;
  padding-top: 2px;
}

.insight-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.insight-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--color-text-secondary);
  flex-wrap: wrap;
}

.insight-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  align-self: center;
}

.dot-bad {
  background: var(--color-danger);
}

.dot-flat {
  background: var(--color-info);
}

.insight-text {
  min-width: 0;
}

.insight-link {
  font-size: 12px;
  color: var(--color-primary);
  text-decoration: none;
  flex-shrink: 0;
}

.insight-link:hover {
  text-decoration: underline;
}
</style>
