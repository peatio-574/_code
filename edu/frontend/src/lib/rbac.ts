/**
 * 前端权限工具。
 *
 * 仅用于控制菜单、按钮与路由体验，最终授权以后端返回的 403 为准。
 */
import type { AuthUser } from '@/types'

export { PERMISSIONS } from '@/types'

/** 用户是否拥有指定权限码。 */
export function hasPermission(user: AuthUser | null | undefined, permission: string): boolean {
  return user?.permissions?.includes(permission) ?? false
}

/** 用户是否拥有其中任一权限码。 */
export function hasAnyPermission(
  user: AuthUser | null | undefined,
  permissions: readonly string[],
): boolean {
  return permissions.some((permission) => hasPermission(user, permission))
}

/** 用户是否拥有指定角色。 */
export function hasRole(user: AuthUser | null | undefined, role: string): boolean {
  return user?.roles?.includes(role) ?? user?.role === role
}
