<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import {
  TooltipComponent,
  GridComponent,
  LegendComponent,
  LegendScrollComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
echarts.use([
  BarChart,
  LineChart,
  PieChart,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  LegendScrollComponent,
  CanvasRenderer,
]);
const props = defineProps<{ option: EChartsOption }>();
const root = ref<HTMLDivElement>();
let chart: ReturnType<typeof echarts.init> | undefined;
let observer: ResizeObserver | undefined;
onMounted(() => {
  if (!root.value) return;
  chart = echarts.init(root.value);
  chart.setOption(props.option);
  observer = new ResizeObserver(() => chart?.resize());
  observer.observe(root.value);
});
watch(
  () => props.option,
  (option) => chart?.setOption(option, true),
  { deep: true },
);
onUnmounted(() => {
  observer?.disconnect();
  chart?.dispose();
});
</script>
<template>
  <div
    ref="root"
    class="analytics-chart"
    role="img"
    aria-label="园区安全统计图表"
  ></div>
</template>
