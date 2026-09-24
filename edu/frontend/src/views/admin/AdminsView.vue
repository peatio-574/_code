<script setup lang="ts">
// 管理员管理：账号 CRUD、角色/校区、重置密码与启停。
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import {
  createAdmin,
  deleteAdmin,
  listAdmins,
  listCampuses,
  resetAdminPassword,
  toggleAdmin,
  updateAdmin,
} from '@/api/admin'
import { getRoles, type RoleItem } from '@/api/auth'
import DataPage from '@/components/data-page.vue'
import StatusSwitch from '@/components/status-switch.vue'
import { formatDateTime, roleLabel, STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const isSuper = auth.user?.roles?.includes('system_admin') ?? false

const items = ref<Record<string, any>[]>([])
const total = ref(0)
const loading = ref(false)
const saving = ref(false)
const roles = ref<RoleItem[]>([])
const campuses = ref<Record<string, any>[]>([])
const query = reactive({ p: 1, page_size: 20, keyword: '', status: '', campus_id: '' })

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({ real_name: '', phone: '', role_code: 'principal', campus_id: 0, password: '', status: 1 })

async function load() {
  loading.value = true
  try {
    const page = await listAdmins({
      p: query.p,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      status: query.status || undefined,
      campus_id: query.campus_id || undefined,
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
  query.p = 1
  load()
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { real_name: '', phone: '', role_code: 'principal', campus_id: 0, password: '', status: 1 })
  dialogVisible.value = true
}

function openEdit(row: Record<string, any>) {
  editingId.value = row.id
  Object.assign(form, {
    real_name: row.display_name,
    phone: '',
    role_code: row.role_codes?.[0] ?? 'principal',
    campus_id: row.campus_id ?? 0,
    password: '',
    status: row.status,
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.phone && !editingId.value) {
    ElMessage.warning('请填写手机号')
    return
  }
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      real_name: form.real_name,
      phone: form.phone,
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

onMounted(async () => {
  roles.value = (await getRoles()).filter((role) => ['principal', 'homeroom_teacher'].includes(role.code))
  campuses.value = (await listCampuses({ page_size: 100 }))?.items ?? []
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
      <el-select v-model="query.status" placeholder="状态" clearable>
        <el-option label="已启用" value="1" />
        <el-option label="已禁用" value="0" />
      </el-select>
      <el-button type="primary" @click="() => { query.p = 1; load() }">搜索</el-button>
      <el-button @click="reset">重置</el-button>
    </template>

    <el-table :data="items" row-key="id" height="100%" empty-text="暂无管理员">
      <el-table-column label="账号信息" min-width="200">
        <template #default="{ row }">
          <div class="user-cell">
            <el-avatar :size="36" :src="row.avatar ? `/api/image/${row.avatar}` : undefined">
              {{ (row.display_name || row.username || '管').slice(0, 1) }}
            </el-avatar>
            <div>
              <div class="user-cell__name">{{ row.display_name || '—' }}</div>
              <div class="user-cell__meta">{{ row.username }}</div>
            </div>
          </div>
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
      <el-table-column label="操作" width="210" fixed="right">
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
    <el-form label-position="top">
      <el-form-item label="姓名" required>
        <el-input v-model="form.real_name" placeholder="请输入姓名" />
      </el-form-item>
      <el-form-item label="手机号" required>
        <el-input v-model="form.phone" :placeholder="editingId ? '留空则不修改' : '作为登录账号，11 位手机号'" />
      </el-form-item>
      <el-form-item label="角色">
        <el-select v-model="form.role_code" style="width: 100%">
          <el-option v-for="role in roles" :key="role.code" :label="role.name" :value="role.code" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="isSuper" label="所属校区">
        <el-select v-model="form.campus_id" style="width: 100%">
          <el-option label="不指定" :value="0" />
          <el-option v-for="campus in campuses" :key="campus.id" :label="campus.name" :value="campus.id" />
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

<style scoped>
.role-tag {
  margin-right: 4px;
}
</style>
