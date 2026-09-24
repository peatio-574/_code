/**
 * 认证状态（Pinia）。
 *
 * 保存当前用户及其角色/权限/数据范围，提供登录、加载自身、退出能力。
 * 是否为管理员以角色判断；权限判断统一走 lib/rbac。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { fetchSelf, login as loginApi, logout as logoutApi } from '@/api/auth'
import type { AuthUser } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  // 当前登录用户；null 表示未登录
  const user = ref<AuthUser | null>(null)
  // 是否已完成一次会话加载（避免重复请求 /api/user/self）
  const loaded = ref(false)

  const isAuthenticated = computed(() => user.value !== null)
  // 管理员/超管可进入控制台
  const isAdmin = computed(() => {
    const roles = user.value?.roles ?? []
    return roles.includes('system_admin') || roles.includes('principal') || roles.includes('homeroom_teacher')
  })

  /** 判断当前用户是否拥有指定权限码。 */
  function hasPermission(permission: string): boolean {
    return user.value?.permissions?.includes(permission) ?? false
  }

  /** 登录：成功则写入用户信息。 */
  async function login(username: string, password: string) {
    const result = await loginApi(username, password)
    if (result.success) {
      user.value = result.data ?? null
    }
    loaded.value = true
    return result
  }

  /** 从后端加载当前会话用户（刷新页面时恢复登录态）；未登录时置空。 */
  async function loadSelf() {
    try {
      user.value = await fetchSelf()
    } catch {
      user.value = null
    } finally {
      loaded.value = true
    }
    return user.value
  }

  /** 退出登录：无论接口是否成功都清空本地用户。 */
  async function logout() {
    try {
      await logoutApi()
    } finally {
      user.value = null
    }
  }

  return { user, loaded, isAuthenticated, isAdmin, hasPermission, login, loadSelf, logout }
})
