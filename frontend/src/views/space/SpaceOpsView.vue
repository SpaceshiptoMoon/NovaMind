<template>
  <div class="space-ops">
    <PageHeader title="知识运营" />

    <!-- 运营分层：空间管理员/平台 admin 可见（URL 直达同样拦截为占位页） -->
    <template v-if="canSeeOps">
      <router-view />
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
 * 知识运营区壳：页头 + 角色门控 + 子路由出口（收件箱/下钻页）。
 *
 * 收件箱式一页（2026-11-16 用户拍板）：默认子路由是收件箱（结论行+待办流
 * +折叠明细）；gaps/queue/health 为下钻子路由，从收件箱进入。
 * opsRefreshBadges 保留 provide（下钻页处置动作后的同步钩子）——收件箱
 * 自持数据，此处为轻量空钩子。
 */
import { computed, provide } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { usePermissionStore } from '@/stores/permission'
import { useMySpaceRole } from '@/composables/useMySpaceRole'

const route = useRoute()
const permStore = usePermissionStore()

const spaceId = computed(() => parseInt(String(route.params.id), 10))

const { isSpaceAdmin, loaded: roleLoaded } = useMySpaceRole(spaceId)
const canSeeOps = computed(() => permStore.isAdmin || isSpaceAdmin.value)

// 下钻页处置后回调（收件箱数据自持，刷新由其自身 loadAll 承担）
provide('opsRefreshBadges', () => {})
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
