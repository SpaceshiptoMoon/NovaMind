import { request } from './index'
import type {
  LoginRequest,
  LoginResponse,
  RegisterRequest,
  CreateUserRequest,
  UpdateUserRequest,
  User,
  MyPermissionsResponse,
  UserAppAccess,
  UpdateUserAppAccessRequest,
  ModelConfig,
  ModelConfigListResponse,
  AvailableModelsResponse,
  AvailableModelDetail,
  CreateModelConfigRequest,
  UpdateModelConfigRequest,
  ModelConfigTestRequest,
  ModelConfigTestResponse,
  SearchEngineConfig,
  SearchEngineConfigListResponse,
  CreateSearchEngineConfigRequest,
  UpdateSearchEngineConfigRequest,
  SearchEngineTestRequest,
  SearchEngineTestResponse,
  Role,
  Permission,
  CreateRoleRequest,
  UpdateRoleRequest,
  UserRoleAssignRequest,
} from './types'

const BASE_URL = '/user/users'

/**
 * 用户与认证 API
 *
 * 分组：认证（登录/注册/登出）、用户管理（CRUD/状态/权限）、
 * 模型配置、搜索引擎配置、密码管理、角色与 RBAC、应用级访问控制。
 */
export const userApi = {
  // 认证
  /** 账号密码登录，返回 access/refresh 双令牌 */
  login(data: LoginRequest) {
    return request.post<LoginResponse>(`${BASE_URL}/login`, data)
  },
  /** 注册新账号，成功即登录（返回令牌） */
  register(data: RegisterRequest) {
    return request.post<LoginResponse>(`${BASE_URL}/register`, data)
  },
  /** 用 refresh token 换新 access token（静默续期） */
  refreshToken(refreshToken: string) {
    return request.post<LoginResponse>(`${BASE_URL}/refresh`, { refresh_token: refreshToken })
  },
  /** 登出；带 refreshToken 时后端同步吊销该刷新令牌 */
  logout(refreshToken?: string) {
    return request.post<{ message: string }>(
      `${BASE_URL}/logout`,
      refreshToken ? { refresh_token: refreshToken } : undefined,
    )
  },

  // 用户管理
  /** 当前用户的权限码集合（前端路由/按钮显隐依据） */
  getMyPermissions() {
    return request.get<MyPermissionsResponse>(`${BASE_URL}/me/permissions`)
  },
  /** 用户列表（分页；需管理员权限） */
  getUsers(params?: { skip?: number; limit?: number }) {
    return request.get<User[]>(BASE_URL, params)
  },
  /** 用户详情 */
  getUser(userId: number) {
    return request.get<User>(`${BASE_URL}/${userId}`)
  },
  /** 管理员创建用户 */
  createUser(data: CreateUserRequest) {
    return request.post<User>(BASE_URL, data)
  },
  /** 更新用户资料/角色/状态 */
  updateUser(userId: number, data: UpdateUserRequest) {
    return request.put<User>(`${BASE_URL}/${userId}`, data)
  },
  /** 软删除用户，同时吊销其全部令牌 */
  deleteUser(userId: number) {
    return request.delete<{ message: string }>(`${BASE_URL}/${userId}`)
  },
  /** 启用/停用切换（停用即吊销令牌） */
  toggleUserStatus(userId: number) {
    return request.patch<{ message: string }>(`${BASE_URL}/${userId}/status`)
  },
  /** 踢出该用户所有已登录会话（吊销全部令牌） */
  logoutAll(userId: number) {
    return request.post<{ message: string; revoked_count: number }>(
      `${BASE_URL}/${userId}/logout-all`,
    )
  },

  // 模型配置
  /** 当前用户的模型客户端配置列表（可按 llm/embedding/rerank/asr 过滤） */
  getModelConfigs(modelType?: string) {
    return request.get<ModelConfigListResponse>(
      '/user/model-configs',
      modelType ? { model_type: modelType } : undefined,
    )
  },
  /** 平台可用模型清单（按类型分组的厂商+模型名） */
  getAvailableModels() {
    return request.get<AvailableModelsResponse>('/user/model-configs/available')
  },
  /** 平台可用模型的详细元数据（含端点/能力描述） */
  getAvailableModelDetails() {
    return request.get<AvailableModelDetail>('/user/model-configs/available/detail')
  },
  /** 单个模型客户端配置详情 */
  getModelConfig(configId: number) {
    return request.get<ModelConfig>(`/user/model-configs/${configId}`)
  },
  /** 创建模型客户端配置（API Key 后端加密存储） */
  createModelConfig(data: CreateModelConfigRequest) {
    return request.post<ModelConfig>('/user/model-configs', data)
  },
  /** 更新模型客户端配置（密钥字段留空=不修改） */
  updateModelConfig(configId: number, data: UpdateModelConfigRequest) {
    return request.put<ModelConfig>(`/user/model-configs/${configId}`, data)
  },
  /** 删除模型客户端配置 */
  deleteModelConfig(configId: number) {
    return request.delete<{ message: string }>(`/user/model-configs/${configId}`)
  },
  /** 连通性测试：向厂商发一次真实轻量请求验证配置可用 */
  testModelConfig(data: ModelConfigTestRequest) {
    return request.post<ModelConfigTestResponse>('/user/model-configs/test', data)
  },
  /** 按厂商模型名删除配置（同模型多配置清理用） */
  deleteModelConfigByModel(modelType: string, model: string) {
    return request.delete<{ message: string }>(`/user/model-configs/by-model/${modelType}/${model}`)
  },

  // 搜索引擎配置（联网搜索 provider 凭证，多租户）
  /** 已配置的搜索引擎 provider 列表（tavily/serpapi/duckduckgo 等） */
  getSearchEngineConfigs() {
    return request.get<SearchEngineConfigListResponse>('/user/search-configs')
  },
  /** 新增搜索引擎 provider 凭证 */
  createSearchEngineConfig(data: CreateSearchEngineConfigRequest) {
    return request.post<SearchEngineConfig>('/user/search-configs', data)
  },
  /** 更新搜索引擎凭证（密钥字段留空=不修改） */
  updateSearchEngineConfig(configId: number, data: UpdateSearchEngineConfigRequest) {
    return request.put<SearchEngineConfig>(`/user/search-configs/${configId}`, data)
  },
  /** 删除搜索引擎凭证 */
  deleteSearchEngineConfig(configId: number) {
    return request.delete<{ message: string }>(`/user/search-configs/${configId}`)
  },
  /** 设为主搜索源（联网搜索默认走它） */
  setSearchEnginePrimary(configId: number) {
    return request.put<SearchEngineConfig>(`/user/search-configs/${configId}/primary`)
  },
  /** 连通性测试：真实调用一次搜索验证凭证可用 */
  testSearchEngineConfig(data: SearchEngineTestRequest) {
    return request.post<SearchEngineTestResponse>('/user/search-configs/test', data)
  },

  // 密码管理
  /** 管理员重置用户密码，返回一次性临时密码 */
  adminResetPassword(userId: number) {
    return request.post<{ message: string; temp_password: string; user_id: number }>(
      `${BASE_URL}/${userId}/reset-password`,
    )
  },
  /** 本人改密（须验旧密码；改后其他会话令牌吊销） */
  changePassword(oldPassword: string, newPassword: string) {
    return request.post<{ message: string }>('/user/users/me/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  },
  /** 忘记密码：发重置邮件 */
  forgotPassword(email: string) {
    return request.post<{ message: string }>('/user/auth/forgot-password', { email })
  },
  /** 凭邮件令牌重置密码 */
  resetPassword(token: string, newPassword: string) {
    return request.post<{ message: string }>('/user/auth/reset-password', {
      token,
      new_password: newPassword,
    })
  },

  // 角色管理（列表接口返回裸数组，无 { items } 包装）
  // 角色管理（列表接口返回裸数组，无 { items } 包装）
  /** 角色列表 */
  getRoles() {
    return request.get<Role[]>('/user/roles')
  },
  /** 创建角色 */
  createRole(data: CreateRoleRequest) {
    return request.post<Role>('/user/roles', data)
  },
  /** 更新角色（含权限码集合调整） */
  updateRole(roleId: number, data: UpdateRoleRequest) {
    return request.put<Role>(`/user/roles/${roleId}`, data)
  },
  /** 删除角色（仍有用户挂靠时后端拒绝） */
  deleteRole(roleId: number) {
    return request.delete<{ message: string }>(`/user/roles/${roleId}`)
  },
  /** 全量权限码清单（角色编辑表单的可选项来源） */
  getPermissions() {
    return request.get<Permission[]>('/user/permissions')
  },
  /** 给用户分配角色 */
  assignUserRole(userId: number, data: UserRoleAssignRequest) {
    return request.put<{ message: string }>(`/user/users/${userId}/role`, data)
  },

  // 应用级权限（deny-list）
  /** 读取用户的应用级访问黑名单 */
  getUserAppAccess(userId: number) {
    return request.get<UserAppAccess>(`/user/users/${userId}/app-access`)
  },
  /** 更新用户的应用级访问黑名单 */
  updateUserAppAccess(userId: number, data: UpdateUserAppAccessRequest) {
    return request.put<UserAppAccess>(`/user/users/${userId}/app-access`, data)
  },
}
