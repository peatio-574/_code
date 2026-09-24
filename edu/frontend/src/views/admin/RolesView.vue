<script setup lang="ts">
// 角色管理：角色列表（隐藏超级管理员/学员）与新增、权限配置弹窗。
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import {
  createRole,
  getPermissions,
  getRoles,
  setRolePermissions,
  updateRole,
  type PermissionItem,
  type RoleItem,
} from '@/api/auth'
import DataPage from '@/components/data-page.vue'
import { formatDateTime } from '@/lib/labels'

const SCOPE_NAMES: Record<string, string> = {
  self: '仅本人',
  direct: '直接下级',
  tree: '下级树',
  all: '全部数据',
}

// 权限模块的中文名，弹窗按此分组展示
const MODULE_NAMES: Record<string, string> = {
  dashboard: '控制台总览',
  courses: '课程管理',
  questions: '题库管理',
  exams: '考试管理',
  teachers: '教师管理',
  campuses: '校区管理',
  administrators: '管理员管理',
  students: '学员管理',
  roles: '角色管理',
  announcements: '通知公告',
  dictionaries: '字典管理',
  system: '系统配置',
  learning: '学习功能',
}

// 按权限模块分配颜色，使同类权限标签视觉一致
const MODULE_TAG_TYPES: Record<string, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  dashboard: 'primary',
  courses: 'success',
  questions: 'warning',
  exams: 'danger',
  teachers: 'info',
  campuses: 'primary',
  administrators: 'success',
  students: 'warning',
  roles: 'danger',
  announcements: 'info',
  dictionaries: 'primary',
  system: 'danger',
  learning: 'success',
}

function moduleName(module: string) {
  return MODULE_NAMES[module] ?? module
}

const roles = ref<RoleItem[]>([])
const permissions = ref<PermissionItem[]>([])
const loading = ref(false)
const saving = ref(false)

const dialogVisible = ref(false)
const editingRole = ref<RoleItem | null>(null)
const form = reactive({ name: '', description: '', data_scope: 'self', level: 100 })
const selectedPermissions = ref<string[]>([])

const permissionMap = computed(() => new Map(permissions.value.map((item) => [item.code, item])))
const permissionGroups = computed(() => {
  const groups = new Map<string, PermissionItem[]>()
  for (const item of permissions.value) {
    const list = groups.get(item.module) ?? []
    list.push(item)
    groups.set(item.module, list)
  }
  return [...groups.entries()]
})

/** 角色已授权的权限项（用于标签展示）。 */
function rolePermissions(role: RoleItem): PermissionItem[] {
  return (role.permission_codes ?? []).map((code) => permissionMap.value.get(code) ?? {
    id: 0,
    code,
    name: code,
    description: '',
    module: '',
    built_in: false,
    status: 1,
  })
}

function moduleTagType(module: string) {
  return MODULE_TAG_TYPES[module] ?? 'info'
}

async function load() {
  loading.value = true
  try {
    const [roleItems, permissionItems] = await Promise.all([getRoles(), getPermissions()])
    // 隐藏超级管理员与学员，仅展示可配置的管理类角色
    roles.value = roleItems.filter((role) => !['teacher', 'system_admin', 'student'].includes(role.code))
    permissions.value = permissionItems
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingRole.value = null
  Object.assign(form, { name: '', description: '', data_scope: 'self', level: 100 })
  selectedPermissions.value = []
  dialogVisible.value = true
}

function openEdit(role: RoleItem) {
  editingRole.value = role
  form.name = role.name
  form.description = role.description || ''
  form.data_scope = role.data_scope
  form.level = role.level
  selectedPermissions.value = [...(role.permission_codes ?? [])]
  dialogVisible.value = true
}

function togglePermission(code: string, checked: boolean) {
  if (checked) {
    if (!selectedPermissions.value.includes(code)) selectedPermissions.value.push(code)
  } else {
    selectedPermissions.value = selectedPermissions.value.filter((item) => item !== code)
  }
}

/** 新增角色时按名称生成内部标识（前端不暴露英文名）。 */
function generateRoleCode() {
  return `role_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写角色名称')
    return
  }
  saving.value = true
  try {
    let roleId = editingRole.value?.id
    if (editingRole.value) {
      const updated = await updateRole(editingRole.value.id, {
        name: form.name.trim(),
        description: form.description,
        data_scope: form.data_scope,
        level: form.level,
        status: editingRole.value.status,
      })
      if (!updated.success) {
        ElMessage.error(updated.message || '保存失败')
        return
      }
    } else {
      const created = await createRole({
        code: generateRoleCode(),
        name: form.name.trim(),
        description: form.description,
        data_scope: form.data_scope,
        level: form.level,
        status: 1,
      })
      if (!created.success || !created.data?.id) {
        ElMessage.error(created.message || '创建失败')
        return
      }
      roleId = created.data.id
    }
    if (roleId && editingRole.value?.code !== 'system_admin') {
      const result = await setRolePermissions(roleId, selectedPermissions.value)
      if (!result.success) {
        ElMessage.error(result.message || '权限保存失败')
        return
      }
    }
    ElMessage.success(editingRole.value ? '角色已更新' : '角色已创建')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <DataPage
    title="角色管理"
    description="配置各角色的数据范围与功能权限；保存后该角色下用户的会话将立即失效。"
    :total="roles.length"
    :page="1"
    :page-size="roles.length || 20"
    :loading="loading"
    :pagination="false"
  >
    <template #actions>
      <el-button type="primary" :icon="Plus" @click="openCreate">新增角色</el-button>
    </template>

    <el-table :data="roles" row-key="id" height="100%" empty-text="暂无角色">
      <el-table-column label="角色" min-width="200">
        <template #default="{ row }">
          <div class="user-cell">
            <el-avatar :size="36" shape="square" class="role-avatar">{{ row.name.slice(0, 1) }}</el-avatar>
            <div class="user-cell__name">{{ row.name }}</div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="数据范围" min-width="140">
        <template #default="{ row }">
          <el-tag effect="light" type="primary">{{ SCOPE_NAMES[row.data_scope] ?? row.data_scope }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="已授权限" min-width="360">
        <template #default="{ row }">
          <div class="permission-tags">
            <el-tag
              v-for="permission in rolePermissions(row)"
              :key="permission.code"
              :type="moduleTagType(permission.module)"
              effect="light"
              size="small"
            >
              {{ permission.name }}
            </el-tag>
            <span v-if="!rolePermissions(row).length" class="cell-muted">—</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" min-width="190">
        <template #default="{ row }"><span class="cell-muted tabular">{{ formatDateTime(row.updated_at) }}</span></template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>
  </DataPage>

  <el-dialog
    v-model="dialogVisible"
    :lock-scroll="false"
    :title="editingRole ? '编辑角色' : '新增角色'"
    width="760px"
    top="6vh"
    append-to-body
  >
    <el-form label-position="top">
      <el-row :gutter="16">
        <el-col :span="12"><el-form-item label="角色名称" required><el-input v-model="form.name" placeholder="请输入角色名称" /></el-form-item></el-col>
        <el-col :span="12">
          <el-form-item label="数据范围">
            <el-select v-model="form.data_scope" :disabled="editingRole?.built_in" style="width: 100%">
              <el-option v-for="(label, value) in SCOPE_NAMES" :key="value" :label="label" :value="value" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12"><el-form-item label="角色级别"><el-input-number v-model="form.level" :min="1" :disabled="editingRole?.built_in" style="width: 100%" /></el-form-item></el-col>
        <el-col :span="12"><el-form-item label="说明"><el-input v-model="form.description" placeholder="可选" /></el-form-item></el-col>
      </el-row>
    </el-form>

    <el-alert
      v-if="editingRole?.code === 'system_admin'"
      type="info"
      :closable="false"
      title="超级管理员权限固定，不允许取消。"
      class="permission-alert"
    />

    <p class="permission-title">功能权限</p>
    <div v-for="[module, items] in permissionGroups" :key="module" class="permission-group">
      <div class="permission-group__title">{{ moduleName(module) }}</div>
      <div class="permission-items">
        <label v-for="item in items" :key="item.id" class="permission-item" :class="{ 'is-checked': selectedPermissions.includes(item.code) }">
          <el-checkbox
            :model-value="selectedPermissions.includes(item.code)"
            @update:model-value="(checked: any) => togglePermission(item.code, checked === true)"
          />
          <span>{{ item.name }}</span>
        </label>
      </div>
    </div>

    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.role-avatar {
  background: var(--brand-50);
  color: var(--brand-500);
  font-weight: 700;
}
.permission-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-2);
}
.permission-alert {
  margin-bottom: var(--space-4);
}
.permission-title {
  margin-bottom: var(--space-3);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
}
.permission-group {
  margin-bottom: var(--space-4);
}
.permission-group__title {
  margin-bottom: var(--space-2);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-strong);
}
.permission-items {
  display: grid;
  gap: var(--space-2);
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.permission-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: var(--text-sm);
  transition: all var(--duration-fast) var(--ease-out);
}
.permission-item:hover {
  background: var(--slate-50);
}
.permission-item.is-checked {
  border-color: var(--brand-300);
  background: var(--brand-50);
}
</style>
