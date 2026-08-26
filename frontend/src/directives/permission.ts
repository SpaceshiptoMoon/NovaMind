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
