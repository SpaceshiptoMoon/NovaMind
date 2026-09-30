/**
 * 剪贴板写入统一工具
 *
 * navigator.clipboard.writeText 在非用户手势上下文或权限被拒时会 reject
 * （NotAllowedError），降级走隐藏 textarea + document.execCommand('copy')。
 * execCommand 已废弃但作为降级路径仍被所有浏览器保留，仅在 clipboard API
 * 不可用时触达。
 */

/** 写文本到剪贴板；成功 resolve true，两条路径都失败 resolve false（不抛异常）。 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // 权限拒绝 / 非安全上下文等，落到降级路径
    }
  }
  return copyToClipboardLegacy(text)
}

/** 降级路径：隐藏 textarea + execCommand('copy')（需在用户手势调用栈内）。 */
function copyToClipboardLegacy(text: string): boolean {
  const textarea = document.createElement('textarea')
  textarea.value = text
  // 移到视口外而非 display:none：部分浏览器对不可聚焦元素拒绝复制
  textarea.style.position = 'fixed'
  textarea.style.top = '-9999px'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  document.body.removeChild(textarea)
  return ok
}
