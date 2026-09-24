<script setup lang="ts">
// 题库管理：练习类型配置、题目 CRUD、批量删除与导入。
import { Plus, Search, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import {
  batchDeleteQuestions,
  createQuestion,
  createQuestionCategory,
  deleteQuestion,
  deleteQuestionCategory,
  listQuestionCategories,
  listQuestions,
  toggleQuestion,
  updateQuestion,
  updateQuestionCategory,
} from '@/api/admin'
import DataPage from '@/components/data-page.vue'
import StatusSwitch from '@/components/status-switch.vue'
import { api } from '@/lib/api'
import { formatDateTime, STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'

const QUESTION_TYPES = [
  { value: 'single', label: '单选题' },
  { value: 'multiple', label: '多选题' },
  { value: 'true_false', label: '判断题' },
  { value: 'fill', label: '填空题' },
  { value: 'qa', label: '问答题' },
  { value: 'group', label: '综合答题' },
]

const loading = ref(false)
const items = ref<Record<string, any>[]>([])
const total = ref(0)
const categories = ref<Record<string, any>[]>([])
const query = reactive({ p: 1, page_size: 20, keyword: '', type: '', category_id: '', status: '' })
const selection = ref<Record<string, any>[]>([])

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  type: 'single',
  title: '',
  options: '',
  answer: '',
  explanation: '',
  status: 1,
  category_id: 0,
  score: 1,
})

const categoryVisible = ref(false)
const categoryForm = reactive({ id: 0, name: '', sort_order: 0, status: 1 })

async function load() {
  loading.value = true
  try {
    const page = await listQuestions({
      p: query.p,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      type: query.type || undefined,
      category_id: query.category_id || undefined,
      status: query.status || undefined,
    })
    items.value = page?.items ?? []
    total.value = page?.total ?? 0
  } finally {
    loading.value = false
  }
}

function reset() {
  Object.assign(query, { keyword: '', type: '', category_id: '', status: '', p: 1 })
  load()
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { type: 'single', title: '', options: '', answer: '', explanation: '', status: 1, category_id: 0, score: 1 })
  dialogVisible.value = true
}

async function openEdit(row: Record<string, any>) {
  const detail = await api.get(`/api/admin/question/${row.id}`)
  const question = detail.data?.data?.question
  editingId.value = row.id
  Object.assign(form, {
    type: question.type,
    title: question.title,
    options: question.options,
    answer: question.answer,
    explanation: question.explanation,
    status: question.status === 2 ? 0 : 1,
    category_id: question.category_id,
    score: question.score,
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.title.trim()) {
    ElMessage.warning('请填写题目')
    return
  }
  const payload = { ...form, id: editingId.value ?? undefined }
  const result = editingId.value ? await updateQuestion(payload) : await createQuestion(payload)
  if (result.success) {
    ElMessage.success('保存成功')
    dialogVisible.value = false
    await load()
  } else {
    ElMessage.error(result.message || '保存失败')
  }
}

async function remove(row: Record<string, any>) {
  try {
    await ElMessageBox.confirm('确定删除该题目吗？', '删除确认', { type: 'warning' })
  } catch {
    return
  }
  const result = await deleteQuestion(row.id)
  if (result.success) {
    ElMessage.success('已删除')
    await load()
  }
}

async function batchRemove() {
  if (!selection.value.length) {
    ElMessage.warning('请选择要删除的题目')
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${selection.value.length} 道题吗？`, '批量删除', { type: 'warning' })
  } catch {
    return
  }
  await batchDeleteQuestions(selection.value.map((row) => row.id))
  ElMessage.success('已删除')
  await load()
}

async function loadCategories() {
  const data = await listQuestionCategories()
  categories.value = data?.items ?? []
}

async function saveCategory() {
  if (!categoryForm.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  const result = categoryForm.id
    ? await updateQuestionCategory(categoryForm)
    : await createQuestionCategory(categoryForm)
  if (result.success) {
    ElMessage.success('已保存')
    categoryForm.id = 0
    categoryForm.name = ''
    await loadCategories()
  } else {
    ElMessage.error(result.message || '保存失败')
  }
}

async function removeCategory(row: Record<string, any>) {
  const result = await deleteQuestionCategory(row.id)
  if (result.success) {
    ElMessage.success('已删除')
    await loadCategories()
  }
}

function editCategory(row: Record<string, any>) {
  Object.assign(categoryForm, { id: row.id, name: row.name, sort_order: row.sort_order, status: row.status })
}

async function importFile(options: any) {
  // 简化导入：读取 CSV（题型,标题,答案,分值）
  const text = await options.file.text()
  const lines = text.split(/\r?\n/).filter((line: string) => line.trim())
  let imported = 0
  for (const line of lines.slice(1)) {
    const [type, title, answer, score] = line.split(',')
    if (!title) continue
    try {
      await createQuestion({ type: type?.trim() || 'single', title: title.trim(), answer: (answer || '').trim(), score: Number(score) || 1 })
      imported += 1
    } catch {
      /* skip */
    }
  }
  ElMessage.success(`已导入 ${imported} 道题`)
  await load()
}

async function toggleStatus(row: Record<string, any>, next: number) {
  const previous = row.status
  row.status = next
  const result = await toggleQuestion(row.id, next)
  if (!result.success) {
    row.status = previous
    ElMessage.error(result.message || STATUS_FAILURE_TEXT)
  } else {
    ElMessage.success(statusChangeMessage(next))
  }
}

onMounted(async () => {
  await loadCategories()
  await load()
})
</script>

<template>
  <DataPage
    title="题库管理"
    description="维护练习题与练习类型；练习类型也可在「字典管理 → 练习类型」中统一维护。"
    :total="total"
    :page="query.p"
    :page-size="query.page_size"
    :loading="loading"
    @update:page="(value) => (query.p = value)"
    @update:page-size="(value) => (query.page_size = value)"
    @change="load"
  >
    <template #actions>
      <el-upload :show-file-list="false" :http-request="importFile" accept=".csv">
        <el-button :icon="Upload">导入题目</el-button>
      </el-upload>
      <el-button type="primary" :icon="Plus" @click="openCreate">添加题目</el-button>
    </template>

    <template #filters>
      <el-input
        v-model="query.keyword"
        placeholder="题目关键词"
        clearable
        :prefix-icon="Search"
        @keyup.enter="() => { query.p = 1; load() }"
      />
      <el-select v-model="query.type" placeholder="题型" clearable style="width: 160px">
        <el-option v-for="type in QUESTION_TYPES" :key="type.value" :label="type.label" :value="type.value" />
      </el-select>
      <el-select v-model="query.category_id" placeholder="练习类型" clearable style="width: 180px">
        <el-option v-for="category in categories" :key="category.id" :label="category.name" :value="String(category.id)" />
      </el-select>
      <el-button type="primary" @click="() => { query.p = 1; load() }">搜索</el-button>
      <el-button @click="reset">重置</el-button>
      <span class="toolbar-spacer" />
      <el-button @click="categoryVisible = true">练习类型配置</el-button>
      <el-button type="danger" plain :disabled="!selection.length" @click="batchRemove">
        批量删除{{ selection.length ? `（${selection.length}）` : '' }}
      </el-button>
    </template>

    <el-table
      :data="items"
      row-key="id"
      height="100%"
      empty-text="暂无题目，点击右上角「添加题目」开始"
      @selection-change="(rows: any[]) => (selection = rows)"
    >
      <el-table-column type="selection" width="48" />
      <el-table-column label="题目" min-width="280">
        <template #default="{ row }">
          <div class="question-cell">
            <el-tag size="small" effect="plain" class="question-cell__type">
              {{ QUESTION_TYPES.find((t) => t.value === row.type)?.label || row.type }}
            </el-tag>
            <span class="question-cell__title">{{ row.title }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="category_name" label="练习类型" min-width="140">
        <template #default="{ row }">{{ row.category_name || '未分类' }}</template>
      </el-table-column>
      <el-table-column label="分值" min-width="90" align="right">
        <template #default="{ row }"><span class="tabular">{{ row.score }} 分</span></template>
      </el-table-column>
      <el-table-column label="答案" min-width="140">
        <template #default="{ row }"><span class="cell-muted">{{ row.answer || '—' }}</span></template>
      </el-table-column>
      <el-table-column label="状态" min-width="160">
        <template #default="{ row }">
          <StatusSwitch :status="row.status" @change="(next) => toggleStatus(row, next)" />
        </template>
      </el-table-column>
      <el-table-column label="更新时间" min-width="180">
        <template #default="{ row }"><span class="cell-muted tabular">{{ formatDateTime(row.updated_at) }}</span></template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </DataPage>

  <el-dialog v-model="dialogVisible" :lock-scroll="false" :title="editingId ? '编辑题目' : '新增题目'" width="680px" append-to-body>
    <el-form label-position="top">
      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="题型">
            <el-select v-model="form.type" style="width: 100%">
              <el-option v-for="type in QUESTION_TYPES" :key="type.value" :label="type.label" :value="type.value" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="练习类型">
            <el-select v-model="form.category_id" style="width: 100%">
              <el-option label="未分类" :value="0" />
              <el-option v-for="category in categories" :key="category.id" :label="category.name" :value="category.id" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="题目内容" required>
        <el-input v-model="form.title" type="textarea" :rows="3" placeholder="请输入题干" />
      </el-form-item>
      <template v-if="form.type !== 'group'">
        <el-form-item label="选项">
          <el-input v-model="form.options" placeholder='JSON 格式，如 [{"key":"A","text":"选项A"}]' />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="正确答案"><el-input v-model="form.answer" placeholder="如 A 或 ABC" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="分值"><el-input-number v-model="form.score" :min="1" style="width: 100%" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="答案解析">
          <el-input v-model="form.explanation" type="textarea" :rows="2" placeholder="作答后展示的解析" />
        </el-form-item>
      </template>
      <el-form-item label="状态">
        <el-switch v-model="form.status" :active-value="1" :inactive-value="0" inline-prompt active-text="启用" inactive-text="禁用" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="categoryVisible" :lock-scroll="false" title="练习类型配置" width="560px" append-to-body>
    <div class="category-form">
      <el-input v-model="categoryForm.name" placeholder="练习类型名称" class="category-form__name" />
      <el-input-number v-model="categoryForm.sort_order" :min="0" placeholder="排序" />
      <el-button type="primary" @click="saveCategory">{{ categoryForm.id ? '更新' : '新增' }}</el-button>
      <el-button v-if="categoryForm.id" @click="categoryForm.id = 0, categoryForm.name = ''">取消</el-button>
    </div>
    <el-table :data="categories" row-key="id" empty-text="暂无练习类型">
      <el-table-column prop="name" label="练习类型" min-width="180" />
      <el-table-column prop="sort_order" label="排序" min-width="90" align="right" />
      <el-table-column label="操作" min-width="140">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button link type="primary" @click="editCategory(row)">编辑</el-button>
            <el-button link type="danger" @click="removeCategory(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </el-dialog>
</template>

<style scoped>
.question-cell {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}
.question-cell__type {
  flex-shrink: 0;
}
.question-cell__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.category-form {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  padding: var(--space-4);
  background: var(--slate-50);
  border-radius: var(--radius-md);
}
.category-form__name {
  flex: 1;
}
</style>

