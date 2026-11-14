/**
 * 聊天附件待发队列 slice（纯搬移自 stores/agent.ts）
 *
 * 状态独立（pendingAttachments）；上传走共享 /agent/attachments 端点，
 * 发消息时按 id 过滤进 extra.attachments（clear 由 sendMessageStream 回调）。
 */
import { ref } from 'vue'
import { agentApi } from '@/api/agent'
import type { ChatAttachment } from '@/api/types'

/** 创建附件域状态与操作（在 store setup 内调用一次） */
export function createAttachmentState() {
  const pendingAttachments = ref<ChatAttachment[]>([])

  /** 上传附件（共享 /agent/attachments 端点），成功后加入待发队列 */
  async function uploadAttachment(
    file: File,
    onProgress?: (percent: number) => void,
  ): Promise<ChatAttachment> {
    const result = await agentApi.uploadAttachment(file, onProgress)
    const attachment: ChatAttachment = {
      id: result.attachment_id,
      filename: result.filename,
      file_type: result.file_type,
      file_size: result.file_size,
    }
    pendingAttachments.value.push(attachment)
    return attachment
  }

  function removePendingAttachment(attachmentId: number) {
    pendingAttachments.value = pendingAttachments.value.filter((a) => a.id !== attachmentId)
  }

  function clearPendingAttachments() {
    pendingAttachments.value = []
  }

  return {
    pendingAttachments,
    uploadAttachment,
    removePendingAttachment,
    clearPendingAttachments,
  }
}

export type AttachmentState = ReturnType<typeof createAttachmentState>
