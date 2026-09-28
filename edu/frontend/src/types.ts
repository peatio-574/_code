// 共享类型定义与前端权限码常量。
export type DataScope = 'self' | 'direct' | 'tree' | 'all'

export interface ApiResult<T> {
  success: boolean
  code: string
  message: string
  data?: T
}

export interface AuthUser {
  id: number
  username: string
  display_name: string
  avatar: string
  mobile?: string
  role: string
  roles: string[]
  permissions: string[]
  data_scope: DataScope
  csrf_token?: string | null
}

export const PERMISSIONS = {
  dashboardView: 'console.dashboard.view',
  teacherManage: 'console.teachers.manage',
  administratorManage: 'console.administrators.manage',
  studentManage: 'console.students.manage',
  courseManage: 'console.courses.manage',
  announcementManage: 'console.announcements.manage',
  questionManage: 'console.questions.manage',
  examView: 'console.exams.view',
  examCompose: 'console.exams.compose',
  examManage: 'console.exams.manage',
  systemManage: 'console.system.manage',
  campusView: 'console.campuses.view',
  campusManage: 'console.campuses.manage',
  campusMembersManage: 'console.campus_members.manage',
  dictionaryManage: 'console.dictionaries.manage',
  rolesManage: 'console.roles.manage',
} as const
