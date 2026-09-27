/**
 * v-permission 权限指令
 *
 * 无对应权限码时直接移除 DOM 元素（挂载时一次性判定，不响应权限变化）。
 */
import type { Directive } from 'vue'
import { usePermissionStore } from '@/stores/permission'

export const vPermission: Directive<HTMLElement, string | string[] | undefined> = {
  mounted(el, binding) {
    const store = usePermissionStore()
    if (binding.value && !store.hasPermission(binding.value)) {
      el.parentNode?.removeChild(el)
    }
  },
}
