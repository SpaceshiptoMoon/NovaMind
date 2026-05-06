import { request } from './index'
import type {
  LoginRequest,
  LoginResponse,
  CreateUserRequest,
  UpdateUserRequest,
  User,
  ModelConfig,
  ModelConfigListResponse,
  AvailableModelsResponse,
  AvailableModelDetail,
  CreateModelConfigRequest,
  UpdateModelConfigRequest,
  ModelConfigTestRequest,
  ModelConfigTestResponse,
} from './types'

const BASE_URL = '/user/users'

export const userApi = {
  // 认证
  login(data: LoginRequest) {
    return request.post<LoginResponse>(`${BASE_URL}/login`, data)
  },
  refreshToken(refreshToken: string) {
    return request.post<LoginResponse>(`${BASE_URL}/refresh`, { refresh_token: refreshToken })
  },
  logout() {
    return request.post<{ message: string }>(`${BASE_URL}/logout`)
  },

  // 用户管理
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
    return request.post<{ message: string; revoked_count: number }>(`${BASE_URL}/${userId}/logout-all`)
  },

  // 模型配置
  getModelConfigs(modelType?: string) {
    return request.get<ModelConfigListResponse>('/user/model-configs', modelType ? { model_type: modelType } : undefined)
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
}
