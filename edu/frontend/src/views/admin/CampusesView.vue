<script setup lang="ts">
// 校区管理：校区 CRUD、状态联动与成员维护。
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { computed, nextTick, onMounted, reactive, ref } from 'vue'

import {
  createCampus,
  deleteCampus,
  deleteCampusMember,
  listCampusMembers,
  listCampuses,
  toggleCampus,
  updateCampus,
  updateCampusMember,
} from '@/api/admin'
import DataPage from '@/components/data-page.vue'
import StatusSwitch from '@/components/status-switch.vue'
import { formatDateTime, STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'
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
const formRef = ref<FormInstance>()
const rules: FormRules = {
  name: [{ required: true, message: '请填写校区名称', trigger: 'blur' }],
}

const membersVisible = ref(false)
const activeCampus = ref<Record<string, any> | null>(null)
const members = ref<Record<string, any>[]>([])
const memberLoading = ref(false)
const memberTotal = ref(0)
const memberQuery = reactive({ p: 1, page_size: 20, keyword: '', member_type: '' })
const memberPageSizes = [20, 50, 100]

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

async function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', address: '', contact_name: '', contact_mobile: '', status: 1 })
  dialogVisible.value = true
  await nextTick()
  formRef.value?.clearValidate()
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
  nextTick(() => formRef.value?.clearValidate())
}

async function save() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
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
  memberQuery.p = 1
  memberQuery.keyword = ''
  memberQuery.member_type = ''
  membersVisible.value = true
  await refreshMembers()
}

async function refreshMembers() {
  if (!activeCampus.value) return
  memberLoading.value = true
  try {
    const data = await listCampusMembers(activeCampus.value.id, {
      p: memberQuery.p,
      page_size: memberQuery.page_size,
      keyword: memberQuery.keyword || undefined,
      member_type: memberQuery.member_type || undefined,
    })
    members.value = data?.items ?? []
    memberTotal.value = data?.total ?? 0
  } finally {
    memberLoading.value = false
  }
}

function searchMembersList() {
  memberQuery.p = 1
  refreshMembers()
}

function resetMembersFilter() {
  memberQuery.keyword = ''
  memberQuery.member_type = ''
  memberQuery.p = 1
  refreshMembers()
}

/** 移除/改类后若当前页已空则回退一页，避免出现空白页。 */
function afterMemberChange() {
  if (members.value.length === 0 && memberQuery.p > 1) memberQuery.p -= 1
  refreshMembers()
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
    afterMemberChange()
  } else {
    ElMessage.error(result.message || '移除失败')
  }
}

async function changeMemberType(row: Record<string, any>, type: string) {
  const result = await updateCampusMember(activeCampus.value!.id, row.user_id, { member_type: type })
  if (result.success) refreshMembers()
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
      <el-table-column label="校区" min-width="200">
        <template #default="{ row }"><span class="cell-strong">{{ row.name }}</span></template>
      </el-table-column>
      <el-table-column label="负责人" min-width="140">
        <template #default="{ row }">{{ row.contact_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="联系方式" min-width="160">
        <template #default="{ row }"><span class="tabular">{{ row.contact_mobile || '—' }}</span></template>
      </el-table-column>
      <el-table-column label="校区地址" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">{{ row.address || '—' }}</template>
      </el-table-column>
      <el-table-column label="管理员数量" min-width="120" align="center">
        <template #default="{ row }">
          <span class="count-chip count-chip--manager tabular">{{ row.manager_count ?? 0 }}</span>
        </template>
      </el-table-column>
      <el-table-column label="学员数量" min-width="120" align="center">
        <template #default="{ row }">
          <span class="count-chip count-chip--student tabular">{{ row.student_count ?? 0 }}</span>
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
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="校区名称" prop="name">
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

  <el-drawer
    v-model="membersVisible"
    :lock-scroll="false"
    :title="`校区成员 · ${activeCampus?.name ?? ''}`"
    size="min(92vw, 1080px)"
    class="member-drawer"
  >
    <section class="member-page">
      <div class="member-toolbar">
        <el-input
          v-model="memberQuery.keyword"
          placeholder="搜索姓名 / 账号"
          clearable
          :prefix-icon="Search"
          class="member-toolbar__search"
          @keyup.enter="searchMembersList"
          @clear="searchMembersList"
        />
        <el-select
          v-model="memberQuery.member_type"
          placeholder="成员类型"
          clearable
          class="member-toolbar__type"
          @change="searchMembersList"
        >
          <el-option label="校长" value="principal" />
          <el-option label="班主任" value="homeroom_teacher" />
          <el-option label="学员" value="student" />
        </el-select>
        <el-button type="primary" @click="searchMembersList">搜索</el-button>
        <el-button @click="resetMembersFilter">重置</el-button>
      </div>

      <div class="member-body">
        <el-table
          v-loading="memberLoading"
          :data="members"
          row-key="id"
          height="100%"
          empty-text="暂无成员"
        >
          <el-table-column label="成员" min-width="180">
            <template #default="{ row }">
              <span class="cell-strong">{{ row.display_name || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="成员类型" min-width="160">
            <template #default="{ row }">
              <el-select :model-value="row.member_type" @change="(value: string) => changeMemberType(row, value)">
                <el-option label="校长" value="principal" :disabled="!isSuper" />
                <el-option label="班主任" value="homeroom_teacher" />
                <el-option label="学员" value="student" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="120">
            <template #default="{ row }">
              <el-tag :type="row.status === 1 ? 'success' : 'info'" effect="light">
                {{ row.status === 1 ? '启用' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" min-width="90">
            <template #default="{ row }">
              <el-button link type="danger" @click="removeMember(row)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <footer class="member-footer">
        <span class="member-footer__total">共 {{ memberTotal }} 条记录</span>
        <el-pagination
          :current-page="memberQuery.p"
          :page-size="memberQuery.page_size"
          :page-sizes="memberPageSizes"
          :total="memberTotal"
          background
          layout="sizes, prev, pager, next, jumper"
          @current-change="(value: number) => { memberQuery.p = value; refreshMembers() }"
          @size-change="(value: number) => { memberQuery.page_size = value; memberQuery.p = 1; refreshMembers() }"
        />
      </footer>
    </section>
  </el-drawer>
</template>

<style scoped>
.count-chip {
  display: inline-flex;
  min-width: 44px;
  align-items: center;
  justify-content: center;
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  font-weight: 700;
}
.count-chip--manager {
  background: var(--brand-50);
  color: var(--brand-600);
}
.count-chip--student {
  background: var(--success-bg);
  color: var(--success);
}
/* 成员抽屉：与外部列表页一致（卡片 + 工具栏/分页固定，仅列表滚动） */
.member-page {
  display: flex;
  flex: 1;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  padding: var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}
.member-toolbar {
  display: flex;
  flex-wrap: wrap;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.member-toolbar__search {
  width: 220px;
}
.member-toolbar__type {
  width: 150px;
}
.member-body {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
}
.member-body > .el-table {
  flex: 1;
  min-height: 0;
}
.member-footer {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2) var(--space-4);
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--border-color);
}
.member-footer__total {
  flex-shrink: 0;
  white-space: nowrap;
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.member-footer :deep(.el-pagination) {
  flex-wrap: wrap;
  row-gap: var(--space-2);
}
</style>

<!--
  非 scoped：el-drawer 的 class 合并到 .el-drawer，而 scoped 属性落在 .el-overlay，
  复合选择器 .member-drawer[data-v-x] 无法匹配，故对抽屉结构用全局选择器（类名唯一不泄漏）。
-->
<style>
.member-drawer.el-drawer {
  display: flex;
  flex-direction: column;
}
.member-drawer .el-drawer__header {
  flex-shrink: 0;
  margin-bottom: 0;
}
.member-drawer .el-drawer__body {
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  padding: 20px 24px;
}
</style>
