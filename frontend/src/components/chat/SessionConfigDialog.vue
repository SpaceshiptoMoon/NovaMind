<template>
  <el-dialog v-model="visible" width="560px" append-to-body destroy-on-close @close="handleClose">
    <template #header>
      <span class="dialog-title">会话设置</span>
    </template>

    <!-- === 压缩卡片 === -->
    <div class="config-card">
      <div class="card-row-between">
        <div class="card-label">自动压缩长对话</div>
        <el-switch v-model="configForm.enable_compression" size="small" />
      </div>

      <template v-if="configForm.enable_compression">
        <div class="card-row">
          <span class="row-label">策略</span>
          <el-select v-model="configForm.strategy" size="small" style="width:180px">
            <el-option label="摘要压缩" value="summary" />
            <el-option label="滑动窗口" value="sliding_window" />
            <el-option label="保留最近" value="keep_recent" />
            <el-option label="截断" value="truncate" />
          </el-select>
        </div>
        <div class="card-row">
          <span class="row-label">触发阈值</span>
          <el-input-number v-model="configForm.threshold" :min="500" :max="200000" :step="1000" size="small" style="width:160px" />
          <span class="row-hint">token</span>
        </div>
        <div class="card-row">
          <span class="row-label">保留消息</span>
          <el-input-number v-model="configForm.keep_recent" :min="0" :max="10" size="small" style="width:100px" />
          <span class="row-hint">条</span>
        </div>
        <div v-if="configForm.strategy === 'summary'" class="card-row">
          <span class="row-label">目标长度</span>
          <el-input-number v-model="configForm.target_tokens" :min="100" :max="2000" :step="100" size="small" style="width:140px" />
          <span class="row-hint">token</span>
        </div>
        <div v-if="configForm.strategy === 'summary'" class="card-row-block">
          <div class="row-label">自定义提示词</div>
          <el-input v-model="configForm.custom_prompt" type="textarea" :rows="2" placeholder="留空使用默认" maxlength="2000" size="small" />
        </div>
      </template>
    </div>

    <!-- === RAG 卡片 === -->
    <div class="config-card">
      <div class="card-row-between">
        <div class="card-label">会话级自动 RAG</div>
        <el-switch v-model="ragForm.auto_rag" size="small" />
      </div>

      <template v-if="ragForm.auto_rag">
        <div class="card-row">
          <span class="row-label">空间</span>
          <el-select v-model="ragForm.space_id" placeholder="选择空间" filterable clearable size="small" style="width:180px" @change="handleRagFormSpaceChange">
            <el-option v-for="s in spaceStore.spaces" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </div>
        <div class="card-row">
          <span class="row-label">知识库</span>
          <el-select v-model="ragForm.kb_ids" multiple filterable placeholder="可多选" size="small" style="width:180px" :disabled="!ragForm.space_id">
            <el-option v-for="kb in ragFormKbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </div>
        <div class="card-row-between">
          <div>
            <span class="row-label">分级拒答</span>
            <div class="row-hint" style="margin-top:2px">过滤低相关结果，检索为空时直接拒答</div>
          </div>
          <el-switch v-model="ragForm.refusal_enabled" size="small" />
        </div>
        <div v-if="ragForm.refusal_enabled" class="card-row">
          <span class="row-label">低置信阈值</span>
          <el-input-number v-model="ragForm.score_threshold" :min="0" :max="1" :step="0.05" :precision="2" size="small" style="width:100px" />
        </div>
        <div class="card-row">
          <span class="row-label">检索模式</span>
          <el-select v-model="ragForm.search_mode" size="small" style="width:180px">
            <el-option label="内容混合（推荐）" value="content_hybrid" />
            <el-option label="向量语义" value="vector" />
            <el-option label="关键词 BM25" value="bm25" />
            <el-option label="问题混合" value="question_hybrid" />
          </el-select>
        </div>
        <div class="card-row">
          <span class="row-label">检索条数</span>
          <el-input-number v-model="ragForm.top_k" :min="1" :max="20" size="small" style="width:100px" />
        </div>
      </template>
    </div>

    <!-- === 模型卡片 === -->
    <div class="config-card">
      <div class="card-row-between" @click="modelExpanded = !modelExpanded" style="cursor:pointer">
        <div class="card-label">模型生成参数</div>
        <el-icon :size="12" class="card-arrow" :class="{ expanded: modelExpanded }"><ArrowDown /></el-icon>
      </div>

      <template v-if="modelExpanded">
        <div class="card-row">
          <span class="row-label">温度</span>
          <el-input-number v-model="llmForm.temperature" :min="0" :max="2" :step="0.1" size="small" style="width:120px" />
          <span class="row-hint">越高越随机</span>
        </div>
        <div class="card-row">
          <span class="row-label">Top-P</span>
          <el-input-number v-model="llmForm.top_p" :min="0" :max="1" :step="0.1" size="small" style="width:120px" />
        </div>
        <div class="card-row">
          <span class="row-label">最大 Tokens</span>
          <el-input-number v-model="llmForm.max_tokens" :min="1" :max="8192" :step="256" size="small" style="width:140px" />
        </div>
        <div class="card-row-block">
          <div class="row-label">系统提示词</div>
          <el-input v-model="llmForm.system_prompt" type="textarea" :rows="2" placeholder="留空使用后端模板" maxlength="4000" size="small" />
        </div>
      </template>
    </div>

    <template #footer>
      <el-button size="small" @click="visible = false">取消</el-button>
      <el-button size="small" type="primary" :loading="saving" @click="handleSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
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
const modelExpanded = ref(false)
const configForm = reactive({
  enable_compression: true,
  strategy: 'summary' as 'summary' | 'sliding_window' | 'keep_recent' | 'truncate',
  threshold: 70000,
  keep_recent: 6,
  target_tokens: 2000,
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
      configForm.threshold = cfg.threshold || 70000
      configForm.keep_recent = cfg.keep_recent ?? 6
      configForm.target_tokens = cfg.target_tokens || 2000
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

<style scoped>
.dialog-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text);
}

.config-card {
  padding: 14px 16px;
  margin-bottom: 10px;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-bg-card);
}

.card-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.card-row-between {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}

.card-row-block {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.row-label {
  font-size: 12px;
  color: var(--color-text-muted);
  min-width: 56px;
  flex-shrink: 0;
}

.row-hint {
  font-size: 11px;
  color: var(--color-text-faint);
}

.card-arrow {
  transition: transform 0.2s;
  color: var(--color-text-muted);
}
.card-arrow.expanded {
  transform: rotate(180deg);
}
</style>
