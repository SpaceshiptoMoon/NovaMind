/**
 * 成员标识色：按名字散列色相（主题中性的中等亮度，亮/暗主题均可读）
 *
 * 黄金角散列（137.5°）让相邻哈希值色相差尽量大；名字是用户认知锚点，
 * 同一成员在气泡头像/名字文字/群头像格/状态条全程同色。
 */

/** 名字 → 0-359 色相（确定性散列，跨会话稳定） */
export function memberHue(name: string): number {
  let hash = 0
  for (const ch of name) {
    hash = (hash * 31 + (ch.codePointAt(0) ?? 0)) >>> 0
  }
  return (hash * 137.508) % 360
}

/** 头像底色 + 白字（中等亮度饱和，亮暗主题通用） */
export function memberAvatarStyle(name: string): Record<string, string> {
  const h = memberHue(name)
  return { background: `hsl(${h} 58% 46%)`, color: '#fff' }
}

/** 名字文字色（中等亮度，暗底不刺眼、亮底可读） */
export function memberNameColor(name: string): string {
  return `hsl(${memberHue(name)} 52% 44%)`
}
