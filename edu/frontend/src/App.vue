<script setup lang="ts">
// 应用根组件。
// 全局使用 large 尺寸与中文语言包，配合 global.css 放大组件与字号。
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { RouterView } from 'vue-router'
</script>

<template>
  <el-config-provider size="large" :locale="zhCn">
    <RouterView />
  </el-config-provider>
</template>
