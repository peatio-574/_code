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
// banner 场景背景图地址（课程中心等页面顶部）
const bannerBackgrounds = ref<string[]>([])

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
    const rawBackgrounds = data.homeBackgrounds ?? (data as any).home_backgrounds
    bannerBackgrounds.value = parseBackgrounds(rawBackgrounds, 'banner')
  } catch {
    // 读取失败时保留默认系统名称、无 Logo
  }
}

/**
 * 解析图片地址：完整 URL 或绝对路径原样返回，其余按文件 id 走 /api/image。
 * 兼容 <img src>、背景图等场景，避免 `/api/image//logo.png` 这类拼接错误。
 */
export function resolveImageUrl(value: string | undefined | null): string {
  const raw = (value || '').trim()
  if (!raw) return ''
  if (raw.startsWith('/') || raw.startsWith('http://') || raw.startsWith('https://')) return raw
  return `/api/image/${raw}`
}

/**
 * 解析背景配置，过滤停用项并按排序返回图片地址。
 * `scene` 为应用场景：首页(home) / banner(课程中心等顶部)，未标注的场景按首页处理。
 */
export function parseBackgrounds(raw: string | undefined, scene: 'home' | 'banner' = 'home'): string[] {
  try {
    const parsed = JSON.parse(raw || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item) => item && item.status !== 0 && item.url && (item.scene || 'home') === scene)
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
    bannerBackgrounds: computed(() => bannerBackgrounds.value),
  }
}

/** 立即应用新的系统名称与 Logo，使全站（门户顶部、控制台侧栏等）同步生效。 */
export function applySystemConfig(next: {
  systemName?: string
  logo?: string
  friendLinks?: string
  homeBackgrounds?: string
}) {
  if (typeof next.systemName === 'string' && next.systemName.trim()) {
    systemName.value = next.systemName.trim()
  }
  if (typeof next.logo === 'string') {
    logo.value = next.logo.trim()
  }
  if (typeof next.friendLinks === 'string') {
    friendLinks.value = parseFriendLinks(next.friendLinks)
  }
  if (typeof next.homeBackgrounds === 'string') {
    bannerBackgrounds.value = parseBackgrounds(next.homeBackgrounds, 'banner')
  }
}

