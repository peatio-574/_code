<script setup lang="ts">
// 校区管理：校区 CRUD、状态联动与成员维护。
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import {
  addCampusMember,
  createCampus,
  deleteCampus,
  deleteCampusMember,
  listAdmins,
  listCampusMembers,
  listCampuses,
  listStudents,
  toggleCampus,
  updateCampus,
  updateCampusMember,
} from '@/api/admin'
import DataPage from '@/components/data-page.vue'
import StatusSwitch from '@/components/status-switch.vue'
import { MEMBER_TYPE_LABELS, formatDateTime, STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const isSuper = computed(() => auth.user?.roles?.includes('system_admin') ?? false)

const items = ref<Record<string, any>[]>([])
const total = ref(0)
const loading = ref(false)
const saving = ref(false)
const query = reactive({ p: 1, page_size: 20, keyword: '', status: '' })

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({ name: '', address: '', contact_name: '', contact_mobile: '', status: 1 })

const membersVisible = ref(false)
const activeCampus = ref<Record<string, any> | null>(null)
const members = ref<Record<string, any>[]>([])
const memberLoading = ref(false)
const memberOptions = ref<Record<string, any>[]>([])
const memberSearching = ref(false)
const memberForm = reactive<{ user_id: number | null; member_type: string; is_primary: boolean }>({
  user_id: null,
  member_type: 'homeroom_teacher',
  is_primary: true,
})

async function load() {
  loading.value = true
  try {
    const page = await listCampuses({
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
  Object.assign(form, { name: '', address: '', contact_name: '', contact_mobile: '', status: 1 })
  dialogVisible.value = true
}

function openEdit(row: Record<string, any>) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    address: row.address,
    contact_name: row.contact_name,
    contact_mobile: row.contact_mobile,
    status: row.status,
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写校区名称')
    return
  }
  saving.value = true
  try {
    const result = editingId.value ? await updateCampus(editingId.value, form) : await createCampus(form)
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
  try {
    await ElMessageBox.confirm(
      '切换校区状态将同时启停该校全部管理员与学员，确定继续吗？',
      '状态联动确认',
      { type: 'warning', confirmButtonText: '确定切换', cancelButtonText: '取消' },
    )
  } catch {
    row.status = previous
    return
  }
  const result = await toggleCampus(row.id)
  if (result.success) {
    await load()
    ElMessage.success(statusChangeMessage(next))
  } else {
    row.status = previous
    ElMessage.error(result.message || STATUS_FAILURE_TEXT)
  }
}

async function remove(row: Record<string, any>) {
  try {
    await ElMessageBox.confirm(`确定删除校区“${row.name}”吗？删除前需先移除全部成员。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const result = await deleteCampus(row.id)
  if (result.success) {
    ElMessage.success('已删除')
    await load()
  } else {
    ElMessage.error(result.message || '删除失败')
  }
}

async function openMembers(row: Record<string, any>) {
  activeCampus.value = row
  memberForm.user_id = null
  memberForm.member_type = 'homeroom_teacher'
  memberForm.is_primary = true
  memberOptions.value = []
  membersVisible.value = true
  await refreshMembers()
}

async function refreshMembers() {
  if (!activeCampus.value) return
  memberLoading.value = true
  try {
    const data = await listCampusMembers(activeCampus.value.id)
    members.value = data?.items ?? []
  } finally {
    memberLoading.value = false
  }
}

/** 远程搜索候选用户：合并管理员与学员，按关键词过滤。 */
async function searchMembers(keyword: string) {
  if (!keyword || keyword.trim().length < 1) {
    memberOptions.value = []
    return
  }
  memberSearching.value = true
  try {
    const [students, admins] = await Promise.all([
      listStudents({ keyword: keyword.trim(), page_size: 20 }),
      listAdmins({ keyword: keyword.trim(), page_size: 20 }),
    ])
    const merged = [...(admins?.items ?? []), ...(students?.items ?? [])]
    const seen = new Set<number>()
    memberOptions.value = merged.filter((user) => {
      if (seen.has(user.id)) return false
      seen.add(user.id)
      return true
    })
  } finally {
    memberSearching.value = false
  }
}

async function addMember() {
  if (!activeCampus.value || !memberForm.user_id) {
    ElMessage.warning('请选择要添加的用户')
    return
  }
  const result = await addCampusMember(activeCampus.value.id, {
    user_id: memberForm.user_id,
    member_type: memberForm.member_type,
    is_primary: memberForm.is_primary,
  })
  if (result.success) {
    ElMessage.success('已添加成员')
    await refreshMembers()
    memberForm.user_id = null
    memberOptions.value = []
  } else {
    ElMessage.error(result.message || '添加失败')
  }
}

async function removeMember(row: Record<string, any>) {
  try {
    await ElMessageBox.confirm(`确定将「${row.display_name || row.username}」移出该校区吗？`, '移除确认', {
      type: 'warning',
      confirmButtonText: '确认移除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const result = await deleteCampusMember(activeCampus.value!.id, row.user_id)
  if (result.success) {
    ElMessage.success('已移除')
    await refreshMembers()
  } else {
    ElMessage.error(result.message || '移除失败')
  }
}

async function changeMemberType(row: Record<string, any>, type: string) {
  const result = await updateCampusMember(activeCampus.value!.id, row.user_id, { member_type: type })
  if (result.success) await refreshMembers()
  else ElMessage.error(result.message || '更新失败')
}

onMounted(load)
</script>

<template>
  <DataPage
    title="校区管理"
    description="维护校区资料与成员归属，校区间数据相互隔离。"
    :total="total"
    :page="query.p"
    :page-size="query.page_size"
    :loading="loading"
    @update:page="(value) => (query.p = value)"
    @update:page-size="(value) => (query.page_size = value)"
    @change="load"
  >
    <template v-if="isSuper" #actions>
      <el-button type="primary" :icon="Plus" @click="openCreate">添加校区</el-button>
    </template>

    <template #filters>
      <el-input
        v-model="query.keyword"
        placeholder="校区名称"
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

    <el-table :data="items" row-key="id" height="100%" empty-text="暂无校区">
      <el-table-column label="校区" min-width="220">
        <template #default="{ row }">
          <div class="campus-cell">
            <span class="campus-cell__mark">{{ row.name.slice(0, 1) }}</span>
            <div>
              <div class="user-cell__name">{{ row.name }}</div>
              <div class="user-cell__meta">{{ row.address || '未填写地址' }}</div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="负责人" min-width="140">
        <template #default="{ row }">{{ row.contact_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="联系方式" min-width="160">
        <template #default="{ row }"><span class="tabular">{{ row.contact_mobile || '—' }}</span></template>
      </el-table-column>
      <el-table-column label="人数（管理员 / 学员）" min-width="180" align="center">
        <template #default="{ row }">
          <span class="tabular"><b>{{ row.principal_count }}</b> / <b>{{ row.student_count }}</b></span>
        </template>
      </el-table-column>
      <el-table-column label="状态" min-width="160">
        <template #default="{ row }">
          <StatusSwitch :status="row.status" :disabled="!isSuper" @change="(next) => toggle(row, next)" />
        </template>
      </el-table-column>
      <el-table-column label="更新时间" min-width="180">
        <template #default="{ row }"><span class="cell-muted tabular">{{ formatDateTime(row.updated_at) }}</span></template>
      </el-table-column>
      <el-table-column label="操作" width="190" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button link type="primary" @click="openMembers(row)">成员管理</el-button>
            <el-button v-if="isSuper" link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button v-if="isSuper" link type="danger" @click="remove(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </DataPage>

  <el-dialog v-model="dialogVisible" :lock-scroll="false" :title="editingId ? '编辑校区' : '新增校区'" width="520px" append-to-body>
    <el-form label-position="top">
      <el-form-item label="校区名称" required>
        <el-input v-model="form.name" placeholder="请输入校区名称" />
      </el-form-item>
      <el-form-item label="校区地址">
        <el-input v-model="form.address" placeholder="请输入详细地址" />
      </el-form-item>
      <el-form-item label="负责人">
        <el-input v-model="form.contact_name" placeholder="请输入负责人姓名" />
      </el-form-item>
      <el-form-item label="联系方式">
        <el-input v-model="form.contact_mobile" placeholder="请输入联系电话" />
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

  <el-drawer v-model="membersVisible" :lock-scroll="false" :title="`校区成员 · ${activeCampus?.name ?? ''}`" size="680px">
    <div class="member-add">
      <el-select
        v-model="memberForm.user_id"
        filterable
        remote
        clearable
        reserve-keyword
        :remote-method="searchMembers"
        :loading="memberSearching"
        placeholder="输入姓名或账号搜索用户"
        class="member-add__user"
      >
        <el-option
          v-for="user in memberOptions"
          :key="user.id"
          :label="`${user.display_name || user.username}（${user.username}）`"
          :value="user.id"
        />
      </el-select>
      <el-select v-model="memberForm.member_type" class="member-add__type">
        <el-option v-if="isSuper" label="校长" value="principal" />
        <el-option label="班主任" value="homeroom_teacher" />
        <el-option label="学员" value="student" />
      </el-select>
      <el-button type="primary" @click="addMember">添加成员</el-button>
    </div>

    <el-table v-loading="memberLoading" :data="members" row-key="id" empty-text="暂无成员">
      <el-table-column label="成员" min-width="200">
        <template #default="{ row }">
          <div class="user-cell">
            <el-avatar :size="34" :src="row.avatar ? `/api/image/${row.avatar}` : undefined">
              {{ (row.display_name || row.username || '用').slice(0, 1) }}
            </el-avatar>
            <div>
              <div class="user-cell__name">{{ row.display_name || '—' }}</div>
              <div class="user-cell__meta">{{ row.username }}</div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="成员类型" min-width="160">
        <template #default="{ row }">
          <el-select :model-value="row.member_type" @change="(value: string) => changeMemberType(row, value)">
            <el-option v-if="isSuper" label="校长" value="principal" />
            <el-option label="班主任" value="homeroom_teacher" />
            <el-option label="学员" value="student" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="状态" min-width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 1 ? 'success' : 'info'" effect="light">
            {{ row.status === 1 ? '在籍' : '已离开' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="90">
        <template #default="{ row }">
          <el-button link type="danger" @click="removeMember(row)">移除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-drawer>
</template>

<style scoped>
.campus-cell {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.campus-cell__mark {
  display: grid;
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  place-items: center;
  border-radius: var(--radius-md);
  background: var(--brand-50);
  color: var(--brand-500);
  font-weight: 700;
}
.member-add {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.member-add__user {
  flex: 1;
}
.member-add__type {
  width: 160px;
}
</style>
