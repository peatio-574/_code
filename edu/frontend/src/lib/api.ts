/**
 * Axios 实例与全局拦截器。
 *
 * - 所有请求携带 Cookie 会话（withCredentials）。
 * - 写请求自动附带 CSRF 令牌（从 XSRF-TOKEN Cookie 读取）。
 * - 收到 401 时跳转登录页（登录页本身除外）。
 */
import axios from 'axios'

export const api = axios.create({
  baseURL: '/',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

/** 读取指定的浏览器 Cookie 值。 */
function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

// 请求拦截：写操作自动带上 CSRF 令牌
api.interceptors.request.use((config) => {
  const method = (config.method || 'get').toUpperCase()
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const token = readCookie('XSRF-TOKEN')
    if (token) {
      config.headers.set('x-csrf-token', token)
    }
  }
  return config
})

// 未登录探测接口：401 属于正常状态，由 auth store / 路由守卫处理，不触发跳转
const SESSION_PROBE_PATHS = ['/api/user/self', '/api/user/me']

// 响应拦截：仅在受保护请求会话失效时跳转登录
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const url: string = error.config?.url ?? ''
    const isProbe = SESSION_PROBE_PATHS.some((path) => url.includes(path))
    if (
      error.response?.status === 401 &&
      !isProbe &&
      !window.location.pathname.startsWith('/login')
    ) {
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

/** 把接口异常转换为可展示的中文提示。 */
export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    return (error.response?.data as { message?: string } | undefined)?.message || '请求失败'
  }
  return '请求失败'
}
