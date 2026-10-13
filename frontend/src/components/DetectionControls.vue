<script setup lang="ts">
import { classes } from "../constants";
defineProps<{ disabled?: boolean }>();
const confidence = defineModel<number>("confidence", { required: true });
const selected = defineModel<number[]>("classes", { required: true });
</script>
<template>
  <div class="detection-controls">
    <div class="section-heading">
      <h3>检测参数</h3>
      <span class="muted">20 类物流目标</span>
    </div>
    <label class="field-label"
      >置信度阈值
      <b class="float-right">{{ Math.round(confidence * 100) }}%</b></label
    ><el-slider
      v-model="confidence"
      :min="0.05"
      :max="0.95"
      :step="0.05"
      :disabled="disabled"
    /><label class="field-label">目标类别</label
    ><el-select
      v-model="selected"
      multiple
      collapse-tags
      collapse-tags-tooltip
      :max-collapse-tags="3"
      clearable
      :disabled="disabled"
      placeholder="全部 20 类"
      class="full-width"
      ><el-option
        v-for="(item, index) in classes"
        :key="item[0]"
        :value="index"
        :label="item[1]"
    /></el-select>
    <p class="hint">
      留空表示检测全部类别。类别筛选可能影响依赖该目标的事件规则。
    </p>
  </div>
</template>
