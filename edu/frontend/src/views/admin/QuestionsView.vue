<script setup lang="ts">
// 题库管理：题目 CRUD、批量删除与导入。
import { Download, Plus, Search, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, ElLoading } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import {
  batchDeleteQuestions,
  createQuestion,
  deleteQuestion,
  importQuestions,
  listQuestionCategories,
  listQuestions,
  toggleQuestion,
  updateQuestion,
} from '@/api/admin'
import DataPage from '@/components/data-page.vue'
import StatusSwitch from '@/components/status-switch.vue'
import { api } from '@/lib/api'
import { formatDateTime, STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'
import { buildXlsx, readXlsx } from '@/lib/xlsx'

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

const importing = ref(false)

const TYPE_ALIASES: Record<string, string> = {
  单选题: 'single',
  单选: 'single',
  多选题: 'multiple',
  多选: 'multiple',
  判断题: 'true_false',
  判断: 'true_false',
  填空题: 'fill',
  填空: 'fill',
  问答题: 'qa',
  问答: 'qa',
  综合题: 'group',
  综合答题: 'group',
  材料题: 'group',
}

function normalizeType(value: string | undefined): string {
  const raw = (value || '').trim()
  if (!raw) return 'single'
  if (QUESTION_TYPES.some((t) => t.value === raw)) return raw
  return TYPE_ALIASES[raw] || 'single'
}

/** 解析 CSV 文本为二维数组，支持双引号包裹与转义。 */
function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"'
          i++
        } else {
          quoted = false
        }
      } else {
        cell += ch
      }
    } else if (ch === '"') {
      quoted = true
    } else if (ch === ',') {
      row.push(cell.trim())
      cell = ''
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++
      row.push(cell.trim())
      rows.push(row)
      row = []
      cell = ''
    } else {
      cell += ch
    }
  }
  if (cell !== '' || row.length) {
    row.push(cell.trim())
    rows.push(row)
  }
  return rows
}

/** 将「；/;」分隔的选项文本转为题库存储的 JSON 结构。 */
function optionsToJson(raw: string): string {
  const text = (raw || '').trim()
  if (!text) return ''
  if (text.startsWith('[') || text.startsWith('{')) return text
  const parts = text.split(/[；;]/).map((item) => item.trim()).filter(Boolean)
  if (!parts.length) return ''
  return JSON.stringify(parts.map((item, index) => ({ key: String.fromCharCode(65 + index), text: item })))
}

interface ImportColumns {
  iType: number
  iTitle: number
  iOptions: number
  iAnswer: number
  iScore: number
  iStatus: number
  iCategory: number
  iExplanation: number
  hasHeader: boolean
}

/** 根据表头定位各列索引；无表头时按固定顺序回退。 */
function detectColumns(grid: string[][]): ImportColumns {
  const header = (grid[0] ?? []).map((cell) => String(cell ?? '').trim())
  const hasHeader = header.some((h) =>
    ['题型', '类型', '题目', '题干', '选项', '答案', 'type', 'title'].includes(h),
  )
  const col = (names: string[], fallback: number) => {
    if (!hasHeader) return fallback
    const idx = header.findIndex((h) => names.includes(h))
    return idx >= 0 ? idx : fallback
  }
  return {
    iType: col(['题型', '类型', 'type'], 0),
    iTitle: col(['题目', '题干', 'title'], 1),
    iOptions: col(['选项', 'options'], 2),
    iAnswer: col(['答案', 'answer'], 3),
    iScore: col(['分值', '分数', 'score'], 4),
    iStatus: col(['状态', 'status'], -1),
    iCategory: col(['分类', '题目方向', 'category'], -1),
    iExplanation: col(['解析', '答案解析', 'explanation'], -1),
    hasHeader,
  }
}

/** 将表格二维数据转为 { payload, categoryName } 列表。 */
function toRows(grid: string[][]): { payload: Record<string, unknown>; categoryName: string }[] {
  const data = grid.filter((row) => row.some((cell) => String(cell ?? '').trim()))
  if (!data.length) return []
  const cols = detectColumns(data)
  const body = cols.hasHeader ? data.slice(1) : data
  const rows: { payload: Record<string, unknown>; categoryName: string }[] = []
  for (const row of body) {
    const title = String(row[cols.iTitle] ?? '').trim()
    if (!title) continue
    const type = normalizeType(row[cols.iType])
    const payload: Record<string, unknown> = {
      type,
      title,
      options: type === 'group' ? '' : optionsToJson(String(row[cols.iOptions] ?? '')),
      answer: String(row[cols.iAnswer] ?? '').trim(),
      score: Number(row[cols.iScore]) || 1,
      explanation: cols.iExplanation >= 0 ? String(row[cols.iExplanation] ?? '').trim() : '',
    }
    if (cols.iStatus >= 0) {
      const status = String(row[cols.iStatus] ?? '').trim()
      payload.status = status === '0' || status === '禁用' || status === '停用' ? 0 : 1
    }
    const categoryName = cols.iCategory >= 0 ? String(row[cols.iCategory] ?? '').trim() : ''
    rows.push({ payload, categoryName })
  }
  return rows
}

/** 下载导入模板（xlsx），表头与导入解析规则保持一致。 */
function downloadTemplate() {
  const rows: (string | number)[][] = [
    ['类型', '题目', '选项', '答案', '分值', '状态', '分类', '解析'],
    [
      'single',
      '一项工程，甲单独做需10天，乙单独做需15天，两人合作需多少天完成？',
      '5；6；7；8',
      'B',
      1,
      1,
      '行政测试-数量关系',
      '甲效率1/10，乙1/15，合作效率1/10+1/15=1/6，故需6天',
    ],
    [
      'single',
      '甲、乙两地相距240千米，汽车去时速度60千米/时，返回速度40千米/时，往返平均速度是多少？',
      '50；48；45；52',
      'B',
      1,
      1,
      '行政测试-数量关系',
      '平均速度=2×60×40÷(60+40)=48',
    ],
    [
      'single',
      '商品进价100元，按20%利润率定价，售价为多少元？',
      '110；120；125；130',
      'B',
      1,
      1,
      '行政测试-数量关系',
      '售价=100×(1+20%)=120',
    ],
    [
      'single',
      '从5个人中任选2人参加比赛，共有多少种选法？',
      '15；10；20；8',
      'B',
      1,
      1,
      '行政测试-数量关系',
      'C(5,2)=5×4÷2=10',
    ],
    [
      'single',
      '掷一枚骰子，点数为偶数的概率是多少？',
      '1/3；1/2；1/6；2/3',
      'B',
      1,
      1,
      '行政测试-数量关系',
      '偶数有2、4、6三种，3÷6=1/2',
    ],
  ]
  const blob = buildXlsx(rows)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = '题库导入模板.xlsx'
  link.click()
  URL.revokeObjectURL(url)
}

async function importFile(options: any) {
  const file: File = options.file
  const isExcel = /\.xlsx$/i.test(file.name)
  const loader = ElLoading.service({
    lock: true,
    text: isExcel ? '正在解析 Excel 并导入…' : '正在导入题目…',
    background: 'rgba(255, 255, 255, 0.7)',
  })
  importing.value = true
  let imported = 0
  let failed = 0
  try {
    let grid: string[][]
    if (isExcel) {
      grid = await readXlsx(file)
    } else {
      const text = await file.text()
      grid = parseCsv(text)
    }
    const rows = toRows(grid)
    if (!rows.length) {
      ElMessage.warning('未解析到有效题目，请检查文件内容')
      return
    }
    // 一次性批量提交，避免逐条请求
    const items = rows.map(({ payload, categoryName }) => ({
      ...payload,
      category: categoryName,
    }))
    const result = await importQuestions({ items })
    if (result.success) {
      imported = result.data?.imported ?? items.length
      failed = result.data?.skipped ?? 0
      await loadCategories()
      await load()
      ElMessage.success(failed ? `已导入 ${imported} 道题，跳过 ${failed} 道` : `已导入 ${imported} 道题`)
    } else {
      ElMessage.error(result.message || '导入失败，请检查文件格式')
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '导入失败')
  } finally {
    loader.close()
    importing.value = false
  }
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
    description="维护练习题与题目方向；题目方向与「字典管理 → 题目方向」共用同一份枚举值。"
    :total="total"
    :page="query.p"
    :page-size="query.page_size"
    :loading="loading"
    @update:page="(value) => (query.p = value)"
    @update:page-size="(value) => (query.page_size = value)"
    @change="load"
  >
    <template #actions>
      <el-button :icon="Download" @click="downloadTemplate">下载模板</el-button>
      <el-upload
        :show-file-list="false"
        :http-request="importFile"
        :disabled="importing"
        accept=".xlsx,.csv"
      >
        <el-button :icon="Upload" :loading="importing">导入题目</el-button>
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
      <el-select v-model="query.category_id" placeholder="题目方向" clearable style="width: 180px">
        <el-option v-for="category in categories" :key="category.id" :label="category.name" :value="String(category.id)" />
      </el-select>
      <el-button type="primary" @click="() => { query.p = 1; load() }">搜索</el-button>
      <el-button @click="reset">重置</el-button>
      <span class="toolbar-spacer" />
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
          <span class="question-cell__title" :title="row.title">{{ row.title }}</span>
        </template>
      </el-table-column>
      <el-table-column label="题型" min-width="120">
        <template #default="{ row }">
          <el-tag size="small" effect="plain" class="question-type-tag">
            {{ QUESTION_TYPES.find((t) => t.value === row.type)?.label || row.type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="category_name" label="题目方向" min-width="140">
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
          <el-form-item label="题目方向">
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
</template>

<style scoped>
.question-cell__title {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-strong);
}
.question-type-tag {
  flex-shrink: 0;
}
</style>

