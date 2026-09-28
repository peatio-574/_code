<script setup lang="ts">
// 学员管理：账号 CRUD、上级归属、启停与删除。
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { nextTick, onMounted, reactive, ref } from 'vue'

import {
  batchDeleteStudents,
  createStudent,
  deleteStudent,
  getAdminDetail,
  listCampuses,
  listHierarchy,
  listStudents,
  toggleStudent,
  updateStudent,
} from '@/api/admin'
import DataPage from '@/components/data-page.vue'
import StatusSwitch from '@/components/status-switch.vue'
import { api, errorMessage } from '@/lib/api'
import { formatDateTime, STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'

const items = ref<Record<string, any>[]>([])
const total = ref(0)
const loading = ref(false)
const saving = ref(false)
const managers = ref<Record<string, any>[]>([])
const campuses = ref<Record<string, any>[]>([])
const query = reactive({ p: 1, page_size: 20, keyword: '', status: '', campus_id: '', manager_id: '' })

const selection = ref<Record<string, any>[]>([])

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({ real_name: '', phone: '', avatar: '', manager_id: 0, campus_id: 0, password: '', status: 1 })
const formRef = ref<FormInstance>()
const rules: FormRules = {
  real_name: [{ required: true, message: '请填写姓名', trigger: 'blur' }],
  phone: [
    {
      required: true,
      validator: (_rule, value: string, callback) => {
        if (!value) return callback(new Error('请填写手机号'))
        if (!/^\d{11}$/.test(value)) return callback(new Error('请输入 11 位手机号'))
        callback()
      },
      trigger: 'blur',
    },
  ],
  campus_id: [
    {
      required: true,
      validator: (_rule, value: number, callback) => {
        if (!value) return callback(new Error('请选择所属校区'))
        callback()
      },
      trigger: 'change',
    },
  ],
  manager_id: [
    {
      required: true,
      validator: (_rule, value: number, callback) => {
        if (!value) return callback(new Error('请选择上级管理员'))
        callback()
      },
      trigger: 'change',
    },
  ],
  password: [
    {
      required: true,
      validator: (_rule, value: string, callback) => {
        if (!value) return callback(new Error('请填写密码'))
        if (value.length < 6) return callback(new Error('密码长度不能少于 6 位'))
        callback()
      },
      trigger: 'blur',
    },
  ],
}

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

async function openCreate() {
  editingId.value = null
  Object.assign(form, { real_name: '', phone: '', avatar: '', manager_id: 0, campus_id: 0, password: '', status: 1 })
  dialogVisible.value = true
  await nextTick()
  formRef.value?.clearValidate()
}

async function openEdit(row: Record<string, any>) {
  editingId.value = row.id
  Object.assign(form, {
    real_name: row.display_name,
    phone: row.phone || row.mobile || '',
    avatar: row.avatar ?? '',
    manager_id: row.manager_id ?? 0,
    campus_id: row.campus_id ?? 0,
    password: '',
    status: row.status,
  })
  dialogVisible.value = true
  nextTick(() => formRef.value?.clearValidate())
  // 手机号在列表中脱敏，编辑时拉取完整手机号与密码回填
  try {
    const detail = await getAdminDetail(row.id)
    form.phone = detail?.mobile || detail?.phone || form.phone
    form.password = detail?.password || ''
  } catch {
    /* 拉取失败时保留原值 */
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

async function save() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      real_name: form.real_name,
      phone: form.phone,
      avatar: form.avatar,
      manager_id: form.manager_id || undefined,
      campus_id: form.campus_id || undefined,
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

async function batchRemove() {
  if (!selection.value.length) {
    ElMessage.warning('请先选择要删除的学员')
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${selection.value.length} 名学员吗？删除后不可恢复。`, '批量删除', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const result = await batchDeleteStudents(selection.value.map((row) => row.id))
  if (result.success) {
    const deleted = result.data?.deleted_count ?? 0
    const skipped = result.data?.skipped_count ?? 0
    ElMessage.success(skipped ? `已删除 ${deleted} 名，跳过 ${skipped} 名（无权限）` : `已删除 ${deleted} 名学员`)
    await load()
  } else {
    ElMessage.error(result.message || '批量删除失败')
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
  // 辅助数据（上级选项/校区）获取失败不应阻断主列表加载
  try {
    const [hierarchy, campusPage] = await Promise.all([
      listHierarchy(true),
      listCampuses({ p: 1, page_size: 100 }),
    ])
    managers.value = hierarchy?.manager_options ?? []
    campuses.value = campusPage?.items ?? []
  } catch {
    managers.value = []
    campuses.value = []
  }
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
      <span class="toolbar-spacer" />
      <el-button type="danger" plain :disabled="!selection.length" @click="batchRemove">
        批量删除{{ selection.length ? `（${selection.length}）` : '' }}
      </el-button>
    </template>

    <el-table
      :data="items"
      row-key="id"
      height="100%"
      empty-text="暂无学员，点击右上角「添加学员」开始"
      @selection-change="(rows: any[]) => (selection = rows)"
    >
      <el-table-column type="selection" width="48" />
      <el-table-column label="头像" width="80" align="center">
        <template #default="{ row }">
          <el-avatar
            :key="row.avatar || 'empty'"
            :size="40"
            :src="row.avatar ? `/api/image/${row.avatar}` : undefined"
          >
            {{ (row.display_name || row.username || '学').slice(0, 1) }}
          </el-avatar>
        </template>
      </el-table-column>
      <el-table-column label="姓名" min-width="160">
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
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="头像">
        <div class="avatar-field">
          <el-upload :show-file-list="false" :http-request="uploadAvatar" accept="image/*">
            <el-avatar
              :key="form.avatar || 'empty'"
              :size="64"
              :src="form.avatar ? `/api/image/${form.avatar}` : undefined"
            >
              {{ (form.real_name || '学').slice(0, 1) }}
            </el-avatar>
          </el-upload>
          <span class="avatar-field__hint">点击上传头像，建议 1:1 方形图片</span>
        </div>
      </el-form-item>
      <el-form-item label="姓名" prop="real_name">
        <el-input v-model="form.real_name" placeholder="请输入学员姓名" />
      </el-form-item>
      <el-form-item label="手机号" prop="phone">
        <el-input v-model="form.phone" placeholder="作为登录账号，11 位手机号" />
      </el-form-item>
      <el-form-item label="所属校区" prop="campus_id">
        <el-select v-model="form.campus_id" placeholder="请选择所属校区" style="width: 100%">
          <el-option v-for="campus in campuses" :key="campus.id" :label="campus.name" :value="campus.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="上级管理员" prop="manager_id">
        <el-select v-model="form.manager_id" placeholder="请选择上级管理员" filterable style="width: 100%">
          <el-option
            v-for="manager in managers"
            :key="manager.id"
            :label="manager.display_name || manager.username"
            :value="manager.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="密码" prop="password">
        <el-input v-model="form.password" :placeholder="editingId ? '当前密码' : '请输入密码，至少 6 位'" />
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
