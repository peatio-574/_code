<script setup lang="ts">
// 系统配置：基础信息、友情链接、首页背景与模拟考试参数。
import { Plus, Search } from '@element-plus/icons-vue'
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { getAdminConfig, listQuestionCategories, listQuestions, saveConfig } from '@/api/admin'
import StatusSwitch from '@/components/status-switch.vue'
import { api, errorMessage } from '@/lib/api'
import { STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'
import { applySystemConfig, resolveImageUrl } from '@/lib/system-config'

const activeTab = ref('basic')

const basic = reactive({ systemName: '', logo: '' })
const friendLinks = ref<{ name: string; url: string; sort: number; status: number }[]>([])
const linkDialogVisible = ref(false)
const linkEditingIndex = ref<number | null>(null)
const linkSaving = ref(false)
const linkForm = reactive({ name: '', url: '', sort: 1, status: 1 })
type BackgroundScene = 'home' | 'banner'
const SCENE_LABELS: Record<BackgroundScene, string> = { home: '首页', banner: 'banner' }
const backgrounds = ref<{ url: string; sort: number; status: number; scene: BackgroundScene }[]>([])
const bgDialogVisible = ref(false)
const bgEditingIndex = ref<number | null>(null)
const bgSaving = ref(false)
const bgForm = reactive<{ url: string; sort: number; status: number; scene: BackgroundScene }>({
  url: '',
  sort: 1,
  status: 1,
  scene: 'home',
})

function sceneLabel(scene: string | undefined): string {
  return SCENE_LABELS[(scene as BackgroundScene) || 'home'] ?? '首页'
}
const QUESTION_TYPES = [
  { value: 'single', label: '单选题' },
  { value: 'multiple', label: '多选题' },
  { value: 'true_false', label: '判断题' },
  { value: 'fill', label: '填空题' },
  { value: 'qa', label: '问答题' },
  { value: 'group', label: '综合答题' },
]

const exam = reactive({ title: '模拟考试', duration: 60 })
// 题目方向（单选）
const examDirections = ref<{ id: number; name: string }[]>([])
// 题型分组：与「新增试卷」一致，每组含题型、题目方向（单选）、取题方式（勾选/按比例）、抽取题数、每题分值
interface ExamSectionRow {
  type: string
  directionId: number | null
  mode: 'select' | 'ratio'
  question_ids: number[]
  ratio: number
  score: number
  poolCount: number | null
  poolLoading: boolean
}
const examSections = ref<ExamSectionRow[]>([])

function createExamSection(type = 'single'): ExamSectionRow {
  return {
    type,
    directionId: null,
    mode: 'ratio',
    question_ids: [],
    ratio: 10,
    score: 1,
    poolCount: null,
    poolLoading: false,
  }
}

const examTotalQuestions = computed(() =>
  examSections.value.reduce(
    (sum, section) => sum + (section.mode === 'select' ? section.question_ids.length : Number(section.ratio) || 0),
    0,
  ),
)

function addExamSection() {
  examSections.value.push(createExamSection('single'))
}

function removeExamSection(index: number) {
  examSections.value.splice(index, 1)
}

// 选择题库弹窗
const pickerVisible = ref(false)
const pickerOptions = ref<Record<string, any>[]>([])
const pickerKeyword = ref('')
const pickerPage = ref(1)
const pickerTotal = ref(0)
const pickerLoading = ref(false)
const PICKER_PAGE_SIZE = 20
const activeExamSection = ref(0)

function onExamSectionTypeChange(section: ExamSectionRow) {
  section.question_ids = []
  section.poolCount = null
  if (section.mode === 'ratio') void loadExamPool(section)
}

function onExamSectionDirectionChange(section: ExamSectionRow) {
  section.question_ids = []
  section.poolCount = null
  if (section.mode === 'ratio') void loadExamPool(section)
}

async function loadExamPool(section: ExamSectionRow) {
  section.poolLoading = true
  try {
    const exclude = examOtherUsedIds(section)
    const response = await api.get('/api/admin/questions/pool-count', {
      params: {
        type: section.type,
        category_id: section.directionId || undefined,
        exclude: exclude.join(',') || undefined,
      },
    })
    section.poolCount = Number(response.data?.data?.count ?? 0)
  } catch {
    section.poolCount = null
  } finally {
    section.poolLoading = false
  }
}

function onExamSectionModeChange(section: ExamSectionRow) {
  if (section.mode === 'ratio' && section.poolCount === null) {
    void loadExamPool(section)
  }
}

/** 其他分组已占用的题目 id（用于跨分组去重）。 */
function examOtherUsedIds(section: ExamSectionRow): number[] {
  const ids: number[] = []
  examSections.value.forEach((item) => {
    if (item !== section) ids.push(...item.question_ids)
  })
  return ids
}

/** 勾选弹窗：判断该题是否已被其他分组占用（占用则禁选）。 */
function examUsedByOtherSections(id: number) {
  return examSections.value.some(
    (section, index) => index !== activeExamSection.value && section.question_ids.includes(id),
  )
}

async function loadExamPickerOptions() {
  pickerLoading.value = true
  try {
    const section = examSections.value[activeExamSection.value]
    const page = await listQuestions({
      p: pickerPage.value,
      page_size: PICKER_PAGE_SIZE,
      type: section?.type,
      category_id: section?.directionId || undefined,
      exclude: section ? examOtherUsedIds(section).join(',') || undefined : undefined,
      keyword: pickerKeyword.value || undefined,
      status: 1,
    })
    pickerOptions.value = page?.items ?? []
    pickerTotal.value = page?.total ?? 0
  } finally {
    pickerLoading.value = false
  }
}

async function openExamPicker(sectionIndex: number) {
  activeExamSection.value = sectionIndex
  pickerKeyword.value = ''
  pickerPage.value = 1
  pickerVisible.value = true
  await loadExamPickerOptions()
}

function searchExamPicker() {
  pickerPage.value = 1
  loadExamPickerOptions()
}

function toggleExamQuestion(id: number) {
  const section = examSections.value[activeExamSection.value]
  if (!section) return
  if (section.question_ids.includes(id)) {
    section.question_ids = section.question_ids.filter((value) => value !== id)
  } else {
    if (examUsedByOtherSections(id)) {
      ElMessage.warning('该题已被其他题型分组选用，不能重复选择')
      return
    }
    section.question_ids.push(id)
  }
}

function clearExamPicked() {
  const section = examSections.value[activeExamSection.value]
  if (section) section.question_ids = []
}

async function load() {
  const config = await getAdminConfig()
  basic.systemName = config.systemName ?? ''
  basic.logo = config.logo ?? ''
  try {
    friendLinks.value = JSON.parse(config.friendLinks || '[]')
  } catch {
    friendLinks.value = []
  }
  try {
    const parsed = JSON.parse(config.homeBackgrounds || '[]')
    // 兼容旧数据：未标注场景的背景按「首页」处理
    backgrounds.value = Array.isArray(parsed)
      ? parsed.map((item: any) => ({ ...item, scene: item.scene || 'home' }))
      : []
  } catch {
    backgrounds.value = []
  }
  exam.title = config.autoExamTitle ?? '模拟考试'
  exam.duration = Number(config.autoExamDuration ?? 60) || 60
  // 题目方向候选项
  try {
    examDirections.value = ((await listQuestionCategories())?.items ?? []).map((item: any) => ({
      id: Number(item.id),
      name: item.name,
    }))
  } catch {
    examDirections.value = []
  }
  // 题型分组：优先使用新配置 autoExamSections，其次兼容旧的按题型比例配置
  let sections: ExamSectionRow[] = []
  try {
    const parsed = JSON.parse(config.autoExamSections || '[]')
    if (Array.isArray(parsed)) {
      sections = parsed
        .filter((item: any) => item && QUESTION_TYPES.some((t) => t.value === item.type))
        .map((item: any) => ({
          type: item.type,
          directionId: Number(item.category_id) > 0 ? Number(item.category_id) : null,
          mode: item.mode === 'select' ? 'select' : 'ratio',
          question_ids: Array.isArray(item.question_ids)
            ? item.question_ids.map((v: any) => Number(v)).filter((v: number) => Number.isInteger(v) && v > 0)
            : [],
          ratio: Number(item.count) > 0 ? Number(item.count) : Number(item.ratio) || 0,
          score: Number(item.score) || 1,
          poolCount: null,
          poolLoading: false,
        }))
    }
  } catch {
    sections = []
  }
  if (!sections.length) {
    let ratios: Record<string, number> = {}
    try {
      ratios = JSON.parse(config.autoExamRatios || '{}')
    } catch {
      ratios = {}
    }
    let directionId: number | null = null
    try {
      const parsed = JSON.parse(config.autoExamCategories || '[]')
      const first = Array.isArray(parsed) ? parsed.find((v: any) => Number(v) > 0) : Number(parsed) || 0
      directionId = Number(first) > 0 ? Number(first) : null
    } catch {
      directionId = null
    }
    sections = QUESTION_TYPES.filter((type) => Number(ratios[type.value] || 0) > 0).map((type) => ({
      type: type.value,
      directionId,
      mode: 'ratio' as const,
      question_ids: [],
      ratio: Number(ratios[type.value] || 0),
      score: 1,
      poolCount: null,
      poolLoading: false,
    }))
  }
  examSections.value = sections.length ? sections : [createExamSection('single')]
}

async function saveBasic() {
  const result = await saveConfig(basic)
  if (result.success) {
    applySystemConfig({ systemName: basic.systemName, logo: basic.logo })
  }
  ElMessage[result.success ? 'success' : 'error'](result.success ? '已保存' : result.message || '保存失败')
}

async function persistLinks() {
  const result = await saveConfig({ friendLinks: JSON.stringify(friendLinks.value) })
  if (result.success) {
    ElMessage.success('友情链接已保存')
    applySystemConfig({ friendLinks: JSON.stringify(friendLinks.value) })
    return true
  }
  ElMessage.error(result.message || '保存失败')
  return false
}

function openCreateLink() {
  linkEditingIndex.value = null
  Object.assign(linkForm, { name: '', url: '', sort: friendLinks.value.length + 1, status: 1 })
  linkDialogVisible.value = true
}

function openEditLink(index: number) {
  linkEditingIndex.value = index
  const row = friendLinks.value[index]
  Object.assign(linkForm, { name: row.name, url: row.url, sort: row.sort, status: row.status })
  linkDialogVisible.value = true
}

async function saveLink() {
  if (!linkForm.name.trim() || !linkForm.url.trim()) {
    ElMessage.warning('请填写名称和链接地址')
    return
  }
  const duplicated = friendLinks.value.some(
    (item, index) => index !== linkEditingIndex.value && item.sort === linkForm.sort,
  )
  if (duplicated) {
    ElMessage.warning('排序值已存在，请使用其他序号')
    return
  }
  linkSaving.value = true
  try {
    const entry = { ...linkForm, name: linkForm.name.trim(), url: linkForm.url.trim() }
    if (linkEditingIndex.value === null) {
      friendLinks.value.push(entry)
    } else {
      friendLinks.value[linkEditingIndex.value] = entry
    }
    friendLinks.value.sort((a, b) => a.sort - b.sort)
    if (await persistLinks()) linkDialogVisible.value = false
  } finally {
    linkSaving.value = false
  }
}

async function toggleLink(row: { status: number }, next: number) {
  const previous = row.status
  row.status = next
  const result = await saveConfig({ friendLinks: JSON.stringify(friendLinks.value) })
  if (result.success) {
    applySystemConfig({ friendLinks: JSON.stringify(friendLinks.value) })
    ElMessage.success(statusChangeMessage(next))
  } else {
    row.status = previous
    ElMessage.error(result.message || STATUS_FAILURE_TEXT)
  }
}

async function removeLink(index: number) {
  try {
    await ElMessageBox.confirm(`确定删除友情链接“${friendLinks.value[index].name}”吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  friendLinks.value.splice(index, 1)
  await persistLinks()
}

async function persistBackgrounds() {
  const payload = JSON.stringify(backgrounds.value)
  const result = await saveConfig({ homeBackgrounds: payload })
  if (result.success) {
    ElMessage.success('背景图已保存')
    applySystemConfig({ homeBackgrounds: payload })
    return true
  }
  ElMessage.error(result.message || '保存失败')
  return false
}

function openCreateBackground() {
  bgEditingIndex.value = null
  Object.assign(bgForm, { url: '', sort: backgrounds.value.length + 1, status: 1, scene: 'home' })
  bgDialogVisible.value = true
}

function openEditBackground(index: number) {
  bgEditingIndex.value = index
  const row = backgrounds.value[index]
  Object.assign(bgForm, { url: row.url, sort: row.sort, status: row.status, scene: row.scene || 'home' })
  bgDialogVisible.value = true
}

async function saveBackground() {
  if (!bgForm.url.trim()) {
    ElMessage.warning('请填写图片 URL')
    return
  }
  const duplicated = backgrounds.value.some(
    (item, index) =>
      index !== bgEditingIndex.value && item.sort === bgForm.sort && (item.scene || 'home') === bgForm.scene,
  )
  if (duplicated) {
    ElMessage.warning('同一场景下排序值已存在，请使用其他序号')
    return
  }
  bgSaving.value = true
  try {
    const entry = { ...bgForm, url: bgForm.url.trim() }
    if (bgEditingIndex.value === null) {
      backgrounds.value.push(entry)
    } else {
      backgrounds.value[bgEditingIndex.value] = entry
    }
    backgrounds.value.sort((a, b) => a.sort - b.sort)
    if (await persistBackgrounds()) bgDialogVisible.value = false
  } finally {
    bgSaving.value = false
  }
}

async function toggleBackground(row: { status: number }, next: number) {
  const previous = row.status
  row.status = next
  const payload = JSON.stringify(backgrounds.value)
  const result = await saveConfig({ homeBackgrounds: payload })
  if (result.success) {
    applySystemConfig({ homeBackgrounds: payload })
    ElMessage.success(statusChangeMessage(next))
  } else {
    row.status = previous
    ElMessage.error(result.message || STATUS_FAILURE_TEXT)
  }
}

async function removeBackground(index: number) {
  try {
    await ElMessageBox.confirm('确定删除该背景图吗？', '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  backgrounds.value.splice(index, 1)
  await persistBackgrounds()
}

async function saveExam() {
  if (!examSections.value.length) {
    ElMessage.warning('请至少配置一种题型')
    return
  }
  const missingType = examSections.value.findIndex((section) => !section.type)
  if (missingType !== -1) {
    ElMessage.warning(`第 ${missingType + 1} 个分组请选择题型`)
    return
  }
  for (let i = 0; i < examSections.value.length; i += 1) {
    const section = examSections.value[i]
    if (section.mode === 'select') {
      if (!section.question_ids.length) {
        ElMessage.warning(`第 ${i + 1} 个分组请勾选题目`)
        return
      }
    } else if (Number(section.ratio) <= 0) {
      ElMessage.warning(`第 ${i + 1} 个分组请填写抽取题数`)
      return
    }
  }
  const sections = examSections.value.map((section) => ({
    type: section.type,
    category_id: Number(section.directionId) || 0,
    mode: section.mode,
    count: section.mode === 'select' ? section.question_ids.length : Number(section.ratio) || 0,
    score: Number(section.score) || 0,
    question_ids: section.mode === 'select' ? [...section.question_ids] : [],
  }))
  const firstDirection = sections.find((section) => section.category_id > 0)?.category_id ?? 0
  const result = await saveConfig({
    autoExamEnabled: 'true',
    autoExamTitle: exam.title,
    autoExamTotal: String(examTotalQuestions.value || sections.length),
    autoExamDuration: String(exam.duration),
    autoExamSections: JSON.stringify(sections),
    autoExamCategories: JSON.stringify(firstDirection ? [firstDirection] : []),
    autoExamIncludeGroup: 'false',
  })
  ElMessage[result.success ? 'success' : 'error'](result.success ? '模拟考试配置已保存' : result.message || '保存失败')
}

async function uploadLogo(options: any) {
  const formData = new FormData()
  formData.append('file', options.file)
  try {
    const response = await api.post('/api/file/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    basic.logo = response.data?.data?.id ?? ''
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function uploadBackground(options: any) {
  const formData = new FormData()
  formData.append('file', options.file)
  try {
    const response = await api.post('/api/file/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    const fileId = response.data?.data?.id
    if (fileId) {
      bgForm.url = `${window.location.origin}/api/image/${fileId}`
      ElMessage.success('图片上传成功')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

onMounted(load)
</script>

<template>
  <div class="settings-page">
    <el-card class="settings-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="基础信息" name="basic">
          <div class="settings-section">
            <el-form label-position="top" class="settings-form">
              <el-form-item label="系统名称"><el-input v-model="basic.systemName" placeholder="显示在页面顶部的系统名称" /></el-form-item>
              <el-form-item label="系统 Logo">
                <div class="logo-field">
                  <div v-if="basic.logo" class="logo-preview" :style="{ backgroundImage: `url(${resolveImageUrl(basic.logo)})` }" />
                  <div v-else class="logo-placeholder">暂无 Logo</div>
                  <div class="logo-actions">
                    <el-upload :show-file-list="false" :http-request="uploadLogo" accept="image/*">
                      <el-button>{{ basic.logo ? '重新上传' : '上传 Logo' }}</el-button>
                    </el-upload>
                  </div>
                </div>
              </el-form-item>
              <el-form-item><el-button type="primary" @click="saveBasic">保存基础信息</el-button></el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <el-tab-pane label="友情链接" name="links">
          <div class="settings-section">
            <div class="section-toolbar">
              <el-button type="primary" :icon="Plus" @click="openCreateLink">新增链接</el-button>
            </div>
            <el-table :data="friendLinks" empty-text="暂无友情链接">
              <el-table-column prop="name" label="名称" min-width="160" />
              <el-table-column label="链接地址" min-width="260">
                <template #default="{ row }">
                  <a :href="row.url" target="_blank" rel="noopener noreferrer" class="link-url">{{ row.url }}</a>
                </template>
              </el-table-column>
              <el-table-column prop="sort" label="排序" min-width="90" align="center" />
              <el-table-column label="状态" min-width="120">
                <template #default="{ row }">
                  <StatusSwitch :status="row.status" @change="(next) => toggleLink(row, next)" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="140">
                <template #default="{ $index }">
                  <div class="row-actions">
                    <el-button link type="primary" @click="openEditLink($index)">编辑</el-button>
                    <el-button link type="danger" @click="removeLink($index)">删除</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <el-tab-pane label="首页背景" name="backgrounds">
          <div class="settings-section">
            <p class="settings-section__hint">「首页」用于首页轮播背景；「banner」用于课程中心等页面顶部背景图。</p>
            <div class="section-toolbar">
              <el-button type="primary" :icon="Plus" @click="openCreateBackground">新增背景</el-button>
            </div>
            <el-table :data="backgrounds" empty-text="暂无背景图">
              <el-table-column label="应用场景" width="120" align="center">
                <template #default="{ row }">
                  <el-tag :type="(row.scene || 'home') === 'banner' ? 'warning' : 'primary'" effect="light">
                    {{ sceneLabel(row.scene) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="预览" width="120">
                <template #default="{ row }">
                  <div class="bg-thumb" :style="{ backgroundImage: `url(${row.url})` }" />
                </template>
              </el-table-column>
              <el-table-column label="图片 URL" min-width="320">
                <template #default="{ row }">
                  <a :href="row.url" target="_blank" rel="noopener noreferrer" class="link-url">{{ row.url }}</a>
                </template>
              </el-table-column>
              <el-table-column prop="sort" label="排序" min-width="90" align="center" />
              <el-table-column label="状态" min-width="120">
                <template #default="{ row }">
                  <StatusSwitch :status="row.status" @change="(next) => toggleBackground(row, next)" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="140">
                <template #default="{ $index }">
                  <div class="row-actions">
                    <el-button link type="primary" @click="openEditBackground($index)">编辑</el-button>
                    <el-button link type="danger" @click="removeBackground($index)">删除</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <el-tab-pane label="模拟考试" name="exam">
          <div class="settings-section">
            <el-form label-position="top" class="exam-form">
              <el-row :gutter="16">
                <el-col :span="24">
                  <el-form-item label="试卷名称" required>
                    <el-input v-model="exam.title" placeholder="请输入试卷名称" />
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="16">
                <el-col :span="12">
                  <el-form-item label="时长（分钟）">
                    <el-input-number v-model="exam.duration" :min="1" style="width: 100%" />
                  </el-form-item>
                </el-col>
              </el-row>
            </el-form>

            <p class="section-label">题型配置</p>
            <div v-for="(section, index) in examSections" :key="index" class="section-block">
              <div class="section-head">
                <el-select
                  v-model="section.type"
                  placeholder="题型"
                  class="section-head__type"
                  @change="onExamSectionTypeChange(section)"
                >
                  <el-option v-for="type in QUESTION_TYPES" :key="type.value" :label="type.label" :value="type.value" />
                </el-select>
                <el-select
                  v-model="section.directionId"
                  placeholder="题目方向"
                  clearable
                  class="section-head__desc"
                  @change="onExamSectionDirectionChange(section)"
                >
                  <el-option
                    v-for="direction in examDirections"
                    :key="direction.id"
                    :label="direction.name"
                    :value="direction.id"
                  />
                </el-select>
                <el-radio-group v-model="section.mode" @change="() => onExamSectionModeChange(section)">
                  <el-radio-button value="select">勾选题目</el-radio-button>
                  <el-radio-button value="ratio">按比例抽题</el-radio-button>
                </el-radio-group>
                <el-button link type="danger" @click="removeExamSection(index)">删除</el-button>
              </div>
              <div class="section-body">
                <template v-if="section.mode === 'select'">
                  <span class="section-head__count">已选 {{ section.question_ids.length }} 题</span>
                  <el-button link type="primary" @click="openExamPicker(index)">选择题库</el-button>
                </template>
                <template v-else>
                  <span class="section-head__count">抽取题数</span>
                  <el-input-number v-model="section.ratio" :min="1" :max="999" style="width: 140px" />
                  <el-button
                    link
                    type="primary"
                    class="section-body__refresh"
                    :loading="section.poolLoading"
                    @click="loadExamPool(section)"
                  >
                    刷新
                  </el-button>
                  <span class="section-head__count section-body__pool">
                    题库可用 {{ section.poolCount === null ? '-' : section.poolCount }} 题
                  </span>
                </template>
                <span class="section-head__count">每题分值</span>
                <el-input-number v-model="section.score" :min="0" :max="100" style="width: 130px" />
              </div>
            </div>
            <el-button @click="addExamSection">增加题型</el-button>
            <div class="section-actions">
              <el-button type="primary" @click="saveExam">保存模拟考试配置</el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-dialog v-model="pickerVisible" :lock-scroll="false" title="从题库选择题目" width="680px" append-to-body>
      <div class="picker-toolbar">
        <el-input
          v-model="pickerKeyword"
          placeholder="搜索题目内容"
          clearable
          :prefix-icon="Search"
          class="picker-toolbar__search"
          @keyup.enter="searchExamPicker"
          @clear="searchExamPicker"
        />
        <span class="picker-toolbar__count">
          已选 <b>{{ examSections[activeExamSection]?.question_ids.length ?? 0 }}</b> 题
          <span class="picker-toolbar__total">/ 题库共 {{ pickerTotal }} 题</span>
        </span>
        <el-button
          v-if="examSections[activeExamSection]?.question_ids.length"
          link
          type="danger"
          @click="clearExamPicked"
        >
          清空已选
        </el-button>
      </div>
      <el-table
        v-loading="pickerLoading"
        :data="pickerOptions"
        row-key="id"
        max-height="420"
        empty-text="该题型暂无题目"
        :row-class-name="({ row }: any) => (examUsedByOtherSections(row.id) ? 'picker-row--disabled' : '')"
        @row-click="(row: any) => !examUsedByOtherSections(row.id) && toggleExamQuestion(row.id)"
      >
        <el-table-column width="56">
          <template #default="{ row }">
            <el-checkbox
              :model-value="examSections[activeExamSection]?.question_ids.includes(row.id)"
              :disabled="examUsedByOtherSections(row.id)"
              @click.stop
              @change="() => toggleExamQuestion(row.id)"
            />
          </template>
        </el-table-column>
        <el-table-column prop="title" label="题目" min-width="240" show-overflow-tooltip />
        <el-table-column prop="score" label="分值" min-width="90" align="right" />
      </el-table>
      <template #footer>
        <div class="picker-footer" style="display: flex; width: 100%; flex-wrap: nowrap; align-items: center; justify-content: space-between; gap: 12px">
          <span class="picker-footer__total" style="flex: none; white-space: nowrap; margin-left: -12px; margin-right: auto">
            共 {{ pickerTotal }} 题
          </span>
          <el-pagination
            :current-page="pickerPage"
            :page-size="PICKER_PAGE_SIZE"
            :total="pickerTotal"
            background
            layout="prev, pager, next"
            @current-change="(value: number) => { pickerPage = value; loadExamPickerOptions() }"
          />
          <el-button type="primary" @click="pickerVisible = false">确定</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="linkDialogVisible"
      :lock-scroll="false"
      :title="linkEditingIndex === null ? '新增友情链接' : '编辑友情链接'"
      width="480px"
      append-to-body
    >
      <el-form label-position="top">
        <el-form-item label="名称" required>
          <el-input v-model="linkForm.name" placeholder="如：关于我们" />
        </el-form-item>
        <el-form-item label="链接地址" required>
          <el-input v-model="linkForm.url" placeholder="https://..." />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="linkForm.sort" :min="0" style="width: 160px" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="linkForm.status" :active-value="1" :inactive-value="0" inline-prompt active-text="启用" inactive-text="禁用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="linkDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="linkSaving" @click="saveLink">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="bgDialogVisible"
      :lock-scroll="false"
      :title="bgEditingIndex === null ? '新增首页背景' : '编辑首页背景'"
      width="480px"
      append-to-body
    >
      <el-form label-position="top">
        <el-form-item label="应用场景" required>
          <el-select v-model="bgForm.scene" style="width: 100%">
            <el-option label="首页" value="home" />
            <el-option label="banner" value="banner" />
          </el-select>
        </el-form-item>
        <el-form-item label="图片 URL">
          <div class="bg-url-field">
            <el-input v-model="bgForm.url" placeholder="填写图片地址，或点击右侧上传" />
            <el-upload :show-file-list="false" :http-request="uploadBackground" accept="image/*">
              <el-button>上传图片</el-button>
            </el-upload>
          </div>
        </el-form-item>
        <div v-if="bgForm.url" class="bg-preview" :style="{ backgroundImage: `url(${bgForm.url})` }" />
        <el-form-item label="排序">
          <el-input-number v-model="bgForm.sort" :min="0" style="width: 160px" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="bgForm.status" :active-value="1" :inactive-value="0" inline-prompt active-text="启用" inactive-text="禁用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bgDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="bgSaving" @click="saveBackground">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.settings-page {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: var(--space-4);
  min-height: 0;
}
.settings-card {
  flex: 1;
  min-height: 0;
}
.settings-section__hint {
  margin-bottom: var(--space-5);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.section-toolbar {
  display: flex;
  justify-content: flex-start;
  margin-bottom: var(--space-4);
}
.link-url {
  color: var(--brand-500);
  word-break: break-all;
}
.link-url:hover {
  text-decoration: underline;
}
.bg-thumb {
  width: 72px;
  height: 40px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--slate-50) center/cover no-repeat;
}
.bg-preview {
  width: 100%;
  height: 140px;
  margin-bottom: var(--space-4);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--slate-50) center/cover no-repeat;
}
.bg-url-field {
  display: flex;
  gap: var(--space-2);
  width: 100%;
}
.bg-url-field .el-input {
  flex: 1;
}
.settings-form {
  max-width: 560px;
}
.settings-form--wide {
  max-width: 900px;
}
.actions {
  display: flex;
  gap: var(--space-3);
  margin-top: var(--space-4);
}
.logo-field {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}
.logo-preview {
  width: 72px;
  height: 72px;
  flex-shrink: 0;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--slate-50) center/contain no-repeat;
}
.logo-placeholder {
  display: grid;
  width: 72px;
  height: 72px;
  flex-shrink: 0;
  place-items: center;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
.logo-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}
/* 题型配置：与「考试管理-新增试卷」完全一致的区块式布局 */
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
.section-head__type {
  width: 130px;
  flex: none;
}
.section-head__desc {
  width: 360px;
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
.section-head__count {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  white-space: nowrap;
}
.section-body__pool {
  min-width: 150px;
}
.section-body__refresh {
  width: 64px;
  align-self: center;
  justify-content: center;
  margin: 0;
}
.section-actions {
  margin-top: var(--space-4);
}
/* 选择题库弹窗（与「考试管理-新增试卷」一致） */
.picker-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.picker-toolbar__search {
  width: 240px;
}
.picker-toolbar__count {
  margin-left: auto;
  white-space: nowrap;
}
.picker-toolbar__count b {
  color: var(--brand-600);
  font-size: var(--text-md);
}
.picker-toolbar__total {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
.picker-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.picker-footer__total {
  font-size: var(--text-sm);
  color: var(--text-secondary);
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

