<script setup lang="ts">
// 课程中心：课程方向多选筛选、搜索、分页与课程卡片。
import { Search } from '@element-plus/icons-vue'
import { onMounted, reactive, ref, watch } from 'vue'

import { getCourseTypes, getCourses } from '@/api/portal'
import CourseCard from '@/components/course-card.vue'

const types = ref<{ id: number; code: string; name: string }[]>([])
const items = ref<Record<string, any>[]>([])
const total = ref(0)
const loading = ref(false)

const PAGE_SIZE = 12

const query = reactive({
  p: 1,
  page_size: PAGE_SIZE,
  keyword: '',
  course_type_code: [] as string[],
})

async function load() {
  loading.value = true
  try {
    const page = await getCourses({
      p: query.p,
      page_size: query.page_size,
      keyword: query.keyword,
      course_type_code: query.course_type_code,
    })
    items.value = page?.items ?? []
    total.value = page?.total ?? 0
  } finally {
    loading.value = false
  }
}

function reset() {
  query.keyword = ''
  query.course_type_code = []
  query.p = 1
  load()
}

watch(
  () => query.p,
  () => load(),
)

onMounted(async () => {
  types.value = await getCourseTypes()
  await load()
})
</script>

<template>
  <div class="courses">
    <header class="data-page__header courses__header page-hero">
      <div>
        <h1 class="data-page__title">课程中心</h1>
        <p class="data-page__desc">浏览全部课程，按课程方向筛选并进入学习。</p>
      </div>
    </header>

    <div class="courses__toolbar">
      <el-input
        v-model="query.keyword"
        placeholder="搜索课程名称"
        clearable
        :prefix-icon="Search"
        class="courses__search"
        @keyup.enter="() => { query.p = 1; load() }"
      />
      <el-select
        v-model="query.course_type_code"
        multiple
        collapse-tags
        collapse-tags-tooltip
        clearable
        placeholder="课程方向"
        class="courses__types"
        @change="() => { query.p = 1; load() }"
      >
        <el-option v-for="type in types" :key="type.code" :label="type.name" :value="type.code" />
      </el-select>
      <el-button type="primary" @click="() => { query.p = 1; load() }">搜索</el-button>
      <el-button @click="reset">重置</el-button>
    </div>

    <div v-if="items.length" v-loading="loading" class="courses__grid">
      <CourseCard v-for="course in items" :key="course.id" :course="course" />
    </div>
    <el-empty v-else-if="!loading" description="没有找到符合条件的课程" />

    <div class="courses__footer">
      <span class="courses__total">共 {{ total }} 条课程</span>
      <el-pagination
        :current-page="query.p"
        :page-size="query.page_size"
        :total="total"
        background
        layout="prev, pager, next, jumper"
        @current-change="(value: number) => (query.p = value)"
      />
    </div>
  </div>
</template>

<style scoped>
.courses {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  /* 由门户壳层固定为整屏布局，此处仅占满剩余空间，不产生页面滚动 */
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
/* 顶部书法背景图，高度与其他页面顶部保持一致 */
.courses__header {
  height: clamp(112px, 14vh, 150px);
}
/* 筛选条件独立一行，置于标题面板下方 */
.courses__toolbar {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xs);
}
.courses__search {
  width: 280px;
}
.courses__types {
  width: 280px;
}
/* 网格占满剩余空间并固定两行，保证各分页布局一致 */
.courses__grid {
  display: grid;
  flex: 1;
  min-height: 0;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  grid-template-rows: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}
.courses__grid :deep(.course-card) {
  height: 100%;
}
/* 封面自适应卡片高度，图片铺满 */
.courses__grid :deep(.course-card__cover) {
  flex: 1;
  min-height: 0;
  height: auto;
}
/* 统计与分页固定在内容区底部 */
.courses__footer {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-top: auto;
}
.courses__total {
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

/* 中等屏：维持 6 列 × 2 行（12 条），卡片高度不变 */
@media (max-width: 1024px) {
  .courses__grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    grid-template-rows: repeat(3, minmax(0, 1fr));
  }
}
/* 手机端：放开固定高度，自然滚动 */
@media (max-width: 640px) {
  .courses {
    overflow: visible;
  }
  .courses__header {
    flex: none;
    height: auto;
    min-height: 0;
  }
  .courses__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    grid-template-rows: none;
    grid-auto-rows: auto;
  }
  .courses__grid :deep(.course-card) {
    height: auto;
  }
  .courses__grid :deep(.course-card__cover) {
    flex: none;
    height: 120px;
  }
  .courses__search,
  .courses__types {
    width: 100%;
  }
  .courses__footer {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
