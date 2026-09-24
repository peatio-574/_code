<script setup lang="ts">
// 状态开关：统一列表页的启用/禁用交互。
// 通过 v-model:status 双向绑定，切换时触发 change 事件，由父组件负责调用接口。
import { ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    status: number
    activeText?: string
    inactiveText?: string
    disabled?: boolean
    /** 切换前确认文案；传空则不弹确认 */
    confirmText?: string
  }>(),
  {
    activeText: '启用',
    inactiveText: '禁用',
    disabled: false,
    confirmText: '',
  },
)

const emit = defineEmits<{
  (event: 'change', next: number): void
}>()

const inner = ref(props.status === 1)

watch(
  () => props.status,
  (value) => {
    inner.value = value === 1
  },
)

function handleChange(value: string | number | boolean) {
  const next = value === true || value === 1 || value === '1' ? 1 : 0
  // 切换失败时由父组件回写 status，这里先同步内部状态
  inner.value = next === 1
  emit('change', next)
}
</script>

<template>
  <div class="status-switch">
    <el-switch
      v-model="inner"
      size="large"
      :disabled="disabled"
      inline-prompt
      :active-text="activeText"
      :inactive-text="inactiveText"
      @change="handleChange"
    />
  </div>
</template>

<style scoped>
.status-switch {
  display: inline-flex;
  align-items: center;
}
</style>
