import { ref } from 'vue'

/**
 * 主题切换 composable
 * - 持久化到 localStorage，无记录时跟随系统 prefers-color-scheme
 * - data-theme 属性挂在 <html> 上，配合 base.css 的 [data-theme='dark'] token 块生效
 * - 模块级共享 state，多处调用拿到同一份 theme
 */

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'novamind-theme'

const theme = ref<Theme>('light')
let initialized = false

function applyTheme(value: Theme): void {
  document.documentElement.dataset.theme = value
}

/** 在应用挂载前调用一次，避免首屏主题闪烁 */
export function initTheme(): void {
  if (initialized) return
  initialized = true

  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') {
    theme.value = stored
  } else {
    theme.value = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  applyTheme(theme.value)
}

export function useTheme() {
  function toggleTheme(): void {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    localStorage.setItem(STORAGE_KEY, theme.value)
    applyTheme(theme.value)
  }

  return { theme, toggleTheme }
}