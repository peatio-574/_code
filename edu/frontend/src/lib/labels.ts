// 全站文案映射：角色、状态等编码到中文名称。

export const ROLE_LABELS: Record<string, string> = {
  system_admin: '超级管理员',
  principal: '校长',
  homeroom_teacher: '班主任',
  student: '学员',
}

export const ROLE_TAG_TYPE: Record<string, 'danger' | 'warning' | 'primary' | 'info'> = {
  system_admin: 'danger',
  principal: 'warning',
  homeroom_teacher: 'primary',
  student: 'info',
}

export const MEMBER_TYPE_LABELS: Record<string, string> = {
  principal: '校长',
  homeroom_teacher: '班主任',
  student: '学员',
}

export function roleLabel(code: string): string {
  return ROLE_LABELS[code] ?? code
}

export function formatDateTime(timestamp: number | undefined): string {
  if (!timestamp) return '—'
  return new Date(timestamp * 1000).toLocaleString('zh-CN', { hour12: false })
}

export function formatDate(timestamp: number | undefined): string {
  if (!timestamp) return '—'
  return new Date(timestamp * 1000).toLocaleDateString('zh-CN')
}

/** 将秒数格式化为「X 小时 Y 分」/「Y 分 SS 秒」/「SS 秒」。 */
export function formatDuration(seconds: number | undefined): string {
  const total = Math.round(seconds || 0)
  if (total <= 0) return '0 秒'
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h} 小时 ${m} 分`
  return `${m} 分 ${String(s).padStart(2, '0')} 秒`
}

// ---------------- 启用 / 禁用 统一文案 ----------------
export const STATUS_ENABLED_TEXT = '已启用'
export const STATUS_DISABLED_TEXT = '已禁用'
export const STATUS_FAILURE_TEXT = '操作失败'

/** 启用/禁用切换成功后的统一提示文案。 */
export function statusChangeMessage(next: number): string {
  return next === 1 ? STATUS_ENABLED_TEXT : STATUS_DISABLED_TEXT
}
