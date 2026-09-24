// 门户端接口封装：系统配置、课程、学习、题库、考试。
import { api } from '@/lib/api'
import type { ApiResult } from '@/types'

export interface PageData<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export async function getSystemConfig() {
  const response = await api.get<ApiResult<Record<string, string>>>('/api/system/config')
  return response.data.data as any ?? {}
}

export async function getAbout() {
  const response = await api.get<ApiResult<string>>('/api/about')
  return response.data.data as any ?? ''
}

export async function getCourses(params: {
  p?: number
  page_size?: number
  keyword?: string
  course_type_code?: string[]
}) {
  const query = new URLSearchParams()
  query.set('p', String(params.p ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.keyword) query.set('keyword', params.keyword)
  for (const code of params.course_type_code ?? []) query.append('course_type_code', code)
  const response = await api.get<ApiResult<PageData<Record<string, unknown>>>>(`/api/course/?${query.toString()}`)
  return response.data.data as any
}

export async function getCourseDetail(courseId: number) {
  const response = await api.get<ApiResult<Record<string, any>>>(`/api/course/${courseId}`)
  return response.data.data as any
}

export async function getCourseTypes() {
  const response = await api.get<ApiResult<{ items: { id: number; code: string; name: string }[] }>>(
    '/api/dictionaries/course_type/items',
  )
  return response.data.data?.items ?? []
}

export async function getQuestionTypes() {
  const response = await api.get<ApiResult<{ items: { id: number; code: string; name: string }[] }>>(
    '/api/dictionaries/question_type/items',
  )
  return response.data.data?.items ?? []
}

export async function getLearningOverview() {
  const response = await api.get<ApiResult<Record<string, any>>>('/api/learning/overview')
  return response.data.data as any
}

export async function startLearning(courseId: number) {
  const response = await api.post<ApiResult<Record<string, unknown>>>('/api/learning/start', { course_id: courseId })
  return response.data
}

export async function getWatchProgress(courseId: number) {
  const response = await api.get<ApiResult<Record<string, any>>>('/api/learning/progress', {
    params: { course_id: courseId },
  })
  return response.data.data as any
}

export async function watchStart(payload: { course_id: number; chapter_id: number; client_session_id: string }) {
  const response = await api.post<ApiResult<Record<string, any>>>('/api/learning/watch/start', payload)
  return response.data.data as any
}

export async function watchProgress(payload: {
  watch_session_id: number
  position_seconds: number
  video_duration_seconds: number
  sequence: number
  event: string
}) {
  const response = await api.post<ApiResult<Record<string, any>>>('/api/learning/watch/progress', payload)
  return response.data.data as any
}

export async function watchFinish(payload: { watch_session_id: number; position_seconds?: number }) {
  const response = await api.post<ApiResult<Record<string, any>>>('/api/learning/watch/finish', payload)
  return response.data.data as any
}

// ---------------- 题库 ----------------

export async function getQuestionCategories() {
  const response = await api.get<ApiResult<{ items: { id: number; name: string }[] }>>('/api/question-categories')
  return response.data.data?.items ?? []
}

export async function getRandomQuestion(params: { type: string; category_id?: number[] }) {
  const query = new URLSearchParams()
  query.set('type', params.type)
  for (const id of params.category_id ?? []) query.append('category_id', String(id))
  const response = await api.get<ApiResult<Record<string, any>>>(`/api/questions/random?${query.toString()}`)
  return response.data.data as any
}

export async function submitPracticeAnswer(payload: { question_id: number; answer: string; category_id?: number }) {
  const response = await api.post<ApiResult<Record<string, any>>>('/api/questions/answer', payload)
  return response.data
}

export async function getPracticeStatistics() {
  const response = await api.get<ApiResult<Record<string, number>>>('/api/questions/statistics')
  return response.data.data as any
}

export async function getWrongQuestions(params: { p?: number; page_size?: number }) {
  const response = await api.get<ApiResult<PageData<Record<string, unknown>>>>('/api/questions/wrong', { params })
  return response.data.data as any
}

export async function getWrongDetail(questionId: number) {
  const response = await api.get<ApiResult<Record<string, any>>>(`/api/questions/wrong/${questionId}`)
  return response.data.data as any
}

export async function startWrongRetry() {
  const response = await api.post<ApiResult<Record<string, any>>>('/api/questions/wrong/retry/start')
  return response.data
}

export async function submitWrongRetry(payload: { attempt_id: number; question_id: number; answer: string }) {
  const response = await api.post<ApiResult<Record<string, any>>>('/api/questions/wrong/retry/answer', payload)
  return response.data
}

export async function restartPractice() {
  const response = await api.post<ApiResult<Record<string, unknown>>>('/api/questions/restart')
  return response.data
}

// ---------------- 考试 ----------------

export async function getAvailableExams() {
  const response = await api.get<ApiResult<{ items: Record<string, unknown>[] }>>('/api/exams/available')
  return response.data.data?.items ?? []
}

export async function getExamStatistics() {
  const response = await api.get<ApiResult<Record<string, number>>>('/api/exams/statistics')
  return response.data.data as any
}

export async function getExamHistory() {
  const response = await api.get<ApiResult<{ items: Record<string, any>[] }>>('/api/exams/history')
  return response.data.data?.items ?? []
}

export async function startExamAttempt(examId: number) {
  const response = await api.post<ApiResult<Record<string, any>>>(`/api/exams/${examId}/attempt`)
  return response.data
}

export async function startMockExam() {
  const response = await api.post<ApiResult<Record<string, any>>>('/api/exams/mock')
  return response.data
}

export async function saveExamAnswers(payload: { attempt_id: number; answers: { question_id: number; answer: string }[] }) {
  const response = await api.post<ApiResult<Record<string, any>>>('/api/exams/answers', payload)
  return response.data
}

export async function submitExam(payload: { attempt_id: number; answers: { question_id: number; answer: string }[] }) {
  const response = await api.post<ApiResult<Record<string, any>>>('/api/exams/submit', payload)
  return response.data
}

export async function getExamResult(attemptId: number) {
  const response = await api.get<ApiResult<Record<string, any>>>('/api/exams/result', { params: { attempt_id: attemptId } })
  return response.data.data as any
}

// ---------------- 公告 ----------------

export async function getPublicAnnouncements(pageSize = 5) {
  const response = await api.get<ApiResult<PageData<Record<string, any>>>>('/api/announcements/', {
    params: { p: 1, page_size: pageSize },
  })
  return response.data.data?.items ?? []
}

/** 将当前用户对指定公告的阅读状态上报服务端（幂等）。 */
export async function markAnnouncementsRead(ids: number[]) {
  if (!ids.length) return
  await api.post('/api/announcement/read', { ids })
}
