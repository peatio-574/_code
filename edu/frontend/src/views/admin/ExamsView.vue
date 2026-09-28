<script setup lang="ts">
// 考试管理：组卷、发布/撤回、考试结果与批量删除。
// 注：考试列表由 DataPage 承载，单试卷「结果」通过弹窗查看。
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import {
  batchDeleteExams,
  createExam,
  deleteExam,
  getExam,
  listCampuses,
  listExamAttempts,
  publishExam,
  updateExam,
  withdrawExam,
} from '@/api/admin'
import DataPage from '@/components/data-page.vue'
import { api, errorMessage } from '@/lib/api'
import { formatDateTime } from '@/lib/labels'

const QUESTION_TYPES = [
  { value: 'single', label: '单选题' },
  { value: 'multiple', label: '多选题' },
  { value: 'true_false', label: '判断题' },
  { value: 'fill', label: '填空题' },
  { value: 'qa', label: '问答题' },
  { value: 'group', label: '综合答题' },
]

/** 题型配置：勾选模式存具体题目；按比例模式存抽取题数，保存时随机抽题。 */
interface SectionForm {
  type: string
  description: string
  mode: 'select' | 'ratio'
  question_ids: number[]
  ratio: number
  score: number
  poolCount: number | null
  poolLoading: boolean
}

function typeLabel(value: string) {
  return QUESTION_TYPES.find((item) => item.value === value)?.label ?? value
}

function createSection(type = 'single', score = 1): SectionForm {
  return {
    type,
    description: typeLabel(type),
    mode: 'select',
    question_ids: [],
    ratio: 10,
    score,
    poolCount: null,
    poolLoading: false,
  }
}

/** Fisher-Yates 洗牌，用于按比例随机抽题。 */
function shuffle<T>(items: T[]): T[] {
  const result = [...items]
  for (let i = result.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[result[i], result[j]] = [result[j], result[i]]
  }
  return result
}

const items = ref<Record<string, any>[]>([])
const total = ref(0)
const loading = ref(false)
const query = reactive({ p: 1, page_size: 20, keyword: '' })
const selection = ref<Record<string, any>[]>([])
const campuses = ref<Record<string, any>[]>([])

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  title: '',
  exam_time: '',
  end_time: '',
  duration: 60,
  pass_score: 60,
  status: 1,
  campus_ids: [] as number[],
  sections: [] as SectionForm[],
})

/** 开放校区：多选，全部选中即对全部校区开放。 */
const allCampusIds = computed(() => campuses.value.map((campus) => Number(campus.id)))
const allCampusesSelected = computed(
  () => allCampusIds.value.length > 0 && form.campus_ids.length === allCampusIds.value.length,
)
const campusIndeterminate = computed(
  () => form.campus_ids.length > 0 && form.campus_ids.length < allCampusIds.value.length,
)

function toggleAllCampuses(value: boolean) {
  form.campus_ids = value ? [...allCampusIds.value] : []
}

const pickerVisible = ref(false)
const pickerType = ref('single')
const pickerOptions = ref<Record<string, any>[]>([])
const activeSection = ref(0)

const resultVisible = ref(false)
const resultAttempts = ref<Record<string, any>[]>([])

const contentVisible = ref(false)
const contentLoading = ref(false)
const contentExam = ref<Record<string, any> | null>(null)
const contentSections = ref<Record<string, any>[]>([])

const DISPLAY_STATUS_TEXT: Record<string, string> = {
  draft: '草稿',
  withdrawn: '已撤回',
  not_started: '未开始',
  in_progress: '进行中',
  ended: '已结束',
}

const DISPLAY_STATUS_TAG: Record<string, 'success' | 'warning' | 'info' | 'primary'> = {
  draft: 'info',
  withdrawn: 'info',
  not_started: 'primary',
  in_progress: 'success',
  ended: 'warning',
}

/** 有效截止时间：显式 end_time 优先，否则回退 开始时间 + 时长（分钟）。 */
function effectiveEndTime(row: Record<string, any>): number {
  const explicit = Number(row.end_time || 0)
  if (explicit > 0) return explicit
  return Number(row.exam_time || 0) + Number(row.duration || 0) * 60
}

/** 列表状态：优先用后端 display_status，缺失时按发布状态与有效时间在前端判定。 */
function displayStatus(row: Record<string, any>): string {
  if (row.display_status) return row.display_status as string
  if (row.status === 0) return 'draft'
  if (row.status === 2) return 'withdrawn'
  const now = Math.floor(Date.now() / 1000)
  if (now < Number(row.exam_time || 0)) return 'not_started'
  const end = effectiveEndTime(row)
  if (end > 0 && now > end) return 'ended'
  return 'in_progress'
}

function statusText(row: Record<string, any>) {
  return DISPLAY_STATUS_TEXT[displayStatus(row)] ?? '已发布'
}

function statusTag(row: Record<string, any>) {
  return DISPLAY_STATUS_TAG[displayStatus(row)] ?? 'info'
}

async function load() {
  loading.value = true
  try {
    const page = await api.get('/api/admin/exams', { params: { p: query.p, page_size: query.page_size, keyword: query.keyword || undefined } })
    items.value = page.data?.data?.items ?? []
    total.value = page.data?.data?.total ?? 0
  } finally {
    loading.value = false
  }
}

/** 时间戳（秒）格式化为 el-date-picker 的 value-format。 */
function formatDateTimeValue(timestamp: number) {
  if (!timestamp) return ''
  const date = new Date(timestamp * 1000)
  const pad = (value: number) => String(value).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}

/** el-date-picker 的值（YYYY-MM-DD HH:mm:ss）转 Unix 秒。 */
function toTimestamp(value: string) {
  if (!value) return 0
  return Math.floor(new Date(value.replace(/-/g, '/')).getTime() / 1000)
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    title: '',
    exam_time: '',
    end_time: '',
    duration: 60,
    pass_score: 60,
    status: 1,
    campus_ids: [...allCampusIds.value],
    sections: [createSection('single')],
  })
  dialogVisible.value = true
}

async function openEdit(row: Record<string, any>) {
  const detail = await getExam(row.id)
  editingId.value = row.id
  Object.assign(form, {
    title: detail.exam.title,
    exam_time: formatDateTimeValue(detail.exam.exam_time),
    end_time: detail.exam.end_time ? formatDateTimeValue(detail.exam.end_time) : '',
    duration: detail.exam.duration,
    pass_score: detail.exam.pass_score,
    status: detail.exam.status,
    campus_ids: Array.isArray(detail.exam.campus_ids) ? [...detail.exam.campus_ids] : [],
    sections: detail.sections.map((section: any) => ({
      ...createSection(section.type, Number(section.score) || 0),
      description: section.description,
      mode: 'select',
      question_ids: section.questions.map((q: any) => q.id),
    })),
  })
  dialogVisible.value = true
}

function addSection() {
  form.sections.push(createSection('single'))
}

function removeSection(index: number) {
  form.sections.splice(index, 1)
}

function onSectionTypeChange(section: SectionForm) {
  section.description = typeLabel(section.type)
  section.question_ids = []
  section.poolCount = null
}

async function loadPool(section: SectionForm) {
  section.poolLoading = true
  try {
    section.poolCount = await fetchPoolCount(section)
  } finally {
    section.poolLoading = false
  }
}

function onSectionModeChange(section: SectionForm) {
  if (section.mode === 'ratio' && section.poolCount === null) {
    void loadPool(section)
  }
}

/** 题库可用数：启用题目中，剔除已被其他分组占用的题目。 */
async function fetchPoolCount(section: SectionForm) {
  const response = await api.get('/api/admin/questions/options', { params: { type: section.type } })
  const items = (response.data?.data?.items ?? []) as { id: number; status: number }[]
  const others = new Set<number>()
  form.sections.forEach((item) => {
    if (item !== section) item.question_ids.forEach((id) => others.add(id))
  })
  return items.filter((item) => item.status === 1 && !others.has(item.id)).length
}

async function openPicker(sectionIndex: number) {
  activeSection.value = sectionIndex
  pickerType.value = form.sections[sectionIndex].type
  const response = await api.get('/api/admin/questions/options', { params: { type: pickerType.value } })
  pickerOptions.value = response.data?.data?.items ?? []
  pickerVisible.value = true
}

function toggleQuestion(id: number) {
  const section = form.sections[activeSection.value]
  if (!section) return
  if (section.question_ids.includes(id)) {
    section.question_ids = section.question_ids.filter((value) => value !== id)
  } else {
    if (usedByOtherSections(id)) {
      ElMessage.warning('该题已被其他题型分组选用，不能重复选择')
      return
    }
    section.question_ids.push(id)
  }
}

function clearPicked() {
  const section = form.sections[activeSection.value]
  if (section) section.question_ids = []
}

/**
 * 解析某题型配置最终使用的题目 id。
 * `used` 收集已其他分组占用的题目 id，用于跨分组去重（同一题型勾选与按比例并存时剔除重复）。
 */
async function resolveSectionQuestionIds(section: SectionForm, used: Set<number>): Promise<number[]> {
  if (section.mode === 'select') {
    return section.question_ids.filter((id) => !used.has(id))
  }
  const count = Math.max(0, Math.floor(Number(section.ratio) || 0))
  if (!count) return []
  const response = await api.get('/api/admin/questions/options', { params: { type: section.type } })
  const items = (response.data?.data?.items ?? []) as { id: number; status: number }[]
  // 题库排除已被其他分组选用的题目，避免重复出题
  const pool: number[] = items
    .filter((item) => item.status === 1 && !used.has(item.id))
    .map((item) => item.id)
  section.poolCount = pool.length
  if (pool.length < count) {
    throw new Error(
      `「${typeLabel(section.type)}」题库可用 ${pool.length} 题（已剔除其他分组已选题目），不足以抽取 ${count} 题`,
    )
  }
  return shuffle(pool).slice(0, count)
}

/** 勾选弹窗：判断该题是否已被其他分组占用（占用则禁选）。 */
function usedByOtherSections(id: number) {
  return form.sections.some(
    (section, index) => index !== activeSection.value && section.question_ids.includes(id),
  )
}

async function save() {
  if (!form.title.trim() || !form.exam_time || !form.end_time) {
    ElMessage.warning('请填写试卷名称、开始时间和结束时间')
    return
  }
  const examTime = toTimestamp(form.exam_time)
  const endTime = toTimestamp(form.end_time)
  if (endTime <= examTime) {
    ElMessage.warning('结束时间必须晚于开始时间')
    return
  }
  const sections: { type: string; description: string; question_ids: number[]; score: number }[] = []
  const used = new Set<number>()
  try {
    for (const section of form.sections) {
      const ids = await resolveSectionQuestionIds(section, used)
      if (!ids.length) continue
      ids.forEach((id) => used.add(id))
      sections.push({
        type: section.type,
        description: (section.description || typeLabel(section.type)).trim(),
        question_ids: ids,
        score: Math.max(0, Math.floor(Number(section.score) || 0)),
      })
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '题目配置有误')
    return
  }
  if (!sections.length) {
    ElMessage.warning('请至少配置一种题型的题目')
    return
  }
  const payload = {
    title: form.title,
    exam_time: examTime,
    end_time: endTime,
    duration: form.duration,
    pass_score: form.pass_score,
    status: form.status,
    campus_ids: form.campus_ids,
    sections,
  }
  try {
    const result = editingId.value ? await updateExam(editingId.value, payload) : await createExam(payload)
    if (result.success) {
      ElMessage.success('保存成功')
      dialogVisible.value = false
      await load()
    } else {
      ElMessage.error(result.message || '保存失败')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function publish(row: Record<string, any>) {
  try {
    const result = await publishExam(row.id)
    if (result.success) {
      await load()
      ElMessage.success('已发布')
    } else {
      ElMessage.error(result.message || '发布失败')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function withdraw(row: Record<string, any>) {
  try {
    await withdrawExam(row.id)
    ElMessage.success('已撤回')
    await load()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function remove(row: Record<string, any>) {
  try {
    await ElMessageBox.confirm('确定删除该试卷吗？', '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteExam(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function batchRemove() {
  if (!selection.value.length) {
    ElMessage.warning('请选择要删除的试卷')
    return
  }
  try {
    await batchDeleteExams(selection.value.map((row) => row.id))
    ElMessage.success('已删除')
    await load()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function viewResults(row: Record<string, any>) {
  const page = await listExamAttempts({ p: 1, page_size: 100 })
  resultAttempts.value = (page?.items ?? []).filter((item: any) => item.exam_id === row.id)
  resultVisible.value = true
}

/** 解析题目选项：支持 JSON 数组/对象与「；」分隔文本（仅用于预览展示）。 */
function parseOptions(options: string): { key: string; text: string }[] {
  const raw = (options || '').trim()
  if (!raw) return []
  if (raw.startsWith('{') || raw.startsWith('[')) {
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        return parsed.map((item: any, index: number) => ({
          key: item.key || String.fromCharCode(65 + index),
          text: item.text ?? item.value ?? String(item),
        }))
      }
      return Object.entries(parsed).map(([key, value]) => ({ key, text: String(value) }))
    } catch {
      return []
    }
  }
  return raw
    .split(/[；;]/)
    .map((text) => text.trim())
    .filter(Boolean)
    .map((text, index) => ({ key: String.fromCharCode(65 + index), text }))
}

async function viewContent(row: Record<string, any>) {
  contentLoading.value = true
  contentVisible.value = true
  contentExam.value = null
  contentSections.value = []
  try {
    const detail = await getExam(row.id)
    contentExam.value = detail.exam
    contentSections.value = detail.sections ?? []
  } finally {
    contentLoading.value = false
  }
}

/** 试卷内容弹窗：总题量与总分。 */
const contentTotalQuestions = computed(() =>
  contentSections.value.reduce((sum, section) => sum + (section.questions?.length ?? 0), 0),
)
const contentTotalScore = computed(() =>
  contentSections.value.reduce(
    (sum, section) => sum + (section.questions ?? []).reduce((t: number, q: any) => t + Number(q.score || 0), 0),
    0,
  ),
)

onMounted(async () => {
  try {
    campuses.value = (await listCampuses({ page_size: 100 }))?.items ?? []
  } catch {
    campuses.value = []
  }
  await load()
})
</script>

<template>
  <div class="exam-page">
    <DataPage
      title="考试管理"
      description="组卷、发布试卷并查看学员考试结果。试卷发布后学员即可在考试中心参加。"
      :total="total"
      :page="query.p"
      :page-size="query.page_size"
      :loading="loading"
      @update:page="(value) => (query.p = value)"
      @update:page-size="(value) => (query.page_size = value)"
      @change="load"
    >
      <template #actions>
        <el-button type="primary" :icon="Plus" @click="openCreate">添加试卷</el-button>
      </template>

      <template #filters>
        <el-input
          v-model="query.keyword"
          placeholder="试卷标题"
          clearable
          :prefix-icon="Search"
          @keyup.enter="() => { query.p = 1; load() }"
        />
        <el-button type="primary" @click="() => { query.p = 1; load() }">搜索</el-button>
        <el-button @click="() => { query.keyword = ''; query.p = 1; load() }">重置</el-button>
        <span class="toolbar-spacer" />
        <el-button type="danger" plain :disabled="!selection.length" @click="batchRemove">
          批量删除{{ selection.length ? `（${selection.length}）` : '' }}
        </el-button>
      </template>

      <el-table :data="items" row-key="id" height="100%" empty-text="暂无试卷，点击右上角「添加试卷」开始" @selection-change="(rows: any[]) => (selection = rows)">
        <el-table-column type="selection" width="48" />
        <el-table-column label="试卷名称" min-width="220">
          <template #default="{ row }">
            <div class="user-cell__name">{{ row.title }}</div>
            <div class="user-cell__meta">{{ row.total_questions }} 题 · 时长 {{ row.duration }} 分钟</div>
          </template>
        </el-table-column>
        <el-table-column label="有效时间" min-width="200">
          <template #default="{ row }">
            <span class="cell-muted tabular">{{ formatDateTime(row.exam_time) }} ~ {{ formatDateTime(row.end_time) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="110">
          <template #default="{ row }">
            <el-tag :type="statusTag(row)" effect="light">
              {{ statusText(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="发布人" min-width="110">
          <template #default="{ row }">{{ row.creator_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="考试统计" min-width="250">
          <template #default="{ row }">
            <div class="exam-stats">
              <span class="exam-stats__item"><b class="exam-stats__pending">{{ row.pending_count ?? 0 }}</b>待参考</span>
              <span class="exam-stats__item"><b>{{ row.attempt_user_count ?? row.attempt_count }}</b>已参考</span>
              <span class="exam-stats__item"><b>{{ row.pass_count }}</b>合格</span>
              <span class="exam-stats__item"><b>{{ Number(row.average_score).toFixed(1) }}</b>均分</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="330" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="primary" @click="viewContent(row)">试卷内容</el-button>
              <el-button v-if="row.status !== 1" link type="success" @click="publish(row)">发布</el-button>
              <el-button v-else link type="warning" @click="withdraw(row)">撤回</el-button>
              <el-button link type="primary" @click="viewResults(row)">结果</el-button>
              <el-button link type="danger" @click="remove(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </DataPage>

  </div>

  <el-dialog v-model="dialogVisible" :lock-scroll="false" :title="editingId ? '编辑试卷' : '新增试卷'" width="860px" top="4vh" append-to-body>
    <el-form label-position="top" class="exam-form">
      <el-row :gutter="16">
        <el-col :span="24">
          <el-form-item label="试卷名称" required>
            <el-input v-model="form.title" placeholder="请输入试卷名称" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="16">
        <el-col :span="8">
          <el-form-item label="开始时间" required>
            <el-date-picker
              v-model="form.exam_time"
              type="datetime"
              placeholder="选择开始时间"
              value-format="YYYY-MM-DD HH:mm:ss"
              format="YYYY-MM-DD HH:mm:ss"
              :disabled-date="(date: Date) => date.getTime() < Date.now() - 86400000"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="结束时间" required>
            <el-date-picker
              v-model="form.end_time"
              type="datetime"
              placeholder="选择结束时间"
              value-format="YYYY-MM-DD HH:mm:ss"
              format="YYYY-MM-DD HH:mm:ss"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="时长（分钟）">
            <el-input-number v-model="form.duration" :min="1" style="width: 100%" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="16">
        <el-col :span="8">
          <el-form-item label="合格线（分）">
            <el-input-number v-model="form.pass_score" :min="0" style="width: 100%" />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="状态">
            <el-switch
              v-model="form.status"
              class="exam-status-switch"
              :active-value="1"
              :inactive-value="0"
              inline-prompt
              active-text="发布"
              inactive-text="草稿"
            />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="开放校区">
        <div class="campus-field">
          <el-select
            v-model="form.campus_ids"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择开放校区（可多选，全选即对全部校区开放）"
            class="campus-field__select"
          >
            <el-option v-for="campus in campuses" :key="campus.id" :label="campus.name" :value="Number(campus.id)" />
          </el-select>
          <el-checkbox
            :model-value="allCampusesSelected"
            :indeterminate="campusIndeterminate"
            :disabled="!campuses.length"
            @change="(value: any) => toggleAllCampuses(value === true)"
          >
            全选
          </el-checkbox>
        </div>
        <span class="campus-field__hint">
          已选 {{ form.campus_ids.length }} 个校区{{ form.campus_ids.length === 0 ? '（不限制，面向全部校区）' : '' }}
        </span>
      </el-form-item>
    </el-form>

    <p class="section-label">题型配置</p>
    <div v-for="(section, index) in form.sections" :key="index" class="section-block">
      <div class="section-head">
        <el-select v-model="section.type" style="width: 140px" @change="onSectionTypeChange(section)">
          <el-option v-for="type in QUESTION_TYPES" :key="type.value" :label="type.label" :value="type.value" />
        </el-select>
        <el-input v-model="section.description" placeholder="题型说明，如「单选题」" class="section-head__desc" />
        <el-radio-group v-model="section.mode" @change="() => onSectionModeChange(section)">
          <el-radio-button value="select">勾选题目</el-radio-button>
          <el-radio-button value="ratio">按比例抽题</el-radio-button>
        </el-radio-group>
        <el-button link type="danger" @click="removeSection(index)">删除</el-button>
      </div>
      <div class="section-body">
        <template v-if="section.mode === 'select'">
          <span class="section-head__count">已选 {{ section.question_ids.length }} 题</span>
          <el-button link type="primary" @click="openPicker(index)">选择题库</el-button>
        </template>
        <template v-else>
          <span class="section-head__count">抽取题数</span>
          <el-input-number v-model="section.ratio" :min="1" :max="999" style="width: 140px" />
          <span class="section-head__count">
            题库可用 {{ section.poolCount === null ? '—' : section.poolCount }} 题
          </span>
          <el-button link type="primary" :loading="section.poolLoading" @click="loadPool(section)">刷新</el-button>
        </template>
        <span class="section-head__count section-body__score">每题分值</span>
        <el-input-number v-model="section.score" :min="0" :max="100" style="width: 130px" />
      </div>
    </div>
    <el-button @click="addSection">增加题型</el-button>

    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="pickerVisible" :lock-scroll="false" title="从题库选择题目" width="680px" append-to-body>
    <div class="picker-toolbar">
      <span class="picker-toolbar__count">
        已选 <b>{{ form.sections[activeSection]?.question_ids.length ?? 0 }}</b> 题
        <span class="picker-toolbar__total">/ 共 {{ pickerOptions.length }} 题</span>
      </span>
      <el-button
        v-if="form.sections[activeSection]?.question_ids.length"
        link
        type="danger"
        @click="clearPicked"
      >
        清空已选
      </el-button>
    </div>
    <el-table
      :data="pickerOptions"
      row-key="id"
      max-height="420"
      empty-text="该题型暂无题目"
      :row-class-name="({ row }: any) => (usedByOtherSections(row.id) ? 'picker-row--disabled' : '')"
      @row-click="(row: any) => !usedByOtherSections(row.id) && toggleQuestion(row.id)"
    >
      <el-table-column width="56">
        <template #default="{ row }">
          <el-checkbox
            :model-value="form.sections[activeSection]?.question_ids.includes(row.id)"
            :disabled="usedByOtherSections(row.id)"
            @click.stop
            @change="() => toggleQuestion(row.id)"
          />
        </template>
      </el-table-column>
      <el-table-column prop="title" label="题目" min-width="240" show-overflow-tooltip />
      <el-table-column prop="score" label="分值" min-width="90" align="right" />
      <el-table-column label="状态" width="90" align="center">
        <template #default="{ row }">
          <el-tag v-if="usedByOtherSections(row.id)" type="info" size="small" effect="light">他组已选</el-tag>
        </template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-button type="primary" @click="pickerVisible = false">确定</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="resultVisible" :lock-scroll="false" title="考试结果" width="760px" append-to-body>
    <el-table :data="resultAttempts" row-key="id" empty-text="暂无考试记录">
      <el-table-column prop="display_name" label="学员" min-width="160" />
      <el-table-column prop="total_score" label="成绩" min-width="100" align="right" />
      <el-table-column label="状态" min-width="120">
        <template #default="{ row }">
          <el-tag :type="row.status === 1 ? 'success' : 'info'" effect="light">{{ row.status === 1 ? '已交卷' : '进行中' }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
  </el-dialog>

  <el-dialog v-model="contentVisible" :lock-scroll="false" title="试卷内容" width="860px" top="5vh" append-to-body>
    <div v-loading="contentLoading" class="paper-content">
      <template v-if="contentExam">
        <div class="paper-head">
          <div class="paper-head__title">{{ contentExam.title }}</div>
          <div class="paper-head__stats">
            <span class="paper-stat"><b>{{ contentTotalQuestions }}</b> 题量</span>
            <span class="paper-stat"><b>{{ contentTotalScore }}</b> 总分</span>
            <span class="paper-stat"><b>{{ contentExam.duration }}</b> 分钟</span>
            <span class="paper-stat"><b>{{ contentExam.pass_score }}</b> 合格线</span>
          </div>
        </div>
        <div v-for="(section, sIndex) in contentSections" :key="section.id" class="paper-section">
          <div class="paper-section__head">
            <span class="paper-section__index">{{ sIndex + 1 }}</span>
            <span class="paper-section__title">{{ section.description || typeLabel(section.type) }}</span>
            <el-tag size="small" effect="plain" class="paper-section__type">{{ typeLabel(section.type) }}</el-tag>
            <span class="paper-section__count">
              {{ section.questions.length }} 题{{ section.score ? ` · 每题 ${section.score} 分` : '' }}
            </span>
          </div>
          <ol class="paper-question-list">
            <li v-for="question in section.questions" :key="question.id" class="paper-question">
              <div class="paper-question__title">
                <span class="paper-question__text">{{ question.title }}</span>
                <span class="paper-question__score">{{ question.score }} 分</span>
              </div>
              <div v-if="parseOptions(question.options).length" class="paper-question__options">
                <span v-for="option in parseOptions(question.options)" :key="option.key" class="paper-option">
                  <em class="paper-option__key">{{ option.key }}</em>
                  <span class="paper-option__text">{{ option.text }}</span>
                </span>
              </div>
            </li>
          </ol>
        </div>
        <el-empty v-if="!contentSections.length" description="该试卷暂无题目" />
      </template>
    </div>
    <template #footer>
      <el-button type="primary" @click="contentVisible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.exam-page {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
}
.exam-page > .data-page {
  flex: 1;
  min-height: 0;
}
.exam-stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-4);
}
.exam-stats__item {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  white-space: nowrap;
}
.exam-stats__item b {
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--text-strong);
  font-variant-numeric: tabular-nums;
}
.exam-stats__pending {
  color: var(--warning) !important;
}
.campus-field {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
}
.campus-field__select {
  flex: 1;
}
.campus-field__hint {
  display: block;
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.section-label {
  margin-bottom: var(--space-3);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
}
.section-block {
  padding: var(--space-3);
  margin-bottom: var(--space-3);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--slate-25);
}
.section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}
.section-head__desc {
  width: 150px;
  flex: none;
}
.section-body {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--border-color);
}
.section-body__score {
  margin-left: auto;
}
.picker-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.picker-toolbar__count b {
  color: var(--brand-600);
  font-size: var(--text-md);
}
.picker-toolbar__total {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
.section-head__count {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  white-space: nowrap;
}
/* 状态按钮加大（左对齐缩放，不破坏布局） */
.exam-status-switch.el-switch {
  transform: scale(1.25);
  transform-origin: left center;
}
.paper-content {
  max-height: 64vh;
  overflow-y: auto;
  padding-right: var(--space-2);
}
/* 试卷头部：标题 + 统计 */
.paper-head {
  margin-bottom: var(--space-5);
  padding: var(--space-4) var(--space-5);
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, var(--brand-600), var(--brand-500));
  color: #fff;
}
.paper-head__title {
  font-size: var(--text-lg);
  font-weight: 700;
}
.paper-head__stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-5);
  margin-top: var(--space-3);
}
.paper-stat {
  display: inline-flex;
  align-items: baseline;
  gap: var(--space-1);
  font-size: var(--text-sm);
  color: rgba(255, 255, 255, 0.85);
}
.paper-stat b {
  font-size: var(--text-lg);
  font-weight: 700;
  color: #fff;
}
/* 题型分组卡片 */
.paper-section {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  overflow: hidden;
}
.paper-section + .paper-section {
  margin-top: var(--space-4);
}
.paper-section__head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--slate-50);
  border-bottom: 1px solid var(--border-color);
}
.paper-section__index {
  display: grid;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  place-items: center;
  border-radius: var(--radius-sm);
  background: var(--brand-500);
  color: #fff;
  font-size: var(--text-sm);
  font-weight: 700;
}
.paper-section__title {
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--text-strong);
}
.paper-section__type {
  flex-shrink: 0;
}
.paper-section__count {
  margin-left: auto;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  white-space: nowrap;
}
.paper-question-list {
  margin: 0;
  padding: var(--space-4) var(--space-5) var(--space-4) var(--space-8);
  list-style: decimal;
}
.paper-question + .paper-question {
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px dashed var(--border-color);
}
.paper-question::marker {
  color: var(--brand-500);
  font-weight: 700;
}
.paper-question__title {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  font-weight: 500;
  color: var(--text-primary);
  line-height: var(--leading-normal);
}
.paper-question__text {
  flex: 1;
  min-width: 0;
}
.paper-question__score {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.paper-question__options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2) var(--space-4);
  margin-top: var(--space-3);
  font-size: var(--text-sm);
}
.paper-option {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  color: var(--text-secondary);
}
.paper-option__key {
  display: grid;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  place-items: center;
  border-radius: var(--radius-pill);
  background: var(--slate-100);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-style: normal;
  font-weight: 600;
}
.paper-option__text {
  line-height: 1.5;
  word-break: break-word;
}
</style>

<!-- 非 scoped：选择题目弹窗 append-to-body，需全局样式标记「他组已选」行 -->
<style>
.picker-row--disabled,
.picker-row--disabled:hover > td.el-table__cell {
  opacity: 0.5;
  cursor: not-allowed;
  background: var(--slate-50);
}
</style>

