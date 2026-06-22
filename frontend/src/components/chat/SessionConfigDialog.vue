<template>
  <el-dialog v-model="visible" title="会话配置" width="520px" append-to-body destroy-on-close @close="handleClose">
    <el-form :model="configForm" label-width="120px">
      <!-- 压缩配置 -->
      <el-form-item label="自动压缩长对话">
        <el-switch v-model="configForm.enable_compression" />
      </el-form-item>

      <el-form-item label="压缩策略">
        <el-select v-model="configForm.strategy" style="width: 100%" :disabled="!configForm.enable_compression">
          <el-option label="摘要压缩（需要 LLM）" value="summary" />
          <el-option label="滑动窗口" value="sliding_window" />
          <el-option label="保留最近" value="keep_recent" />
          <el-option label="截断" value="truncate" />
        </el-select>
      </el-form-item>

      <el-form-item label="压缩阈值">
        <el-input-number v-model="configForm.threshold" :min="500" :max="200000" :step="1000" style="width: 100%" :disabled="!configForm.enable_compression" />
      </el-form-item>

      <el-form-item label="保留消息数">
        <el-input-number v-model="configForm.keep_recent" :min="0" :max="10" style="width: 100%" :disabled="!configForm.enable_compression" />
      </el-form-item>

      <el-form-item label="压缩后目标长度">
        <el-input-number v-model="configForm.target_tokens" :min="100" :max="2000" :step="100" style="width: 100%" :disabled="!configForm.enable_compression" />
      </el-form-item>

      <el-form-item label="摘要提示词">
        <el-input v-model="configForm.custom_prompt" type="textarea" :rows="3" placeholder="自定义摘要生成提示词（可选）" maxlength="2000" :disabled="!configForm.enable_compression || configForm.strategy !== 'summary'" />
      </el-form-item>

      <el-divider content-position="left">会话级自动 RAG</el-divider>

      <el-form-item label="启用自动检索">
        <el-switch v-model="ragForm.auto_rag" />
        <span class="form-hint">开启后本会话无需每次手动开关，自动检索绑定的知识库</span>
      </el-form-item>

      <el-form-item label="绑定空间">
        <el-select v-model="ragForm.space_id" placeholder="选择空间" filterable clearable style="width: 100%" @change="handleRagFormSpaceChange">
          <el-option v-for="s in spaceStore.spaces" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
      </el-form-item>

      <el-form-item label="绑定知识库">
        <el-select v-model="ragForm.kb_ids" multiple filterable placeholder="选择知识库（可多选）" style="width: 100%" :disabled="!ragForm.space_id">
          <el-option v-for="kb in ragFormKbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
      </el-form-item>

      <el-form-item label="分级拒答">
        <el-switch v-model="ragForm.refusal_enabled" />
        <span class="form-hint">检索为空时拒答，单库低分时标记「依据较弱」</span>
      </el-form-item>

      <el-form-item v-if="ragForm.refusal_enabled" label="低置信阈值">
        <el-input-number v-model="ragForm.score_threshold" :min="0" :max="1" :step="0.05" :precision="2" style="width: 100%" />
      </el-form-item>

      <el-form-item label="检索模式">
        <el-select v-model="ragForm.search_mode" style="width: 100%">
          <el-option label="内容混合（推荐）" value="content_hybrid" />
          <el-option label="向量语义" value="vector" />
          <el-option label="关键词 BM25" value="bm25" />
          <el-option label="问题混合" value="question_hybrid" />
        </el-select>
      </el-form-item>

      <el-form-item label="检索条数">
        <el-input-number v-model="ragForm.top_k" :min="1" :max="20" style="width: 100%" />
      </el-form-item>

      <el-divider content-position="left">模型生成参数</el-divider>

      <el-form-item label="温度">
        <el-input-number v-model="llmForm.temperature" :min="0" :max="2" :step="0.1" style="width: 100%" />
      </el-form-item>

      <el-form-item label="Top-P">
        <el-input-number v-model="llmForm.top_p" :min="0" :max="1" :step="0.1" style="width: 100%" />
      </el-form-item>

      <el-form-item label="最大 Tokens">
        <el-input-number v-model="llmForm.max_tokens" :min="1" :max="8192" :step="256" style="width: 100%" />
      </el-form-item>

      <el-form-item label="系统提示词">
        <el-input v-model="llmForm.system_prompt" type="textarea" :rows="3" placeholder="自定义系统提示词（留空用后端 QA 模板）" maxlength="4000" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { sessionApi } from '@/api/session'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import { useChatStore } from '@/stores/chat'
import { useSpaceStore } from '@/stores/space'

const emit = defineEmits<{ saved: [] }>()
const props = withDefaults(defineProps<{ sessionId?: string | null }>(), { sessionId: null })

const chatStore = useChatStore()
const spaceStore = useSpaceStore()
const visible = ref(false)
const saving = ref(false)
const configForm = reactive({
  enable_compression: true,
  strategy: 'summary' as 'summary' | 'sliding_window' | 'keep_recent' | 'truncate',
  threshold: 3000,
  keep_recent: 2,
  target_tokens: 500,
  custom_prompt: '',
})

const ragForm = reactive({
  space_id: null as number | null,
  kb_ids: [] as number[],
  auto_rag: false,
  refusal_enabled: false,
  score_threshold: 0.3,
  search_mode: 'content_hybrid',
  top_k: 5,
})

const ragFormKbOptions = ref<{ id: number; name: string }[]>([])

const llmForm = reactive({
  max_tokens: 2048 as number | null,
  temperature: 0.7 as number | null,
  top_p: 0.8 as number | null,
  system_prompt: '',
})

watch(() => props.sessionId, (newId) => {
  if (newId) {
    visible.value = true
    loadConfig(newId)
  }
})

function handleClose() {
  visible.value = false
}

async function loadConfig(sessionId: string) {
  // 重置表单
  ragForm.space_id = null; ragForm.kb_ids = []; ragForm.auto_rag = false
  ragForm.refusal_enabled = false; ragForm.score_threshold = 0.3
  ragForm.search_mode = 'content_hybrid'; ragForm.top_k = 5
  llmForm.max_tokens = 2048; llmForm.temperature = 0.7
  llmForm.top_p = 0.8; llmForm.system_prompt = ''
  ragFormKbOptions.value = []

  if (spaceStore.spaces.length === 0) {
    try { await spaceStore.fetchSpaces() } catch { /* 忽略 */ }
  }

  try {
    await chatStore.fetchSessionConfig(sessionId)
    const cfg = chatStore.sessionConfig?.compression_config
    if (cfg) {
      configForm.enable_compression = cfg.enable_compression ?? true
      configForm.strategy = cfg.strategy || 'summary'
      configForm.threshold = cfg.threshold || 3000
      configForm.keep_recent = cfg.keep_recent ?? 2
      configForm.target_tokens = cfg.target_tokens || 500
      configForm.custom_prompt = cfg.custom_prompt || ''
    }
    const kb = chatStore.sessionConfig?.kb_bindings
    if (kb) {
      const boundKbIds = Array.isArray(kb.kb_ids) ? [...kb.kb_ids] : []
      ragForm.space_id = kb.space_id ?? null
      ragForm.auto_rag = !!kb.auto_rag
      ragForm.refusal_enabled = !!kb.refusal_enabled
      ragForm.score_threshold = kb.score_threshold ?? 0.3
      ragForm.search_mode = kb.search_mode || 'content_hybrid'
      ragForm.top_k = kb.top_k ?? 5
      if (ragForm.space_id) {
        await handleRagFormSpaceChange(ragForm.space_id)
      }
      ragForm.kb_ids = boundKbIds
    }
    const llm = chatStore.sessionConfig?.llm_config
    if (llm) {
      llmForm.max_tokens = llm.max_tokens ?? 2048
      llmForm.temperature = llm.temperature ?? 0.7
      llmForm.top_p = llm.top_p ?? 0.8
      llmForm.system_prompt = llm.system_prompt || ''
    }
  } catch {
    // 使用默认值
  }
}

async function handleRagFormSpaceChange(spaceId: number | null) {
  ragForm.kb_ids = []
  ragFormKbOptions.value = []
  if (!spaceId) return
  try {
    const resp = await knowledgeBaseApi.getKnowledgeBases(spaceId)
    ragFormKbOptions.value = (resp?.items ?? []).map((kb) => ({ id: kb.id, name: kb.name }))
  } catch {
    ragFormKbOptions.value = []
  }
}

async function handleSave() {
  saving.value = true
  try {
    await sessionApi.updateCompressionConfig(props.sessionId!, {
      compression: {
        enable_compression: configForm.enable_compression,
        strategy: configForm.strategy,
        threshold: configForm.threshold,
        keep_recent: configForm.keep_recent,
        target_tokens: configForm.target_tokens,
        custom_prompt: configForm.custom_prompt || undefined,
      },
    })
    await sessionApi.updateLlmConfig(props.sessionId!, {
      llm_config: {
        max_tokens: llmForm.max_tokens,
        temperature: llmForm.temperature,
        top_p: llmForm.top_p,
        system_prompt: llmForm.system_prompt || undefined,
      },
    })
    const ragUpdated = await sessionApi.updateRagConfig(props.sessionId!, {
      rag: {
        space_id: ragForm.space_id,
        kb_ids: ragForm.kb_ids,
        auto_rag: ragForm.auto_rag,
        refusal_enabled: ragForm.refusal_enabled,
        score_threshold: ragForm.score_threshold,
        search_mode: ragForm.search_mode,
        top_k: ragForm.top_k,
      },
    })
    chatStore.sessionConfig = ragUpdated
    ElMessage.success('配置已保存')
    visible.value = false
    emit('saved')
  } catch {
    ElMessage.error('保存配置失败')
  } finally {
    saving.value = false
  }
}
</script>
