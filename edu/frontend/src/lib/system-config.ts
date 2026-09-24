// 系统配置读取（模块级缓存）：供顶部品牌栏等处展示系统名称与 Logo。
import { computed, ref } from 'vue'

import { api } from '@/lib/api'
import type { ApiResult } from '@/types'

export interface FriendLink {
  name: string
  url: string
}

const systemName = ref('聘书云课堂')
const logo = ref('')
const friendLinks = ref<FriendLink[]>([])

let loaded = false
let pending: Promise<void> | null = null

async function loadConfig(): Promise<void> {
  try {
    const response = await api.get<ApiResult<Record<string, string>>>('/api/system/config')
    const data = response.data.data ?? {}
    if (data.systemName?.trim()) {
      systemName.value = data.systemName.trim()
    }
    logo.value = data.logo?.trim() ?? ''
    friendLinks.value = parseFriendLinks(data.friendLinks)
  } catch {
    // 读取失败时保留默认系统名称、无 Logo
  }
}

/** 解析首页背景配置，过滤停用项并按排序返回图片地址。 */
export function parseBackgrounds(raw: string | undefined): string[] {
  try {
    const parsed = JSON.parse(raw || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item) => item && item.status !== 0 && item.url)
      .sort((a, b) => (a.sort || 0) - (b.sort || 0))
      .map((item) => item.url)
  } catch {
    return []
  }
}

/** 解析友情链接配置，过滤停用项并按排序排列。 */
export function parseFriendLinks(raw: string | undefined): FriendLink[] {
  try {
    const parsed = JSON.parse(raw || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item) => item && item.status !== 0 && item.url)
      .sort((a, b) => (a.sort || 0) - (b.sort || 0))
      .map((item) => ({ name: item.name || item.url, url: item.url }))
  } catch {
    return []
  }
}

/** 获取系统名称、Logo 与友情链接；首次调用触发加载，之后复用缓存。 */
export function useSystemConfig() {
  if (!loaded && !pending) {
    pending = loadConfig().finally(() => {
      loaded = true
      pending = null
    })
  }
  return {
    systemName,
    logo,
    friendLinks: computed(() => friendLinks.value),
  }
}

/** 立即应用新的系统名称与 Logo，使全站（门户顶部、控制台侧栏等）同步生效。 */
export function applySystemConfig(next: { systemName?: string; logo?: string; friendLinks?: string }) {
  if (typeof next.systemName === 'string' && next.systemName.trim()) {
    systemName.value = next.systemName.trim()
  }
  if (typeof next.logo === 'string') {
    logo.value = next.logo.trim()
  }
  if (typeof next.friendLinks === 'string') {
    friendLinks.value = parseFriendLinks(next.friendLinks)
  }
}

/** 重新从服务端拉取系统配置并更新全站。 */
export async function refreshSystemConfig() {
  loaded = true
  await loadConfig()
}
