<script setup lang="ts">
// 学员管理：账号 CRUD、上级归属、启停与删除。
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import {
  createStudent,
  deleteStudent,
  listCampuses,
  listHierarchy,
  listStudents,
  toggleStudent,
  updateStudent,
} from '@/api/admin'
import DataPage from '@/components/data-page.vue'
import StatusSwitch from '@/components/status-switch.vue'
import { formatDateTime, STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'

const items = ref<Record<string, any>[]>([])
const total = ref(0)
const loading = ref(false)
const saving = ref(false)
const managers = ref<Record<string, any>[]>([])
const campuses = ref<Record<string, any>[]>([])
const query = reactive({ p: 1, page_size: 20, keyword: '', status: '', campus_id: '', manager_id: '' })

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({ real_name: '', phone: '', manager_id: 0, password: '', status: 1 })

async function load() {
  loading.value = true
  try {
    const page = await listStudents({
      p: query.p,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      status: query.status || undefined,
      campus_id: query.campus_id || undefined,
      manager_id: query.manager_id || undefined,
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
  query.campus_id = ''
  query.manager_id = ''
  query.p = 1
  load()
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { real_name: '', phone: '', manager_id: 0, password: '', status: 1 })
  dialogVisible.value = true
}

function openEdit(row: Record<string, any>) {
  editingId.value = row.id
  Object.assign(form, {
    real_name: row.display_name,
    phone: '',
    manager_id: row.manager_id ?? 0,
    password: '',
    status: row.status,
  })
  dialogVisible.value = true
}

async function save() {
  if (!editingId.value && !form.phone.trim()) {
    ElMessage.warning('请填写手机号')
    return
  }
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      real_name: form.real_name,
      phone: form.phone,
      manager_id: form.manager_id || undefined,
      status: form.status,
    }
    if (form.password) payload.password = form.password
    const result = editingId.value
      ? await updateStudent({ ...payload, id: editingId.value })
      : await createStudent(payload)
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

async function toggle(row: Record<string, any>, next: number) {
  const previous = row.status
  row.status = next
  const result = await toggleStudent(row.id, next)
  if (!result.success) {
    row.status = previous
    ElMessage.error(result.message || STATUS_FAILURE_TEXT)
  } else {
    ElMessage.success(statusChangeMessage(next))
  }
}

async function remove(row: Record<string, any>) {
  try {
    await ElMessageBox.confirm(`确定删除学员“${row.display_name}”吗？删除后不可恢复。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const result = await deleteStudent(row.id)
  if (result.success) {
    ElMessage.success('已删除')
    await load()
  } else {
    ElMessage.error(result.message || '删除失败')
  }
}

onMounted(async () => {
  const [hierarchy, campusPage] = await Promise.all([listHierarchy(), listCampuses({ p: 1, page_size: 100 })])
  managers.value = hierarchy?.manager_options ?? []
  campuses.value = campusPage?.items ?? []
  await load()
})
</script>

<template>
  <DataPage
    title="学员管理"
    description="维护学员账号与上级归属，学员仅可访问本人学习数据。"
    :total="total"
    :page="query.p"
    :page-size="query.page_size"
    :loading="loading"
    @update:page="(value) => (query.p = value)"
    @update:page-size="(value) => (query.page_size = value)"
    @change="load"
  >
    <template #actions>
      <el-button type="primary" :icon="Plus" @click="openCreate">添加学员</el-button>
    </template>

    <template #filters>
      <el-input
        v-model="query.keyword"
        placeholder="姓名 / 账号 / 手机号"
        clearable
        :prefix-icon="Search"
        @keyup.enter="() => { query.p = 1; load() }"
      />
      <el-select v-model="query.campus_id" placeholder="所有校区" clearable>
        <el-option
          v-for="campus in campuses"
          :key="campus.id"
          :label="campus.name"
          :value="String(campus.id)"
        />
      </el-select>
      <el-select v-model="query.manager_id" placeholder="所属管理员" clearable filterable>
        <el-option
          v-for="manager in managers"
          :key="manager.id"
          :label="manager.display_name || manager.username"
          :value="String(manager.id)"
        />
      </el-select>
      <el-select v-model="query.status" placeholder="状态" clearable>
        <el-option label="已启用" value="1" />
        <el-option label="已禁用" value="0" />
      </el-select>
      <el-button type="primary" @click="() => { query.p = 1; load() }">搜索</el-button>
      <el-button @click="reset">重置</el-button>
    </template>

    <el-table :data="items" row-key="id" height="100%" empty-text="暂无学员，点击右上角「添加学员」开始">
      <el-table-column label="学员" min-width="200">
        <template #default="{ row }">
          <span class="cell-strong">{{ row.display_name || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="所属校区" min-width="150">
        <template #default="{ row }">{{ row.campus_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="上级管理员" min-width="150">
        <template #default="{ row }">{{ row.manager_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="手机号" min-width="150">
        <template #default="{ row }"><span class="tabular">{{ row.phone || '—' }}</span></template>
      </el-table-column>
      <el-table-column label="状态" min-width="160">
        <template #default="{ row }">
          <StatusSwitch :status="row.status" @change="(next) => toggle(row, next)" />
        </template>
      </el-table-column>
      <el-table-column label="更新时间" min-width="180">
        <template #default="{ row }"><span class="cell-muted tabular">{{ formatDateTime(row.updated_at) }}</span></template>
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

  <el-dialog v-model="dialogVisible" :lock-scroll="false" :title="editingId ? '编辑学员' : '新增学员'" width="520px" append-to-body>
    <el-form label-position="top">
      <el-form-item label="姓名" required>
        <el-input v-model="form.real_name" placeholder="请输入学员姓名" />
      </el-form-item>
      <el-form-item label="手机号" required>
        <el-input v-model="form.phone" :placeholder="editingId ? '留空则不修改' : '作为登录账号，11 位手机号'" />
      </el-form-item>
      <el-form-item label="上级管理员">
        <el-select v-model="form.manager_id" style="width: 100%">
          <el-option label="默认归属当前操作人" :value="0" />
          <el-option
            v-for="manager in managers"
            :key="manager.id"
            :label="manager.display_name || manager.username"
            :value="manager.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="密码">
        <el-input v-model="form.password" type="password" placeholder="留空则默认手机号后 6 位" show-password />
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
