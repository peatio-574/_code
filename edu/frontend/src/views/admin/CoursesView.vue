<script setup lang="ts">
// 课程管理：课程分类筛选、CRUD、批量删除与章节管理（课程分类在字典管理中配置）。
import { Plus, Search } from '@element-plus/icons-vue'
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
const chapterForm = reactive({ id: 0, title: '', description: '', file: '', duration: 0, teacher_id: 0, sort_order: 0 })

async function load() {
  loading.value = true
  try {
    const page = await listCourses({
      p: query.p,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
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
  Object.assign(chapterForm, { id: 0, title: '', description: '', file: '', duration: 0, teacher_id: 0, sort_order: 0 })
  chapterVisible.value = true
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
}

async function saveChapter() {
  if (!chapterForm.title.trim()) {
    ElMessage.warning('请填写章节标题')
    return
  }
  const payload = { ...chapterForm }
  const result = chapterForm.id
    ? await updateChapter(chapterCourse.value!.id, chapterForm.id, payload)
    : await createChapter(chapterCourse.value!.id, payload)
  if (result.success) {
    ElMessage.success('保存成功')
    await openChapters(chapterCourse.value!)
  } else {
    ElMessage.error(result.message || '保存失败')
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
  const formData = new FormData()
  formData.append('file', options.file)
  try {
    const response = await api.post('/api/file/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    chapterForm.file = response.data?.data?.id ?? ''
    const video = document.createElement('video')
    video.preload = 'metadata'
    video.src = `/api/video/${chapterForm.file}`
    video.onloadedmetadata = () => {
      chapterForm.duration = Math.round(video.duration)
    }
    ElMessage.success('视频上传成功，时长已自动识别')
  } catch (error) {
    ElMessage.error(errorMessage(error))
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

/** 把课程分类编码转换为名称用于列表展示。 */
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
  const teacherPage = await listTeachers({ page_size: 100 })
  teachers.value = teacherPage?.items ?? []
  await loadTypes()
  await load()
})
</script>

<template>
  <DataPage
    title="课程管理"
    description="维护课程、章节与授课教师；课程分类在「字典管理 → 课程分类」中维护。"
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
      <el-select v-model="query.course_type_code" placeholder="课程分类" clearable style="width: 180px">
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
      <el-table-column label="课程" min-width="280">
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
              <div class="user-cell__meta">
                {{ row.teacher_names?.join('、') || '未设置教师' }} · {{ row.chapter_count }} 章节
              </div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="课程分类" min-width="140">
        <template #default="{ row }">{{ typeName(row.course_type_code) }}</template>
      </el-table-column>
      <el-table-column label="价格" min-width="100" align="right">
        <template #default="{ row }">
          <span class="tabular">{{ Number(row.price) > 0 ? `¥${Number(row.price).toFixed(2)}` : '免费' }}</span>
        </template>
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

  <el-dialog v-model="dialogVisible" :lock-scroll="false" :title="editingId ? '编辑课程' : '新增课程'" width="720px" append-to-body>
    <el-form label-position="top">
      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="课程名称" required><el-input v-model="form.name" placeholder="请输入课程名称" /></el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="课程概述"><el-input v-model="form.short_description" placeholder="一句话概括课程内容" /></el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="授课教师">
        <el-select v-model="form.teacher_ids" multiple style="width: 100%" placeholder="选择授课教师（可多选）">
          <el-option v-for="teacher in teachers" :key="teacher.id" :label="teacher.name" :value="teacher.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="课程分类">
        <el-select v-model="form.course_type_codes" multiple style="width: 100%" placeholder="在字典管理中维护课程分类">
          <el-option v-for="type in courseTypes" :key="type.code" :label="type.name" :value="type.code" />
        </el-select>
      </el-form-item>
      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="价格（元）"><el-input-number v-model="form.price" :min="0" :precision="2" style="width: 100%" /></el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="状态">
            <el-switch v-model="form.status" :active-value="1" :inactive-value="0" inline-prompt active-text="启用" inactive-text="禁用" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="封面图">
        <div class="cover-field">
          <div class="cover-field__preview" :style="form.cover ? { backgroundImage: `url(/api/image/${form.cover})` } : {}">
            <span v-if="!form.cover">未上传</span>
          </div>
          <div>
            <el-upload :show-file-list="false" :http-request="uploadCoverFile" accept="image/*">
              <el-button>{{ form.cover ? '重新上传' : '上传封面' }}</el-button>
            </el-upload>
            <p class="cover-field__hint">建议尺寸 16:9，用于课程列表与详情展示</p>
          </div>
        </div>
      </el-form-item>
      <el-form-item label="课程详情">
        <el-input v-model="form.description" type="textarea" :rows="4" placeholder="支持 HTML 富文本" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>

  <el-drawer v-model="chapterVisible" :lock-scroll="false" :title="`章节管理 · ${chapterCourse?.name ?? ''}`" size="760px">
    <div class="chapter-form">
      <div class="chapter-form__row">
        <el-input v-model="chapterForm.title" placeholder="章节标题" class="chapter-form__title" />
        <el-input-number v-model="chapterForm.sort_order" :min="0" placeholder="排序" />
      </div>
      <div class="chapter-form__row">
        <el-upload :show-file-list="false" :http-request="uploadVideo" accept="video/*">
          <el-button :icon="Plus">上传视频</el-button>
        </el-upload>
        <el-input-number v-model="chapterForm.duration" :min="0" placeholder="时长（秒）" />
        <span v-if="chapterForm.file" class="chapter-form__file">已选择视频 · {{ formatDuration(chapterForm.duration) }}</span>
        <span class="toolbar-spacer" />
        <el-button v-if="chapterForm.id" @click="Object.assign(chapterForm, { id: 0, title: '', file: '', duration: 0 })">取消编辑</el-button>
        <el-button type="primary" @click="saveChapter">{{ chapterForm.id ? '保存修改' : '添加章节' }}</el-button>
      </div>
    </div>
    <el-table :data="chapters" row-key="id" empty-text="暂无章节">
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
  width: 120px;
  height: 68px;
  flex-shrink: 0;
  place-items: center;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-md);
  background: var(--slate-50) center/cover no-repeat;
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
.cover-field__hint {
  margin-top: var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.chapter-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  padding: var(--space-4);
  background: var(--slate-50);
  border-radius: var(--radius-md);
}
.chapter-form__row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.chapter-form__title {
  flex: 1;
}
.chapter-form__file {
  font-size: var(--text-xs);
  color: var(--success);
}
</style>
