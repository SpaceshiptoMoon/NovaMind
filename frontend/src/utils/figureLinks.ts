/**
 * PDF 解析产物中 figure 短路径 → 带鉴权代理端点 URL 的拼接。
 *
 * 后端解析管道把 figure 占位符替换为短文件名（figure_{safe_id}_{page}.png，
 * 相对文档 figure 目录），MD 全文 / chunk content 里即此形态。渲染时把
 * 短文件名拼成 documents/{id}/figures/{file} 代理端点（302 到即时签发的
 * MinIO 预签名 URL）。
 *
 * 历史（未重解析）文档正文里可能残留旧预签名 URL——不匹配本模式，原样
 * 保留，由重解析刷新。
 */

/** 与后端 resolve_figure_object_name 白名单一致（figure_xxx.png） */
const FIGURE_FILE_RE = /\]\((figure_[A-Za-z0-9_.-]+\.png)\)/g

const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

/**
 * 把 content 里 markdown 图片链接的 figure 短文件名替换为代理端点完整 URL。
 * 无匹配时原样返回（纯函数，安全用于模板表达式）。
 */
export function resolveFigureLinks(
  content: string,
  spaceId: number,
  kbId: number,
  docId: number,
): string {
  if (!content) return content
  return content.replace(
    FIGURE_FILE_RE,
    (_m, file: string) =>
      `](${baseURL}/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/figures/${encodeURIComponent(file)})`,
  )
}
