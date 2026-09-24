<script setup lang="ts">
// 教师管理：教师资料 CRUD、头像上传与启停。
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { createTeacher, deleteTeacher, listTeachers, toggleTeacher, updateTeacher } from '@/api/admin'
import DataPage from '@/components/data-page.vue'
import StatusSwitch from '@/components/status-switch.vue'
import { api, errorMessage } from '@/lib/api'
import { STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'

const items = ref<Record<string, any>[]>([])
const total = ref(0)
const loading = ref(false)
const query = reactive({ p: 1, page_size: 20, keyword: '', status: '' })
const selection = ref<Record<string, any>[]>([])

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const form = reactive({ name: '', description: '', avatar: '', status: 1 })

async function load() {
  loading.value = true
  try {
    const page = await listTeachers({
      p: query.p,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
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
  query.status = ''
  query.p = 1
  load()
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', description: '', avatar: '', status: 1 })
  dialogVisible.value = true
}

function openEdit(row: Record<string, any>) {
  editingId.value = row.id
  Object.assign(form, { name: row.name, description: row.description, avatar: row.avatar, status: row.status })
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写教师姓名')
    return
  }
  saving.value = true
  try {
    const payload = { ...form, id: editingId.value ?? undefined }
    const result = editingId.value ? await updateTeacher(payload) : await createTeacher(payload)
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

async function uploadAvatar(options: any) {
  const formData = new FormData()
  formData.append('file', options.file)
  try {
    const response = await api.post('/api/file/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    form.avatar = response.data?.data?.id ?? ''
    ElMessage.success('头像上传成功')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function toggle(row: Record<string, any>, next: number) {
  const previous = row.status
  row.status = next
  const result = await toggleTeacher(row.id, next)
  if (!result.success) {
    row.status = previous
    ElMessage.error(result.message || STATUS_FAILURE_TEXT)
  } else {
    ElMessage.success(statusChangeMessage(next))
  }
}

async function remove(row: Record<string, any>) {
  try {
    await ElMessageBox.confirm(`确定删除教师“${row.name}”吗？删除后不可恢复。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const result = await deleteTeacher(row.id)
  if (result.success) {
    ElMessage.success('已删除')
    await load()
  } else {
    ElMessage.error(result.message || '删除失败')
  }
}

async function batchRemove() {
  if (!selection.value.length) {
    ElMessage.warning('请先选择要删除的教师')
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${selection.value.length} 位教师吗？`, '批量删除', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  for (const row of selection.value) await deleteTeacher(row.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<template>
  <DataPage
    title="教师管理"
    description="维护课程授课教师资料，教师仅作为课程关联对象，不设登录账号。"
    :total="total"
    :page="query.p"
    :page-size="query.page_size"
    :loading="loading"
    @update:page="(value) => (query.p = value)"
    @update:page-size="(value) => (query.page_size = value)"
    @change="load"
  >
    <template #actions>
      <el-button type="primary" :icon="Plus" @click="openCreate">添加教师</el-button>
    </template>

    <template #filters>
      <el-input
        v-model="query.keyword"
        placeholder="教师名称 / 简介"
        clearable
        :prefix-icon="Search"
        @keyup.enter="() => { query.p = 1; load() }"
      />
      <el-select v-model="query.status" placeholder="状态" clearable>
        <el-option label="已启用" value="1" />
        <el-option label="已禁用" value="0" />
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
      empty-text="暂无教师，点击右上角「添加教师」开始"
      @selection-change="(rows: any[]) => (selection = rows)"
    >
      <el-table-column type="selection" width="48" />
      <el-table-column label="教师" min-width="220">
        <template #default="{ row }">
          <div class="user-cell">
            <el-avatar :size="38" shape="square" :src="row.avatar ? `/api/image/${row.avatar}` : undefined">
              {{ (row.name || '师').slice(0, 1) }}
            </el-avatar>
            <div>
              <div class="user-cell__name">{{ row.name }}</div>
              <div class="user-cell__meta">ID {{ row.id }}</div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="简介" min-width="240">
        <template #default="{ row }">
          <span class="cell-muted">{{ row.description || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" min-width="180">
        <template #default="{ row }">
          <span class="cell-muted tabular">{{ new Date(row.updated_at * 1000).toLocaleString() }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" min-width="160">
        <template #default="{ row }">
          <StatusSwitch :status="row.status" @change="(next) => toggle(row, next)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </DataPage>

  <el-dialog v-model="dialogVisible" :lock-scroll="false" :title="editingId ? '编辑教师' : '新增教师'" width="520px" append-to-body>
    <el-form label-position="top">
      <el-form-item label="教师姓名" required>
        <el-input v-model="form.name" placeholder="请输入教师姓名" />
      </el-form-item>
      <el-form-item label="简介">
        <el-input v-model="form.description" type="textarea" :rows="3" placeholder="用于课程详情展示的教师介绍" />
      </el-form-item>
      <el-form-item label="头像">
        <div class="avatar-field">
          <el-upload :show-file-list="false" :http-request="uploadAvatar" accept="image/*">
            <el-avatar :size="64" shape="square" :src="form.avatar ? `/api/image/${form.avatar}` : undefined">
              {{ (form.name || '师').slice(0, 1) }}
            </el-avatar>
          </el-upload>
          <span class="avatar-field__hint">点击上传，建议 1:1 方形图片</span>
        </div>
      </el-form-item>
      <el-form-item label="状态">
        <el-switch v-model="form.status" :active-value="1" :inactive-value="0" inline-prompt active-text="启用" inactive-text="禁用" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.avatar-field {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}
.avatar-field__hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
</style>
