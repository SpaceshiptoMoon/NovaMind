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
                  <el-button v-else size="small" @click="showTagInput"> + 添加标签 </el-button>
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
            <p class="section-desc">
              配置空间级别的 AI 模型。所有知识库默认使用此配置，知识库可在其自身配置中选择覆盖。
            </p>

            <!-- 空间模态：中性 chip（语义靠文字，不上彩色） -->
            <div class="modality-badges">
              <span v-for="mt in spaceTypes" :key="mt" class="modality-chip">
                <el-icon :size="12"><component :is="modalityIcon(mt)" /></el-icon>
                {{ modalityLabel(mt) }}
              </span>
            </div>

            <!-- ─── Embedding 模型 ─── -->
            <div class="model-card">
              <div class="model-card-header">
                <span class="model-card-icon">
                  <el-icon :size="18"><Coordinate /></el-icon>
                </span>
                <div class="model-card-title-wrap">
                  <h4 class="model-card-title">Embedding 模型</h4>
                  <p class="model-card-desc">
                    将文本块转换为向量，用于语义检索和相似度匹配。所有空间必需。
                  </p>
                </div>
                <el-tooltip
                  :content="
                    embeddingForm.model
                      ? '空间已固化 Embedding 配置'
                      : effectiveEmbeddingModel
                        ? '空间未单独配置，当前使用「模型管理」中的默认 Embedding 模型（文档处理/检索均 fallback 到此）'
                        : '尚未配置任何 Embedding 模型'
                  "
                  placement="top"
                >
                  <span
                    class="model-status-chip"
                    :class="{
                      'is-set': !!embeddingForm.model,
                      'is-fallback': !embeddingForm.model && !!effectiveEmbeddingModel,
                    }"
                  >
                    {{
                      embeddingForm.model
                        ? `已配置 · ${embeddingForm.model}`
                        : effectiveEmbeddingModel
                          ? `默认 · ${effectiveEmbeddingModel}`
                          : '未配置'
                    }}
                  </span>
                </el-tooltip>
              </div>
              <el-form label-width="130px" class="model-card-form">
                <div v-if="embeddingLocked" class="locked-note">
                  <el-icon :size="14"><Lock /></el-icon>
                  <span>
                    已有 {{ documentCount }} 个文档，Embedding
                    模型已锁定：不同模型的向量不兼容，更改会导致检索失效。如需更换，请新建空间。
                  </span>
                </div>
                <el-form-item label="文本 Embedding">
                  <el-select
                    v-if="embeddingModels.length"
                    v-model="embeddingForm.model"
                    placeholder="选择文本嵌入模型"
                    clearable
                    filterable
                    :disabled="embeddingLocked"
                    style="width: 100%"
                  >
                    <el-option
                      v-for="m in embeddingModels"
                      :key="m.model"
                      :label="m.model"
                      :value="m.model"
                    />
                  </el-select>
                  <div v-else class="model-empty-state">
                    <span>尚未在「模型管理」中配置 Embedding 模型</span>
                    <el-button type="primary" link size="small" @click="goToModelConfig">
                      前往模型管理
                    </el-button>
                  </div>
                </el-form-item>
                <el-form-item v-if="embeddingForm.dimension" label="向量维度">
                  <span class="dimension-display">{{ embeddingForm.dimension }}（自动检测）</span>
                </el-form-item>
                <el-form-item label="批处理大小">
                  <el-input-number
                    v-model="embeddingForm.batch_size"
                    :min="1"
                    :max="128"
                    style="width: 200px"
                  />
                </el-form-item>
                <el-form-item label="向量归一化">
                  <el-switch v-model="embeddingForm.normalize" />
                </el-form-item>
              </el-form>
            </div>

            <!-- ─── LLM 模型 ─── -->
            <div class="model-card">
              <div class="model-card-header">
                <span class="model-card-icon">
                  <el-icon :size="18"><MagicStick /></el-icon>
                </span>
                <div class="model-card-title-wrap">
                  <h4 class="model-card-title">LLM 模型</h4>
                  <p class="model-card-desc">
                    用于问题生成（HyDE）、查询改写、摘要生成等通用语言任务。
                  </p>
                </div>
                <span class="model-status-chip" :class="{ 'is-set': !!modelForm.llm_model }">
                  {{ modelForm.llm_model ? `已配置 · ${modelForm.llm_model}` : '未配置' }}
                </span>
              </div>
              <el-form label-width="130px" class="model-card-form">
                <el-form-item label="LLM 模型">
                  <el-select
                    v-if="llmModels.length"
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
                  <div v-else class="model-empty-state">
                    <span>尚未在「模型管理」中配置 LLM 模型</span>
                    <el-button type="primary" link size="small" @click="goToModelConfig">
                      前往模型管理
                    </el-button>
                  </div>
                </el-form-item>
              </el-form>
            </div>

            <!-- ─── ASR 模型 ─── -->
            <div v-if="hasAudio" class="model-card">
              <div class="model-card-header">
                <span class="model-card-icon">
                  <el-icon :size="18"><Microphone /></el-icon>
                </span>
                <div class="model-card-title-wrap">
                  <h4 class="model-card-title">ASR 模型</h4>
                  <p class="model-card-desc">
                    用于音频文件转文字（语音识别），仅含「音频」模态的空间需要。
                  </p>
                </div>
                <span class="model-status-chip" :class="{ 'is-set': !!modelForm.asr_model }">
                  {{ modelForm.asr_model ? `已配置 · ${modelForm.asr_model}` : '未配置' }}
                </span>
              </div>
              <el-form label-width="130px" class="model-card-form">
                <el-form-item label="ASR 模型">
                  <el-select
                    v-if="asrModels.length"
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
                  <div v-else class="model-empty-state">
                    <span>尚未在「模型管理」中配置 ASR 模型</span>
                    <el-button type="primary" link size="small" @click="goToModelConfig">
                      前往模型管理
                    </el-button>
                  </div>
                </el-form-item>
              </el-form>
            </div>

            <!-- ─── VLM 模型 ─── -->
            <div v-if="hasImageModality || hasVideo" class="model-card">
              <div class="model-card-header">
                <span class="model-card-icon">
                  <el-icon :size="18"><View /></el-icon>
                </span>
                <div>
                  <h4 class="model-card-title">VLM 模型</h4>
                  <p class="model-card-desc">
                    用于图片/视频帧转文字描述，将视觉内容转为可检索的文本。
                  </p>
                </div>
                <span class="model-status-chip is-dev">开发中</span>
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
            <el-button @click="showDirectAddDialog">
              <el-icon><UserFilled /></el-icon>
              直接添加
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
            <el-table-column label="操作" width="230" fixed="right">
              <template #default="{ row }">
                <template v-if="row.user_id !== currentUserId">
                  <el-button type="primary" link size="small" @click="showRoleDialog(row)">
                    修改角色
                  </el-button>
                  <el-button type="primary" link size="small" @click="showPermDialog(row)">
                    细粒度权限
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
            <el-form
              ref="inviteFormRef"
              :model="inviteForm"
              :rules="inviteRules"
              label-width="80px"
            >
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
              <template #title> 邀请链接已生成 </template>
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

          <!-- 直接添加成员弹窗 -->
          <el-dialog v-model="directAddDialogVisible" title="直接添加成员" width="480px">
            <el-alert type="info" :closable="false" show-icon style="margin-bottom: 16px">
              <template #title>
                输入用户的<strong>用户名</strong>或<strong>邮箱</strong>，直接将其加为本空间成员（无需邀请链接，立即生效）。
              </template>
            </el-alert>
            <el-form
              ref="directAddFormRef"
              :model="directAddForm"
              :rules="directAddRules"
              label-width="80px"
            >
              <el-form-item label="用户" prop="identifier">
                <el-input v-model="directAddForm.identifier" placeholder="用户名或邮箱" />
              </el-form-item>
              <el-form-item label="角色" prop="role">
                <el-radio-group v-model="directAddForm.role">
                  <el-radio :value="0">查看者</el-radio>
                  <el-radio :value="1">编辑者</el-radio>
                  <el-radio :value="2">管理员</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-form>
            <template #footer>
              <el-button @click="directAddDialogVisible = false">取消</el-button>
              <el-button type="primary" :loading="directAddLoading" @click="handleDirectAdd">
                添加
              </el-button>
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

          <!-- 细粒度权限弹窗 -->
          <el-dialog v-model="permDialogVisible" title="细粒度权限" width="560px">
            <el-alert type="info" :closable="false" show-icon style="margin-bottom: 16px">
              <template #title>
                每项可设为<strong>继承</strong>（按角色，默认）、<strong>允许</strong>、<strong>拒绝</strong>。
                显式允许/拒绝会覆盖角色默认；未列出项保持继承。
              </template>
            </el-alert>
            <el-form label-width="120px">
              <el-form-item
                v-for="cap in CAPABILITIES"
                :key="`${cap.resource}.${cap.action}`"
                :label="cap.label"
              >
                <el-radio-group v-model="permState[`${cap.resource}.${cap.action}`]">
                  <el-radio value="inherit">继承</el-radio>
                  <el-radio value="allow">允许</el-radio>
                  <el-radio value="deny">拒绝</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-form>
            <template #footer>
              <el-button @click="permDialogVisible = false">取消</el-button>
              <el-button type="primary" :loading="permLoading" @click="handleSavePermissions">
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
/**
 * 空间设置页：空间配置 / 模型配置 / 成员管理三个 tab。
 *
 * 对应路由 /home/spaces/:id/settings（SpaceSettings），统一维护空间基本信息、
 * 各模态 AI 模型（Embedding 锁定保护）、成员角色与细粒度权限、邀请与直接添加。
 */

import { ref, reactive, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Loading,
  Plus,
  UserFilled,
  Coordinate,
  MagicStick,
  Microphone,
  View,
  Lock,
  Document,
  Picture,
  VideoCamera,
  Headset,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'
import { spaceApi } from '@/api/space'
import { userApi } from '@/api/user'
import { memberApi } from '@/api/member'
import { useUserStore } from '@/stores/user'
import { normalizeSpaceTypes } from '@/components/knowledge'
import { copyToClipboard } from '@/utils/clipboard'
import type {
  SpaceConfigResponse,
  SpaceConfigStats,
  AvailableModelItem,
  Member,
  SpaceConfigUpdateRequest,
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

// 模态 chip 的图标与文案映射（统一中性色，仅靠形状区分——不上 emoji 不上彩色）
const modalityIcons: Record<string, Component> = {
  text: Document,
  image: Picture,
  video: VideoCamera,
  audio: Headset,
}

const modalityLabels: Record<string, string> = {
  text: '文本',
  image: '图片',
  video: '视频',
  audio: '音频',
}

function modalityIcon(mt: string): Component {
  return modalityIcons[mt] ?? Document
}

function modalityLabel(mt: string): string {
  return modalityLabels[mt] ?? mt
}

// Embedding 表单
const embeddingForm = reactive({
  model: '',
  dimension: 1024,
  batch_size: 32,
  normalize: true,
})

// 实际生效的 Embedding 模型：空间已固化 → 用空间配置；否则 fallback 到用户默认（首个可用）。
// 后端文档处理/检索在空间未配时同样 fallback 到用户默认模型（document_pipeline._get_embedding_client_static）。
const effectiveEmbeddingModel = computed(
  () => embeddingForm.model || embeddingModels.value[0]?.model || '',
)

// Embedding 变更保护：空间已有文档时锁定 Embedding select，禁止修改
// （不同模型向量不兼容，后端 _check_embedding_change_allowed 同样拒绝）。无文档时可自由修改。
const documentCount = computed(() => stats.value?.document_count ?? 0)
const embeddingLocked = computed(() => documentCount.value > 0)

// LLM / ASR / VLM 表单
const modelForm = reactive({
  llm_model: '',
  asr_model: '',
  vlm_model: '',
})

const modelsSaving = ref(false)
const embeddingModels = ref<AvailableModelItem[]>([])
const llmModels = ref<AvailableModelItem[]>([])
const vlmModels = ref<AvailableModelItem[]>([])
const asrModels = ref<AvailableModelItem[]>([])

// === 标签 ===

const tagInputVisible = ref(false)
const tagInputValue = ref('')
const tagInputRef = ref<InstanceType<(typeof import('element-plus'))['ElInput']>>()

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

// 直接添加成员
const directAddDialogVisible = ref(false)
const directAddLoading = ref(false)
const directAddFormRef = ref<FormInstance>()
const directAddForm = reactive({
  identifier: '',
  role: 0,
})
const directAddRules: FormRules = {
  identifier: [
    { required: true, message: '请输入用户名或邮箱', trigger: 'blur' },
    { min: 1, max: 128, message: '长度不合法', trigger: 'blur' },
  ],
}

// 细粒度权限：6 个有效能力项（与后端 SpaceAccessChecker.CAPABILITY_KEYS 对齐）
const CAPABILITIES = [
  { resource: 'knowledge_bases', action: 'manage', label: '管理知识库' },
  { resource: 'documents', action: 'upload', label: '上传文档' },
  { resource: 'documents', action: 'delete', label: '删除文档' },
  { resource: 'documents', action: 'delete_any', label: '删除任意文档' },
  { resource: 'members', action: 'invite', label: '邀请成员' },
  { resource: 'members', action: 'manage', label: '管理成员' },
] as const

type PermTriState = 'inherit' | 'allow' | 'deny'
const permDialogVisible = ref(false)
const permLoading = ref(false)
const permMember = ref<Member | null>(null)
const permState = reactive<Record<string, PermTriState>>({})

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

function showDirectAddDialog() {
  directAddForm.identifier = ''
  directAddForm.role = 0
  directAddDialogVisible.value = true
}

async function handleDirectAdd() {
  if (!directAddFormRef.value) return
  await directAddFormRef.value.validate(async (valid) => {
    if (!valid) return
    directAddLoading.value = true
    try {
      await memberApi.addMemberDirect(spaceId.value, {
        identifier: directAddForm.identifier.trim(),
        role: directAddForm.role,
      })
      ElMessage.success('成员已添加')
      directAddDialogVisible.value = false
      fetchMembers()
    } catch {
      // 拦截器已统一弹错
    } finally {
      directAddLoading.value = false
    }
  })
}

/** 从 member.custom_permissions 反填三态（true→allow / false→deny / 缺失→inherit）。 */
function showPermDialog(member: Member) {
  permMember.value = member
  // 从 member.custom_permissions 反填三态：true→allow, false→deny, 缺失→inherit
  const perms = (member.custom_permissions || {}) as Record<string, Record<string, boolean>>
  for (const cap of CAPABILITIES) {
    const key = `${cap.resource}.${cap.action}`
    const val = perms[cap.resource]?.[cap.action]
    permState[key] = val === true ? 'allow' : val === false ? 'deny' : 'inherit'
  }
  permDialogVisible.value = true
}

/** 仅收集非继承项构建 resource→action→bool 提交；继承项缺省，由后端按角色回退。 */
async function handleSavePermissions() {
  if (!permMember.value) return
  // 仅收集非继承项，构建 resource→action→bool
  const custom_permissions: Record<string, Record<string, boolean>> = {}
  for (const cap of CAPABILITIES) {
    const key = `${cap.resource}.${cap.action}`
    const state = permState[key]
    if (state === 'allow' || state === 'deny') {
      if (!custom_permissions[cap.resource]) custom_permissions[cap.resource] = {}
      custom_permissions[cap.resource]![cap.action] = state === 'allow'
    }
  }
  permLoading.value = true
  try {
    await memberApi.updateMemberPermissions(spaceId.value, permMember.value.user_id, {
      custom_permissions,
    })
    ElMessage.success('细粒度权限已更新')
    permDialogVisible.value = false
    fetchMembers()
  } catch {
    // 拦截器已统一弹错
  } finally {
    permLoading.value = false
  }
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
      inviteLink.value = `${baseUrl}/home/spaces/${spaceId.value}/join?token=${data.invite_token}`
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
  copyToClipboard(inviteLink.value).then((ok) => {
    if (ok) ElMessage.success('链接已复制到剪贴板')
    else ElMessage.error('复制失败，请手动选择链接复制')
  })
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
    await ElMessageBox.confirm(`确定要将 "${member.username}" 移除出空间吗？`, '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
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

/** 并行拉取空间配置与用户可用模型，回填基本信息、Embedding/LLM/ASR/VLM 各表单。 */
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
    llmModels.value = modelData.llm || []
    vlmModels.value = modelData.vlm || []
    asrModels.value = modelData.asr || []

    // 填充基本信息
    infoForm.name = config.name
    infoForm.description = config.config?.description || ''
    infoForm.tags = [...(config.config?.tags || [])]

    // 填充 Embedding
    const emb = config.config?.embedding
    spaceTypes.value = normalizeSpaceTypes(config.config)
    embeddingForm.model = emb?.model || ''
    embeddingForm.dimension = emb?.dimension ?? 1024
    embeddingForm.batch_size = emb?.batch_size ?? 32
    embeddingForm.normalize = emb?.normalize ?? true

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
    const payload: SpaceConfigUpdateRequest = {
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

function goToModelConfig() {
  router.push('/home/settings/models')
}
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
  transition: border-color var(--transition-fast);
}

.stat-card:hover {
  border-color: var(--color-border);
}

.stat-value {
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  font-family: var(--font-display);
  font-variant-numeric: tabular-nums;
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
  /* secondary 非 muted：12px 说明文字对比度过 AA（评审 P2） */
  color: var(--color-text-secondary);
  margin: 0 0 var(--space-4);
}

/* 模态标签：中性 chip（语义靠文字与图标形状，不上彩色） */
.modality-badges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-5);
}

.modality-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: var(--radius-full);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  font-size: var(--text-xs);
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

/* 卡片图标：中性灰底方形容器（与 KB 列表头像同语言），替代 emoji */
.model-card-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
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
  /* secondary 非 muted：12px 小字在 elevated 卡底上 muted 仅 3.1:1（评审 P2），secondary 4.9:1 过 AA */
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.model-card-title-wrap {
  flex: 1;
  min-width: 0;
}

/* 配置状态 chip：中性（已配置=深字实底、fallback/未配置=虚线弱化、开发中=警示文字色），
   语义只靠文字传达，不用 EP 语义色底 */
.model-status-chip {
  flex-shrink: 0;
  align-self: center;
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  padding: 3px 10px;
  border-radius: var(--radius-full);
  border: 1px dashed var(--color-border);
  color: var(--color-text-muted);
}

.model-status-chip.is-set {
  border-style: solid;
  border-color: var(--color-border);
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.model-status-chip.is-dev {
  border-style: solid;
  border-color: transparent;
  background: var(--color-warning-subtle);
  color: var(--color-warning);
}

/* Embedding 锁定说明：浅灰说明行替代黄色大 alert 横幅（信息保留，色块撤掉） */
.locked-note {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  border: 1px solid var(--color-border-light);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.locked-note .el-icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--color-text-muted);
}

.model-empty-state {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
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

/* 窄屏（评审 P2-2/P3-4）：模型卡 header 换行——文本列给足最小宽度防"一字一行"竖排，
   状态 chip 换行独占一行不再压住描述文字 */
@media (max-width: 640px) {
  .model-card-header {
    flex-wrap: wrap;
  }

  .model-card-title-wrap,
  .model-card-header > div:last-of-type {
    flex: 1 1 180px;
    min-width: 180px;
  }

  .model-status-chip {
    max-width: 100%;
  }
}
</style>
