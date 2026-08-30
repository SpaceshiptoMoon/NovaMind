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

export const userApi = {
  // 认证
  login(data: LoginRequest) {
    return request.post<LoginResponse>(`${BASE_URL}/login`, data)
  },
  register(data: RegisterRequest) {
    return request.post<LoginResponse>(`${BASE_URL}/register`, data)
  },
  refreshToken(refreshToken: string) {
    return request.post<LoginResponse>(`${BASE_URL}/refresh`, { refresh_token: refreshToken })
  },
  logout(refreshToken?: string) {
    return request.post<{ message: string }>(`${BASE_URL}/logout`, refreshToken ? { refresh_token: refreshToken } : undefined)
  },

  // 用户管理
  getMyPermissions() {
    return request.get<MyPermissionsResponse>(`${BASE_URL}/me/permissions`)
  },
  getUsers(params?: { skip?: number; limit?: number }) {
    return request.get<User[]>(BASE_URL, params)
  },
  getUser(userId: number) {
    return request.get<User>(`${BASE_URL}/${userId}`)
  },
  createUser(data: CreateUserRequest) {
    return request.post<User>(BASE_URL, data)
  },
  updateUser(userId: number, data: UpdateUserRequest) {
    return request.put<User>(`${BASE_URL}/${userId}`, data)
  },
  deleteUser(userId: number) {
    return request.delete<{ message: string }>(`${BASE_URL}/${userId}`)
  },
  toggleUserStatus(userId: number) {
    return request.patch<{ message: string }>(`${BASE_URL}/${userId}/status`)
  },
  logoutAll(userId: number) {
    return request.post<{ message: string; revoked_count: number }>(
      `${BASE_URL}/${userId}/logout-all`,
    )
  },

  // 模型配置
  getModelConfigs(modelType?: string) {
    return request.get<ModelConfigListResponse>(
      '/user/model-configs',
      modelType ? { model_type: modelType } : undefined,
    )
  },
  getAvailableModels() {
    return request.get<AvailableModelsResponse>('/user/model-configs/available')
  },
  getAvailableModelDetails() {
    return request.get<AvailableModelDetail>('/user/model-configs/available/detail')
  },
  getModelConfig(configId: number) {
    return request.get<ModelConfig>(`/user/model-configs/${configId}`)
  },
  createModelConfig(data: CreateModelConfigRequest) {
    return request.post<ModelConfig>('/user/model-configs', data)
  },
  updateModelConfig(configId: number, data: UpdateModelConfigRequest) {
    return request.put<ModelConfig>(`/user/model-configs/${configId}`, data)
  },
  deleteModelConfig(configId: number) {
    return request.delete<{ message: string }>(`/user/model-configs/${configId}`)
  },
  testModelConfig(data: ModelConfigTestRequest) {
    return request.post<ModelConfigTestResponse>('/user/model-configs/test', data)
  },
  deleteModelConfigByModel(modelType: string, model: string) {
    return request.delete<{ message: string }>(`/user/model-configs/by-model/${modelType}/${model}`)
  },

  // 搜索引擎配置（联网搜索 provider 凭证，多租户）
  getSearchEngineConfigs() {
    return request.get<SearchEngineConfigListResponse>('/user/search-configs')
  },
  createSearchEngineConfig(data: CreateSearchEngineConfigRequest) {
    return request.post<SearchEngineConfig>('/user/search-configs', data)
  },
  updateSearchEngineConfig(configId: number, data: UpdateSearchEngineConfigRequest) {
    return request.put<SearchEngineConfig>(`/user/search-configs/${configId}`, data)
  },
  deleteSearchEngineConfig(configId: number) {
    return request.delete<{ message: string }>(`/user/search-configs/${configId}`)
  },
  setSearchEnginePrimary(configId: number) {
    return request.put<SearchEngineConfig>(`/user/search-configs/${configId}/primary`)
  },
  testSearchEngineConfig(data: SearchEngineTestRequest) {
    return request.post<SearchEngineTestResponse>('/user/search-configs/test', data)
  },

  // 密码管理
  adminResetPassword(userId: number) {
    return request.post<{ message: string; temp_password: string; user_id: number }>(
      `${BASE_URL}/${userId}/reset-password`,
    )
  },
  changePassword(oldPassword: string, newPassword: string) {
    return request.post<{ message: string }>('/user/users/me/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  },
  forgotPassword(email: string) {
    return request.post<{ message: string }>('/user/auth/forgot-password', { email })
  },
  resetPassword(token: string, newPassword: string) {
    return request.post<{ message: string }>('/user/auth/reset-password', {
      token,
      new_password: newPassword,
    })
  },

  // 角色管理（列表接口返回裸数组，无 { items } 包装）
  getRoles() {
    return request.get<Role[]>('/user/roles')
  },
  createRole(data: CreateRoleRequest) {
    return request.post<Role>('/user/roles', data)
  },
  updateRole(roleId: number, data: UpdateRoleRequest) {
    return request.put<Role>(`/user/roles/${roleId}`, data)
  },
  deleteRole(roleId: number) {
    return request.delete<{ message: string }>(`/user/roles/${roleId}`)
  },
  getPermissions() {
    return request.get<Permission[]>('/user/permissions')
  },
  assignUserRole(userId: number, data: UserRoleAssignRequest) {
    return request.put<{ message: string }>(`/user/users/${userId}/role`, data)
  },

  // 应用级权限（deny-list）
  getUserAppAccess(userId: number) {
    return request.get<UserAppAccess>(`/user/users/${userId}/app-access`)
  },
  updateUserAppAccess(userId: number, data: UpdateUserAppAccessRequest) {
    return request.put<UserAppAccess>(`/user/users/${userId}/app-access`, data)
  },
}
