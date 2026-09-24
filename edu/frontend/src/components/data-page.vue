<script setup lang="ts">
// 数据页通用外壳：页头（标题/说明/操作）+ 卡片（工具栏/内容/分页）。
// 列表页统一使用该组件，保证全站一致的间距、圆角、分页与滚动行为。
withDefaults(
  defineProps<{
    title: string
    description?: string
    total: number
    page: number
    pageSize: number
    pageSizes?: number[]
    /** 加载中：表格区域显示加载态 */
    loading?: boolean
    /** 是否显示分页（无分页数据页可关闭） */
    pagination?: boolean
  }>(),
  {
    description: '',
    pageSizes: () => [20, 50, 100],
    loading: false,
    pagination: true,
  },
)

const emit = defineEmits<{
  (event: 'update:page', value: number): void
  (event: 'update:pageSize', value: number): void
  (event: 'change'): void
}>()

function handlePage(value: number) {
  emit('update:page', value)
  emit('change')
}

function handlePageSize(value: number) {
  emit('update:pageSize', value)
  emit('update:page', 1)
  emit('change')
}
</script>

<template>
  <section class="data-page">
    <div class="data-page__card">
      <div v-if="$slots.actions || $slots.filters" class="data-page__toolbar">
        <slot name="actions" />
        <slot name="filters" />
      </div>

      <div v-loading="loading" class="data-page__body">
        <slot />
      </div>

      <footer v-if="pagination" class="data-page__footer">
        <span class="data-page__total">共 {{ total }} 条记录</span>
        <el-pagination
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="pageSizes"
          :total="total"
          background
          layout="sizes, prev, pager, next, jumper"
          @current-change="handlePage"
          @size-change="handlePageSize"
        />
      </footer>
    </div>
  </section>
</template>
