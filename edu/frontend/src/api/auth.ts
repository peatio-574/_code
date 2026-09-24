// 认证/个人中心/角色权限接口封装。
import { api } from '@/lib/api'
import type { ApiResult, AuthUser, DataScope } from '@/types'

export interface RoleItem {
  id: number
  code: string
  name: string
  description: string
  data_scope: DataScope
  level: number
  built_in: boolean
  status: number
  created_at: number
  updated_at: number
  permission_codes: string[]
}

export interface PermissionItem {
  id: number
  code: string
  name: string
  description: string
  module: string
  built_in: boolean
  status: number
}

export async function login(username: string, password: string) {
  const response = await api.post<ApiResult<AuthUser>>('/api/login', { username, password })
  return response.data
}

export async function logout() {
  await api.post('/api/logout')
}

/**
 * 获取当前登录用户。
 *
 * 未登录（401）属于正常状态而非错误，这里直接返回 null，
 * 避免路由守卫因异常中断导航导致页面空白。
 */
export async function fetchSelf() {
  try {
    const response = await api.get<ApiResult<AuthUser>>('/api/user/self')
    return response.data.data ?? null
  } catch {
    return null
  }
}

export async function updateProfile(payload: { display_name?: string; mobile?: string; avatar?: string }) {
  const response = await api.put<ApiResult<{ id: number }>>('/api/user/profile', payload)
  return response.data
}

export async function changePassword(payload: { old_password: string; new_password: string; confirm_password: string }) {
  const response = await api.post<ApiResult<{ id: number }>>('/api/user/change-password', payload)
  return response.data
}

export async function getRoles() {
  const response = await api.get<ApiResult<{ items: RoleItem[] }>>('/api/admin/rbac/roles')
  return response.data.data?.items ?? []
}

export async function getPermissions() {
  const response = await api.get<ApiResult<{ items: PermissionItem[] }>>('/api/admin/rbac/permissions')
  return response.data.data?.items ?? []
}

export async function updateRole(
  id: number,
  input: { name: string; description: string; data_scope: string; level: number; status: number },
) {
  const response = await api.put<ApiResult<{ id: number }>>(`/api/admin/rbac/roles/${id}`, input)
  return response.data
}

export async function setRolePermissions(id: number, permissionCodes: string[]) {
  const response = await api.put<ApiResult<{ id: number }>>(`/api/admin/rbac/roles/${id}/permissions`, {
    permission_codes: permissionCodes,
  })
  return response.data
}

export async function createRole(input: {
  code: string
  name: string
  description: string
  data_scope: string
  level: number
  status: number
}) {
  const response = await api.post<ApiResult<RoleItem>>('/api/admin/rbac/roles', input)
  return response.data
}

export async function deleteRole(id: number) {
  const response = await api.delete<ApiResult<{ id: number }>>(`/api/admin/rbac/roles/${id}`)
  return response.data
}
