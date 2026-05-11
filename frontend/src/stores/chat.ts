import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { chatApi } from '@/api/chat'
import { sessionApi } from '@/api/session'
import type { ChatMessage, SessionItem, SessionConfigResponse, CompressionConfig } from '@/api/types'

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<SessionItem[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const isStreaming = ref(false)
  const streamingContent = ref('')
  const streamingReasoning = ref('')
  const loading = ref(false)
  const error = ref<string | null>(null)
  const sessionConfig = ref<SessionConfigResponse | null>(null)
  const sessionsTotal = ref(0)
  const abortController = ref<AbortController | null>(null)

  const hasSession = computed(() => !!currentSessionId.value)

  async function fetchSessions(params?: { limit?: number; offset?: number }) {
    try {
      const data = await sessionApi.getSessions(params)
      if (params?.offset && params.offset > 0) {
        sessions.value.push(...data.items)
      } else {
        sessions.value = data.items
      }
      sessionsTotal.value = data.total
    } catch {
      sessions.value = []
    }
  }

  async function fetchMessages(sessionId: string) {
    loading.value = true
    error.value = null
    try {
      const data = await sessionApi.getSessionMessages(sessionId)
      messages.value = data
      currentSessionId.value = sessionId
    } catch (e) {
      messages.value = []
      error.value = e instanceof Error ? e.message : '获取消息失败'
    } finally {
      loading.value = false
    }
  }

  async function deleteSession(sessionId: string) {
    await sessionApi.deleteSession(sessionId)
    sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
      messages.value = []
    }
  }

  async function sendMessage(content: string, options?: {
    system_prompt?: string
    llm_model?: string
    max_tokens?: number
    temperature?: number
    top_p?: number
    enable_thinking?: boolean
  }) {
    if (!content.trim()) return

    // 防止重复发送
    const lastMsg = messages.value[messages.value.length - 1]
    if (lastMsg?.role === 'user' && lastMsg.content === content && loading.value) {
      return
    }

    const userMessage: ChatMessage = {
      id: Date.now(),
      session_id: currentSessionId.value || '',
      role: 'user',
      content,
      user_id: 0,
      space_id: null,
      kb_id: null,
      extra: null,
      created_at: new Date().toISOString(),
    }
    messages.value.push(userMessage)

    loading.value = true
    error.value = null
    try {
      const data = await chatApi.chat({
        content,
        session_id: currentSessionId.value || undefined,
        system_prompt: options?.system_prompt,
        llm_model: options?.llm_model,
        max_tokens: options?.max_tokens,
        temperature: options?.temperature,
        top_p: options?.top_p,
        enable_thinking: options?.enable_thinking,
      })

      if (!currentSessionId.value) {
        currentSessionId.value = data.session_id
        sessions.value.unshift({
          session_id: data.session_id,
          preview: content.slice(0, 30),
        })
      }

      const lastIdx = messages.value.length - 1
      if (lastIdx >= 0) {
        messages.value[lastIdx] = data.user_message
      }
      messages.value.push(data.ai_message)
      return data
    } catch (e) {
      messages.value.pop()
      error.value = e instanceof Error ? e.message : '发送失败'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function sendMessageStream(content: string, options?: {
    system_prompt?: string
    llm_model?: string
    max_tokens?: number
    temperature?: number
    top_p?: number
    enable_thinking?: boolean
  }) {
    if (!content.trim()) return

    // 防止重复发送：如果最后一条消息内容相同且还在流式中，跳过
    const lastMsg = messages.value[messages.value.length - 1]
    if (lastMsg?.role === 'user' && lastMsg.content === content && isStreaming.value) {
      return
    }

    const userMessage: ChatMessage = {
      id: Date.now(),
      session_id: currentSessionId.value || '',
      role: 'user',
      content,
      user_id: 0,
      space_id: null,
      kb_id: null,
      extra: null,
      created_at: new Date().toISOString(),
    }
    messages.value.push(userMessage)

    const aiMessage: ChatMessage = {
      id: Date.now() + 1,
      session_id: currentSessionId.value || '',
      role: 'assistant',
      content: '',
      user_id: 0,
      space_id: null,
      kb_id: null,
      extra: null,
      created_at: new Date().toISOString(),
    }
    messages.value.push(aiMessage)

    isStreaming.value = true
    streamingContent.value = ''
    streamingReasoning.value = ''
    error.value = null

    const controller = new AbortController()
    abortController.value = controller

    try {
      await chatApi.chatStream({
        content,
        session_id: currentSessionId.value || undefined,
        system_prompt: options?.system_prompt,
        llm_model: options?.llm_model,
        max_tokens: options?.max_tokens,
        temperature: options?.temperature,
        top_p: options?.top_p,
        enable_thinking: options?.enable_thinking,
      }, {
        signal: controller.signal,
        onUserMessage(d) {
          // 用服务端返回的消息替换本地临时用户消息，保持 ID 一致
          const localUserMsg = messages.value.find(
            (m) => m.role === 'user' && m.content === content && typeof m.id === 'number' && m.id > 1000000000000
          )
          if (localUserMsg) {
            localUserMsg.id = d.id
            localUserMsg.session_id = d.session_id
            localUserMsg.created_at = d.created_at
          }

          if (d.session_id && !currentSessionId.value) {
            currentSessionId.value = d.session_id
            sessions.value.unshift({
              session_id: d.session_id,
              preview: content.slice(0, 30),
            })
          }
        },
        onReasoning(text) {
          streamingReasoning.value += text || ''
          const lastMsg = messages.value[messages.value.length - 1]
          if (lastMsg?.role === 'assistant') {
            lastMsg.reasoning = streamingReasoning.value
          }
        },
        onContent(text) {
          streamingContent.value += text || ''
          const lastMsg = messages.value[messages.value.length - 1]
          if (lastMsg?.role === 'assistant') {
            lastMsg.content = streamingContent.value
          }
        },
        onDone(d) {
          const lastMsg = messages.value[messages.value.length - 1]
          if (lastMsg?.role === 'assistant') {
            lastMsg.content = d.content || streamingContent.value
            if (d.id) lastMsg.id = d.id
          }
          if (d.session_id && !currentSessionId.value) {
            currentSessionId.value = d.session_id
            sessions.value.unshift({
              session_id: d.session_id,
              preview: content.slice(0, 30),
            })
          }
          controller.abort()
        },
        onError(err) {
          error.value = err.message
        },
      })
    } catch (e) {
      const lastMsg = messages.value[messages.value.length - 1]
      if (lastMsg?.role === 'assistant' && !lastMsg.content) {
        messages.value.pop()
      }
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : '发送失败'
      throw e
    } finally {
      isStreaming.value = false
      streamingContent.value = ''
      streamingReasoning.value = ''
      abortController.value = null
    }
  }

  function cancelStream() {
    abortController.value?.abort()
  }

  function clearMessages() {
    messages.value = []
    currentSessionId.value = null
    sessionConfig.value = null
  }

  async function fetchSessionConfig(sessionId: string) {
    if (!sessionId) {
      sessionConfig.value = null
      return
    }
    try {
      sessionConfig.value = await sessionApi.getConfig(sessionId)
    } catch {
      sessionConfig.value = null
    }
  }

  async function saveSessionConfig(sessionId: string, config: CompressionConfig) {
    sessionConfig.value = await sessionApi.createConfig(sessionId, { compression: config })
    return sessionConfig.value
  }

  async function deleteSessionConfig(sessionId: string) {
    await sessionApi.deleteConfig(sessionId)
    sessionConfig.value = null
  }

  function setSession(sessionId: string | null) {
    currentSessionId.value = sessionId
    if (!sessionId) {
      messages.value = []
    }
  }

  return {
    sessions,
    currentSessionId,
    messages,
    isStreaming,
    streamingContent,
    streamingReasoning,
    loading,
    error,
    sessionConfig,
    sessionsTotal,
    hasSession,
    fetchSessions,
    fetchMessages,
    deleteSession,
    sendMessage,
    sendMessageStream,
    cancelStream,
    clearMessages,
    setSession,
    fetchSessionConfig,
    saveSessionConfig,
    deleteSessionConfig,
  }
})
