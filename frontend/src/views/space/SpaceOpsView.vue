<template>
  <div class="space-ops">
    <PageHeader title="知识运营">
      <template #actions>
        <el-button
          v-if="canSeeOps"
          size="small"
          :icon="Refresh"
          :loading="badgesLoading"
          @click="refreshBadges"
        >
          刷新
        </el-button>
      </template>
    </PageHeader>

    <!-- 运营区分层：空间管理员/平台 admin 可见（URL 直达同样拦截为占位页） -->
    <template v-if="canSeeOps">
      <OpsSubNav :badges="badges" />

      <router-view :key="route.fullPath" />
    </template>
    <EmptyState
      v-else-if="roleLoaded"
      title="无权访问知识运营"
      description="知识运营面向空间管理员开放；如有需要请联系空间管理员调整你的角色"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * 知识运营区壳：页头 + 四页签子导航 + 子路由出口。
 *
 * 徽标数（缺口待办/队列 open 建议）在此轻量拉取，子页经 inject 拿
 * refreshBadges 在处置动作后同步角标；切页时自动刷新一次。
 * 消费/运营分层：入口卡与本级壳都按「空间管理员或平台 admin」门控，
 * 普通成员经 URL 直达时渲染无权限占位而非运营数据视图。
 */
import { computed, onMounted, provide, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import PageHeader from '@/components/common/PageHeader.vue'
import OpsSubNav from '@/components/knowledge/ops/OpsSubNav.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { spaceStatsApi } from '@/api/knowledge'
import { usePermissionStore } from '@/stores/permission'
import { useMySpaceRole } from '@/composables/useMySpaceRole'

const route = useRoute()
const permStore = usePermissionStore()

const spaceId = computed(() => parseInt(String(route.params.id), 10))

const { isSpaceAdmin, loaded: roleLoaded } = useMySpaceRole(spaceId)
const canSeeOps = computed(() => permStore.isAdmin || isSpaceAdmin.value)

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
    if (canSeeOps.value && typeof name === 'string' && name.startsWith('SpaceOps')) {
      void refreshBadges()
    }
  },
)

onMounted(() => {
  if (canSeeOps.value) void refreshBadges()
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
