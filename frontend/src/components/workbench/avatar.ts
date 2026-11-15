/**
 * 侧栏首字墨块取色：全站 Neutral Minimal 语言——不按名称上彩色，
 * 靠首字与位置辨识；哈希取色逻辑的色板收敛为灰阶档位。
 */

const AVATAR_PALETTE: readonly string[] = [
  'var(--color-bg-hover)',
  'var(--color-bg-card-elevated)',
]

export function avatarColor(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) | 0
  }
  return AVATAR_PALETTE[Math.abs(hash) % AVATAR_PALETTE.length] ?? 'var(--color-bg-hover)'
}
