<template>
  <div class="space-settings-view">
    <div v-if="loading" style="text-align: center; padding: 60px">
      <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      <p style="margin-top: 12px; color: var(--color-text-muted)">加载中...</p>
    </div>

    <template v-else>
      <el-tabs v-model="activeTab" class="settings-tabs">
        <!-- Tab 1: 空间配置 -->
        <el-tab-pane label="空间配置" name="config">
          <!-- 统计信息 -->
          <div class="stats-grid">
            <div class="stat-card">
              <span class="stat-value">{{ stats?.kb_count ?? 0 }}</span>
              <span class="stat-label">知识库</span>
            </div>
            <div class="stat-card">
              <span class="stat-value">{{ stats?.document_count ?? 0 }}</span>
              <span class="stat-label">文档</span>
            </div>
            <div class="stat-card">
              <span class="stat-value">{{ stats?.chunk_count ?? 0 }}</span>
              <span class="stat-label">分块</span>
            </div>
            <div class="stat-card">
              <span class="stat-value">{{ Number(stats?.total_size_mb ?? 0).toFixed(1) }}</span>
              <span class="stat-label">存储 (MB)</span>
            </div>
            <div class="stat-card">
              <span class="stat-value">{{ stats?.member_count ?? 0 }}</span>
              <span class="stat-label">成员</span>
            </div>
          </div>

          <!-- 基本信息 -->
          <div class="settings-section">
            <h3 class="section-title">基本信息</h3>
            <el-form label-width="100px" style="max-width: 600px">
              <el-form-item label="空间名称">
                <el-input v-model="infoForm.name" maxlength="100" show-word-limit />
              </el-form-item>
              <el-form-item label="可见性">
                <el-radio-group v-model="infoForm.visibility">
                  <el-radio :value="0">私有</el-radio>
                  <el-radio :value="1">团队</el-radio>
                  <el-radio :value="2">公开</el-radio>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="描述">
                <el-input
                  v-model="infoForm.description"
                  type="textarea"
                  :rows="3"
                  maxlength="2000"
                  show-word-limit
                  placeholder="空间描述"
                />
              </el-form-item>
              <el-form-item label="标签">
                <div class="tags-editor">
                  <el-tag
                    v-for="tag in infoForm.tags"
                    :key="tag"
                    closable
                    @close="removeTag(tag)"
                    style="margin-right: 6px"
                  >
                    {{ tag }}
                  </el-tag>
                  <el-input
                    v-if="tagInputVisible"
                    ref="tagInputRef"
                    v-model="tagInputValue"
                    size="small"
                    style="width: 120px"
                    @keyup.enter="addTag"
                    @blur="addTag"
                  />
                  <el-button v-else size="small" @click="showTagInput">
                    + 添加标签
                  </el-button>
                </div>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="infoSaving" @click="handleSaveInfo">
                  保存基本信息
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <!-- Tab 2: 模型配置 -->
        <el-tab-pane label="模型配置" name="models">
          <div class="settings-section">
            <h3 class="section-title">模型配置</h3>
            <p class="section-desc">
              配置空间级别的 AI 模型。所有知识库默认使用此配置，知识库可在其自身配置中选择覆盖。
            </p>

            <!-- 模态展示 -->
            <div class="model-section-label" style="display:none">
              <span class="label-text">空间模态（已下放到知识库）</span>
            </div>
            <div class="modality-badges">
              <el-tag
                v-for="mt in spaceTypes"
                :key="mt"
                :type="mt === 'image' || mt === 'video' ? 'primary' : mt === 'audio' ? 'danger' : 'info'"
              >{{ mt === 'text' ? '📄 文本' : mt === 'image' ? '🖼 图片' : mt === 'video' ? '🎬 视频' : mt === 'audio' ? '🎵 音频' : mt }}</el-tag>
            </div>

            <!-- ─── Embedding 模型 ─── -->
            <div class="model-card">
              <div class="model-card-header">
                <span class="model-card-icon">📝</span>
                <div>
                  <h4 class="model-card-title">Embedding 模型</h4>
                  <p class="model-card-desc">将文本块转换为向量，用于语义检索和相似度匹配。所有空间必需。</p>
                </div>
              </div>
              <el-form label-width="130px" class="model-card-form">
                <el-form-item label="文本 Embedding">
                  <el-select
                    v-model="embeddingForm.model"
                    placeholder="选择文本嵌入模型"
                    clearable
                    filterable
                    style="width: 100%"
                  >
                    <el-option
                      v-for="m in embeddingModels"
                      :key="m.model"
                      :label="m.model"
                      :value="m.model"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item v-if="embeddingForm.dimension" label="向量维度">
                  <span class="dimension-display">{{ embeddingForm.dimension }}（自动检测）</span>
                </el-form-item>
                <el-form-item v-if="hasImageModality" label="多模态 Embedding">
                  <el-select
                    v-model="embeddingForm.mm_model"
                    placeholder="选择多模态嵌入模型（用于以图搜图）"
                    clearable
                    filterable
                    style="width: 100%"
                  >
                    <el-option
                      v-for="m in mmModels"
                      :key="m.model"
                      :label="m.model"
                      :value="m.model"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item v-if="hasImageModality && embeddingForm.mm_dimension" label="多模态向量维度">
                  <span class="dimension-display">{{ embeddingForm.mm_dimension }}（自动检测）</span>
                </el-form-item>
                <el-form-item label="批处理大小">
                  <el-input-number v-model="embeddingForm.batch_size" :min="1" :max="128" style="width: 200px" />
                </el-form-item>
                <el-form-item label="向量归一化">
                  <el-switch v-model="embeddingForm.normalize" />
                </el-form-item>
              </el-form>
            </div>

            <!-- ─── LLM 模型 ─── -->
            <div class="model-card">
              <div class="model-card-header">
                <span class="model-card-icon">🤖</span>
                <div>
                  <h4 class="model-card-title">LLM 模型</h4>
                  <p class="model-card-desc">用于问题生成（HyDE）、查询改写、摘要生成等通用语言任务。</p>
                </div>
              </div>
              <el-form label-width="130px" class="model-card-form">
                <el-form-item label="LLM 模型">
                  <el-select
                    v-model="modelForm.llm_model"
                    placeholder="选择 LLM 模型"
                    clearable
                    filterable
                    style="width: 100%"
                  >
                    <el-option
                      v-for="m in llmModels"
                      :key="m.model"
                      :label="m.model"
                      :value="m.model"
                    />
                  </el-select>
                </el-form-item>
              </el-form>
            </div>

            <!-- ─── ASR 模型 ─── -->
            <div v-if="hasAudio" class="model-card">
              <div class="model-card-header">
                <span class="model-card-icon">🎤</span>
                <div>
                  <h4 class="model-card-title">ASR 模型</h4>
                  <p class="model-card-desc">用于音频文件转文字（语音识别），仅含「音频」模态的空间需要。</p>
                </div>
              </div>
              <el-form label-width="130px" class="model-card-form">
                <el-form-item label="ASR 模型">
                  <el-select
                    v-model="modelForm.asr_model"
                    placeholder="选择 ASR 模型（如 whisper-1）"
                    clearable
                    filterable
                    style="width: 100%"
                  >
                    <el-option
                      v-for="m in asrModels"
                      :key="m.model"
                      :label="m.model"
                      :value="m.model"
                    />
                  </el-select>
                </el-form-item>
              </el-form>
            </div>

            <!-- ─── VLM 模型 ─── -->
            <div v-if="hasImageModality || hasVideo" class="model-card">
              <div class="model-card-header">
                <span class="model-card-icon">👁</span>
                <div>
                  <h4 class="model-card-title">VLM 模型</h4>
                  <p class="model-card-desc">用于图片/视频帧转文字描述，将视觉内容转为可检索的文本。</p>
                </div>
                <el-tag type="warning" size="small" effect="plain">开发中</el-tag>
              </div>
              <el-form label-width="130px" class="model-card-form">
                <el-form-item label="VLM 模型">
                  <el-select
                    v-model="modelForm.vlm_model"
                    placeholder="选择 VLM 模型"
                    clearable
                    filterable
                    disabled
                    style="width: 100%"
                  >
                    <el-option
                      v-for="m in vlmModels"
                      :key="m.model"
                      :label="m.model"
                      :value="m.model"
                    />
                  </el-select>
                </el-form-item>
              </el-form>
            </div>

            <div style="margin-top: var(--space-4)">
              <el-button type="primary" :loading="modelsSaving" @click="handleSaveModels">
                保存模型配置
              </el-button>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 3: 成员管理 -->
        <el-tab-pane label="成员管理" name="members">
          <div class="action-bar">
            <el-button type="primary" @click="showInviteDialog">
              <el-icon><Plus /></el-icon>
              邀请成员
            </el-button>
          </div>

          <el-table :data="members" v-loading="memberLoading" stripe>
            <el-table-column prop="username" label="用户名" min-width="120" />
            <el-table-column prop="email" label="邮箱" min-width="180" />
            <el-table-column prop="role" label="角色" width="120" align="center">
              <template #default="{ row }">
                <el-tag :type="getRoleType(row.role)" size="small">
                  {{ getRoleText(row.role) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="joined_at" label="加入时间" width="160">
              <template #default="{ row }">
                {{ formatMemberDate(row.joined_at) }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="160" fixed="right">
              <template #default="{ row }">
                <template v-if="row.user_id !== currentUserId">
                  <el-button type="primary" link size="small" @click="showRoleDialog(row)">
                    修改角色
                  </el-button>
                  <el-button type="danger" link size="small" @click="handleRemove(row)">
                    移除
                  </el-button>
                </template>
                <span v-else class="self-label">（我）</span>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="memberTotal > memberPageSize" class="member-pagination">
            <el-pagination
              v-model:current-page="memberCurrentPage"
              :page-size="memberPageSize"
              :total="memberTotal"
              layout="total, prev, pager, next"
              @current-change="fetchMembers"
            />
          </div>

          <!-- 邀请成员弹窗 -->
          <el-dialog v-model="inviteDialogVisible" title="邀请成员" width="480px">
            <el-form ref="inviteFormRef" :model="inviteForm" :rules="inviteRules" label-width="80px">
              <el-form-item label="邮箱" prop="email">
                <el-input v-model="inviteForm.email" placeholder="请输入被邀请人邮箱" />
              </el-form-item>
              <el-form-item label="角色" prop="role">
                <el-radio-group v-model="inviteForm.role">
                  <el-radio :value="0">查看者</el-radio>
                  <el-radio :value="1">编辑者</el-radio>
                  <el-radio :value="2">管理员</el-radio>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="有效期" prop="expires_hours">
                <el-select v-model="inviteForm.expires_hours" style="width: 100%">
                  <el-option label="24 小时" :value="24" />
                  <el-option label="72 小时" :value="72" />
                  <el-option label="7 天" :value="168" />
                </el-select>
              </el-form-item>
            </el-form>
            <template #footer>
              <el-button @click="inviteDialogVisible = false">取消</el-button>
              <el-button type="primary" :loading="inviteLoading" @click="handleInvite">
                发送邀请
              </el-button>
            </template>
          </el-dialog>

          <!-- 邀请成功弹窗 -->
          <el-dialog v-model="inviteResultVisible" title="邀请成功" width="480px">
            <el-alert type="success" :closable="false" show-icon>
              <template #title>
                邀请链接已生成
              </template>
            </el-alert>
            <div class="invite-link-wrapper">
              <el-input v-model="inviteLink" readonly>
                <template #append>
                  <el-button @click="copyInviteLink">复制</el-button>
                </template>
              </el-input>
            </div>
            <p class="invite-expire">链接有效期至：{{ formatMemberDate(inviteExpires) }}</p>
            <template #footer>
              <el-button type="primary" @click="inviteResultVisible = false">完成</el-button>
            </template>
          </el-dialog>

          <!-- 修改角色弹窗 -->
          <el-dialog v-model="roleDialogVisible" title="修改成员角色" width="400px">
            <el-form label-width="80px">
              <el-form-item label="用户">
                <span>{{ editMember?.username }}</span>
              </el-form-item>
              <el-form-item label="角色">
                <el-radio-group v-model="editRole">
                  <el-radio :value="0">查看者</el-radio>
                  <el-radio :value="1">编辑者</el-radio>
                  <el-radio :value="2">管理员</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-form>
            <template #footer>
              <el-button @click="roleDialogVisible = false">取消</el-button>
              <el-button type="primary" :loading="roleLoading" @click="handleUpdateRole">
                保存
              </el-button>
            </template>
          </el-dialog>
        </el-tab-pane>
      </el-tabs>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, Plus } from '@element-plus/icons-vue'
import { spaceApi } from '@/api/space'
import { userApi } from '@/api/user'
import { memberApi } from '@/api/member'
import { useUserStore } from '@/stores/user'
import { normalizeSpaceTypes } from '@/utils/document'
import type {
  SpaceConfigResponse,
  SpaceConfigStats,
  AvailableModelItem,
  Member,
} from '@/api/types'
import type { FormInstance, FormRules } from 'element-plus'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const spaceId = computed(() => Number(route.params.id))

const loading = ref(true)
const activeTab = ref('config')
const configData = ref<SpaceConfigResponse | null>(null)
const stats = ref<SpaceConfigStats | null>(null)

// === 基本信息 ===

const infoForm = reactive({
  name: '',
  visibility: 0,
  description: '',
  tags: [] as string[],
})
const infoSaving = ref(false)

// === 模型配置 ===

const spaceTypes = ref<string[]>(['text'])
const hasImageModality = computed(() => spaceTypes.value.includes('image'))
const hasVideo = computed(() => spaceTypes.value.includes('video'))
const hasAudio = computed(() => spaceTypes.value.includes('audio'))

// Embedding 表单
const embeddingForm = reactive({
  model: '',
  mm_model: '',
  dimension: 1024,
  mm_dimension: null as number | null,
  batch_size: 32,
  normalize: true,
})

// LLM / ASR / VLM 表单
const modelForm = reactive({
  llm_model: '',
  asr_model: '',
  vlm_model: '',
})

const modelsSaving = ref(false)
const embeddingModels = ref<AvailableModelItem[]>([])
const mmModels = ref<AvailableModelItem[]>([])
const llmModels = ref<AvailableModelItem[]>([])
const vlmModels = ref<AvailableModelItem[]>([])
const asrModels = ref<AvailableModelItem[]>([])

// === 标签 ===

const tagInputVisible = ref(false)
const tagInputValue = ref('')
const tagInputRef = ref<InstanceType<typeof import('element-plus')['ElInput']>>()

function showTagInput() {
  tagInputVisible.value = true
  tagInputValue.value = ''
  nextTick(() => tagInputRef.value?.focus())
}

function addTag() {
  const val = tagInputValue.value.trim()
  if (val && !infoForm.tags.includes(val)) {
    infoForm.tags.push(val)
  }
  tagInputVisible.value = false
  tagInputValue.value = ''
}

function removeTag(tag: string) {
  infoForm.tags = infoForm.tags.filter((t) => t !== tag)
}

// === 成员管理 ===

const currentUserId = computed(() => userStore.user?.id)
const memberLoading = ref(false)
const inviteLoading = ref(false)
const roleLoading = ref(false)
const inviteDialogVisible = ref(false)
const inviteResultVisible = ref(false)
const roleDialogVisible = ref(false)
const members = ref<Member[]>([])
const memberTotal = ref(0)
const memberCurrentPage = ref(1)
const memberPageSize = 20
const inviteFormRef = ref<FormInstance>()
const inviteForm = reactive({
  email: '',
  role: 0,
  expires_hours: 72,
})

const inviteRules: FormRules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' },
  ],
}

const inviteLink = ref('')
const inviteExpires = ref('')
const editMember = ref<Member | null>(null)
const editRole = ref(0)

const roleMap: Record<number, { text: string; type: string }> = {
  0: { text: '查看者', type: 'info' },
  1: { text: '编辑者', type: 'warning' },
  2: { text: '管理员', type: 'danger' },
}

function getRoleText(role: number): string {
  return roleMap[role]?.text || '未知'
}

function getRoleType(role: number): string {
  return roleMap[role]?.type || 'info'
}

function formatMemberDate(date: string): string {
  try {
    return new Date(date).toLocaleString('zh-CN')
  } catch {
    return '-'
  }
}

async function fetchMembers() {
  memberLoading.value = true
  try {
    const data = await memberApi.getMembers(spaceId.value, {
      skip: (memberCurrentPage.value - 1) * memberPageSize,
      limit: memberPageSize,
    })
    members.value = data.items || []
    memberTotal.value = data.total || 0
  } catch {
    // ignore
  } finally {
    memberLoading.value = false
  }
}

function showInviteDialog() {
  inviteForm.email = ''
  inviteForm.role = 0
  inviteForm.expires_hours = 72
  inviteDialogVisible.value = true
}

async function handleInvite() {
  if (!inviteFormRef.value) return

  await inviteFormRef.value.validate(async (valid) => {
    if (!valid) return

    inviteLoading.value = true
    try {
      const data = await memberApi.inviteMember(spaceId.value, {
        email: inviteForm.email,
        role: inviteForm.role,
        expires_hours: inviteForm.expires_hours,
      })

      const baseUrl = window.location.origin
      inviteLink.value = `${baseUrl}/spaces/${spaceId.value}/join?token=${data.invite_token}`
      inviteExpires.value = data.invite_expires_at

      inviteDialogVisible.value = false
      inviteResultVisible.value = true
      fetchMembers()
    } catch {
      // ignore
    } finally {
      inviteLoading.value = false
    }
  })
}

function copyInviteLink() {
  navigator.clipboard.writeText(inviteLink.value)
  ElMessage.success('链接已复制到剪贴板')
}

function showRoleDialog(member: Member) {
  editMember.value = member
  editRole.value = member.role
  roleDialogVisible.value = true
}

async function handleUpdateRole() {
  if (!editMember.value) return

  roleLoading.value = true
  try {
    await memberApi.updateMemberRole(spaceId.value, editMember.value.user_id, {
      role: editRole.value,
    })
    ElMessage.success('角色更新成功')
    roleDialogVisible.value = false
    fetchMembers()
  } catch {
    // ignore
  } finally {
    roleLoading.value = false
  }
}

async function handleRemove(member: Member) {
  try {
    await ElMessageBox.confirm(
      `确定要将 "${member.username}" 移除出空间吗？`,
      '提示',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    await memberApi.removeMember(spaceId.value, member.user_id)
    ElMessage.success('成员已移除')
    fetchMembers()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      // ignore
    }
  }
}

watch(activeTab, (tab) => {
  if (tab === 'members') {
    fetchMembers()
  }
})

// === 数据加载 ===

async function fetchConfig() {
  loading.value = true
  try {
    const [config, modelData] = await Promise.all([
      spaceApi.getConfig(spaceId.value),
      userApi.getAvailableModelDetails(),
    ])
    configData.value = config
    stats.value = config.stats
    embeddingModels.value = modelData.embedding || []
    mmModels.value = modelData.multimodal_embedding || []
    llmModels.value = modelData.llm || []
    vlmModels.value = modelData.vlm || []
    asrModels.value = modelData.asr || []

    // 填充基本信息
    infoForm.name = config.name
    infoForm.description = config.config?.description || ''
    infoForm.tags = [...(config.config?.tags || [])]

    // 填充 Embedding
    const emb = config.config?.embedding
    const mmEmb = config.config?.multimodal_embedding
    spaceTypes.value = normalizeSpaceTypes(config.config)
    embeddingForm.model = emb?.model || ''
    embeddingForm.dimension = emb?.dimension ?? 1024
    embeddingForm.batch_size = emb?.batch_size ?? 32
    embeddingForm.normalize = emb?.normalize ?? true
    embeddingForm.mm_model = mmEmb?.model || ''
    embeddingForm.mm_dimension = (mmEmb as { dimension?: number } | null)?.dimension ?? null

    // 填充 LLM / ASR / VLM
    const llmCfg = config.config?.llm as Record<string, unknown> | undefined
    const asrCfg = config.config?.asr as Record<string, unknown> | undefined
    const vlmCfg = config.config?.vlm as Record<string, unknown> | undefined
    modelForm.llm_model = (llmCfg?.model as string) || ''
    modelForm.asr_model = (asrCfg?.model as string) || ''
    modelForm.vlm_model = (vlmCfg?.model as string) || ''

    // 从 space 对象取 visibility
    const space = await spaceApi.getSpace(spaceId.value)
    infoForm.visibility = space.visibility
  } catch {
    // handled by interceptor
  } finally {
    loading.value = false
  }
}

// === 保存基本信息 ===

async function handleSaveInfo() {
  if (!infoForm.name.trim()) {
    ElMessage.warning('空间名称不能为空')
    return
  }
  infoSaving.value = true
  try {
    await spaceApi.updateSpace(spaceId.value, {
      name: infoForm.name,
      visibility: infoForm.visibility,
      config: {
        description: infoForm.description || undefined,
        tags: infoForm.tags.length > 0 ? infoForm.tags : undefined,
      },
    })
    ElMessage.success('基本信息已保存')
  } catch {
    // handled by interceptor
  } finally {
    infoSaving.value = false
  }
}

// === 保存模型配置 ===

async function handleSaveModels() {
  modelsSaving.value = true
  try {
    const payload: Record<string, any> = {
      embedding: {
        model: embeddingForm.model || undefined,
        batch_size: embeddingForm.batch_size,
        normalize: embeddingForm.normalize,
      },
      llm: {
        model: modelForm.llm_model || undefined,
      },
      asr: {
        model: modelForm.asr_model || undefined,
      },
      vlm: {
        model: modelForm.vlm_model || undefined,
      },
    }
    // 含 image 模态需额外发送 multimodal_embedding 配置
    if (hasImageModality.value) {
      payload.multimodal_embedding = {
        model: embeddingForm.mm_model || undefined,
      }
    }
    await spaceApi.updateConfig(spaceId.value, payload)
    ElMessage.success('模型配置已保存')
  } catch {
    // handled by interceptor
  } finally {
    modelsSaving.value = false
  }
}

onMounted(() => {
  fetchConfig()
})
</script>

<style scoped>
.space-settings-view {
  padding-top: var(--space-2);
}

.settings-tabs {
  margin-bottom: var(--space-5);
}

/* 统计卡片 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--space-3);
  margin-bottom: var(--space-6);
}

.stat-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  transition: all var(--transition-fast);
}

.stat-card:hover {
  border-color: var(--color-border);
  box-shadow: var(--shadow-xs);
}

.stat-value {
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  font-family: var(--font-display);
}

.stat-label {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

/* 设置区块 */
.settings-section {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  padding: var(--space-5);
  margin-bottom: var(--space-5);
}

.section-title {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  margin: 0 0 var(--space-2);
  font-family: var(--font-display);
}

.section-desc {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin: 0 0 var(--space-4);
}

/* 模态标签 */
.model-section-label {
  margin-bottom: var(--space-2);
}

.label-text {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.modality-badges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-5);
}

/* 模型卡片 */
.model-card {
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  margin-bottom: var(--space-4);
}

.model-card:last-of-type {
  margin-bottom: 0;
}

.model-card-header {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border-light);
}

.model-card-icon {
  font-size: 24px;
  line-height: 1;
  flex-shrink: 0;
}

.model-card-title {
  margin: 0 0 var(--space-1);
  font-size: var(--text-base);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.model-card-desc {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  line-height: 1.5;
}

.model-card-form {
  padding-left: var(--space-1);
}

/* 通用 */
.tags-editor {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
}

.dimension-display {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

/* 成员管理 */
.action-bar {
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
}

.member-pagination {
  display: flex;
  justify-content: center;
  margin-top: var(--space-4);
}

.self-label {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.invite-link-wrapper {
  margin: var(--space-4) 0;
}

.invite-expire {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}
</style>
