/**
 * 大文件分片上传。
 *
 * 与后端 /api/file/upload/init|chunk|complete 对接：
 * 1. init   ：登记上传会话，命中相同 md5+size 的已存在文件时秒传；
 * 2. chunk  ：逐片上传（默认 4MB/片，串行 + 失败重试）；
 * 3. complete：按序合并分片，写入 files 表并返回文件 id。
 *
 * 说明：单文件接口上限 30MB，视频等大文件一律走此分片流程。
 */
import { api, errorMessage } from '@/lib/api'
import type { ApiResult } from '@/types'

export interface UploadedFile {
  id: string
  name: string
  size: number
  type: string
  md5: string
  status: number
}

export interface UploadProgress {
  /** 0-100 */
  percent: number
  /** 已上传字节 */
  loaded: number
  /** 总字节 */
  total: number
  /** 当前分片序号（从 1 开始） */
  part: number
  /** 总分片数 */
  parts: number
}

export interface ChunkUploadOptions {
  /** 分片大小（字节），默认 4MB */
  chunkSize?: number
  /** 每个分片失败后的最大重试次数，默认 2 */
  maxRetries?: number
  /** 进度回调 */
  onProgress?: (progress: UploadProgress) => void
  /** 取消信号 */
  signal?: AbortSignal
}

const DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024

/** 计算分片数量（至少 1）。 */
function chunkCount(size: number, chunkSize: number): number {
  return Math.max(1, Math.ceil(size / chunkSize))
}

/** 单次 HTTP 错误转为可读文案。 */
function fail(error: unknown): never {
  throw new Error(errorMessage(error))
}

/**
 * 分片上传单个文件，返回服务端文件信息。
 * 小文件（<= chunkSize）也会走 init+chunk+complete，行为一致。
 */
export async function uploadFileInChunks(file: File, options: ChunkUploadOptions = {}): Promise<UploadedFile> {
  const chunkSize = options.chunkSize ?? DEFAULT_CHUNK_SIZE
  const maxRetries = options.maxRetries ?? 2
  const totalParts = chunkCount(file.size, chunkSize)

  // 1. 初始化上传会话
  const initResponse = await api
    .post<ApiResult<{ id: string; exist: boolean }>>('/api/file/upload/init', {
      name: file.name,
      size: file.size,
      mime_type: file.type || 'application/octet-stream',
      provider: 'local',
    })
    .catch(fail)

  const uploadId = initResponse.data.data?.id
  if (!uploadId) throw new Error(initResponse.data.message || '初始化上传失败')

  // 秒传：服务端已存在相同文件
  if (initResponse.data.data?.exist) {
    options.onProgress?.({
      percent: 100,
      loaded: file.size,
      total: file.size,
      part: totalParts,
      parts: totalParts,
    })
    return { id: uploadId, name: file.name, size: file.size, type: file.type, md5: '', status: 1 }
  }

  // 2. 逐片上传（串行，保证顺序与后端分片连续性校验一致）
  let uploaded = 0
  for (let part = 1; part <= totalParts; part += 1) {
    const start = (part - 1) * chunkSize
    const end = Math.min(start + chunkSize, file.size)
    const blob = file.slice(start, end)

    let attempt = 0
    for (;;) {
      const form = new FormData()
      form.append('id', uploadId)
      form.append('part_number', String(part))
      form.append('chunk', blob, file.name)
      try {
        const response = await api.post('/api/file/upload/chunk', form, {
          headers: { 'Content-Type': 'multipart/form-data' },
          signal: options.signal,
        })
        if (!response.data?.success) throw new Error(response.data?.message || '分片上传失败')
        break
      } catch (error) {
        if (options.signal?.aborted) throw error
        if (attempt >= maxRetries) fail(error)
        attempt += 1
        // 退避重试
        await new Promise((resolve) => setTimeout(resolve, 400 * attempt))
      }
    }

    uploaded = end
    options.onProgress?.({
      percent: Math.round((uploaded / file.size) * 100),
      loaded: uploaded,
      total: file.size,
      part,
      parts: totalParts,
    })
  }

  // 3. 合并分片
  const completeResponse = await api
    .post<ApiResult<UploadedFile>>('/api/file/upload/complete', {
      id: uploadId,
      parts: [],
    })
    .catch(fail)

  const result = completeResponse.data.data
  if (!completeResponse.data.success || !result) {
    throw new Error(completeResponse.data.message || '文件合并失败')
  }
  return result
}
