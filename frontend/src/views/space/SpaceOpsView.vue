<template>
  <div class="space-ops">
    <PageHeader title="知识运营">
      <template #actions>
        <el-button size="small" :icon="Refresh" :loading="badgesLoading" @click="refreshBadges">
          刷新
        </el-button>
      </template>
    </PageHeader>

    <OpsSubNav :badges="badges" />

    <router-view :key="route.fullPath" />
  </div>
</template>

<script setup lang="ts">
/**
 * 知识运营区壳：页头 + 四页签子导航 + 子路由出口。
 *
 * 徽标数（缺口待办/队列 open 建议）在此轻量拉取，子页经 inject 拿
 * refreshBadges 在处置动作后同步角标；切页时自动刷新一次。
 */
import { computed, onMounted, provide, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import PageHeader from '@/components/common/PageHeader.vue'
import OpsSubNav from '@/components/knowledge/ops/OpsSubNav.vue'
import { spaceStatsApi } from '@/api/knowledge'

const route = useRoute()

const spaceId = computed(() => parseInt(String(route.params.id), 10))

const badges = ref<{ gaps: number; queue: number }>({ gaps: 0, queue: 0 })
const badgesLoading = ref(false)

/** 拉子导航徽标：缺口待办数（gap 簇数）+ 队列 open 建议数。失败静默（角标归零）。 */
async function refreshBadges(): Promise<void> {
  badgesLoading.value = true
  try {
    const [gapReport, suggestions] = await Promise.all([
      spaceStatsApi.getGapReport(spaceId.value),
      spaceStatsApi.getReviewSuggestions(spaceId.value),
    ])
    badges.value = {
      gaps: gapReport.kpi.gap_cluster_count ?? 0,
      queue: suggestions.total ?? 0,
    }
  } catch {
    badges.value = { gaps: 0, queue: 0 }
  } finally {
    badgesLoading.value = false
  }
}

provide('opsRefreshBadges', refreshBadges)

watch(
  () => route.name,
  (name) => {
    // 子页之间切换时刷新一次角标（处置动作后的同步由子页主动调 inject）
    if (typeof name === 'string' && name.startsWith('SpaceOps')) {
      void refreshBadges()
    }
  },
)

onMounted(() => {
  void refreshBadges()
})
</script>

<style scoped>
.space-ops {
  max-width: var(--container-width-lg, 1120px);
  margin: 0 auto;
  padding: var(--space-6, 24px);
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}
</style>
