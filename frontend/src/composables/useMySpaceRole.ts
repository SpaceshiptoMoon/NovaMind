/**
 * 当前用户在指定空间的成员角色获取（带会话级缓存）。
 *
 * 数据源 GET /spaces/{id}/members/me（role：0=查看者 1=编辑者 2=管理员）；
 * 非成员（如公开空间访客）与请求失败均为 null。运营区可见性等空间级
 * 角色门控消费 isSpaceAdmin；平台 admin 短路请叠加 permission store 的
 * isAdmin（本 composable 不感知平台角色）。
 */
import { computed, ref, watch, type Ref } from 'vue'
import { memberApi } from '@/api/member'

/** 会话级缓存：同一空间多组件消费只请求一次（角色变更后刷新页面生效） */
const roleCache = new Map<number, number | null>()

export function useMySpaceRole(spaceId: Ref<number>) {
  const role = ref<number | null>(null)
  const loaded = ref(false)

  async function load(id: number) {
    if (!id) return
    if (roleCache.has(id)) {
      role.value = roleCache.get(id) ?? null
      loaded.value = true
      return
    }
    try {
      const info = await memberApi.getMyMemberInfo(id)
      role.value = typeof info.role === 'number' ? info.role : null
    } catch {
      // 非成员 / 网络失败：null（不可见方向）
      role.value = null
    }
    roleCache.set(id, role.value)
    loaded.value = true
  }

  watch(spaceId, (id) => void load(id), { immediate: true })

  /** 是否空间管理员（role=2） */
  const isSpaceAdmin = computed(() => role.value !== null && role.value >= 2)

  return { role, isSpaceAdmin, loaded }
}
