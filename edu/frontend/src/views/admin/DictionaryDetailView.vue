<script setup lang="ts">
// 字典详情：枚举值编辑、新增、删除与排序，并可维护字典基础信息。
import { ArrowLeft, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  createDictionaryItem,
  deleteDictionaryItem,
  listDictionaryItems,
  listDictionaryTypes,
  toggleDictionaryItem,
  updateDictionaryItem,
  updateDictionaryType,
} from '@/api/admin'
import StatusSwitch from '@/components/status-switch.vue'
import { errorMessage } from '@/lib/api'
import { formatDateTime, STATUS_FAILURE_TEXT, statusChangeMessage } from '@/lib/labels'

const route = useRoute()
const router = useRouter()

const typeId = computed(() => Number(route.params.typeId))
const dictType = ref<Record<string, any> | null>(null)
const items = ref<Record<string, any>[]>([])
const loading = ref(false)

const baseForm = reactive({ name: '', code: '', description: '' })
const baseSaving = ref(false)

const itemDialogVisible = ref(false)
const itemSaving = ref(false)
const itemForm = reactive({ id: 0, name: '', sort: 1 })

const nextSort = computed(() =>
  items.value.reduce((max, item) => Math.max(max, item.sort_order ?? 0), 0) + 1,
)

async function load() {
  loading.value = true
  try {
    const [typeData, itemData] = await Promise.all([listDictionaryTypes(), listDictionaryItems(typeId.value)])
    dictType.value = (typeData?.items ?? []).find((type) => type.id === typeId.value) ?? null
    items.value = [...(itemData?.items ?? [])].sort(
      (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.id - b.id,
    )
    if (!dictType.value) {
      ElMessage.error('字典不存在')
      router.replace({ name: 'admin-dictionaries' })
      return
    }
    Object.assign(baseForm, {
      name: dictType.value.name,
      code: dictType.value.code,
      description: dictType.value.description ?? '',
    })
  } finally {
    loading.value = false
  }
}

function goBack() {
  router.push({ name: 'admin-dictionaries' })
}

async function saveBase() {
  if (!dictType.value) return
  if (!baseForm.name.trim()) {
    ElMessage.warning('请填写字典中文名')
    return
  }
  baseSaving.value = true
  try {
    const result = await updateDictionaryType(dictType.value.id, {
      code: dictType.value.code,
      name: baseForm.name,
      description: baseForm.description,
      status: dictType.value.status,
      sort_order: dictType.value.sort_order,
    })
    if (result.success) {
      ElMessage.success('已保存')
      await load()
    } else {
      ElMessage.error(result.message || '保存失败')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    baseSaving.value = false
  }
}

function openCreate() {
  Object.assign(itemForm, { id: 0, name: '', sort: nextSort.value })
  itemDialogVisible.value = true
}

function openEdit(row: Record<string, any>) {
  Object.assign(itemForm, { id: row.id, name: row.name, sort: row.sort_order ?? 1 })
  itemDialogVisible.value = true
}

async function saveItem() {
  if (!itemForm.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  if (!itemForm.sort || itemForm.sort < 1) {
    ElMessage.warning('请填写排序（从 1 开始的整数）')
    return
  }
  itemSaving.value = true
  try {
    const current = items.value.find((item) => item.id === itemForm.id)
    const payload = itemForm.id
      ? {
          type_id: typeId.value,
          code: current?.code ?? '',
          name: itemForm.name,
          description: current?.description ?? '',
          status: current?.status ?? 1,
          sort_order: itemForm.sort,
        }
      : { type_id: typeId.value, code: '', name: itemForm.name, description: '', status: 1, sort_order: itemForm.sort }
    const result = itemForm.id
      ? await updateDictionaryItem(itemForm.id, payload)
      : await createDictionaryItem(payload)
    if (result.success) {
      ElMessage.success('已保存')
      itemDialogVisible.value = false
      await load()
    } else {
      ElMessage.error(result.message || '保存失败')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    itemSaving.value = false
  }
}

async function removeItem(row: Record<string, any>) {
  try {
    await ElMessageBox.confirm(`确定删除枚举值“${row.name}”吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    const result = await deleteDictionaryItem(row.id)
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

async function toggleItem(row: Record<string, any>, next: number) {
  const previous = row.status
  row.status = next
  try {
    const result = await toggleDictionaryItem(row.id, next)
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

// 组件在同类路由间复用时不会重新挂载，需监听参数变化重新加载
watch(typeId, () => {
  if (Number.isFinite(typeId.value)) void load()
})
</script>

<template>
  <section class="data-page">
    <div class="detail-head">
      <el-button circle class="detail-head__back" :icon="ArrowLeft" @click="goBack" />
      <span class="detail-head__name">{{ dictType?.name || '字典详情' }}</span>
    </div>

    <div class="data-page__card dict-base">
      <div class="dict-base__row">
        <span class="dict-base__label">字典中文名</span>
        <el-input v-model="baseForm.name" style="width: 200px" />
        <span class="dict-base__label">字典英文名</span>
        <el-input v-model="baseForm.code" disabled style="width: 200px" />
        <span class="dict-base__label">备注</span>
        <el-input v-model="baseForm.description" style="width: 260px" placeholder="可选" />
        <el-button type="primary" :loading="baseSaving" :disabled="!dictType" @click="saveBase">保存</el-button>
      </div>
    </div>

    <div class="data-page__card">
      <div class="data-page__toolbar">
        <span class="detail-toolbar__title">枚举值</span>
        <span class="toolbar-spacer" />
        <el-button type="primary" :icon="Plus" :disabled="!dictType" @click="openCreate">新增枚举值</el-button>
      </div>

      <div class="data-page__body">
        <el-table v-loading="loading" :data="items" row-key="id" height="100%" empty-text="暂无枚举值">
          <el-table-column label="排序" min-width="100" align="center">
            <template #default="{ row }">
              <span class="tabular">{{ row.sort_order }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="180">
            <template #default="{ row }">
              <span class="cell-strong">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="140">
            <template #default="{ row }">
              <StatusSwitch :status="row.status" @change="(next) => toggleItem(row, next)" />
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
                <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
                <el-button link type="danger" @click="removeItem(row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="itemDialogVisible" :lock-scroll="false" :title="itemForm.id ? '编辑枚举值' : '新增枚举值'" width="480px" append-to-body>
      <el-form label-position="top">
        <el-form-item label="名称" required>
          <el-input v-model="itemForm.name" placeholder="如 公开课" />
        </el-form-item>
        <el-form-item label="排序" required>
          <el-input-number v-model="itemForm.sort" :min="1" :step="1" style="width: 160px" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="itemDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="itemSaving" @click="saveItem">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.detail-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
}
.detail-head__back {
  width: 40px;
  height: 40px;
  font-size: 20px;
}
.detail-head__name {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--text-strong);
}
.detail-toolbar__title {
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--text-strong);
}
.dict-base {
  flex: 0 0 auto;
}
.dict-base__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}
.dict-base__label {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
}
</style>
