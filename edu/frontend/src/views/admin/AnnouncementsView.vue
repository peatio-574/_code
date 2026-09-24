<script setup lang="ts">
// 通知公告：公告 CRUD、发布/撤回与置顶。
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import {
  createAnnouncement,
  deleteAnnouncement,
  listAnnouncements,
  toggleAnnouncementStatus,
  toggleAnnouncementTop,
  updateAnnouncement,
} from '@/api/admin'
import DataPage from '@/components/data-page.vue'
import { formatDateTime } from '@/lib/labels'

const items = ref<Record<string, any>[]>([])
const total = ref(0)
const loading = ref(false)
const saving = ref(false)
const query = reactive({ p: 1, page_size: 20, keyword: '', status: '' })

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({ title: '', content: '', status: 0 })

async function load() {
  loading.value = true
  try {
    const page = await listAnnouncements({
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
  Object.assign(form, { title: '', content: '', status: 0 })
  dialogVisible.value = true
}

function openEdit(row: Record<string, any>) {
  editingId.value = row.id
  Object.assign(form, { title: row.title, content: row.content, status: row.status })
  dialogVisible.value = true
}

async function save() {
  if (!form.title.trim() || !form.content.trim()) {
    ElMessage.warning('请填写标题和内容')
    return
  }
  saving.value = true
  try {
    const payload: Record<string, unknown> = { title: form.title, content: form.content, status: form.status }
    if (editingId.value) payload.id = editingId.value
    const result = editingId.value ? await updateAnnouncement(payload) : await createAnnouncement(payload)
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

async function toggleStatus(row: Record<string, any>, next: number) {
  const result = await toggleAnnouncementStatus(row.id, next)
  if (result.success) {
    ElMessage.success(next === 1 ? '已发布' : '已撤回')
    await load()
  } else {
    ElMessage.error(result.message || '操作失败')
  }
}

async function toggleTop(row: Record<string, any>, next: number) {
  const result = await toggleAnnouncementTop(row.id, next)
  if (result.success) {
    ElMessage.success(next === 1 ? '已置顶' : '已取消置顶')
    await load()
  } else {
    ElMessage.error(result.message || '操作失败')
  }
}

async function remove(row: Record<string, any>) {
  try {
    await ElMessageBox.confirm(`确定删除公告“${row.title}”吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const result = await deleteAnnouncement(row.id)
  if (result.success) {
    ElMessage.success('已删除')
    await load()
  } else {
    ElMessage.error(result.message || '删除失败')
  }
}

onMounted(load)
</script>

<template>
  <DataPage
    title="通知公告"
    description="发布公告后将展示在首页并登录后弹窗提示。"
    :total="total"
    :page="query.p"
    :page-size="query.page_size"
    :loading="loading"
    @update:page="(value) => (query.p = value)"
    @update:page-size="(value) => (query.page_size = value)"
    @change="load"
  >
    <template #actions>
      <el-button type="primary" :icon="Plus" @click="openCreate">新增公告</el-button>
    </template>

    <template #filters>
      <el-input
        v-model="query.keyword"
        placeholder="公告标题"
        clearable
        :prefix-icon="Search"
        @keyup.enter="() => { query.p = 1; load() }"
      />
      <el-select v-model="query.status" placeholder="状态" clearable>
        <el-option label="已发布" value="1" />
        <el-option label="未发布" value="0" />
      </el-select>
      <el-button type="primary" @click="() => { query.p = 1; load() }">搜索</el-button>
      <el-button @click="reset">重置</el-button>
    </template>

    <el-table :data="items" row-key="id" height="100%" empty-text="暂无公告，点击右上角「新增公告」开始">
      <el-table-column label="标题" min-width="340">
        <template #default="{ row }">
          <div class="announcement-title">
            <el-tag v-if="row.top === 1" type="warning" size="small" effect="light">置顶</el-tag>
            <span class="announcement-title__text" :title="row.title">{{ row.title }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="状态" min-width="96" align="center">
        <template #default="{ row }">
          <el-tag :type="row.status === 1 ? 'success' : 'info'" effect="light" size="large">
            {{ row.status === 1 ? '已发布' : '未发布' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="已阅读" min-width="84" align="center">
        <template #default="{ row }">
          <span class="stat-read tabular">{{ row.read_count ?? 0 }}</span>
        </template>
      </el-table-column>
      <el-table-column label="待阅读" min-width="84" align="center">
        <template #default="{ row }">
          <span class="stat-unread tabular">{{ row.unread_count ?? 0 }}</span>
        </template>
      </el-table-column>
      <el-table-column label="发布时间" min-width="166">
        <template #default="{ row }">
          <span class="announcement-date cell-muted tabular">{{ row.published_at ? formatDateTime(row.published_at) : '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" min-width="166">
        <template #default="{ row }">
          <span class="announcement-date cell-muted tabular">{{ row.updated_at ? formatDateTime(row.updated_at) : '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="290" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link :type="row.status === 1 ? 'warning' : 'success'" @click="toggleStatus(row, row.status === 1 ? 0 : 1)">
              {{ row.status === 1 ? '撤回' : '发布' }}
            </el-button>
            <el-button link type="warning" @click="toggleTop(row, row.top === 1 ? 0 : 1)">
              {{ row.top === 1 ? '取消置顶' : '置顶' }}
            </el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </DataPage>

  <el-dialog
    v-model="dialogVisible"
    :lock-scroll="false"
    :title="editingId ? '编辑公告' : '新增公告'"
    width="860px"
    top="5vh"
    append-to-body
  >
    <el-form label-position="top">
      <el-form-item label="公告标题" required>
        <el-input v-model="form.title" size="large" placeholder="请输入公告标题" />
      </el-form-item>
      <el-form-item label="公告内容" required>
        <el-input
          v-model="form.content"
          type="textarea"
          :autosize="{ minRows: 12, maxRows: 28 }"
          resize="vertical"
          placeholder="支持输入文本与 HTML 富文本，首页将按此内容与格式展示"
        />
      </el-form-item>
      <el-form-item label="状态">
        <el-radio-group v-model="form.status" size="large">
          <el-radio-button :value="1">发布</el-radio-button>
          <el-radio-button :value="0">草稿</el-radio-button>
        </el-radio-group>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.announcement-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  font-weight: 500;
  color: var(--text-strong);
}
.announcement-title__text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}
.stat-read {
  font-weight: 700;
  color: var(--success);
}
.stat-unread {
  font-weight: 700;
  color: var(--warning);
}
.announcement-date {
  white-space: nowrap;
}
</style>
