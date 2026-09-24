// 控制台接口封装：总览、课程、题库、考试、教师、校区、管理员、学员、公告、字典、配置、报表、文件。
import { api } from '@/lib/api'
import type { ApiResult } from '@/types'
import type { PageData } from './portal'

type Params = Record<string, unknown>

async function getData<T>(url: string, params?: Params): Promise<T> {
  const response = await api.get<ApiResult<T>>(url, { params })
  return response.data.data as unknown as T
}

async function send<T = any>(method: 'post' | 'put' | 'delete', url: string, body?: unknown): Promise<ApiResult<T>> {
  const response = await api[method]<ApiResult<T>>(url, body)
  return response.data
}

export { getData, send }

// ---------------- 总览 ----------------
export const getDashboard = () => getData<Record<string, any>>('/api/admin/dashboard')

// ---------------- 课程 ----------------
export const listCourses = (params?: Params) => getData<PageData<any>>('/api/admin/courses', params)
export const getCourse = (id: number) => getData<Record<string, any>>(`/api/admin/course/${id}`)
export const createCourse = (body: unknown) => send('post', '/api/admin/course', body)
export const updateCourse = (body: unknown) => send('put', '/api/admin/course', body)
export const deleteCourse = (id: number) => send('delete', `/api/admin/course/${id}`)
export const toggleCourse = (id: number, status: number) => send('post', '/api/admin/course/toggle-status', { id, status })
export const batchDeleteCourses = (ids: number[]) => send('post', '/api/admin/courses/batch-delete', { ids })
export const createChapter = (courseId: number, body: unknown) => send('post', `/api/admin/course/${courseId}/chapter`, body)
export const updateChapter = (courseId: number, chapterId: number, body: unknown) =>
  send('put', `/api/admin/course/${courseId}/chapter/${chapterId}`, body)
export const deleteChapter = (courseId: number, chapterId: number) =>
  send('delete', `/api/admin/course/${courseId}/chapter/${chapterId}`)

// ---------------- 题库 ----------------
export const listQuestions = (params?: Params) => getData<PageData<any>>('/api/admin/questions', params)
export const getQuestion = (id: number) => getData<Record<string, any>>(`/api/admin/question/${id}`)
export const createQuestion = (body: unknown) => send('post', '/api/admin/question', body)
export const updateQuestion = (body: unknown) => send('put', '/api/admin/question', body)
export const deleteQuestion = (id: number) => send('delete', `/api/admin/question/${id}`)
export const toggleQuestion = (id: number, status: number) =>
  send('post', '/api/admin/question/toggle-status', { id, status })
export const batchDeleteQuestions = (ids: number[]) => send('post', '/api/admin/questions/batch-delete', { ids })
export const listQuestionCategories = () => getData<{ items: any[] }>('/api/admin/question-categories')
export const createQuestionCategory = (body: unknown) => send('post', '/api/admin/question-category', body)
export const updateQuestionCategory = (body: unknown) => send('put', '/api/admin/question-category', body)
export const deleteQuestionCategory = (id: number) => send('delete', `/api/admin/question-category/${id}`)

// ---------------- 考试 ----------------
export const listExams = (params?: Params) => getData<PageData<any>>('/api/admin/exams', params)
export const getExam = (id: number) => getData<Record<string, any>>(`/api/admin/exam/${id}`)
export const createExam = (body: unknown) => send('post', '/api/admin/exam', body)
export const updateExam = (id: number, body: unknown) => send('put', `/api/admin/exam/${id}`, body)
export const deleteExam = (id: number) => send('delete', `/api/admin/exam/${id}`)
export const batchDeleteExams = (ids: number[]) => send('post', '/api/admin/exams/batch-delete', { ids })
export const publishExam = (id: number) => send('post', `/api/admin/exam/${id}/publish`)
export const withdrawExam = (id: number) => send('post', `/api/admin/exam/${id}/withdraw`)
export const listExamAttempts = (params?: Params) => getData<PageData<any>>('/api/admin/exam-attempts', params)

// ---------------- 教师 ----------------
export const listTeachers = (params?: Params) => getData<PageData<any>>('/api/admin/teachers', params)
export const createTeacher = (body: unknown) => send('post', '/api/admin/teacher', body)
export const updateTeacher = (body: unknown) => send('put', '/api/admin/teacher', body)
export const deleteTeacher = (id: number) => send('delete', `/api/admin/teacher/${id}`)
export const toggleTeacher = (id: number, status: number) => send('post', '/api/admin/teacher/toggle-status', { id, status })

// ---------------- 校区 ----------------
export const listCampuses = (params?: Params) => getData<PageData<any>>('/api/admin/campuses', params)
export const createCampus = (body: unknown) => send('post', '/api/admin/campuses', body)
export const updateCampus = (id: number, body: unknown) => send('put', `/api/admin/campuses/${id}`, body)
export const toggleCampus = (id: number) => send('post', `/api/admin/campuses/${id}/toggle-status`)
export const deleteCampus = (id: number) => send('delete', `/api/admin/campuses/${id}`)
export const listCampusMembers = (id: number) => getData<{ items: any[] }>(`/api/admin/campuses/${id}/members`)
export const addCampusMember = (id: number, body: unknown) => send('post', `/api/admin/campuses/${id}/members`, body)
export const updateCampusMember = (id: number, userId: number, body: unknown) =>
  send('put', `/api/admin/campuses/${id}/members/${userId}`, body)
export const deleteCampusMember = (id: number, userId: number) =>
  send('delete', `/api/admin/campuses/${id}/members/${userId}`)

// ---------------- 管理员 / 学员 ----------------
export const listAdmins = (params?: Params) => getData<PageData<any>>('/api/admin/users', params)
export const createAdmin = (body: unknown) => send('post', '/api/admin/user', body)
export const updateAdmin = (body: unknown) => send('put', '/api/admin/user', body)
export const deleteAdmin = (id: number, verify?: { name?: string; phone?: string }) =>
  send('delete', `/api/admin/user/${id}`, undefined)
export const toggleAdmin = (id: number, status: number) => send('post', '/api/admin/user/toggle-status', { id, status })
export const resetAdminPassword = (id: number, password: string) =>
  send('post', '/api/admin/user/reset-password', { id, password })

export const listStudents = (params?: Params) => getData<PageData<any>>('/api/admin/students', params)
export const createStudent = (body: unknown) => send('post', '/api/admin/student', body)
export const updateStudent = (body: unknown) => send('put', '/api/admin/student', body)
export const deleteStudent = (id: number) => send('delete', `/api/admin/student/${id}`)
export const toggleStudent = (id: number, status: number) => send('post', '/api/admin/student/toggle-status', { id, status })

export const listHierarchy = () => getData<{ items: any[]; manager_options: any[] }>('/api/admin/user-hierarchy')
export const updateManager = (userId: number, managerId: number | null) =>
  send('put', `/api/admin/user-hierarchy/${userId}`, { manager_id: managerId })

// ---------------- 公告 ----------------
export const listAnnouncements = (params?: Params) => getData<PageData<any>>('/api/admin/announcements', params)
export const createAnnouncement = (body: unknown) => send('post', '/api/admin/announcement', body)
export const updateAnnouncement = (body: unknown) => send('put', '/api/admin/announcement', body)
export const deleteAnnouncement = (id: number) => send('delete', `/api/admin/announcement/${id}`)
export const toggleAnnouncementStatus = (id: number, status: number) =>
  send('post', '/api/admin/announcement/toggle-status', { id, status })
export const toggleAnnouncementTop = (id: number, top: number) =>
  send('post', '/api/admin/announcement/toggle-top', { id, top })

// ---------------- 字典 ----------------
export const listDictionaryTypes = () => getData<{ items: any[] }>('/api/admin/dictionary-types')
export const createDictionaryType = (body: unknown) => send('post', '/api/admin/dictionary-types', body)
export const updateDictionaryType = (id: number, body: unknown) => send('put', `/api/admin/dictionary-types/${id}`, body)
export const deleteDictionaryType = (id: number) => send('delete', `/api/admin/dictionary-types/${id}`)
export const batchDeleteDictionaryTypes = (ids: number[]) =>
  send('post', '/api/admin/dictionary-types/batch-delete', { ids })
export const toggleDictionaryType = (id: number, status: number) =>
  send('post', '/api/admin/dictionary-types/toggle-status', { id, status })
export const listDictionaryItems = (typeId: number) => getData<{ items: any[] }>(`/api/admin/dictionary-types/${typeId}/items`)
export const createDictionaryItem = (body: unknown) => send('post', '/api/admin/dictionary-items', body)
export const updateDictionaryItem = (id: number, body: unknown) => send('put', `/api/admin/dictionary-items/${id}`, body)
export const deleteDictionaryItem = (id: number) => send('delete', `/api/admin/dictionary-items/${id}`)
export const toggleDictionaryItem = (id: number, status: number) =>
  send('post', '/api/admin/dictionary-items/toggle-status', { id, status })
export const reorderDictionaryItems = (ids: number[]) => send('post', '/api/admin/dictionary-items/reorder', { ids })

// ---------------- 系统配置 ----------------
export const getAdminConfig = () => getData<Record<string, string>>('/api/system/config')
export const saveConfig = (body: unknown) => send('put', '/api/admin/system/config', body)
export const saveHomeBanners = (body: unknown[]) => send('put', '/api/admin/home-banners', body)

// ---------------- 报表 ----------------
export const listLearningRecords = (params?: Params) => getData<PageData<any>>('/api/admin/learning-records', params)
export const getStudentStatistics = () => getData<Record<string, number>>('/api/admin/statistics/students')
