<template>
  <el-dialog
    :model-value="visible"
    title="新建知识空间"
    width="520px"
    class="create-space-dialog"
    destroy-on-close
    @update:model-value="(v: boolean) => emit('update:visible', v)"
  >
    <el-form
      ref="createSpaceFormRef"
      :model="createSpaceForm"
      :rules="spaceFormRules"
      label-width="70px"
      class="create-space-form"
    >
      <!-- 基础信息 -->
      <div class="form-section">
        <div class="section-label">基础信息</div>
        <el-form-item label="名称" prop="name">
          <el-input v-model="createSpaceForm.name" placeholder="请输入空间名称" maxlength="100" />
        </el-form-item>
        <el-form-item label="可见性" prop="visibility">
          <div class="visibility-options">
            <label
              v-for="opt in visibilityOptions"
              :key="opt.value"
              class="visibility-option"
              :class="{ 'is-active': createSpaceForm.visibility === opt.value }"
              @click="createSpaceForm.visibility = opt.value"
            >
              <span class="visibility-dot" :style="{ background: opt.color }" />
              <span class="visibility-option-body">
                <span class="visibility-option-name">{{ opt.label }}</span>
                <span class="visibility-option-desc">{{ opt.desc }}</span>
              </span>
              <el-icon v-if="createSpaceForm.visibility === opt.value" class="visibility-option-check">
                <Check />
              </el-icon>
            </label>
          </div>
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="createSpaceForm.description"
            type="textarea"
            :rows="3"
            placeholder="输入空间描述（可选）"
            maxlength="2000"
          />
        </el-form-item>
      </div>

      <!-- AI 模型配置 -->
      <div class="form-section">
        <div class="section-label">
          <span>AI 模型</span>
          <span class="section-label-hint">可选，创建后可在空间设置中调整</span>
        </div>
        <el-form-item label="文本向量">
          <el-select
            v-model="createSpaceForm.embedding_model"
            placeholder="选择文本向量化模型"
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

        <!-- 高级参数（选了模型后显示） -->
        <div v-if="createSpaceForm.embedding_model" class="advanced-row">
          <div class="advanced-item">
            <span class="advanced-label">批处理大小</span>
            <el-input-number
              v-model="createSpaceForm.embedding_batch_size"
              :min="1"
              :max="128"
              size="small"
              controls-position="right"
              style="width: 120px"
            />
          </div>
          <div class="advanced-item">
            <span class="advanced-label">向量归一化</span>
            <el-switch v-model="createSpaceForm.embedding_normalize" size="small" />
          </div>
        </div>
      </div>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="createSpaceLoading" @click="handleCreateSpace">
        创建空间
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * 创建空间弹窗（自 SpaceListView 平移）：名称/可见性/描述 + 可选 embedding 配置。
 *
 * 消费方：侧栏空间切换器面板 footer、首页空态引导。创建成功后 emit
 * 'created'（携带新空间），由调用方决定跳转。
 */
import { reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Check } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { useSpaceStore } from '@/stores/space'
import { userApi } from '@/api/user'
import type { AvailableModelItem, Space, SpaceConfig } from '@/api/types'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'created', space: Space): void
}>()

const router = useRouter()
const spaceStore = useSpaceStore()

// 可见性卡片选项（色点统一中性灰，语义靠文字与描述传达）
const visibilityOptions = [
  { value: 0, label: '私有', desc: '仅你和受邀成员可见', color: 'var(--color-text-muted)' },
  { value: 1, label: '团队', desc: '组织内成员可访问', color: 'var(--color-text-muted)' },
  { value: 2, label: '公开', desc: '所有登录用户可见', color: 'var(--color-text-muted)' },
] as const

const createSpaceFormRef = ref<FormInstance>()
const createSpaceLoading = ref(false)
const embeddingModels = ref<AvailableModelItem[]>([])

const defaultForm = {
  name: '',
  visibility: 0,
  description: '',
  embedding_model: '',
  embedding_batch_size: 32,
  embedding_normalize: true,
}
const createSpaceForm = reactive({ ...defaultForm })

const spaceFormRules: FormRules = {
  name: [
    { required: true, message: '请输入空间名称', trigger: 'blur' },
    { min: 1, max: 100, message: '名称长度 1-100 字符', trigger: 'blur' },
  ],
}

// 打开时重置表单并拉可选 embedding 模型
watch(
  () => props.visible,
  (visible) => {
    if (!visible) return
    Object.assign(createSpaceForm, defaultForm)
    void (async () => {
      try {
        const data = await userApi.getAvailableModelDetails()
        embeddingModels.value = data.embedding || []
      } catch {
        // 拉取失败留给空列表，创建仍可进行
      }
    })()
  },
)

/** 校验通过后组装 SpaceConfig（含可选 embedding 配置）创建空间，成功后跳转其 KB 列表。 */
async function handleCreateSpace() {
  if (!createSpaceFormRef.value) return

  await createSpaceFormRef.value.validate(async (valid) => {
    if (!valid) return

    createSpaceLoading.value = true
    try {
      const config: SpaceConfig = {
        space_type: ['text'],
        description: createSpaceForm.description || undefined,
        embedding: createSpaceForm.embedding_model
          ? {
              model: createSpaceForm.embedding_model,
              batch_size: createSpaceForm.embedding_batch_size,
              normalize: createSpaceForm.embedding_normalize,
            }
          : undefined,
      }
      const space = await spaceStore.createSpace({
        name: createSpaceForm.name,
        visibility: createSpaceForm.visibility,
        config,
      })
      ElMessage.success('空间创建成功')
      emit('update:visible', false)
      emit('created', space)
      void router.push(`/home/spaces/${space.id}/knowledge-bases`)
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: { message?: string } } } }
      ElMessage.error(err.response?.data?.error?.message || '创建失败')
    } finally {
      createSpaceLoading.value = false
    }
  })
}
</script>

<style scoped>
.form-section {
  margin-bottom: var(--space-5);
}

.section-label {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  margin-bottom: var(--space-3);
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.section-label-hint {
  font-size: var(--text-xs);
  font-weight: var(--weight-normal);
  color: var(--color-text-faint);
}

.visibility-options {
  display: flex;
  gap: var(--space-2);
  width: 100%;
}

.visibility-option {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.visibility-option:hover {
  border-color: var(--color-text-faint);
}

.visibility-option.is-active {
  border-color: var(--color-primary);
  background: var(--color-primary-subtle);
}

.visibility-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.visibility-option-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.visibility-option-name {
  font-size: var(--text-sm);
  color: var(--color-text);
}

.visibility-option-desc {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

.visibility-option-check {
  color: var(--color-primary);
  flex-shrink: 0;
}

.advanced-row {
  display: flex;
  gap: var(--space-5);
  margin-left: 70px;
  margin-bottom: var(--space-3);
}

.advanced-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.advanced-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}
</style>
