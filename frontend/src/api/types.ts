/**
 * 后端 API 契约类型定义
 *
 * 与 backend schemas/ 对应的单一事实源：请求/响应载荷均以此处类型为准，
 * 后端 schema 变更时须同步更新本文件及消费方，禁止前端擅自改名字段。
 */

// ===================== 通用类型 =====================

export interface ApiError {
  error: {
    code: string
    message: string
  }
  timestamp: string
}

// ===================== 认证相关 =====================

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  email: string
  phone?: string
  password: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  must_change_password?: boolean
}

// ===================== 用户相关 =====================

export interface User {
  id: number
  username: string
  email: string
  phone: string | null
  is_admin: boolean
  is_super_admin: boolean
  status: number // 0-禁用 1-正常 2-封禁 3-已删除
  last_login_at: string | null
  created_at: string
  updated_at: string | null
}

export interface MyPermissionsResponse {
  permissions: string[]
  role_code: string
  disabled_apps: string[]
}

export interface UserAppAccess {
  user_id: number
  disabled_apps: string[]
}

export interface UpdateUserAppAccessRequest {
  disabled_apps: string[]
}

export interface CreateUserRequest {
  username: string
  email: string
  password: string
  phone?: string | null
}

export interface UpdateUserRequest {
  username?: string
  email?: string
  // null 表示显式清空手机号；undefined 才是"不提交该字段"（后端 exclude_unset 语义）
  phone?: string | null
  password?: string
  is_admin?: boolean
  status?: number
}

// ===================== 角色权限相关 =====================

export interface Permission {
  id: number
  code: string
  name: string
  module: string
  description: string | null
}

export interface Role {
  id: number
  code: string
  name: string
  description: string | null
  is_system: boolean
  permissions: Permission[]
}

export interface CreateRoleRequest {
  code: string
  name: string
  description?: string
  permission_codes: string[]
}

export interface UpdateRoleRequest {
  name?: string
  description?: string
  permission_codes?: string[]
}

export interface UserRoleAssignRequest {
  role_id: number
}

// ===================== 模型配置相关 =====================

export interface ModelConfig {
  id: number
  user_id: number
  model_type: 'llm' | 'embedding' | 'rerank' | 'vlm' | 'asr'
  protocol: string
  model: string
  base_url: string | null
  api_key: string | null
  extra_config: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface CreateModelConfigRequest {
  model_type: 'llm' | 'embedding' | 'rerank' | 'vlm' | 'asr'
  protocol: string
  model: string
  base_url?: string
  api_key?: string
  extra_config?: Record<string, unknown>
}

export interface UpdateModelConfigRequest {
  protocol?: string
  model?: string
  base_url?: string
  api_key?: string
  extra_config?: Record<string, unknown>
}

export interface ModelConfigTestRequest {
  model_type: 'llm' | 'embedding' | 'rerank' | 'vlm' | 'asr'
  protocol?: string
  model: string
  base_url?: string
  api_key: string
  /** 扩展配置（stream_only/force_thinking 等怪癖声明）；测试请求时后端据此选择探针策略 */
  extra_config?: Record<string, unknown>
}

export interface ModelConfigTestResponse {
  success: boolean
  message: string
  latency_ms: number | null
  detected_dimension: number | null
}

export interface AvailableModelItem {
  model: string
  protocol: string
}

export interface AvailableModelsResponse {
  llm: string[]
  embedding: string[]
  rerank: string[]
  vlm: string[]
  asr: string[]
}

export interface AvailableModelDetail {
  llm: AvailableModelItem[]
  embedding: AvailableModelItem[]
  rerank: AvailableModelItem[]
  vlm: AvailableModelItem[]
  asr: AvailableModelItem[]
}

export interface ModelConfigListResponse {
  total: number
  items: ModelConfig[]
}

// ===================== 搜索引擎配置相关 =====================

export type SearchProvider = 'tavily' | 'serpapi' | 'duckduckgo'

export interface SearchEngineConfig {
  id: number
  user_id: number
  provider: SearchProvider
  api_key: string | null // 已脱敏：'****' 表示已设置，'' / null 表示未设置
  extra_config: Record<string, unknown> | null
  is_primary: boolean
  created_at: string
  updated_at: string
}

export interface CreateSearchEngineConfigRequest {
  provider: SearchProvider
  api_key?: string
  extra_config?: Record<string, unknown>
  is_primary?: boolean
}

export interface UpdateSearchEngineConfigRequest {
  api_key?: string // 留空 = 不修改（保留原密文）
  extra_config?: Record<string, unknown>
  is_primary?: boolean
}

export interface SearchEngineConfigListResponse {
  total: number
  items: SearchEngineConfig[]
}

export interface SearchEngineTestRequest {
  provider: SearchProvider
  api_key?: string
  extra_config?: Record<string, unknown>
}

export interface SearchEngineTestResponse {
  success: boolean
  message: string
  latency_ms: number | null
  results_count: number
}

// ===================== 知识空间相关 =====================

export interface SpaceConfigEmbedding {
  model?: string
  dimension?: number
  batch_size?: number
  normalize?: boolean
}

export interface SpaceConfigEmbeddingUpdate {
  model?: string
  batch_size?: number
  normalize?: boolean
}

export interface SpaceLLMConfig {
  model?: string // LLM 模型名称
}

export interface SpaceASRConfig {
  model?: string // ASR 模型名称（如 whisper-1）
}

export interface SpaceVLMConfig {
  model?: string // VLM 模型名称（视频帧/图片描述）
}

export interface SpaceConfig {
  /**
   * 遗留字段：数据类型（space_type）已下放到知识库（KB）级配置。
   * 后端空间配置不再返回该字段，但历史数据/过渡期 UI 可能仍携带，保持可选。
   */
  space_type?: string | string[]
  description?: string
  tags?: string[]
  embedding?: SpaceConfigEmbedding
  llm?: SpaceLLMConfig // 默认 LLM 配置（问题生成、查询改写、摘要）
  asr?: SpaceASRConfig // 默认 ASR 配置（音频转文字）
  vlm?: SpaceVLMConfig // 默认 VLM 配置（暂未启用）
  storage?: Record<string, unknown>
  ui?: Record<string, unknown>
  defaults?: Record<string, unknown>
  limits?: Record<string, unknown>
}

export interface Space {
  id: number
  name: string
  owner_id: number
  visibility: number // 0-私有 1-团队 2-公开
  config: SpaceConfig | null
  status: number // 1-活跃 2-归档 3-删除
  created_at: string
  updated_at: string | null
}

export interface CreateSpaceRequest {
  name: string
  visibility?: number
  config?: SpaceConfig
}

export interface UpdateSpaceRequest {
  name?: string
  visibility?: number
  config?: SpaceConfig
}

export interface SpaceListResponse {
  items: Space[]
  total: number
  skip: number
  limit: number
}

export interface SpaceConfigStats {
  kb_count: number
  document_count: number
  chunk_count: number
  total_size_mb: number
  member_count: number
}

export interface SpaceConfigResponse {
  space_id: number
  name: string
  config: SpaceConfig
  stats: SpaceConfigStats
}

export interface SpaceConfigUpdateRequest {
  description?: string
  tags?: string[]
  embedding?: SpaceConfigEmbeddingUpdate
  llm?: SpaceLLMConfig
  asr?: SpaceASRConfig
  vlm?: SpaceVLMConfig
  defaults?: Record<string, unknown>
  limits?: Record<string, unknown>
}

// ===================== 知识库相关 =====================

export interface SplittingConfig {
  strategy?:
    | 'recursive'
    | 'fixed_size'
    | 'markdown'
    | 'semantic'
    | 'delimiter'
    | 'sentence_window'
    | 'parent_child'
    | 'hierarchical'
  chunk_size?: number
  chunk_overlap?: number
  min_chunk_size?: number
  max_chunk_size?: number
  similarity_threshold?: number
  batch_size?: number
  /** 分隔符列表（仅 delimiter 生效）：字面量匹配、按序级联应用、切分后丢弃；缺省按空行切 */
  separators?: string[]
  /** 句窗口每侧句数（仅 sentence_window 生效）；0 = 不扩窗 */
  window_size?: number
  /** 父块大小（仅 parent_child 生效）：回带上下文单位，须 ≥ chunk_size */
  parent_chunk_size?: number
}

export interface VideoParsingConfig {
  /** 视频解析策略：7 预设（抽帧/去重/描述三阶段组合） */
  strategy?:
    | 'simple'
    | 'scene'
    | 'dedup'
    | 'grouped'
    | 'rewrite'
    | 'frame_seq'
    | 'video_native'
    | 'adaptive'
  /** 抽帧间隔（秒），0.5~60；动作密集视频可调小捕捉短动作 */
  frame_interval?: number
  /** 最大帧数，1~1000；长视频建议调大（如 300）避免尾部截断 */
  max_frames?: number
  vlm_description_enabled?: boolean
  vlm_model?: string
  vlm_fallback_model?: string
  vlm_skip_on_quota_error?: boolean
  /** 场景抽帧切换点阈值（strategy=scene），0~1，默认 0.3 */
  scene_threshold?: number
  /** 场景抽帧切换点间隔保护（strategy=scene，秒），0.1~10，默认 2.0；动作密集视频调小 */
  scene_min_interval?: number
  /** 去重相似度阈值（strategy=dedup），0~1，默认 0.95 */
  dedup_similarity_threshold?: number
  /** 分组大小（strategy=grouped），每组喂 VLM 多图的帧数，默认 3 */
  group_size?: number
  /** 帧序列伪视频每段帧数上限（strategy=frame_seq），8~512，默认 512；需 VLM 协议 openai_video */
  frame_seq_chunk_frames?: number
  /** 单片时长上限（strategy=video_native，秒），30~540，默认 540；DashScope 10min 硬限留裕量 */
  video_native_chunk_sec?: number
  /** 尾片并入阈值（strategy=video_native，秒），0~120，默认 30 */
  video_native_min_tail_sec?: number
  /** 片间并发上限（strategy=video_native），1~4，默认 2 */
  video_native_concurrency?: number
  /** 服务商拒视频输入时自动降级 frame_seq（strategy=video_native），默认 true */
  video_native_fallback_to_frame_seq?: boolean
  /** 音轨 ASR 融合：提取原始视频音轨转写，旁白按时间归入帧描述行 */
  transcribe_audio?: boolean
  /** 音轨 ASR 模型名（留空 = 部署默认本地档 faster-whisper） */
  asr_model?: string
  /** ASR 语言提示（留空 = 自动检测） */
  language?: string
  /** 音轨 ASR 热词（领域词表，仅本地协议生效，上限 100） */
  hotwords?: string[]
  /** 步骤综合：LLM 汇总双轨描述输出带时间区间的操作步骤（覆盖率校验防遗漏） */
  steps_enabled?: boolean
  /** 步骤综合 LLM 模型名（留空 = 用户默认 LLM） */
  steps_llm_model?: string
  /** 步骤条目上限，1~200，默认 30 */
  steps_max_steps?: number
  /** 叙事合成：解析完成后自动合成章节化连贯叙事文档（Map-Reduce，与碎片块并存；检索命中后附章节摘要） */
  narrative_synthesis?: boolean
  /** 叙事合成 LLM 模型名（留空 = 用户默认 LLM） */
  narrative_llm_model?: string
}

export interface AudioParsingConfig {
  /** ASR 模型名（留空 = 部署默认本地档 faster-whisper；云端模型须在模型管理配置同名凭证） */
  asr_model?: string
  /** 语言提示（留空 = 自动检测） */
  language?: string
  /** ASR 热词（领域词表，如产品名/人名/术语；仅本地协议生效，上限 100） */
  hotwords?: string[]
  /** LLM 清洗开关（双产物：clean 入库检索、raw 溯源；失败逐批降级 raw） */
  clean_enabled?: boolean
  /** 清洗 LLM 模型名（留空 = 用户默认 LLM） */
  clean_llm_model?: string
  /** 切分模式：留空 = 通用切分；'pause_topic' = 停顿边界优先切分 */
  split_mode?: string
  /** 停顿边界阈值（秒，仅 split_mode=pause_topic；默认 0.8） */
  pause_gap_seconds?: number
  /** 说话人分离（仅 DashScope 协议生效；本地协议告警忽略） */
  diarization_enabled?: boolean
  /** 说话人数量参考值（2~100，仅 diarization_enabled 时生效） */
  speaker_count?: number
}

export type PdfParserName = 'full'

export interface TextTypeParsingConfig {
  strategy?: 'default' | 'deepdoc'
}

export interface PdfParsingConfig extends Omit<TextTypeParsingConfig, 'strategy'> {
  strategy?: 'default' | 'deepdoc' | 'external_ocr' | 'vlm'
  parser?: PdfParserName
  /** 仅 strategy=external_ocr 消费：document_parsing(整本直传带版面)/multi_lan(逐页纯文本)；空=document_parsing */
  ocr_task?: 'document_parsing' | 'multi_lan' | null
  /** 仅 strategy=vlm 消费：逐页图 → VLM 转写 markdown 的模型名（配置中心 vlm 类型） */
  vlm_model?: string
}

/** PPT 解析：deepdoc(python-pptx 文本抽取) 或 vlm(soffice 转图后逐页转写) */
export interface PptParsingConfig {
  strategy?: 'deepdoc' | 'vlm'
  /** 仅 strategy=vlm 消费 */
  vlm_model?: string
}

export interface TextParsingConfig {
  pdf?: PdfParsingConfig
  docx?: TextTypeParsingConfig
  excel?: TextTypeParsingConfig
  ppt?: PptParsingConfig
  epub?: TextTypeParsingConfig
  markdown?: TextTypeParsingConfig
  html?: TextTypeParsingConfig
  txt?: TextTypeParsingConfig
  json?: TextTypeParsingConfig
}

export interface ImageParsingConfig {
  strategy?: 'vlm' | 'vlm_doc' | 'deepdoc_ocr' | 'combined' | 'external_ocr'
  /** 仅 external_ocr 消费：document_parsing(PDF 整本直传带版面)/multi_lan(逐页纯文本)；空=按文件形态自动 */
  ocr_task?: 'document_parsing' | 'multi_lan' | null
  vlm_model?: string
  /** VLM 主模型配额/鉴权失败时回退的备用模型名；空=不回退（与视频同名参数同语义） */
  vlm_fallback_model?: string
  /** 主备均配额/鉴权失败时写占位描述继续；默认 false=fail fast */
  vlm_skip_on_quota_error?: boolean
}

export interface ParsingConfig {
  text?: TextParsingConfig
  image?: ImageParsingConfig
  video?: VideoParsingConfig
  audio?: AudioParsingConfig
}

/**
 * 知识库文档统计。六个状态桶按每个文档最新一条任务项归类，互斥且完备：
 * 六桶之和恒等于 document_count。
 */
export interface KBStats {
  document_count: number
  chunk_count: number
  total_size_mb: number
  /** 上传后从未创建解析任务，需要用户手动触发处理 */
  unprocessed_documents: number
  /** 最新任务排队中，系统会自动消费 */
  pending_documents: number
  processing_documents: number
  completed_documents: number
  failed_documents: number
  /** 用户主动取消，需重新触发处理 */
  cancelled_documents: number
}

export interface QuestionGenerationLLMConfig {
  model?: string
  protocol?: string
  temperature?: number
  top_p?: number
  max_tokens?: number
}

export interface QuestionGenerationConfig {
  enabled?: boolean
  llm?: QuestionGenerationLLMConfig
  max_questions_per_chunk?: number
  prompt_template?: string
}

export interface WikiGenerationConfig {
  enabled?: boolean
  llm?: QuestionGenerationLLMConfig
  granularity?: 'focused' | 'standard' | 'exhaustive'
  max_pages_per_ingest?: number
  content_instructions?: string | null
  extraction_instructions?: string | null
}

export interface KBConfig {
  space_type?: string[] // text/image/video/audio，KB 支持的数据模态
  description?: string
  splitting?: SplittingConfig
  parsing?: ParsingConfig
  question_generation?: QuestionGenerationConfig
  wiki?: WikiGenerationConfig
}

export interface KnowledgeBase {
  id: number
  space_id: number
  name: string
  creator_id: number
  config: KBConfig | null
  storage?: Record<string, unknown> | null
  status: number // 0-已删除 1-活跃 2-已归档
  stats?: KBStats
  created_at: string
  updated_at: string | null
}

export interface CreateKnowledgeBaseRequest {
  name: string
  config?: KBConfig
}

export interface UpdateKnowledgeBaseRequest {
  name?: string
  status?: number
  config?: KBConfig
}

export interface KnowledgeBaseListResponse {
  items: KnowledgeBase[]
  total: number
  skip: number
  limit: number
}

export interface KnowledgeBaseConfigResponse {
  kb_id: number
  name: string
  config: KBConfig
  stats: KBStats
}

export interface KnowledgeBaseConfigUpdateRequest {
  space_type?: string[]
  splitting?: SplittingConfig
  parsing?: ParsingConfig
  question_generation?: QuestionGenerationConfig
  wiki?: WikiGenerationConfig
}

// ===================== 文档相关 =====================

export interface Document {
  id: number
  space_id: number
  kb_id: number
  uploader_id: number
  filename: string
  file_type: string
  file_size: number
  file_hash: string
  /** 用户自定义标签（规范化字符串数组，业务分类过滤用） */
  tags?: string[] | null
  doc_metadata: Record<string, unknown> | null
  chunk_count: number
  token_count: number
  // 以下媒体元信息由后端从 DocumentTask.pipeline_result 派生（computed_field），非媒体类型为 null
  chunk_type?: string | null
  duration_seconds?: number | null
  frame_count?: number | null
  segment_count?: number | null
  // 以下文档解析元信息同源派生，按解析器实际产出透出（非该类型文档为 null）
  page_count?: number | null
  outline_count?: number | null
  char_count?: number | null
  section_count?: number | null
  table_count?: number | null
  image_count?: number | null
  embedding_model?: string | null
  embedding_dim?: number | null
  parse_duration_ms?: number | null
  // 解析质量报告（engine 层 quality 元数据透出：parser/warnings/duration_ms），旧任务为 null
  quality?: {
    parser?: string
    warnings?: string[]
    duration_ms?: number
    [key: string]: unknown
  } | null
  created_at: string
  updated_at: string | null
  // 以下字段由后端从 DocumentTask 派生（computed_field），可能为默认值
  status?: number // TaskStatus: 0=PENDING, 1=PROCESSING, 2=COMPLETED, 3=FAILED, 4=CANCELLED
  retry_count?: number
  error_message?: string | null
  /** 最近一次处理完成时间（最新任务 completed_at；无任务或未完成为 null） */
  completed_at?: string | null
  // 存在活跃任务（PENDING/PROCESSING，含 arq 自动重试等待期）——与后端取消接口判定同源
  has_active_task?: boolean
}

export interface Chunk {
  chunk_id: string
  document_id: number
  chunk_index: number
  content: string
  score: number
  has_embedding: boolean
  metadata: Record<string, unknown>
  file_info: Record<string, unknown>
  questions: string[]
  created_at: string
  chunk_type?: string
  image_url?: string
  media_url?: string
}

export interface DocumentDetail extends Document {
  // 分块不再在详情接口返回，前端通过 /chunks 分页接口加载；保留字段以向后兼容
  chunks?: Chunk[]
}

export interface ChunkListResponse {
  items: Chunk[]
  total: number
  page: number
  size: number
}

export interface DocumentFramesResponse {
  frames: Array<{ index: number; url: string }>
  total: number
}

/** 视频叙事章节（叙事合成 Map-Reduce 产物） */
export interface NarrativeChapter {
  title?: string
  start_time?: number
  end_time?: number
  summary?: string
  /** 该章节覆盖的块索引列表（检索附回时按此匹配） */
  chunk_indices?: number[]
}

/** 视频叙事文档（GET narrative 响应；未生成时 exists=false） */
export interface VideoNarrativeResponse {
  document_id: number
  status: 'not_generated' | 'running' | 'completed' | 'failed' | 'unknown'
  exists: boolean
  /** 全片梗概 */
  overview?: string | null
  chapters?: NarrativeChapter[]
  /** 渲染好的完整 Markdown 全文 */
  content_md?: string | null
  error_message?: string | null
  updated_at?: string | null
}

/** 触发叙事合成（POST narrative 响应） */
export interface VideoNarrativeTriggerResponse {
  document_id: number
  job_id: string | null
  status: 'queued'
  message: string
}

export interface DocumentListResponse {
  items: Document[]
  total: number
  skip: number
  limit: number
}

export interface UploadDocumentResponse {
  document_id: number
  filename: string
  status: string
  message: string
}

export interface BatchUploadSuccessItem {
  document_id: number
  filename: string
  status: string
  message: string
}

export interface BatchUploadFailedItem {
  filename: string
  error: string
}

export interface BatchUploadResponse {
  total: number
  success: BatchUploadSuccessItem[]
  failed: BatchUploadFailedItem[]
}

export interface TaskNodeLog {
  status: string // running | done | failed | skipped
  started_at?: string | null
  finished_at?: string | null
  duration_ms?: number | null
  metrics?: Record<string, unknown>
  error?: string | null
}

export interface DocumentTask {
  id: number
  space_id: number
  kb_id: number
  creator_id: number
  action: number
  status: number
  pipeline_config?: Record<string, unknown>
  total_count: number
  processed_count?: number
  task_summary?: {
    pending?: number
    processing?: number
    completed?: number
    failed?: number
    cancelled?: number
  }
  note?: string
  error_message?: string
  started_at?: string
  completed_at?: string
  created_at: string
  updated_at: string
  items: DocumentTaskItem[]
}

export interface DocumentTaskListResponse {
  items: DocumentTask[]
  total: number
}

export interface DocumentTaskItem {
  id: number
  task_id: number
  document_id: number
  document_name?: string | null
  space_id: number
  kb_id: number
  status: number
  job_id?: string
  step_progress?: Record<string, TaskNodeLog | string>
  pipeline_result?: Record<string, unknown>
  error_message?: string
  retry_count: number
  queued_at?: string
  started_at?: string
  completed_at?: string
  created_at: string
  updated_at: string
}

export interface DocumentTaskItemListResponse {
  items: DocumentTaskItem[]
  total: number
}

export interface ProcessDocumentResponse {
  document_id: number
  task_id: number
  task_item_id: number
  status: string
  message: string
}

export interface BatchProcessResultItem {
  document_id: number
  status: string
  message: string
  task_id?: number
  task_item_id?: number
}

export interface BatchProcessResponse {
  task_id: number | null
  total: number
  success: number
  failed: number
  skipped: number
  results: BatchProcessResultItem[]
}

// ===================== 成员相关 =====================

export interface Member {
  id: number
  space_id: number
  user_id: number
  role: number // 0-VIEWER 1-EDITOR 2-ADMIN
  custom_permissions: Record<string, unknown>
  status: number
  invited_by: number
  joined_at: string
  created_at: string
  username: string
  email: string
}

export interface MemberListResponse {
  items: Member[]
  total: number
  skip: number
  limit: number
}

export interface InviteMemberRequest {
  email: string
  role?: number
  expires_hours?: number
}

export interface InviteMemberResponse {
  member_id: number
  invite_token: string
  invite_expires_at: string
  message: string
}

export interface JoinSpaceRequest {
  invite_token: string
}

export interface DirectAddMemberRequest {
  identifier: string // 邮箱或用户名
  role?: number
}

export interface UpdateMemberRoleRequest {
  role: number
}

export interface UpdateMemberPermissionsRequest {
  // resource → action → bool 覆盖；仅设需覆盖项，未列出者回退角色默认
  custom_permissions: Record<string, Record<string, boolean>>
}

// ===================== 检索相关 =====================

export interface SearchWeights {
  vector_weight?: number
  bm25_weight?: number
  content_weight?: number
  question_weight?: number
  rrf_k?: number
}

export interface SearchRerank {
  enabled?: boolean
  top_k?: number
  model?: string
}

export interface SearchLLM {
  enabled?: boolean
  model?: string
  temperature?: number
  top_p?: number
}

export interface SearchQueryRewrite {
  strategy?: 'hyde' | 'sub_query'
  sub_query_count?: number
  sub_query_merge_mode?: 'rrf' | 'score'
  llm_model?: string
}

/** 检索期上下文扩展配置：关闭后恒返回原始检索单元，不拼邻居/父块/章节内容 */
export interface SearchExpansion {
  enabled?: boolean
  /** 允许句子窗口扩窗（仅 strategy=sentence_window 的文档产出该元数据） */
  include_window?: boolean
  /** 允许父子分块回带父块（仅 strategy=parent_child 的文档产出该元数据） */
  include_parent?: boolean
  /** 允许层级切分双向扩展（仅 strategy=hierarchical 的文档产出该元数据） */
  include_hierarchical?: boolean
}

export interface SearchRequest {
  query: string
  search_mode?: string
  top_k?: number
  weights?: SearchWeights
  rerank?: SearchRerank
  llm?: SearchLLM
  query_rewrite?: SearchQueryRewrite
  score_threshold?: number
  fallback_on_unavailable?: boolean
  use_cache?: boolean
  expansion?: SearchExpansion
  /** 元数据过滤（pre-filter）；不传等价不过滤（带过滤的检索后端不走缓存） */
  filters?: SearchFilters
}

export interface SearchFilters {
  /** 文档标签过滤（OR 语义：命中任一标签的文档参与召回；空 = 不过滤） */
  tags?: string[]
}

export interface SearchResultItem {
  chunk_id: string
  document_id: number
  kb_id: number
  content: string
  score: number
  chunk_index: number
  questions: string[] | null
  metadata: Record<string, unknown>
  file_info: Record<string, unknown>
  image_url?: string
  media_url?: string
  chunk_type?: string
  /** 父子分块角色：parent/child（仅 strategy=parent_child）；其余 null */
  chunk_role?: string | null
  /** 层级切分内容类型：text/table/code（仅 strategy=hierarchical）；其余 null */
  content_type?: string | null
}

export interface SearchResponse {
  results: SearchResultItem[]
  total: number
  query: string
  search_mode: string
  original_mode: string | null
  mode_fallback: boolean
  top_k: number
  vector_weight: number | null
  bm25_weight: number | null
  content_weight: number | null
  question_weight: number | null
  rrf_k: number | null
  score_threshold: number | null
  answer: string | null
  answer_model: string | null
  answer_elapsed_ms: number | null
  elapsed_ms: number
  cached: boolean
  rewritten_queries: string[] | null
}

export interface SearchMode {
  mode: string
  label: string
  description: string
  requires_question_generation: boolean
}

/** 跨空间全局检索请求（消费侧入口；范围 = 可访问空间的全部活跃库） */
export interface GlobalSearchRequest {
  query: string
  search_mode?: string
  top_k?: number
  score_threshold?: number
  llm?: SearchLLM
  filters?: SearchFilters
  use_cache?: boolean
}

/** 未参与全局检索的知识库（超上限截断或单库失败） */
export interface GlobalSearchSkippedKb {
  kb_id: number
  kb_name: string
  space_id: number
  /** fan_out_limit（超参与上限）/ error（单库检索失败） */
  reason: string
}

/** 全局检索结果项：单库结果补空间/知识库来源信息 */
export interface GlobalSearchResultItem extends SearchResultItem {
  space_id?: number | null
  space_name?: string | null
  kb_name?: string | null
}

export interface GlobalSearchResponse {
  results: GlobalSearchResultItem[]
  total: number
  query: string
  search_mode: string
  top_k: number
  searched_kbs: number
  skipped_kbs: GlobalSearchSkippedKb[]
  answer: string | null
  answer_model: string | null
  answer_elapsed_ms: number | null
  answer_error?: string | null
  elapsed_ms: number | null
}

export interface SearchModeListResponse {
  modes: SearchMode[]
  total: number
}

export interface SearchModelConfigResponse {
  embedding_model: string
  embedding_dimension: number
  default_llm_model: string
  default_rerank_model: string
  available_embedding_models: string[]
  available_llm_models: string[]
  available_rerank_models: string[]
}

export interface ChunkPositionResponse {
  /** 代表页码（首个高亮矩形所在页）；无坐标数据时为 null */
  page: number | null
  /** 高亮矩形列表（PDF pt 坐标，原点左上，与 pdf.js scale=1 viewport 对齐） */
  bboxes: Array<{
    page: number
    x0: number
    x1: number
    top: number
    bottom: number
  }>
  file_type: string | null
}

/** 知识缺口看板 KPI（批次 2b） */
export interface KnowledgeGapKpi {
  qa_total: number
  down_rate: number
  up_count: number
  zero_hit_rate: number
  low_score_rate: number
  refused_rate: number
  low_score_threshold: number
}

export interface KnowledgeGapTrendItem {
  date: string
  qa_count: number
  zero_hit: number
  refused: number
}

export interface ZeroHitQueryItem {
  query: string
  hit_count: number
  kb_id?: number | null
  last_seen?: string | null
}

// ========== 运营飞轮（健康报告/趋势/徽标/收件箱处置） ==========

/** 健康子分项（透明规则：分数 + 环比 + 一句话构成说明） */
export interface KbOpsHealthSub {
  score: number | null
  prev: number | null
  detail: string
}

/** 知识库健康报告：体检报告「结论」数据面 */
export interface KbOpsHealthReport {
  score: number | null
  prev_score: number | null
  delta: number | null
  subs: Record<'retrieval' | 'freshness' | 'feedback' | 'order', KbOpsHealthSub>
  weekly: {
    gap_converted?: number
    review_confirmed?: number
    todo_ignored?: number
    zero_hit_rate?: number
    zero_hit_delta_pt?: number
  }
}

/** 趋势单日点 */
export interface KbOpsTrendPoint {
  date: string
  query_total: number
  zero_hit: number
  citation_click: number
}

export interface KbOpsTrends {
  window_days: number
  start: string
  end: string
  series: KbOpsTrendPoint[]
}

export interface KbOpsBadgeCounts {
  failed_documents: number
  due_reviews: number
  open_suggestions: number
  gap_clusters: number
}

/** 文档复审状态（周期/下次复审/默认周期） */
export interface DocumentReviewInfo {
  document_id: number
  review_cycle_days: number | null
  next_review_at: string | null
  fallback_cycle_days: number
}

/** 待办忽略留痕载荷 */
export interface TodoIgnorePayload {
  kind: 'gap' | 'review' | 'feedback' | 'evaluation'
  todo_key: string
  query?: string
  /** 忽略原因（一次性提问/非知识需求/误报——自动分诊判例燃料） */
  reason?: 'one_shot' | 'non_kb' | 'false_positive'
}

/** 撤销待办忽略载荷 */
export interface TodoUnignorePayload {
  kind: 'gap' | 'review' | 'feedback' | 'evaluation'
  todo_key: string
}

/** 统一待办行（后端三源聚合同构 shape，影响度排序后端化） */
export interface OpsTodoItem {
  kind: 'gap' | 'review' | 'feedback' | 'evaluation'
  todo_key: string
  title: string
  impact: { count: number | string; unit: string; tone: 'danger' | 'warning' | 'neutral' }
  meta?: string | null
  weight: number
  payload: Record<string, unknown>
}

/** 已忽略待办（忽略区展示 + 撤销入口） */
export interface IgnoredTodoItem {
  kind: string
  todo_key: string
  reason?: string | null
  ignored_at: string
}

/** 统一待办列表响应 */
export interface OpsTodoList {
  items: OpsTodoItem[]
  ignored: IgnoredTodoItem[]
  total: number
}

/** 冷启动单项检查 */
export interface OnboardingCheck {
  key: 'embedding' | 'documents' | 'query_volume'
  label: string
  ok: boolean
  detail: string
  action_hint?: string | null
}

/** 冷启动引导响应 */
export interface OpsOnboarding {
  stage: 'empty' | 'collecting' | 'ready'
  checks: OnboardingCheck[]
  next_step: string
}


export interface LowScoreMessageItem {
  message_id: number
  session_id: string
  kb_id?: number | null
  answer_snippet: string
  max_score?: number | null
  rating?: 'up' | 'down' | null
  created_at?: string | null
}

export interface KbGapStatItem {
  kb_id: number | null
  kb_name: string
  qa_count: number
  down_count: number
  zero_hit_count: number
}

export interface KnowledgeGapStatsResponse {
  kpi: KnowledgeGapKpi
  trend: KnowledgeGapTrendItem[]
  zero_hit_queries: ZeroHitQueryItem[]
  low_score_messages: LowScoreMessageItem[]
  by_kb: KbGapStatItem[]
  window: { start: string; end: string }
}

export interface ActionStatsResponse {
  items: Array<{ action: string; count: number }>
  total: number
}

/** kb-ops gap 清单条目（同一归一化问题聚成一簇，A2） */
export interface KbOpsGapItem {
  query: string
  normalized: string
  hit_count: number
  last_seen: string
  message_ids: number[]
}

/** kb-ops 知识缺口报告（归因分布 + 内容缺口清单） */
export interface KbOpsGapReport {
  kpi: {
    failure_total: number
    pending_attribution: number
    gap_cluster_count: number
    gap_query_count: number
  }
  attribution_distribution: Record<string, number>
  gap_items: KbOpsGapItem[]
  window: { start: string; end: string }
}

/** kb-ops 复审建议条目（new_version=疑似新旧版本 / contradiction=内容矛盾） */
export interface KbOpsSuggestion {
  id: number
  space_id: number
  kb_id: number
  suggestion_type: 'new_version' | 'contradiction' | string
  status: 'open' | 'accepted' | 'dismissed' | string
  score: number | null
  reason: string | null
  old_doc_id: number | null
  new_doc_id: number | null
  resolved_by: number | null
  resolved_at: string | null
  created_at: string
}

export interface KbOpsSuggestionList {
  items: KbOpsSuggestion[]
  total: number
}

export interface KbOpsSuggestionResolve {
  suggestion_id: number
  status: string
  superseded_doc_id: number | null
}

/** kb-ops 重复文档组（exact_hash=同内容上传 / same_normalized_name=同归一化名） */
export interface KbOpsDuplicateGroup {
  group_type: 'exact_hash' | 'same_normalized_name' | string
  kb_id: number
  key: string
  documents: Array<{
    document_id: number
    kb_id: number
    filename: string
    lifecycle_status: string
    created_at: string | null
    superseded_by_doc_id: number | null
  }>
}

export interface KbOpsDuplicates {
  items: KbOpsDuplicateGroup[]
  total: number
}

/** kb-ops 文档贡献统计（点击核验 + 支撑回答） */
export interface KbOpsCitationStats {
  items: Array<{ document_id: number; click_count: number }>
  support_stats: Array<{ document_id: number; support_count: number }>
  total: number
}

/** kb-ops 运营事件账本条目（只追加：query=检索 / query_reformulate=提问改写 / citation_click=引用点击 / attribution=归因写回） */
export interface KbOpsEventHit {
  document_id: number | null
  chunk_id: string | null
  score: number | null
  document_name: string | null
  snippet: string
}

export interface KbOpsEvent {
  id: number
  event_type: string
  user_id: number
  session_id: string | null
  space_id: number | null
  kb_id: number | null
  query_text: string | null
  extra: {
    user_role?: string
    hits?: KbOpsEventHit[]
    results_count?: number
    max_score?: number
    search_mode?: string
    top_k?: number
    bypass_document_permission?: boolean
  } | null
  created_at: string
}

export interface KbOpsEventList {
  items: KbOpsEvent[]
  total: number
  limit: number
  offset: number
}

export interface KbOpsContradictionScan {
  kb_id: number
  suggestions_created: number
  suggestions: Array<{
    suggestion_id: number
    doc_a: number | null
    doc_b: number | null
    similarity: number
    reason: string
  }>
}

/** kb-ops 文档生命周期四态计数（软删排除） */
export interface KbOpsLifecycleCounts {
  active: number
  superseded: number
  archived: number
  draft: number
  total: number
}

/** kb-ops 解析失败文档条目（每文档最新任务行判定，重试成功不再算失败） */
export interface KbOpsFailedDocument {
  document_id: number
  kb_id: number
  filename: string
  completed_at: string | null
  error_message: string | null
}

export interface KbOpsFailedDocumentsSummary {
  count: number
  items: KbOpsFailedDocument[]
}

/** kb-ops 待复审文档条目（next_review_at 落在提醒窗口内） */
export interface KbOpsDueReview {
  document_id: number
  kb_id: number
  filename: string
  owner_id: number | null
  next_review_at: string
  overdue: boolean
}

export interface KbOpsDueReviewsSummary {
  count: number
  items: KbOpsDueReview[]
}

/** kb-ops 空间运营概览（工作台异常区与资产健康页数据面） */
export interface KbOpsOverview {
  documents: KbOpsLifecycleCounts
  kb_count: number
  failed_documents: KbOpsFailedDocumentsSummary
  due_reviews: KbOpsDueReviewsSummary
}

/** kb-ops gap 转测试集响应（flywheel：生产失败变回归用例） */
export interface KbOpsGapConvertResult {
  test_set_id: number
  total_cases: number
  added_cases: number
  message: string
}

/** 两次测评报告对比（批次 3b） */
export interface EvaluationComparisonResponse {
  task_id: number
  baseline_task_id: number
  same_test_set: boolean
  /** summary 逐项 delta（key 形如 retrieval.hit_rate / generation.overall） */
  metrics: Array<{
    key: string
    baseline: number | null
    current: number | null
    delta: number | null
  }>
  /** 按 delta 降序；status: ok/error/removed（仅基线有） */
  cases: Array<{
    question: string
    status: 'ok' | 'error' | 'removed'
    baseline_score: number | null
    current_score: number | null
    delta: number | null
    baseline_retrieval: number | null
    current_retrieval: number | null
  }>
  summary: {
    improved: number
    degraded: number
    unchanged: number
    baseline_only: number
  }
}

// ===================== 评测相关 =====================

export interface TestSet {
  id: number
  name: string
  filename: string
  file_type: string
  file_size: number
  total_cases: number
  created_at: string
  updated_at: string
}

export interface TestSetListResponse {
  items: TestSet[]
  total: number
  skip: number
  limit: number
}

export interface UploadTestSetResponse {
  test_set_id: number
  name: string
  filename: string
  file_type: string
  file_size: number
  total_cases: number
  message: string
}

export interface EvaluationConfig {
  search_mode?: string
  top_k?: number
  score_threshold?: number
  enable_generation?: boolean
  llm_model?: string | null
  embedding_model?: string | null
  retrieval_relevance_strategy?: string
  enable_mrr?: boolean
  enable_recall_at_k?: boolean
  correctness_strategy?: string
  faithfulness_strategy?: string
  relevance_strategy?: string
  enable_context_precision?: boolean
  enable_context_recall?: boolean
  enable_answer_similarity?: boolean
  scoring_dimensions?: string[]
}

export interface EvaluationTask {
  id: number
  test_set_id: number
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'deleted' | 'cancelled'
  config: EvaluationConfig | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface EvaluationTaskListResponse {
  items: EvaluationTask[]
  total: number
  skip: number
  limit: number
}

export interface CreateEvaluationTaskRequest {
  test_set_id: number
  name: string
  config?: EvaluationConfig
}

export interface CreateEvaluationTaskResponse {
  task_id: number
  name: string
  test_set_id: number
  status: string
  message: string
}

export interface EvaluationRetrievalScores {
  precision_at_k?: number
  hit_rate?: number
  mrr?: number
  recall_at_k?: number
  /** gold 模式用例数（自带参考资料跳过检索，不参与检索指标平均） */
  gold_cases?: number
  /** 实际执行检索的用例数 */
  retrieved_cases?: number
}

export interface EvaluationGenerationScores {
  faithfulness?: number
  answer_relevance?: number
  correctness?: number
  quality?: number
  overall?: number
}

export interface EvaluationEndToEndScores {
  context_precision?: number
  context_recall?: number
  answer_similarity?: number
}

export interface EvaluationSummary {
  total_cases: number
  completed_cases: number
  elapsed_seconds: number
  retrieval: EvaluationRetrievalScores | null
  generation: EvaluationGenerationScores | null
  end_to_end: EvaluationEndToEndScores | null
  human_scores: number | null
  /** 切分健康统计（命中样本去重）：碎片/边界信号，null = 无检索样本 */
  chunk_health?: {
    total_chunks: number
    short_chunks: number
    unterminated_chunks: number
  } | null
  /** 报告级诊断建议（批次 4）：归因分组/切分信号/生成低分，空表 = 无需行动 */
  recommendations?: Array<{
    category: string
    count: number
    suggestion: string
    targets: string[]
  }>
  /** 归因分析（批次 E1/E2）：失败用例五阶段根因分布 + 重灾文档 */
  attribution?: {
    attributed_cases: number
    by_stage: Record<string, number>
    by_category: Record<string, number>
    hotspot_documents?: Array<{
      document_id: number
      document_name: string
      failure_count: number
    }>
    deep_checked: boolean
  }
}

export interface RetrievedChunk {
  chunk_id: string
  content: string
  score: number
  document_id?: number
  /** chunk 溯源：来源文档名（映射缺失时为空） */
  document_name?: string | null
}

export interface EvaluationDetail {
  index: number
  question: string
  expected_answer: string
  generated_answer: string
  retrieved_chunks: RetrievedChunk[]
  retrieval: EvaluationRetrievalScores | null
  generation_scores: EvaluationGenerationScores | null
  end_to_end: EvaluationEndToEndScores | null
  human_score: number | null
  human_comment: string | null
  /** 自带参考资料（gold contexts）用例：跳过检索，直接评生成 */
  gold_mode?: boolean
  /** 检索失败多级重放归因结论（expected_sources 未命中时生成） */
  failure_diagnosis?: {
    category:
      | 'permission_boundary'
      | 'ranking_issue'
      | 'mode_mismatch'
      | 'embedding_gap'
      | 'index_missing'
    evidence: string
    suggestion: string
  }
}

export interface EvaluationReport {
  task_id: number
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'deleted' | 'cancelled'
  total_cases: number
  completed_cases: number
  summary: EvaluationSummary
  details: EvaluationDetail[]
}

export interface HumanScoreItem {
  index: number
  score: number
  comment?: string
}

export interface SubmitHumanScoresRequest {
  scores: HumanScoreItem[]
}

export interface SubmitHumanScoresResponse {
  updated_count: number
  message: string
}

export interface TestSetUpdateRequest {
  name: string
}

export interface TestSetCasesResponse {
  test_set_id: number
  total_cases: number
  test_cases: Array<{
    question: string
    expected_answer: string
    contexts?: string[]
    expected_sources?: string[]
  }>
}

export interface TaskCancelResponse {
  task_id: number
  status: string
  message: string
}

export interface TaskProgressResponse {
  task_id: number
  status: string
  current: number
  total: number
}

// ===================== Agent API 密钥（MCP 访问凭证） =====================

export interface ApiKeyItem {
  id: number
  name: string
  /** 脱敏前缀（nvm_xxxxxxxx****），明文只在创建响应出现一次 */
  key_prefix: string
  status: 'active' | 'revoked'
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export interface ApiKeyListResponse {
  keys: ApiKeyItem[]
  total: number
}

/** 创建响应：明文 key 仅此一次返回，前端须提示用户立即保存 */
export interface ApiKeyCreatedResponse {
  id: number
  name: string
  key_prefix: string
  api_key: string
  status: 'active' | 'revoked'
  created_at: string
}

export interface ApiKeyRevokeResponse {
  id: number
  status: 'active' | 'revoked'
  revoked_at: string | null
}

// ===================== 通知相关 =====================

export interface Notification {
  id: number
  user_id: number
  type: string
  title: string
  content: string
  link: string | null
  extra_data: Record<string, unknown> | null
  is_read: boolean
  read_at: string | null
  created_at: string
}

export interface NotificationListResponse {
  items: Notification[]
  total: number
  unread_count: number
}

export interface UnreadCountResponse {
  unread_count: number
}

export interface NotificationPreference {
  id: number
  user_id: number
  email_enabled: boolean
  in_app_enabled: boolean
  types_enabled: string[] | null
}

// ===================== 全模态常量 =====================

/** 模态 → 文件扩展名 accept 映射 */
/** 解析能力描述符（GET /spaces/{id}/knowledge-bases/parsing-descriptors）：
 * 后端格式/策略/数值边界的单一来源；静态表仅作拉取失败时的 fallback */
export interface ParsingDescriptors {
  formats: Record<string, string[]>
  splitting_strategies: string[]
  splitting_limits: Record<string, { default: number; min: number; max: number }>
  parsing_strategies: Record<string, string[]>
}

/** 静态 fallback：运行时优先用 loadParsingDescriptors 拉取的描述符（epub 曾因
 * 此表漏 .epub 而成为「解析支持但传不上来」的半接线格式） */
export const MODALITY_ACCEPT_MAP: Record<string, string> = {
  text: '.pdf,.docx,.doc,.epub,.txt,.md,.csv,.html,.json,.xlsx,.pptx,.zip,.eml,.msg,.ofd',
  image: '.jpg,.jpeg,.png,.gif,.webp',
  video: '.mp4,.mov,.avi,.mkv,.webm',
  audio: '.mp3,.wav,.flac,.aac,.ogg,.m4a',
}

/** 模态 → 最大文件大小 (MB)。与后端 document_upload_service._get_max_file_size 模态上限对齐 */
export const MODALITY_MAX_SIZE_MB: Record<string, number> = {
  text: 100,
  image: 100,
  video: 2000,
  audio: 200,
}

// ===================== Wiki =====================

/** Wiki 页面（详情，含正文） */
export interface WikiPage {
  id: string
  slug: string
  title: string
  page_type: string // summary/entity/concept/synthesis/comparison
  status: string // draft/published/archived
  content: string
  summary: string
  aliases: string[]
  category_path: string[]
  source_refs: string[] // "<document_id>|<filename>" 列表
  chunk_refs: string[]
  in_links: string[]
  out_links: string[]
  version: number
  last_edit_source: string // pipeline/user/agent/revert
  created_at: string
  updated_at: string
}

/** Wiki 页面列表项（轻量，无正文） */
export interface WikiPageListItem {
  id: string
  slug: string
  title: string
  page_type: string
  status: string
  summary: string
  aliases: string[]
  category_path: string[]
  in_links: string[]
  out_links: string[]
  version: number
  last_edit_source: string
  updated_at: string
}

export interface WikiPageListResponse {
  pages: WikiPageListItem[]
  total: number
  page: number
  page_size: number
}

export interface WikiIndexGroup {
  page_type: string
  total: number
  items: WikiPageListItem[]
}

export interface WikiIndexResponse {
  groups: WikiIndexGroup[]
  is_active: boolean
}

export interface WikiStatsResponse {
  total_pages: number
  pages_by_type: Record<string, number>
  total_links: number
  orphan_count: number
  is_active: boolean
}

/** 空间级 Wiki 概览（跨 KB 聚合，工作台首页展示） */
export interface WikiOverview {
  total_pages: number
  pages_by_type: Record<string, number>
  total_links: number
  orphan_count: number
  pending_issues: number
  /** 健康分 0-100 启发式；零页空间为 null */
  health_score: number | null
}

export interface WikiIngestStatusResponse {
  status: string // pending/running/done/failed
  step_progress: Record<
    string,
    {
      status: string
      started_at?: string
      finished_at?: string
      metrics?: Record<string, unknown>
      error?: string
    }
  > | null
  pages_created: number
  pages_updated: number
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  /** 排队等待便签（Redis 瞬态键；最新履历文档在等 per-KB 锁时非空） */
  defer_wait?: string | null
}

export interface WikiPageSourceDocument {
  document_id: number
  filename: string
  deleted: boolean
}

export interface WikiPageSourcesResponse {
  slug: string
  title: string
  source_documents: WikiPageSourceDocument[]
  chunk_refs: string[]
}

export interface WikiSearchResponse {
  items: Array<{
    slug: string
    title: string
    page_type: string
    summary: string
    /** 命中位置前后各 60 字符的正文片段（后端 search_pages_ranked 产出） */
    snippet: string
  }>
  total: number
  query: string
}

export interface WikiRevisionSummary {
  version: number
  title: string
  page_type: string
  status: string
  summary: string
  edit_source: string
  editor_id: number | null
  edited_at: string
}

export interface WikiRevisionListResponse {
  slug: string
  current_version: number
  total: number
  revisions: WikiRevisionSummary[]
}

export interface WikiRevisionDetail extends WikiRevisionSummary {
  content: string
  aliases: string[]
}

export interface WikiPageUpdateRequest {
  title?: string
  content?: string
  summary?: string
  page_type?: string
  status?: string
  aliases?: string[]
  category_path?: string[]
  version?: number
}

export interface WikiPageCreateRequest {
  slug: string
  title: string
  content?: string
  summary?: string
  page_type?: string
  aliases?: string[]
  category_path?: string[]
}

export interface WikiRevertResponse {
  slug: string
  reverted_to_version: number
  new_version: number
}

// ===================== Wiki 图谱 / lint / 问题（P3） =====================

export interface WikiGraphNode {
  slug: string
  title: string
  page_type: string
  link_count: number
}

export interface WikiGraphEdge {
  source: string
  target: string
}

export interface WikiGraphResponse {
  nodes: WikiGraphNode[]
  edges: WikiGraphEdge[]
  meta: {
    mode: string
    total: number
    returned: number
    truncated: boolean
    center?: string | null
    depth?: number | null
  }
}

export interface WikiLintIssue {
  slug: string
  // 对齐后端六类：orphan_page / broken_link / stale_ref / missing_cross_ref /
  // empty_content / duplicate_slug
  issue_type: string
  severity: string // info / warning / error
  description: string
  target_slug: string // broken_link 目标页 / stale_ref 文档标识
  auto_fixable: boolean
}

export interface WikiLintResponse {
  issues: WikiLintIssue[]
  checked_pages: number
  health_score: number // 0-100
  summary: string
}

export interface WikiAutoFixResponse {
  fixed: number
  details: string[]
}

export interface WikiIssue {
  id: string
  slug: string
  issue_type: string
  description: string
  status: string // pending/ignored/resolved
  reported_by: string
  created_at: string
}

export interface WikiIssueCreateRequest {
  slug: string
  issue_type: string
  description: string
  reported_by?: string
}
