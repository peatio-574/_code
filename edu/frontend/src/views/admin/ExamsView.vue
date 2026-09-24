<script setup lang="ts">
// 考试管理：组卷、发布/撤回、考试结果与批量删除。
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import {
  batchDeleteExams,
  createExam,
  deleteExam,
  getExam,
  listExamAttempts,
  listQuestions,
  publishExam,
  updateExam,
  withdrawExam,
} from '@/api/admin'
import DataPage from '@/components/data-page.vue'
import { api } from '@/lib/api'
import { formatDateTime } from '@/lib/labels'

const QUESTION_TYPES = [
  { value: 'single', label: '单选题' },
  { value: 'multiple', label: '多选题' },
  { value: 'true_false', label: '判断题' },
  { value: 'fill', label: '填空题' },
  { value: 'qa', label: '问答题' },
  { value: 'group', label: '综合答题' },
]

const items = ref<Record<string, any>[]>([])
const total = ref(0)
const loading = ref(false)
const attempts = ref<Record<string, any>[]>([])
const query = reactive({ p: 1, page_size: 20, keyword: '' })
const selection = ref<Record<string, any>[]>([])

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  title: '',
  exam_time: '',
  duration: 60,
  pass_score: 60,
  status: 1,
  sections: [] as { type: string; description: string; question_ids: number[] }[],
})

const pickerVisible = ref(false)
const pickerType = ref('single')
const pickerOptions = ref<Record<string, any>[]>([])
const activeSection = ref(0)

const resultVisible = ref(false)
const resultAttempts = ref<Record<string, any>[]>([])

function statusText(row: Record<string, any>) {
  if (row.status === 0) return '草稿'
  if (row.status === 2) return '已撤回'
  return '已发布'
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
  const attemptPage = await listExamAttempts({ p: 1, page_size: 20 })
  attempts.value = attemptPage?.items ?? []
}

function toLocal(timestamp: number) {
  if (!timestamp) return ''
  const date = new Date(timestamp * 1000 - new Date().getTimezoneOffset() * 60000)
  return date.toISOString().slice(0, 16)
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { title: '', exam_time: '', duration: 60, pass_score: 60, status: 1, sections: [{ type: 'single', description: '单选题', question_ids: [] }] })
  dialogVisible.value = true
}

async function openEdit(row: Record<string, any>) {
  const detail = await getExam(row.id)
  editingId.value = row.id
  Object.assign(form, {
    title: detail.exam.title,
    exam_time: toLocal(detail.exam.exam_time),
    duration: detail.exam.duration,
    pass_score: detail.exam.pass_score,
    status: detail.exam.status,
    sections: detail.sections.map((section: any) => ({
      type: section.type,
      description: section.description,
      question_ids: section.questions.map((q: any) => q.id),
    })),
  })
  dialogVisible.value = true
}

async function openPicker(sectionIndex: number) {
  activeSection.value = sectionIndex
  pickerType.value = form.sections[sectionIndex].type
  const response = await api.get('/api/admin/questions/options', { params: { type: pickerType.value } })
  pickerOptions.value = response.data?.data?.items ?? []
  pickerVisible.value = true
}

function toggleQuestion(id: number) {
  const ids = form.sections[activeSection.value].question_ids
  if (ids.includes(id)) {
    form.sections[activeSection.value].question_ids = ids.filter((value) => value !== id)
  } else {
    ids.push(id)
  }
}

async function save() {
  if (!form.title.trim() || !form.exam_time) {
    ElMessage.warning('请填写试卷名称和开始时间')
    return
  }
  const payload = {
    title: form.title,
    exam_time: Math.floor(new Date(form.exam_time).getTime() / 1000),
    duration: form.duration,
    pass_score: form.pass_score,
    status: form.status,
    sections: form.sections.filter((section) => section.question_ids.length),
  }
  const result = editingId.value ? await updateExam(editingId.value, payload) : await createExam(payload)
  if (result.success) {
    ElMessage.success('保存成功')
    dialogVisible.value = false
    await load()
  } else {
    ElMessage.error(result.message || '保存失败')
  }
}

async function publish(row: Record<string, any>) {
  const result = await publishExam(row.id)
  if (result.success) {
    await load()
    ElMessage.success('已发布')
  } else {
    ElMessage.error(result.message || '发布失败')
  }
}

async function withdraw(row: Record<string, any>) {
  await withdrawExam(row.id)
  await load()
}

async function remove(row: Record<string, any>) {
  try {
    await ElMessageBox.confirm('确定删除该试卷吗？', '删除确认', { type: 'warning' })
  } catch {
    return
  }
  await deleteExam(row.id)
  await load()
}

async function batchRemove() {
  if (!selection.value.length) {
    ElMessage.warning('请选择要删除的试卷')
    return
  }
  await batchDeleteExams(selection.value.map((row) => row.id))
  ElMessage.success('已删除')
  await load()
}

async function viewResults(row: Record<string, any>) {
  const page = await listExamAttempts({ p: 1, page_size: 100 })
  resultAttempts.value = (page?.items ?? []).filter((item: any) => item.exam_id === row.id)
  resultVisible.value = true
}

void listQuestions

onMounted(load)
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
        <el-table-column label="试卷名称" min-width="240">
          <template #default="{ row }">
            <div class="user-cell__name">{{ row.title }}</div>
            <div class="user-cell__meta">{{ row.total_questions }} 题 · 时长 {{ row.duration }} 分钟</div>
          </template>
        </el-table-column>
        <el-table-column label="有效时间" min-width="240">
          <template #default="{ row }">
            <span class="cell-muted tabular">{{ formatDateTime(row.exam_time) }} ~ {{ formatDateTime(row.end_time) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="130">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : row.status === 2 ? 'warning' : 'info'" effect="light">
              {{ statusText(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="考试统计" min-width="220">
          <template #default="{ row }">
            <span class="cell-muted">参考 {{ row.attempt_count }} · 合格 {{ row.pass_count }} · 均分 {{ Number(row.average_score).toFixed(1) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button v-if="row.status !== 1" link type="success" @click="publish(row)">发布</el-button>
              <el-button v-else link type="warning" @click="withdraw(row)">撤回</el-button>
              <el-button link type="primary" @click="viewResults(row)">结果</el-button>
              <el-button link type="danger" @click="remove(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </DataPage>

    <el-card class="exam-attempts">
      <template #header>最近考试结果</template>
      <el-table :data="attempts" row-key="id" height="260" empty-text="暂无考试记录">
        <el-table-column prop="display_name" label="学员" min-width="160" />
        <el-table-column prop="exam_title" label="试卷" min-width="200" />
        <el-table-column label="开始时间" min-width="200">
          <template #default="{ row }"><span class="cell-muted tabular">{{ formatDateTime(row.start_time) }}</span></template>
        </el-table-column>
        <el-table-column label="状态" min-width="120">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'info'" effect="light">
              {{ row.status === 1 ? '已交卷' : '进行中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="total_score" label="成绩" min-width="100" align="right" />
      </el-table>
    </el-card>
  </div>

  <el-dialog v-model="dialogVisible" :lock-scroll="false" :title="editingId ? '编辑试卷' : '新增试卷'" width="860px" top="4vh" append-to-body>
    <el-form label-position="top">
      <el-row :gutter="16">
        <el-col :span="12"><el-form-item label="试卷名称" required><el-input v-model="form.title" placeholder="请输入试卷名称" /></el-form-item></el-col>
        <el-col :span="12"><el-form-item label="开始时间" required><el-input v-model="form.exam_time" type="datetime-local" /></el-form-item></el-col>
        <el-col :span="8"><el-form-item label="时长（分钟）"><el-input-number v-model="form.duration" :min="1" style="width: 100%" /></el-form-item></el-col>
        <el-col :span="8"><el-form-item label="合格线（分）"><el-input-number v-model="form.pass_score" :min="0" style="width: 100%" /></el-form-item></el-col>
        <el-col :span="8">
          <el-form-item label="状态">
            <el-switch v-model="form.status" :active-value="1" :inactive-value="0" inline-prompt active-text="启用" inactive-text="禁用" />
          </el-form-item>
        </el-col>
      </el-row>
    </el-form>

    <p class="section-label">题目分组</p>
    <div v-for="(section, index) in form.sections" :key="index" class="section-block">
      <div class="section-head">
        <el-select v-model="section.type" style="width: 150px">
          <el-option v-for="type in QUESTION_TYPES" :key="type.value" :label="type.label" :value="type.value" />
        </el-select>
        <el-input v-model="section.description" placeholder="分组说明，如「单选题」" class="section-head__desc" />
        <span class="section-head__count">已选 {{ section.question_ids.length }} 题</span>
        <el-button link type="primary" @click="openPicker(index)">选择题库</el-button>
        <el-button link type="danger" @click="form.sections.splice(index, 1)">删除分组</el-button>
      </div>
    </div>
    <el-button @click="form.sections.push({ type: 'single', description: '单选题', question_ids: [] })">增加分组</el-button>

    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="pickerVisible" :lock-scroll="false" title="从题库选择题目" width="680px" append-to-body>
    <el-table :data="pickerOptions" row-key="id" max-height="440" empty-text="该题型暂无题目" @row-click="(row: any) => toggleQuestion(row.id)">
      <el-table-column width="56">
        <template #default="{ row }">
          <el-checkbox :model-value="form.sections[activeSection]?.question_ids.includes(row.id)" @click.stop @change="() => toggleQuestion(row.id)" />
        </template>
      </el-table-column>
      <el-table-column prop="title" label="题目" min-width="240" show-overflow-tooltip />
      <el-table-column prop="score" label="分值" min-width="90" align="right" />
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
.exam-attempts {
  flex-shrink: 0;
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
  align-items: center;
  gap: var(--space-3);
}
.section-head__desc {
  flex: 1;
}
.section-head__count {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  white-space: nowrap;
}
</style>

