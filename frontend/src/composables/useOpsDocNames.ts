import { ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { documentApi, knowledgeBaseApi } from '@/api/knowledge'
import type { DocumentListResponse } from '@/api/types'

/**
 * 知识运营区文档名解析兜底（useOpsDocNames）。
 *
 * 治理视图（建议/重复/点击榜）后端只回 document_id 不带文件名；空间级批量
 * 文档名端点缺位，沿用旧 SpaceKbOpsView 的兜底法：逐 KB 拉 200 条建 id→名
 * 映射。KB 文档数超限的文档显示 #id（已知限制，不扩大处理）。
 *
 * @param spaceId 空间 ID（响应式）
 */
export function useOpsDocNames(spaceId: ComputedRef<number> | Ref<number>) {
  const docNames = ref<Record<number, string>>({})
  const loading = ref(false)

  /** 逐 KB 拉文档列表建映射；并发拉全空间 KB。失败静默（名称兜底 #id）。 */
  async function resolveDocNames(): Promise<void> {
    loading.value = true
    try {
      const kbs = await knowledgeBaseApi.getKnowledgeBases(spaceId.value)
      const lists = await Promise.all(
        (kbs.items ?? []).map((kb) =>
          documentApi
            .getDocuments(spaceId.value, kb.id, { limit: 200 })
            .then((r: DocumentListResponse) => r.items ?? [])
            .catch((): DocumentListResponse['items'] => []),
        ),
      )
      const map: Record<number, string> = {}
      for (const items of lists) {
        for (const doc of items) {
          map[doc.id] = doc.filename
        }
      }
      docNames.value = map
    } finally {
      loading.value = false
    }
  }

  /** 文档 ID → 显示名；未解析到时兜底 #id。 */
  function docName(id?: number | null): string {
    if (id === null || id === undefined) return '—'
    return docNames.value[id] ?? `#${id}`
  }

  return { docNames, loading, resolveDocNames, docName }
}
