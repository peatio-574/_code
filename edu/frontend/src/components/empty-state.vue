<script setup lang="ts">
// 空状态：统一的图标 + 标题 + 描述 + 可选操作。
import { Document } from '@element-plus/icons-vue'
import type { Component } from 'vue'

withDefaults(
  defineProps<{
    title?: string
    description?: string
    /** 自定义图标组件；不传则使用默认图标 */
    icon?: Component
  }>(),
  {
    title: '暂无数据',
    description: '',
    icon: undefined,
  },
)

const defaultIcon = Document
</script>

<template>
  <div class="empty-state">
    <div class="empty-state__icon">
      <el-icon :size="30"><component :is="icon ?? defaultIcon" /></el-icon>
    </div>
    <p class="empty-state__title">{{ title }}</p>
    <p v-if="description" class="empty-state__desc">{{ description }}</p>
    <div v-if="$slots.default" class="empty-state__action">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-12) var(--space-6);
  text-align: center;
}
.empty-state__icon {
  display: grid;
  width: 64px;
  height: 64px;
  margin-bottom: var(--space-2);
  place-items: center;
  border-radius: var(--radius-pill);
  background: var(--slate-100);
  color: var(--slate-400);
}
.empty-state__title {
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
}
.empty-state__desc {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}
.empty-state__action {
  margin-top: var(--space-3);
}
</style>
