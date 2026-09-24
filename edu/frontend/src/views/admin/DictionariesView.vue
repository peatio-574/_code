<script setup lang="ts">
// 字典管理：字典类型列表（搜索、新增、批量删除），点击编辑进入详情页维护枚举值。
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  batchDeleteDictionaryTypes,
  createDictionaryType,
  deleteDictionaryType,
  listDictionaryTypes,
  toggleDictionaryType,
} from '@/api/admin'
import StatusSwitch from '@/components/status-switch.vue'
import { errorMessage } from '@/lib/api'
import { formatDateTime, STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'

const router = useRouter()

const types = ref<Record<string, any>[]>([])
const loading = ref(false)
const keyword = ref('')
const selection = ref<Record<string, any>[]>([])

const page = ref(1)
const pageSize = ref(20)
const pageSizes = [20, 50, 100]

const dialogVisible = ref(false)
const saving = ref(false)
const form = reactive({ code: '', name: '', description: '' })

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return types.value
  return types.value.filter(
    (type) =>
      String(type.name ?? '').toLowerCase().includes(kw) ||
      String(type.code ?? '').toLowerCase().includes(kw),
  )
})

const pagedTypes = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filtered.value.slice(start, start + pageSize.value)
})

function handlePage(value: number) {
  page.value = value
}

function handlePageSize(value: number) {
  pageSize.value = value
  page.value = 1
}

watch(keyword, () => {
  page.value = 1
})

watch(filtered, (list) => {
  const maxPage = Math.max(1, Math.ceil(list.length / pageSize.value))
  if (page.value > maxPage) page.value = maxPage
})

async function load() {
  loading.value = true
  try {
    const data = await listDictionaryTypes()
    types.value = data?.items ?? []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, { code: '', name: '', description: '' })
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim() || !form.code.trim()) {
    ElMessage.warning('请填写字段中文名和字段英文名')
    return
  }
  saving.value = true
  try {
    const result = await createDictionaryType({ ...form, status: 1, sort_order: 0 })
    if (result.success) {
      ElMessage.success('已新增')
      dialogVisible.value = false
      await load()
    } else {
      ElMessage.error(result.message || '保存失败')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

function edit(row: Record<string, any>) {
  router.push({ name: 'admin-dictionary-detail', params: { typeId: row.id } })
}

async function remove(row: Record<string, any>) {
  try {
    await ElMessageBox.confirm(`确定删除字典“${row.name}”吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    const result = await deleteDictionaryType(row.id)
    if (result.success) {
      ElMessage.success('已删除')
      await load()
    } else {
      ElMessage.error(result.message || '删除失败')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function batchRemove() {
  if (!selection.value.length) {
    ElMessage.warning('请选择要删除的字典')
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${selection.value.length} 项字典吗？`, '批量删除', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    const result = await batchDeleteDictionaryTypes(selection.value.map((row) => row.id))
    if (result.success) {
      ElMessage.success('已删除')
      selection.value = []
      await load()
    } else {
      ElMessage.error(result.message || '删除失败')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function toggle(row: Record<string, any>, next: number) {
  const previous = row.status
  row.status = next
  try {
    const result = await toggleDictionaryType(row.id, next)
    if (!result.success) {
      row.status = previous
      ElMessage.error(result.message || STATUS_FAILURE_TEXT)
    } else {
      ElMessage.success(statusChangeMessage(next))
    }
  } catch (error) {
    row.status = previous
    ElMessage.error(errorMessage(error))
  }
}

onMounted(load)
</script>

<template>
  <section class="data-page">
    <div class="data-page__card">
      <div class="data-page__toolbar">
        <el-input
          v-model="keyword"
          placeholder="搜索字段中文名 / 英文名"
          clearable
          :prefix-icon="Search"
          style="width: 260px"
        />
        <el-button type="primary" :icon="Plus" @click="openCreate">新增</el-button>
        <el-button type="danger" plain @click="batchRemove">
          批量删除{{ selection.length ? `（${selection.length}）` : '' }}
        </el-button>
        <span class="toolbar-spacer" />
      </div>

      <div class="data-page__body">
        <el-table
          v-loading="loading"
          :data="pagedTypes"
          row-key="id"
          height="100%"
          class="dict-table"
          empty-text="暂无字典"
          @selection-change="(rows: any[]) => (selection = rows)"
        >
          <el-table-column type="selection" width="64" />
          <el-table-column prop="name" label="字段中文名" min-width="150">
            <template #default="{ row }">
              <span class="cell-strong">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="code" label="字段英文名" min-width="150" />
          <el-table-column label="枚举值" min-width="400">
            <template #default="{ row }">
              <span v-if="row.item_names && row.item_names.length" class="cell-muted">{{ row.item_names.join('、') }}</span>
              <span v-else class="cell-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="120">
            <template #default="{ row }">
              <StatusSwitch :status="row.status" @change="(next) => toggle(row, next)" />
            </template>
          </el-table-column>
          <el-table-column label="更新时间" min-width="180">
            <template #default="{ row }">
              <span class="cell-muted tabular">{{ row.updated_at ? formatDateTime(row.updated_at) : '' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <el-button link type="primary" @click="edit(row)">编辑</el-button>
                <el-button link type="danger" @click="remove(row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <footer class="data-page__footer">
        <span class="data-page__total">共 {{ filtered.length }} 条记录</span>
        <el-pagination
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="pageSizes"
          :total="filtered.length"
          background
          layout="sizes, prev, pager, next, jumper"
          @current-change="handlePage"
          @size-change="handlePageSize"
        />
      </footer>
    </div>

    <el-dialog v-model="dialogVisible" :lock-scroll="false" title="新增字典" width="480px" append-to-body>
      <el-form label-position="top">
        <el-form-item label="字段中文名" required>
          <el-input v-model="form.name" placeholder="如 课程分类" />
        </el-form-item>
        <el-form-item label="字段英文名" required>
          <el-input v-model="form.code" placeholder="如 course_type" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.built-tag {
  margin-left: var(--space-2);
}
.dict-table :deep(.el-checkbox__inner) {
  width: 18px;
  height: 18px;
}
.dict-table :deep(.el-checkbox__inner::after) {
  left: 6px;
  top: 2px;
  width: 4px;
  height: 9px;
}
.dict-table :deep(.el-checkbox__inner::before) {
  left: 3px;
  top: 8px;
  width: 10px;
  height: 2px;
}
</style>
