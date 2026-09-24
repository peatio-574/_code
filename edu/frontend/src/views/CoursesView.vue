<script setup lang="ts">
// 课程中心：课程分类多选筛选、搜索、分页与课程卡片。
import { Search } from '@element-plus/icons-vue'
import { onMounted, reactive, ref, watch } from 'vue'

import { getCourseTypes, getCourses } from '@/api/portal'
import CourseCard from '@/components/course-card.vue'

const types = ref<{ id: number; code: string; name: string }[]>([])
const items = ref<Record<string, any>[]>([])
const total = ref(0)
const loading = ref(false)

const query = reactive({
  p: 1,
  page_size: 20,
  keyword: '',
  course_type_code: [] as string[],
})

const pageSizes = [20, 50, 100]

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
  () => [query.p, query.page_size],
  () => load(),
)

onMounted(async () => {
  types.value = await getCourseTypes()
  await load()
})
</script>

<template>
  <div class="courses">
    <header class="courses__header">
      <div>
        <h1 class="data-page__title">课程中心</h1>
        <p class="data-page__desc">浏览全部课程，按分类筛选并进入学习。</p>
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
        placeholder="课程分类"
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
        :page-sizes="pageSizes"
        :total="total"
        background
        layout="sizes, prev, pager, next, jumper"
        @current-change="(value: number) => (query.p = value)"
        @size-change="(value: number) => { query.page_size = value; query.p = 1 }"
      />
    </div>
  </div>
</template>

<style scoped>
.courses {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.courses__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
}
.courses__toolbar {
  display: flex;
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
.courses__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: var(--space-5);
  min-height: 240px;
}
.courses__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--border-color);
}
.courses__total {
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

@media (max-width: 640px) {
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
