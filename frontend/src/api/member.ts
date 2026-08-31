import { request } from './index'
import type {
  Member,
  MemberListResponse,
  InviteMemberRequest,
  InviteMemberResponse,
  JoinSpaceRequest,
  DirectAddMemberRequest,
  UpdateMemberRoleRequest,
  UpdateMemberPermissionsRequest,
} from './types'

export const memberApi = {
  // 获取成员列表
  getMembers(spaceId: number, params?: { skip?: number; limit?: number }) {
    return request.get<MemberListResponse>(`/spaces/${spaceId}/members`, params as Record<string, unknown>)
  },

  // 获取我的成员信息
  getMyMemberInfo(spaceId: number) {
    return request.get<Member>(`/spaces/${spaceId}/members/me`)
  },

  // 邀请成员
  inviteMember(spaceId: number, data: InviteMemberRequest) {
    return request.post<InviteMemberResponse>(
      `/spaces/${spaceId}/members`,
      data
    )
  },

  // 加入空间
  joinSpace(spaceId: number, data: JoinSpaceRequest) {
    return request.post<Member>(`/spaces/${spaceId}/members/join`, data)
  },

  // 直接添加成员（免邀请令牌，管理员按用户名/邮箱直接加为 ACTIVE）
  addMemberDirect(spaceId: number, data: DirectAddMemberRequest) {
    return request.post<Member>(`/spaces/${spaceId}/members/add`, data)
  },

  // 更新成员角色
  updateMemberRole(
    spaceId: number,
    targetUserId: number,
    data: UpdateMemberRoleRequest
  ) {
    return request.put<Member>(
      `/spaces/${spaceId}/members/${targetUserId}`,
      data
    )
  },

  // 更新成员细粒度权限（custom_permissions 全量替换）
  updateMemberPermissions(
    spaceId: number,
    targetUserId: number,
    data: UpdateMemberPermissionsRequest
  ) {
    return request.put<Member>(
      `/spaces/${spaceId}/members/${targetUserId}/permissions`,
      data
    )
  },

  // 移除成员
  removeMember(spaceId: number, targetUserId: number) {
    return request.delete<{ success: boolean; message: string }>(
      `/spaces/${spaceId}/members/${targetUserId}`
    )
  },

  // 离开空间
  leaveSpace(spaceId: number) {
    return request.post<{ success: boolean; message: string }>(`/spaces/${spaceId}/members/leave`)
  },
}
