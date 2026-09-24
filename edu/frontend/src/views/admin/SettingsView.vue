<script setup lang="ts">
// 系统配置：基础信息、友情链接、首页背景与模拟考试参数。
import { Plus } from '@element-plus/icons-vue'
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { getAdminConfig, saveConfig } from '@/api/admin'
import { getQuestionTypes } from '@/api/portal'
import StatusSwitch from '@/components/status-switch.vue'
import { api, errorMessage } from '@/lib/api'
import { STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'
import { applySystemConfig } from '@/lib/system-config'

const activeTab = ref('basic')

const basic = reactive({ systemName: '', logo: '' })
const friendLinks = ref<{ name: string; url: string; sort: number; status: number }[]>([])
const linkDialogVisible = ref(false)
const linkEditingIndex = ref<number | null>(null)
const linkSaving = ref(false)
const linkForm = reactive({ name: '', url: '', sort: 1, status: 1 })
const backgrounds = ref<{ url: string; sort: number; status: number }[]>([])
const bgDialogVisible = ref(false)
const bgEditingIndex = ref<number | null>(null)
const bgSaving = ref(false)
const bgForm = reactive({ url: '', sort: 1, status: 1 })
const exam = reactive({ title: '模拟考试', total: '20', duration: '30' })
interface ExamTypeRow {
  code: string
  name: string
  checked: boolean
  ratio: number
}
const examTypes = ref<ExamTypeRow[]>([])
const examRatioSum = computed(() =>
  examTypes.value.filter((type) => type.checked).reduce((sum, type) => sum + (Number(type.ratio) || 0), 0),
)

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
    backgrounds.value = JSON.parse(config.homeBackgrounds || '[]')
  } catch {
    backgrounds.value = []
  }
  exam.title = config.autoExamTitle ?? '模拟考试'
  exam.total = config.autoExamTotal ?? '20'
  exam.duration = config.autoExamDuration ?? '30'
  let ratios: Record<string, number> = {}
  try {
    ratios = JSON.parse(config.autoExamRatios || '{}')
  } catch {
    ratios = {}
  }
  const types = await getQuestionTypes()
  examTypes.value = types.map((type) => ({
    code: type.code,
    name: type.name,
    checked: Number(ratios[type.code] || 0) > 0,
    ratio: Number(ratios[type.code] || 0),
  }))
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
  const result = await saveConfig({ homeBackgrounds: JSON.stringify(backgrounds.value) })
  if (result.success) {
    ElMessage.success('首页背景已保存')
    return true
  }
  ElMessage.error(result.message || '保存失败')
  return false
}

function openCreateBackground() {
  bgEditingIndex.value = null
  Object.assign(bgForm, { url: '', sort: backgrounds.value.length + 1, status: 1 })
  bgDialogVisible.value = true
}

function openEditBackground(index: number) {
  bgEditingIndex.value = index
  const row = backgrounds.value[index]
  Object.assign(bgForm, { url: row.url, sort: row.sort, status: row.status })
  bgDialogVisible.value = true
}

async function saveBackground() {
  if (!bgForm.url.trim()) {
    ElMessage.warning('请填写图片 URL')
    return
  }
  const duplicated = backgrounds.value.some(
    (item, index) => index !== bgEditingIndex.value && item.sort === bgForm.sort,
  )
  if (duplicated) {
    ElMessage.warning('排序值已存在，请使用其他序号')
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
  const result = await saveConfig({ homeBackgrounds: JSON.stringify(backgrounds.value) })
  if (result.success) {
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
  const checked = examTypes.value.filter((type) => type.checked)
  if (!checked.length) {
    ElMessage.warning('请至少选择一种题型')
    return
  }
  const sum = checked.reduce((total, type) => total + (Number(type.ratio) || 0), 0)
  if (sum !== 100) {
    ElMessage.warning(`已选题型比例合计需为 100%，当前为 ${sum}%`)
    return
  }
  const ratios: Record<string, number> = {}
  for (const type of examTypes.value) {
    ratios[type.code] = type.checked ? Number(type.ratio) || 0 : 0
  }
  const result = await saveConfig({
    autoExamEnabled: 'true',
    autoExamTitle: exam.title,
    autoExamTotal: exam.total,
    autoExamDuration: exam.duration,
    autoExamRatios: JSON.stringify(ratios),
    autoExamCategories: '[]',
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
                  <div v-if="basic.logo" class="logo-preview" :style="{ backgroundImage: `url(/api/image/${basic.logo})` }" />
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
            <div class="section-toolbar">
              <el-button type="primary" :icon="Plus" @click="openCreateBackground">新增背景</el-button>
            </div>
            <el-table :data="backgrounds" empty-text="暂无背景图">
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
            <el-form label-position="top" class="settings-form">
              <el-form-item label="试卷标题"><el-input v-model="exam.title" /></el-form-item>
              <el-row :gutter="16">
                <el-col :span="12"><el-form-item label="题目数量"><el-input v-model="exam.total" /></el-form-item></el-col>
                <el-col :span="12"><el-form-item label="时长（分钟）"><el-input v-model="exam.duration" /></el-form-item></el-col>
              </el-row>
              <el-form-item label="题型配置">
                <div class="type-config">
                  <div v-for="type in examTypes" :key="type.code" class="type-config__row" :class="{ 'is-muted': !type.checked }">
                    <el-checkbox v-model="type.checked">{{ type.name }}</el-checkbox>
                    <div class="type-config__ratio">
                      <el-input-number
                        v-model="type.ratio"
                        :min="0"
                        :max="100"
                        :step="5"
                        controls-position="right"
                        size="small"
                      />
                      <span class="type-config__unit">%</span>
                    </div>
                  </div>
                  <p v-if="examTypes.length" class="type-config__sum" :class="{ 'is-valid': examRatioSum === 100 }">
                    已选题型比例合计：{{ examRatioSum }}%（需等于 100%）
                  </p>
                  <p v-else class="type-config__empty">暂无题型，请先在「字典管理」中维护练习类型枚举值</p>
                </div>
              </el-form-item>
              <el-form-item><el-button type="primary" @click="saveExam">保存模拟考试配置</el-button></el-form-item>
            </el-form>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

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
.type-config {
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: var(--space-3);
}
.type-config__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-4);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
}
.type-config__ratio {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  transition: opacity var(--duration-fast) var(--ease-out);
}
.type-config__row.is-muted .type-config__ratio {
  opacity: 0.45;
}
.type-config__ratio .el-input-number {
  width: 120px;
}
.type-config__unit {
  color: var(--text-secondary);
  font-size: var(--text-sm);
}
.type-config__sum {
  font-size: var(--text-sm);
  color: var(--danger);
}
.type-config__sum.is-valid {
  color: var(--success);
}
.type-config__empty {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}
</style>

