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

/**
 * member API
 *
 * 空间成员：邀请/加入/直加、角色与细粒度权限、移除与退出
 */
export const memberApi = {
  // 获取成员列表
  /** 空间成员列表（分页） */
  getMembers(spaceId: number, params?: { skip?: number; limit?: number }) {
    return request.get<MemberListResponse>(
      `/spaces/${spaceId}/members`,
      params as Record<string, unknown>,
    )
  },

  // 获取我的成员信息
  /** 当前用户在该空间的成员身份（角色/状态/细粒度权限） */
  getMyMemberInfo(spaceId: number) {
    return request.get<Member>(`/spaces/${spaceId}/members/me`)
  },

  // 邀请成员
  /** 生成邀请（返回一次性 invite_token 与过期时间） */
  inviteMember(spaceId: number, data: InviteMemberRequest) {
    return request.post<InviteMemberResponse>(`/spaces/${spaceId}/members`, data)
  },

  // 加入空间
  /** 凭 invite_token 加入空间 */
  joinSpace(spaceId: number, data: JoinSpaceRequest) {
    return request.post<Member>(`/spaces/${spaceId}/members/join`, data)
  },

  // 直接添加成员（免邀请令牌，管理员按用户名/邮箱直接加为 ACTIVE）
  /** 管理员按邮箱/用户名直加成员（跳过邀请流程，直接 ACTIVE） */
  addMemberDirect(spaceId: number, data: DirectAddMemberRequest) {
    return request.post<Member>(`/spaces/${spaceId}/members/add`, data)
  },

  // 更新成员角色
  /** 修改目标成员角色（VIEWER/EDITOR/ADMIN） */
  updateMemberRole(spaceId: number, targetUserId: number, data: UpdateMemberRoleRequest) {
    return request.put<Member>(`/spaces/${spaceId}/members/${targetUserId}`, data)
  },

  // 更新成员细粒度权限（custom_permissions 全量替换）
  /** 覆盖式更新成员自定义权限（resource→action→bool，未列项回退角色默认） */
  updateMemberPermissions(
    spaceId: number,
    targetUserId: number,
    data: UpdateMemberPermissionsRequest,
  ) {
    return request.put<Member>(`/spaces/${spaceId}/members/${targetUserId}/permissions`, data)
  },

  // 移除成员
  /** 将成员移出空间 */
  removeMember(spaceId: number, targetUserId: number) {
    return request.delete<{ success: boolean; message: string }>(
      `/spaces/${spaceId}/members/${targetUserId}`,
    )
  },

  // 离开空间
  /** 当前用户主动退出空间 */
  leaveSpace(spaceId: number) {
    return request.post<{ success: boolean; message: string }>(`/spaces/${spaceId}/members/leave`)
  },
}
