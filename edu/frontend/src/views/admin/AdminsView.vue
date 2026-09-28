<script setup lang="ts">
// 管理员管理：账号 CRUD、角色/校区、重置密码与启停。
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { computed, nextTick, onMounted, reactive, ref } from 'vue'

import {
  batchDeleteAdmins,
  createAdmin,
  deleteAdmin,
  getAdminDetail,
  listAdmins,
  listCampuses,
  resetAdminPassword,
  toggleAdmin,
  updateAdmin,
} from '@/api/admin'
import { getRoles, type RoleItem } from '@/api/auth'
import DataPage from '@/components/data-page.vue'
import StatusSwitch from '@/components/status-switch.vue'
import { api, errorMessage } from '@/lib/api'
import { formatDateTime, roleLabel, STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const isSuper = auth.user?.roles?.includes('system_admin') ?? false
// 非超管（校长）仅可管理班主任，不能创建/改为校长
const selectableRoles = computed(() =>
  isSuper ? roles.value : roles.value.filter((role) => role.code !== 'principal'),
)

const items = ref<Record<string, any>[]>([])
const total = ref(0)
const loading = ref(false)
const saving = ref(false)
const roles = ref<RoleItem[]>([])
const campuses = ref<Record<string, any>[]>([])
const query = reactive({ p: 1, page_size: 20, keyword: '', status: '', campus_id: '', role_code: '' })
const selection = ref<Record<string, any>[]>([])

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const defaultRole = isSuper ? 'principal' : 'homeroom_teacher'
const form = reactive({ real_name: '', phone: '', avatar: '', role_code: defaultRole, campus_id: 0, password: '', status: 1 })
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
  role_code: [{ required: true, message: '请选择角色', trigger: 'change' }],
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
    const page = await listAdmins({
      p: query.p,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      status: query.status || undefined,
      campus_id: query.campus_id || undefined,
      role_code: query.role_code || undefined,
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
  query.role_code = ''
  query.p = 1
  load()
}

async function openCreate() {
  editingId.value = null
  Object.assign(form, { real_name: '', phone: '', avatar: '', role_code: defaultRole, campus_id: 0, password: '', status: 1 })
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
    role_code: row.role_codes?.[0] ?? defaultRole,
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
      role_code: form.role_code,
      campus_id: form.campus_id || undefined,
      status: form.status,
    }
    if (form.password) payload.password = form.password
    const result = editingId.value
      ? await updateAdmin({ ...payload, id: editingId.value })
      : await createAdmin(payload)
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
  const result = await toggleAdmin(row.id, next)
  if (!result.success) {
    row.status = previous
    ElMessage.error(result.message || STATUS_FAILURE_TEXT)
  } else {
    ElMessage.success(statusChangeMessage(next))
  }
}

async function remove(row: Record<string, any>) {
  try {
    await ElMessageBox.confirm(`确定删除管理员“${row.display_name}”吗？删除后不可恢复。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const result = await deleteAdmin(row.id)
  if (result.success) {
    ElMessage.success('已删除')
    await load()
  } else {
    ElMessage.error(result.message || '删除失败')
  }
}

async function batchRemove() {
  if (!selection.value.length) {
    ElMessage.warning('请先选择要删除的管理员')
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${selection.value.length} 名管理员吗？删除后不可恢复。`, '批量删除', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const result = await batchDeleteAdmins(selection.value.map((row) => row.id))
  if (result.success) {
    const deleted = result.data?.deleted_count ?? 0
    const skipped = result.data?.skipped_count ?? 0
    ElMessage.success(skipped ? `已删除 ${deleted} 名，跳过 ${skipped} 名（无权限/不能删除自己）` : `已删除 ${deleted} 名管理员`)
    await load()
  } else {
    ElMessage.error(result.message || '批量删除失败')
  }
}

async function resetPassword(row: Record<string, any>) {
  try {
    const { value } = await ElMessageBox.prompt(`为「${row.display_name}」设置新密码（至少 6 位）`, '重置密码', {
      inputType: 'password',
      inputPlaceholder: '请输入新密码',
      confirmButtonText: '确认重置',
      cancelButtonText: '取消',
    })
    if (!value || value.length < 6) {
      ElMessage.warning('密码长度不能少于 6 位')
      return
    }
    const result = await resetAdminPassword(row.id, value)
    if (result.success) ElMessage.success('密码已重置')
    else ElMessage.error(result.message || '重置失败')
  } catch {
    /* 用户取消 */
  }
}

// 校长无「角色管理」权限，无法读取角色列表时的兜底选项
const FALLBACK_ROLES = [
  { code: 'principal', name: '校长' },
  { code: 'homeroom_teacher', name: '班主任' },
] as unknown as RoleItem[]

onMounted(async () => {
  // 辅助数据（角色/校区）获取失败不应阻断主列表加载
  if (isSuper) {
    try {
      const roleItems = await getRoles()
      roles.value = roleItems.filter((role) => ['principal', 'homeroom_teacher'].includes(role.code))
    } catch {
      roles.value = FALLBACK_ROLES
    }
  } else {
    // 校长无「角色管理」权限，直接用可分配角色的兜底列表
    roles.value = FALLBACK_ROLES
  }
  try {
    campuses.value = (await listCampuses({ page_size: 100 }))?.items ?? []
  } catch {
    campuses.value = []
  }
  await load()
})
</script>

<template>
  <DataPage
    title="管理员管理"
    description="管理校长与班主任账号，按校区归属控制其数据可见范围。"
    :total="total"
    :page="query.p"
    :page-size="query.page_size"
    :loading="loading"
    @update:page="(value) => (query.p = value)"
    @update:page-size="(value) => (query.page_size = value)"
    @change="load"
  >
    <template #actions>
      <el-button type="primary" :icon="Plus" @click="openCreate">添加管理员</el-button>
    </template>

    <template #filters>
      <el-input
        v-model="query.keyword"
        placeholder="姓名 / 账号"
        clearable
        :prefix-icon="Search"
        @keyup.enter="() => { query.p = 1; load() }"
      />
      <el-select v-model="query.role_code" placeholder="角色" clearable>
        <el-option
          v-for="role in roles"
          :key="role.code"
          :label="role.name"
          :value="role.code"
        />
      </el-select>
      <el-select v-model="query.campus_id" placeholder="所属校区" clearable>
        <el-option
          v-for="campus in campuses"
          :key="campus.id"
          :label="campus.name"
          :value="String(campus.id)"
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
      empty-text="暂无管理员"
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
            {{ (row.display_name || row.username || '管').slice(0, 1) }}
          </el-avatar>
        </template>
      </el-table-column>
      <el-table-column label="姓名" min-width="140">
        <template #default="{ row }">
          <span class="cell-strong">{{ row.display_name || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="角色" min-width="150">
        <template #default="{ row }">
          <el-tag
            v-for="code in row.role_codes"
            :key="code"
            size="small"
            effect="light"
            class="role-tag"
          >
            {{ roleLabel(code) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="所属校区" min-width="150">
        <template #default="{ row }">{{ row.campus_name || '—' }}</template>
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
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" @click="resetPassword(row)">重置密码</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </DataPage>

  <el-dialog v-model="dialogVisible" :lock-scroll="false" :title="editingId ? '编辑管理员' : '新增管理员'" width="520px" append-to-body>
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="头像">
        <div class="avatar-field">
          <el-upload :show-file-list="false" :http-request="uploadAvatar" accept="image/*">
            <el-avatar
              :key="form.avatar || 'empty'"
              :size="64"
              :src="form.avatar ? `/api/image/${form.avatar}` : undefined"
            >
              {{ (form.real_name || '管').slice(0, 1) }}
            </el-avatar>
          </el-upload>
          <span class="avatar-field__hint">点击上传头像，建议 1:1 方形图片</span>
        </div>
      </el-form-item>
      <el-form-item label="姓名" prop="real_name">
        <el-input v-model="form.real_name" placeholder="请输入姓名" />
      </el-form-item>
      <el-form-item label="手机号" prop="phone">
        <el-input v-model="form.phone" placeholder="作为登录账号，11 位手机号" />
      </el-form-item>
      <el-form-item label="角色" prop="role_code">
        <el-select v-model="form.role_code" style="width: 100%">
          <el-option v-for="role in selectableRoles" :key="role.code" :label="role.name" :value="role.code" />
        </el-select>
      </el-form-item>
      <el-form-item label="所属校区" prop="campus_id">
        <el-select v-model="form.campus_id" placeholder="请选择所属校区" style="width: 100%">
          <el-option v-for="campus in campuses" :key="campus.id" :label="campus.name" :value="campus.id" />
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
.role-tag {
  margin-right: 4px;
}
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
