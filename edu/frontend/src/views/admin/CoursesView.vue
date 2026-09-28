<script setup lang="ts">
// 课程管理：课程方向筛选、CRUD、批量删除与章节管理（课程方向在字典管理中配置）。
import { Plus, Search, VideoCamera } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import {
  batchDeleteCourses,
  createChapter,
  createCourse,
  deleteChapter,
  deleteCourse,
  getCourse,
  listCourses,
  listTeachers,
  toggleCourse,
  updateChapter,
  updateCourse,
} from '@/api/admin'
import DataPage from '@/components/data-page.vue'
import StatusSwitch from '@/components/status-switch.vue'
import { api, errorMessage } from '@/lib/api'
import { uploadFileInChunks } from '@/lib/upload'
import { formatDateTime, STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'

const loading = ref(false)
const saving = ref(false)
const items = ref<Record<string, any>[]>([])
const total = ref(0)
const teachers = ref<Record<string, any>[]>([])
const courseTypes = ref<Record<string, any>[]>([])

const query = reactive({ p: 1, page_size: 20, keyword: '', teacher_id: '', course_type_code: '', status: '' })
const selection = ref<Record<string, any>[]>([])

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  name: '',
  description: '',
  short_description: '',
  price: 0,
  course_type_codes: [] as string[],
  cover: '',
  description_image: '',
  teacher_ids: [] as number[],
  status: 1,
})

const chapterVisible = ref(false)
const chapterCourse = ref<Record<string, any> | null>(null)
const chapters = ref<Record<string, any>[]>([])
const chapterDialogVisible = ref(false)
const chapterSaving = ref(false)
const chapterUploading = ref(false)
const chapterUploadPercent = ref(0)
const chapterFileName = ref('')
const chapterForm = reactive({ id: 0, title: '', description: '', file: '', duration: 0, teacher_id: 0, sort_order: 0 })

async function load() {
  loading.value = true
  try {
    const page = await listCourses({
      p: query.p,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      teacher_id: query.teacher_id || undefined,
      course_type_code: query.course_type_code || undefined,
      status: query.status || undefined,
    })
    items.value = page?.items ?? []
    total.value = page?.total ?? 0
  } finally {
    loading.value = false
  }
}

function reset() {
  query.keyword = ''
  query.teacher_id = ''
  query.course_type_code = ''
  query.status = ''
  query.p = 1
  load()
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    name: '',
    description: '',
    short_description: '',
    price: 0,
    course_type_codes: [],
    cover: '',
    description_image: '',
    teacher_ids: [],
    status: 1,
  })
  dialogVisible.value = true
}

async function openEdit(row: Record<string, any>) {
  const detail = await getCourse(row.id)
  editingId.value = row.id
  Object.assign(form, {
    name: detail.course.name,
    description: detail.course.description,
    short_description: detail.course.short_description,
    price: Number(detail.course.price),
    course_type_codes: (detail.course.course_type_code || '').split(',').filter(Boolean),
    cover: detail.course.cover,
    description_image: detail.course.description_image,
    teacher_ids: detail.teacher_ids,
    status: detail.course.status,
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写课程名称')
    return
  }
  saving.value = true
  try {
    const payload = { ...form, id: editingId.value ?? undefined }
    const result = editingId.value ? await updateCourse(payload) : await createCourse(payload)
    if (result.success) {
      ElMessage.success('保存成功')
      dialogVisible.value = false
      await load()
    } else {
      ElMessage.error(result.message || '保存失败')
    }
  } finally {
    saving.value = false
  }
}

async function remove(row: Record<string, any>) {
  try {
    await ElMessageBox.confirm(`确定删除课程“${row.name}”吗？其章节与学习记录将一并删除。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const result = await deleteCourse(row.id)
  if (result.success) {
    ElMessage.success('已删除')
    await load()
  } else {
    ElMessage.error(result.message || '删除失败')
  }
}

async function batchRemove() {
  if (!selection.value.length) {
    ElMessage.warning('请先选择要删除的课程')
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${selection.value.length} 门课程吗？`, '批量删除', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const result = await batchDeleteCourses(selection.value.map((row) => row.id))
  ElMessage.success(`已删除 ${result.data?.deleted_count ?? 0} 门课程`)
  await load()
}

async function toggle(row: Record<string, any>, next: number) {
  const previous = row.status
  row.status = next
  const result = await toggleCourse(row.id, next)
  if (!result.success) {
    row.status = previous
    ElMessage.error(result.message || STATUS_FAILURE_TEXT)
  } else {
    ElMessage.success(statusChangeMessage(next))
  }
}

async function openChapters(row: Record<string, any>) {
  chapterCourse.value = row
  const detail = await getCourse(row.id)
  chapters.value = detail.chapters
  chapterVisible.value = true
}

function resetChapterForm() {
  Object.assign(chapterForm, {
    id: 0,
    title: '',
    description: '',
    file: '',
    duration: 0,
    teacher_id: 0,
    sort_order: chapters.value.length + 1,
  })
  chapterFileName.value = ''
}

function openCreateChapter() {
  resetChapterForm()
  chapterDialogVisible.value = true
}

function editChapter(chapter: Record<string, any>) {
  Object.assign(chapterForm, {
    id: chapter.id,
    title: chapter.title,
    description: chapter.description,
    file: chapter.file,
    duration: Number(chapter.duration),
    teacher_id: chapter.teacher_id,
    sort_order: chapter.sort_order,
  })
  chapterFileName.value = chapter.file_name || ''
  chapterDialogVisible.value = true
}

async function refreshChapters() {
  if (!chapterCourse.value) return
  const detail = await getCourse(chapterCourse.value.id)
  chapters.value = detail.chapters
}

async function saveChapter() {
  if (!chapterForm.title.trim()) {
    ElMessage.warning('请填写章节标题')
    return
  }
  chapterSaving.value = true
  try {
    const payload = { ...chapterForm }
    const result = chapterForm.id
      ? await updateChapter(chapterCourse.value!.id, chapterForm.id, payload)
      : await createChapter(chapterCourse.value!.id, payload)
    if (result.success) {
      ElMessage.success('保存成功')
      chapterDialogVisible.value = false
      await refreshChapters()
    } else {
      ElMessage.error(result.message || '保存失败')
    }
  } finally {
    chapterSaving.value = false
  }
}

async function removeChapter(chapter: Record<string, any>) {
  const result = await deleteChapter(chapterCourse.value!.id, chapter.id)
  if (result.success) {
    chapters.value = chapters.value.filter((item) => item.id !== chapter.id)
    ElMessage.success('已删除')
  }
}

async function uploadVideo(options: any) {
  const file: File = options.file
  chapterUploading.value = true
  chapterUploadPercent.value = 0
  try {
    // 大文件走分片上传（单文件接口上限 30MB）
    const uploaded = await uploadFileInChunks(file, {
      onProgress: (progress) => {
        chapterUploadPercent.value = progress.percent
        options.onProgress?.({ percent: progress.percent })
      },
    })
    chapterForm.file = uploaded.id
    chapterFileName.value = uploaded.name || file.name
    const video = document.createElement('video')
    video.preload = 'metadata'
    video.src = `/api/video/${chapterForm.file}`
    video.onloadedmetadata = () => {
      chapterForm.duration = Math.round(video.duration)
    }
    ElMessage.success('视频上传成功，时长已自动识别')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : errorMessage(error))
  } finally {
    chapterUploading.value = false
    chapterUploadPercent.value = 0
  }
}

async function uploadCoverFile(options: any) {
  const formData = new FormData()
  formData.append('file', options.file)
  try {
    const response = await api.post('/api/file/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    const uploaded = response.data?.data?.id
    if (uploaded) {
      form.cover = uploaded
      form.description_image = uploaded
    }
    ElMessage.success('封面上传成功')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function loadTypes() {
  const response = await api.get('/api/dictionaries/course_type/items')
  courseTypes.value = response.data?.data?.items ?? []
}

/** 把课程方向编码转换为名称用于列表展示。 */
function typeName(code: string | undefined): string {
  if (!code) return '—'
  return code
    .split(',')
    .filter(Boolean)
    .map((item) => courseTypes.value.find((type) => type.code === item)?.name ?? item)
    .join('、')
}

function formatDuration(seconds: number): string {
  const total = Math.round(seconds || 0)
  if (total <= 0) return '—'
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`
}

onMounted(async () => {
  // 辅助数据（教师/课程方向）获取失败不应阻断主列表加载
  try {
    const teacherPage = await listTeachers({ page_size: 100 })
    teachers.value = teacherPage?.items ?? []
  } catch {
    teachers.value = []
  }
  try {
    await loadTypes()
  } catch {
    courseTypes.value = []
  }
  await load()
})
</script>

<template>
  <DataPage
    title="课程管理"
    description="维护课程、章节与授课教师；课程方向在「字典管理 → 课程方向」中维护。"
    :total="total"
    :page="query.p"
    :page-size="query.page_size"
    :loading="loading"
    @update:page="(value) => (query.p = value)"
    @update:page-size="(value) => (query.page_size = value)"
    @change="load"
  >
    <template #actions>
      <el-button type="primary" :icon="Plus" @click="openCreate">添加课程</el-button>
    </template>

    <template #filters>
      <el-input
        v-model="query.keyword"
        placeholder="课程名称"
        clearable
        :prefix-icon="Search"
        @keyup.enter="() => { query.p = 1; load() }"
      />
      <el-select v-model="query.teacher_id" placeholder="授课教师" clearable style="width: 180px">
        <el-option v-for="teacher in teachers" :key="teacher.id" :label="teacher.name" :value="String(teacher.id)" />
      </el-select>
      <el-select v-model="query.course_type_code" placeholder="课程方向" clearable style="width: 180px">
        <el-option v-for="type in courseTypes" :key="type.code" :label="type.name" :value="type.code" />
      </el-select>
      <el-button type="primary" @click="() => { query.p = 1; load() }">搜索</el-button>
      <el-button @click="reset">重置</el-button>
      <span class="toolbar-spacer" />
      <el-button type="danger" plain :disabled="!selection.length" @click="batchRemove">
        批量删除{{ selection.length ? `（${selection.length}）` : '' }}
      </el-button>
    </template>

    <el-table :data="items" row-key="id" height="100%" empty-text="暂无课程，点击右上角「添加课程」开始" @selection-change="(rows: any[]) => (selection = rows)">
      <el-table-column type="selection" width="48" />
      <el-table-column label="课程" min-width="240">
        <template #default="{ row }">
          <div class="course-cell">
            <div
              class="course-cell__cover"
              :style="row.cover ? { backgroundImage: `url(/api/image/${row.cover})` } : {}"
            >
              <span v-if="!row.cover">课</span>
            </div>
            <div class="course-cell__info">
              <div class="user-cell__name">{{ row.name }}</div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="授课教师" min-width="180">
        <template #default="{ row }">
          <span v-if="row.teacher_names?.length">{{ row.teacher_names.join('、') }}</span>
          <span v-else class="cell-muted">未设置</span>
        </template>
      </el-table-column>
      <el-table-column label="章节数" min-width="90">
        <template #default="{ row }"><span class="tabular">{{ row.chapter_count ?? 0 }}</span></template>
      </el-table-column>
      <el-table-column label="价格" min-width="100">
        <template #default="{ row }">
          <span class="tabular">{{ Number(row.price) > 0 ? `¥${Number(row.price).toFixed(2)}` : '免费' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="课程方向" min-width="140">
        <template #default="{ row }">{{ typeName(row.course_type_code) }}</template>
      </el-table-column>
      <el-table-column label="状态" min-width="160">
        <template #default="{ row }">
          <StatusSwitch :status="row.status" @change="(next) => toggle(row, next)" />
        </template>
      </el-table-column>
      <el-table-column label="更新时间" min-width="180">
        <template #default="{ row }"><span class="cell-muted tabular">{{ formatDateTime(row.updated_at) }}</span></template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" @click="openChapters(row)">章节</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </DataPage>

  <el-dialog
    v-model="dialogVisible"
    :lock-scroll="false"
    :title="editingId ? '编辑课程' : '新增课程'"
    width="900px"
    top="5vh"
    append-to-body
    class="course-dialog"
  >
    <el-form label-position="top" class="course-form">
      <el-form-item label="课程名称" required><el-input v-model="form.name" size="large" placeholder="请输入课程名称" /></el-form-item>
      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="授课教师">
            <el-select v-model="form.teacher_ids" multiple style="width: 100%" placeholder="选择授课教师（可多选）">
              <el-option v-for="teacher in teachers" :key="teacher.id" :label="teacher.name" :value="teacher.id" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="课程方向">
            <el-select v-model="form.course_type_codes" multiple style="width: 100%" placeholder="在字典管理中维护课程方向">
              <el-option v-for="type in courseTypes" :key="type.code" :label="type.name" :value="type.code" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="价格（元）"><el-input-number v-model="form.price" :min="0" :precision="2" style="width: 100%" /></el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="状态">
            <el-switch
              v-model="form.status"
              class="course-status-switch"
              :active-value="1"
              :inactive-value="0"
              inline-prompt
              active-text="启用"
              inactive-text="禁用"
            />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="课程概述">
        <el-input
          v-model="form.short_description"
          type="textarea"
          :rows="3"
          resize="vertical"
          placeholder="一句话概括课程内容"
        />
      </el-form-item>
      <el-form-item label="封面图">
        <div class="cover-field">
          <div class="cover-field__preview" :style="form.cover ? { backgroundImage: `url(/api/image/${form.cover})` } : {}">
            <span v-if="!form.cover">未上传</span>
          </div>
          <div class="cover-field__actions">
            <el-upload :show-file-list="false" :http-request="uploadCoverFile" accept="image/*">
              <el-button>{{ form.cover ? '重新上传' : '上传封面' }}</el-button>
            </el-upload>
            <span class="cover-field__hint">建议尺寸 16:9，用于课程列表与详情展示</span>
          </div>
        </div>
      </el-form-item>
      <el-form-item label="课程详情">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="10"
          resize="vertical"
          placeholder="支持 HTML 富文本"
          class="course-detail-input"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>

  <el-drawer v-model="chapterVisible" :lock-scroll="false" :title="`章节管理 · ${chapterCourse?.name ?? ''}`" size="760px">
    <div class="chapter-toolbar">
      <el-button type="primary" :icon="Plus" @click="openCreateChapter">添加章节</el-button>
    </div>
    <el-table :data="chapters" row-key="id" empty-text="暂无章节，点击左上角「添加章节」开始">
      <el-table-column type="index" label="#" width="56" />
      <el-table-column prop="title" label="章节标题" min-width="220" />
      <el-table-column label="时长" min-width="110">
        <template #default="{ row }"><span class="tabular">{{ formatDuration(Number(row.duration)) }}</span></template>
      </el-table-column>
      <el-table-column label="操作" min-width="140">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button link type="primary" @click="editChapter(row)">编辑</el-button>
            <el-button link type="danger" @click="removeChapter(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </el-drawer>

  <el-dialog
    v-model="chapterDialogVisible"
    :lock-scroll="false"
    :title="chapterForm.id ? '编辑章节' : '添加章节'"
    width="640px"
    append-to-body
  >
    <el-form label-position="top" class="chapter-dialog-form">
      <el-row :gutter="16">
        <el-col :span="16">
          <el-form-item label="章节标题" required>
            <el-input v-model="chapterForm.title" placeholder="请输入章节标题" />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="排序">
            <el-input-number v-model="chapterForm.sort_order" :min="0" style="width: 100%" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="章节简介">
        <el-input
          v-model="chapterForm.description"
          type="textarea"
          :rows="3"
          resize="vertical"
          placeholder="章节内容简述（可选）"
        />
      </el-form-item>
      <el-form-item label="章节视频">
        <div class="chapter-upload">
          <el-upload
            :show-file-list="false"
            :http-request="uploadVideo"
            accept="video/*"
            :disabled="chapterUploading"
          >
            <el-button
              :icon="Plus"
              :loading="chapterUploading"
              :disabled="chapterUploading"
            >
              {{ chapterUploading ? '上传中…' : chapterForm.file ? '重新上传' : '上传视频' }}
            </el-button>
          </el-upload>
        </div>
        <div v-if="chapterUploading" class="chapter-upload__status">
          <el-progress
            :percentage="chapterUploadPercent"
            :show-text="false"
            :stroke-width="6"
            class="chapter-upload__progress"
          />
          <span>视频上传中 {{ chapterUploadPercent }}%，请勿关闭窗口…</span>
        </div>
        <div v-else-if="chapterForm.file" class="chapter-upload__status chapter-upload__status--ok">
          <el-icon><VideoCamera /></el-icon>
          <span class="chapter-upload__file" :title="chapterFileName || chapterForm.file">
            {{ chapterFileName || '已上传' }}
          </span>
          <span class="chapter-upload__meta">时长 {{ formatDuration(chapterForm.duration) }}</span>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="chapterDialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="chapterSaving" @click="saveChapter">
        {{ chapterForm.id ? '保存修改' : '添加章节' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.course-cell {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.course-cell__cover {
  display: grid;
  width: 64px;
  height: 40px;
  flex-shrink: 0;
  place-items: center;
  border-radius: var(--radius-sm);
  background: var(--slate-100) center/cover no-repeat;
  color: var(--slate-400);
  font-size: var(--text-xs);
}
.course-cell__info {
  min-width: 0;
}
.cover-field {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}
.cover-field__preview {
  display: grid;
  width: 192px;
  height: 108px;
  flex-shrink: 0;
  place-items: center;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-md);
  background: var(--slate-50) center/cover no-repeat;
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
.cover-field__actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}
.cover-field__hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
/* 状态按钮加大（整体放大 1.25 倍，左对齐不破坏布局） */
.course-status-switch.el-switch {
  transform: scale(1.25);
  transform-origin: left center;
}
.course-form :deep(.el-form-item) {
  margin-bottom: var(--space-5);
}
.course-form :deep(.el-textarea__inner) {
  line-height: 1.7;
}
.course-detail-input :deep(.el-textarea__inner) {
  min-height: 240px;
  line-height: 1.7;
}
.chapter-toolbar {
  display: flex;
  justify-content: flex-start;
  margin-bottom: var(--space-4);
}
.chapter-dialog-form :deep(.el-form-item) {
  margin-bottom: var(--space-4);
}
.chapter-upload {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}
.chapter-upload__status {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
  margin-top: var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.chapter-upload__status--ok {
  flex-direction: row;
  align-items: center;
  color: var(--success);
}
.chapter-upload__progress {
  width: 100%;
  max-width: 420px;
}
.chapter-upload__file {
  overflow: hidden;
  max-width: 360px;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}
.chapter-upload__meta {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
</style>

<!--
  非 scoped：el-dialog 的 class 合并到 .el-dialog，scoped 属性在遮罩层，
  复合选择器无法匹配，故对弹窗结构用全局选择器（course-dialog 类名唯一）。
-->
<style>
.course-dialog.el-dialog {
  display: flex;
  height: 84vh;
  flex-direction: column;
  overflow: hidden;
}
.course-dialog .el-dialog__header {
  flex-shrink: 0;
}
.course-dialog .el-dialog__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.course-dialog .el-dialog__footer {
  flex-shrink: 0;
}
</style>
