/**
 * API 类型定义 — 严格对齐后端接口文档
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
  status: number // 0-禁用 1-正常 2-封禁 3-已删除
  last_login_at: string | null
  created_at: string
  updated_at: string | null
}

export interface CreateUserRequest {
  username: string
  email: string
  password: string
  phone?: string
}

export interface UpdateUserRequest {
  username?: string
  email?: string
  phone?: string
  password?: string
  is_admin?: boolean
  status?: number
}

// ===================== 模型配置相关 =====================

export interface ModelConfig {
  id: number
  user_id: number
  model_type: 'llm' | 'embedding' | 'rerank' | 'vlm' | 'multimodal_embedding'
  protocol: string
  model: string
  base_url: string | null
  api_key: string | null
  extra_config: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface CreateModelConfigRequest {
  model_type: 'llm' | 'embedding' | 'rerank' | 'vlm' | 'multimodal_embedding'
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
  model_type: 'llm' | 'embedding' | 'rerank' | 'vlm' | 'multimodal_embedding'
  protocol?: string
  model: string
  base_url?: string
  api_key: string
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
  multimodal_embedding: string[]
}

export interface AvailableModelDetail {
  llm: AvailableModelItem[]
  embedding: AvailableModelItem[]
  rerank: AvailableModelItem[]
  vlm: AvailableModelItem[]
  multimodal_embedding: AvailableModelItem[]
}

export interface ModelConfigListResponse {
  total: number
  items: ModelConfig[]
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

export interface SpaceMultimodalEmbeddingConfig {
  model?: string
  dimension?: number
}

export interface SpaceConfig {
  space_type?: 'text' | 'multimodal'
  description?: string
  tags?: string[]
  embedding?: SpaceConfigEmbedding
  multimodal_embedding?: SpaceMultimodalEmbeddingConfig
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
  space_type?: 'text' | 'multimodal'
  description?: string
  tags?: string[]
  embedding?: SpaceConfigEmbeddingUpdate
  multimodal_embedding?: SpaceMultimodalEmbeddingConfig
  defaults?: Record<string, unknown>
  limits?: Record<string, unknown>
}

// ===================== 知识库相关 =====================

export interface SplittingRecursive {
  strategy: 'recursive'
  chunk_size?: number
  chunk_overlap?: number
}

export interface SplittingFixedSize {
  strategy: 'fixed_size'
  chunk_size?: number
  chunk_overlap?: number
}

export interface SplittingMarkdown {
  strategy: 'markdown'
  max_chunk_size?: number
  min_chunk_size?: number
}

export interface SplittingSemantic {
  strategy: 'semantic'
  max_chunk_size?: number
  similarity_threshold?: number
  batch_size?: number
}

export type SplittingConfig = SplittingRecursive | SplittingFixedSize | SplittingMarkdown | SplittingSemantic

export interface ParsingConfig {
  extract_images?: boolean
  extract_tables?: boolean
  ocr_enabled?: boolean
  preserve_structure?: boolean
  encoding?: string
}

export interface KBStats {
  document_count: number
  chunk_count: number
  total_size_mb: number
  uploaded_documents: number
  completed_documents: number
  failed_documents: number
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

export interface KBConfig {
  description?: string
  splitting?: SplittingConfig
  parsing?: ParsingConfig
  question_generation?: QuestionGenerationConfig
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
  splitting?: SplittingConfig
  parsing?: ParsingConfig
  question_generation?: QuestionGenerationConfig
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
  status: number
  doc_metadata: Record<string, unknown> | null
  status_info: Record<string, unknown> | null
  retry_count: number
  error_message: string
  chunk_count: number
  token_count: number
  created_at: string
  updated_at: string | null
  processing_started_at: string | null
  processed_at: string | null
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
}

export interface DocumentDetail extends Document {
  chunks: Chunk[]
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

export interface ProcessDocumentResponse {
  document_id: number
  status: string
  message: string
}

export interface BatchProcessResponse {
  total: number
  success: number
  failed: number
  skipped: number
  results: ProcessDocumentResponse[]
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

export interface UpdateMemberRoleRequest {
  role: number
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
  hyde_prompt?: string
  sub_query_count?: number
  sub_query_merge_mode?: 'rrf' | 'score'
  llm_model?: string
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
  filters?: Record<string, unknown>
  use_cache?: boolean
}

export type MultimodalSearchMode = 'text_to_image' | 'image_to_image'

export interface MultimodalSearchRequest {
  query?: string
  image_base64?: string
  search_mode: MultimodalSearchMode
  top_k?: number
  score_threshold?: number
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
  chunk_type?: string
}

export interface SearchResponse {
  results: SearchResultItem[]
  total: number
  query: string
  search_mode: string
  original_mode: string | null
  mode_fallback: boolean
  top_k: number
  vector_weight: number
  bm25_weight: number
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

// ===================== 聊天相关 =====================

export interface AddMessageRequest {
  content: string
  role?: 'user' | 'assistant' | 'system'
  session_id?: string
  kb_id?: number
  space_id?: number
}

export interface UpdateMessageRequest {
  content?: string
  role?: 'user' | 'assistant'
}

export interface QAContextResponse {
  context: Array<{ role: string; content: string }>
}

export interface ChatMessage {
  id: number
  content: string
  role: 'user' | 'assistant' | 'system'
  user_id: number
  session_id: string
  space_id: number | null
  kb_id: number | null
  extra: Record<string, unknown> | null
  created_at: string
  reasoning?: string
  attachments?: ChatAttachment[]
}

export interface ChatAttachment {
  id: number
  filename: string
  file_type: string
  file_size: number
  preview_url?: string
}

export interface UploadChatAttachmentResponse {
  attachment_id: number
  filename: string
  file_type: string
  file_size: number
  status: string
  message: string
}

export interface SessionItem {
  session_id: string
  preview: string
}

export interface SessionListResponse {
  items: SessionItem[]
  total: number
  limit: number
  offset: number
}

export interface ChatRequest {
  content: string
  session_id?: string
  llm_model?: string
  max_tokens?: number
  temperature?: number
  top_p?: number
  system_prompt?: string
  enable_thinking?: boolean
  attachment_ids?: number[]
}

export interface ChatResponse {
  session_id: string
  user_message: ChatMessage
  ai_message: ChatMessage
  conversation_history: Array<{ id: number; content: string; role: string; created_at: string }>
}

export interface ChatHistoryResponse {
  session_id: string
  messages: Array<{ id: number; content: string; role: string; created_at: string }>
}

export interface HealthCheckResponse {
  status: string
  message: string
}

export interface ModelsResponse {
  models: Record<string, { max_tokens: number; temperature: number; top_p: number; model_type: string }>
}

// ===================== 会话配置相关 =====================

export interface CompressionConfig {
  enable_compression?: boolean
  strategy?: 'summary' | 'sliding_window' | 'keep_recent' | 'truncate'
  threshold?: number
  target_tokens?: number
  keep_recent?: number
  custom_prompt?: string
}

export interface CreateSessionConfigRequest {
  compression?: CompressionConfig
}

export interface SessionConfigResponse {
  id: number
  session_id: string
  user_id: number
  compression_config: CompressionConfig
  created_at: string | null
  updated_at: string | null
}

// ===================== 深度研究相关 =====================

export interface ResearchInternalSearch {
  kb_ids?: number[]
  search_mode?: string
  top_k?: number
  vector_weight?: number
  bm25_weight?: number
  score_threshold?: number
  rerank_enabled?: boolean
  rerank_top_k?: number
  rerank_model?: string
  query_rewrite_enabled?: boolean
  query_rewrite_strategy?: 'hyde' | 'sub_query'
  sub_query_count?: number
  query_rewrite_llm_model?: string
}

export interface ResearchExternalSearch {
  provider?: 'tavily' | 'serpapi' | 'duckduckgo'
  max_results?: number
  search_depth?: 'basic' | 'advanced'
  time_range?: 'day' | 'week' | 'month' | 'year'
  region?: string
}

export interface ResearchLLM {
  llm_model?: string
  temperature?: number
  top_p?: number
  max_tokens?: number
}

export interface ResearchRequest {
  query: string
  research_mode?: 'quick' | 'standard' | 'deep'
  search_source?: 'internal' | 'external' | 'hybrid'
  internal_search?: ResearchInternalSearch
  external_search?: ResearchExternalSearch
  llm?: ResearchLLM
}

export interface ResearchTask {
  task_id: string
  description: string
  priority: number
  dependencies: string[]
}

export interface ResearchSearchSummary {
  search_results?: Array<{
    source_type: string
    content: string
    url: string | null
    score: number
    document_id: number | null
    chunk_id: number | null
    document_name: string | null
    kb_id: number | null
    kb_name: string | null
  }>
  sources?: string[]
}

export interface ResearchStats {
  elapsed_seconds: number
  internal_searches: number
  external_searches: number
  total_results: number
}

export interface Research {
  session_id: string
  query: string
  research_mode: string
  search_source: string
  external_provider: string | null
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  research_topic: string | null
  research_tasks: ResearchTask[] | null
  final_report: string | null
  search_summary: ResearchSearchSummary | null
  stats: ResearchStats | null
  created_at: string
  completed_at: string | null
}

export interface ResearchListResponse {
  items: Research[]
  total: number
  offset: number
  limit: number
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
}

export interface RetrievedChunk {
  chunk_id: string
  content: string
  score: number
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

// ===================== Agent 相关 =====================

export interface Agent {
  id: number
  user_id: number | null
  name: string
  description: string | null
  system_prompt: string
  llm_model: string | null
  max_tokens: number
  context_window: number
  temperature: number
  top_p: number
  max_tool_calls_per_turn: number
  enabled_tools: string[] | null
  enabled_mcp_servers: number[] | null
  created_at: string
  updated_at: string
}

export interface CreateAgentRequest {
  name: string
  description?: string
  system_prompt: string
  llm_model?: string
  max_tokens?: number
  context_window?: number
  temperature?: number
  top_p?: number
  max_tool_calls_per_turn?: number
  enabled_tools?: string[]
  enabled_mcp_servers?: number[]
}

export type UpdateAgentRequest = Partial<CreateAgentRequest>

export interface AgentListResponse {
  items: Agent[]
  total: number
  limit: number
  offset: number
}

export interface AgentConversation {
  id: number
  user_id: number
  agent_id: number
  session_id: string
  title: string | null
  status: string
  message_count: number
  total_tokens_used: number
  created_at: string
  updated_at: string
}

export interface AgentConversationListResponse {
  items: AgentConversation[]
  total: number
  limit: number
  offset: number
}

export interface AgentMessage {
  id: number
  conversation_id: number
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string | null
  tool_call_id: string | null
  tool_name: string | null
  token_count: number | null
  extra?: Record<string, any> | null
  created_at: string
  reasoning?: string
}

export interface AgentMessageListResponse {
  items: AgentMessage[]
  total: number
}

export interface McpServer {
  id: number
  user_id: number | null
  name: string
  description: string | null
  transport_type: 'stdio' | 'streamable_http'
  connection_config: Record<string, unknown>
  enabled: boolean
  status: 'disconnected' | 'connecting' | 'connected' | 'error'
  last_error: string | null
  available_tools: McpTool[] | null
  created_at: string
  updated_at: string
}

export interface McpTool {
  name: string
  description: string
  inputSchema?: Record<string, unknown>
}

export interface CreateMcpServerRequest {
  name: string
  description?: string
  transport_type: 'stdio' | 'streamable_http'
  connection_config: Record<string, unknown>
  enabled?: boolean
}

export type UpdateMcpServerRequest = Partial<CreateMcpServerRequest>

export interface ToolFunction {
  name: string
  description: string
  parameters: Record<string, unknown>
}

export interface ToolProvider {
  name: string
  description: string
  tools: ToolFunction[]
  system_prompt_fragment: string
}

export interface AgentChatDoneData {
  message_id: number
  tool_calls_count: number
  total_tokens: number
  iterations: number
  truncated: boolean
}

export interface ToolCallRecord {
  toolName: string
  arguments: Record<string, unknown>
  callId: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  result?: string
  durationMs?: number
}

// ==================== 技能广场 ====================

export interface SkillReviewRules {
  passed: boolean
  matches: string[]
}

export interface SkillReviewLlm {
  level: string | null
  reason: string | null
}

export interface SkillReviewResult {
  rules: SkillReviewRules
  llm: SkillReviewLlm
  admin_reason?: string
}

export interface SkillDefinition {
  id: number
  user_id: number | null
  name: string
  display_name: string
  description: string
  license: string | null
  allowed_tools: string[] | null
  frontmatter_raw: string | null
  body_markdown: string
  category: string | null
  tags: string[] | null
  icon: string | null
  version: number
  version_note: string | null
  skill_source: 'builtin' | 'custom'
  visibility: number
  status: number
  install_count: number
  rating_avg: number
  rating_count: number
  review_status: number // 0=PENDING 1=APPROVED 2=SUSPICIOUS 3=REJECTED
  review_result: SkillReviewResult | null
  reviewed_at: string | null
  author_name: string | null
  created_at: string | null
  updated_at: string | null
}

export interface SkillListItem {
  id: number
  name: string
  display_name: string
  description: string
  category: string | null
  tags: string[] | null
  icon: string | null
  version: number
  skill_source: 'builtin' | 'custom'
  install_count: number
  rating_avg: number
  rating_count: number
  author_name: string | null
  created_at: string | null
  updated_at: string | null
}

export interface SkillMarketplaceListResponse {
  items: SkillListItem[]
  total: number
  limit: number
  offset: number
}

export interface SkillReviewItem {
  id: number
  skill_id: number
  user_id: number
  rating: number
  content: string | null
  user_name: string | null
  created_at: string | null
  updated_at: string | null
}

export interface SkillReviewListResponse {
  items: SkillReviewItem[]
  total: number
}

export interface SkillInstallationItem {
  id: number
  skill_id: number
  agent_id: number
  created_at: string | null
}

export interface SkillValidateResponse {
  valid: boolean
  errors: string[]
  parsed: Record<string, unknown> | null
}

// ==================== 技能广场 — 管理员 ====================

export interface SkillAdminSettingsResponse {
  llm_review_enabled: boolean
  llm_review_model: string | null
}

export interface SkillAdminSettingsUpdate {
  llm_review_enabled: boolean
  llm_review_model?: string | null
}

export interface SkillAdminReviewAction {
  reason?: string
}

export interface SkillPendingReviewListResponse {
  items: SkillListItem[]
  total: number
}

// ==================== 技能分类和标签 ====================

export interface SkillCategoriesResponse {
  categories: string[]
}

export interface SkillTagsResponse {
  tags: string[]
}

// ==================== AI 搜索 ====================

export interface SkillAISearchParsedQuery {
  keywords: string[]
  category: string | null
  tags: string[] | null
  sort: string
  intent_summary: string
}

export interface SkillAISearchResponse {
  items: SkillListItem[]
  total: number
  limit: number
  offset: number
  explanation: string
  ai_query: SkillAISearchParsedQuery
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
