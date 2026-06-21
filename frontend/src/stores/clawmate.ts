/**
 * ClawMate Store
 *
 * 管理 ClawMate AI 对话（SSE 流式）状态。
 * 遵循 Composition API 模式（与 agent.ts 一致）。
 */

import { ref } from 'vue'
import { defineStore } from 'pinia'
import { clawmateApi } from '@/api/clawmate'
import type {
  ClawMateChatMessage,
  ClawMateToolCallRecord,
} from '@/api/types'

export const useClawMateStore = defineStore('clawmate', () => {
  // ==================== 对话状态 ====================
  const messages = ref<ClawMateChatMessage[]>([])
  const isStreaming = ref(false)
  const streamingContent = ref('')
  const streamingReasoning = ref('')
  const toolCalls = ref<ClawMateToolCallRecord[]>([])
  const abortController = ref<AbortController | null>(null)
  const error = ref<string | null>(null)
  const warning = ref<string | null>(null)

  // ==================== AI 对话（SSE 流式） ====================

  /** 发送消息（SSE 流式） */
  async function sendMessage(content: string, model?: string) {
    if (!content.trim()) return

    // 添加用户消息
    const userMsg: ClawMateChatMessage = {
      id: Date.now(),
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    }
    messages.value.push(userMsg)

    isStreaming.value = true
    streamingContent.value = ''
    streamingReasoning.value = ''
    toolCalls.value = []
    error.value = null
    warning.value = null

    let assistantMsg: ClawMateChatMessage | null = null

    /** 确保 assistant 消息存在（返回响应式引用） */
    function ensureAssistant() {
      if (assistantMsg) return
      const msg: ClawMateChatMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        content: '',
        created_at: new Date().toISOString(),
      }
      messages.value.push(msg)
      // 取响应式代理引用，后续写入才能触发视图更新
      assistantMsg = messages.value[messages.value.length - 1]
    }

    const controller = new AbortController()
    abortController.value = controller

    try {
      await clawmateApi.chatStream(
        { content, model: model || null },
        {
          signal: controller.signal,
          onContent(text) {
            streamingContent.value += text || ''
            ensureAssistant()
            assistantMsg!.content = streamingContent.value
          },
          onReasoning(text) {
            streamingReasoning.value += text || ''
            ensureAssistant()
            assistantMsg!.reasoning = streamingReasoning.value
          },
          onToolCall(d) {
            const record: ClawMateToolCallRecord = {
              name: d.name,
              arguments: d.arguments,
              call_id: d.call_id,
              status: 'running',
            }
            toolCalls.value.push(record)

            // 在消息列表中插入工具消息
            const toolMsg: ClawMateChatMessage = {
              id: Date.now() + Math.random(),
              role: 'tool',
              content: '',
              tool_call_id: d.call_id,
              tool_name: d.name,
              created_at: new Date().toISOString(),
            }
            messages.value.push(toolMsg)
          },
          onToolResult(d) {
            // 更新工具调用记录状态
            const call = toolCalls.value.find((c) => c.call_id === d.call_id)
            if (call) {
              call.status = 'completed'
              call.result = d.result
            }
            // 更新工具消息内容
            const toolMsg = messages.value.find(
              (m) => m.tool_call_id === d.call_id && m.role === 'tool',
            )
            if (toolMsg) {
              toolMsg.content = d.result
            }
          },
          onWarning(msg) {
            warning.value = msg
          },
          onDone() {
            ensureAssistant()
            if (!assistantMsg!.content) {
              assistantMsg!.content = streamingContent.value
            }
            // done 后关闭流
            controller.abort()
          },
          onError(msg) {
            error.value = msg
            ensureAssistant()
            if (!assistantMsg!.content) {
              assistantMsg!.content = `[错误] ${msg}`
            }
          },
        },
      )
    } catch (e) {
      // 移除空的 assistant 消息
      if (assistantMsg && !assistantMsg.content) {
        const idx = messages.value.indexOf(assistantMsg)
        if (idx !== -1) messages.value.splice(idx, 1)
      }
      // 忽略 abort（用户主动取消）
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : '发送失败'
    } finally {
      isStreaming.value = false
      streamingContent.value = ''
      streamingReasoning.value = ''
      abortController.value = null
    }
  }

  /** 取消流式对话 */
  function cancelStream() {
    abortController.value?.abort()
  }

  /** 清空对话 */
  function clearChat() {
    messages.value = []
    toolCalls.value = []
    streamingContent.value = ''
    streamingReasoning.value = ''
    error.value = null
    warning.value = null
  }

  return {
    // State
    messages,
    isStreaming,
    streamingContent,
    streamingReasoning,
    toolCalls,
    abortController,
    error,
    warning,
    // Actions
    sendMessage,
    cancelStream,
    clearChat,
  }
})
