<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { classLabel, colorFor } from "../constants";
import type { Detection } from "../types";
const props = defineProps<{
  src: string;
  detections: Detection[];
  width?: number;
  height?: number;
  overlay?: boolean;
}>();
const canvas = ref<HTMLCanvasElement>();
const image = ref<HTMLImageElement>();
const hidden = ref<number[]>([]);
const selected = ref<Detection | null>(null);
const categories = computed(() => [
  ...new Set(props.detections.map((d) => d.class_id)),
]);
function draw() {
  const el = canvas.value;
  const img = image.value;
  if (!el || !img?.naturalWidth) return;
  el.width = props.width || img.naturalWidth;
  el.height = props.height || img.naturalHeight;
  const ctx = el.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, el.width, el.height);
  if (props.overlay === false) return;
  const font = Math.max(13, Math.round(el.width / 70));
  ctx.font = `600 ${font}px sans-serif`;
  ctx.lineWidth = Math.max(2, el.width / 500);
  for (const detection of props.detections) {
    if (hidden.value.includes(detection.class_id)) continue;
    const [x1, y1, x2, y2] = detection.box;
    const color = colorFor(detection.class_id);
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    if (selected.value === detection) {
      ctx.globalAlpha = 0.16;
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
      ctx.globalAlpha = 1;
    }
    const text = `${classLabel(detection.class_name)} ${(detection.confidence * 100).toFixed(0)}%${detection.track_id != null ? ` #${detection.track_id}` : ""}`;
    const w = ctx.measureText(text).width + 12;
    const y = Math.max(font + 8, y1);
    ctx.fillRect(x1, y - font - 8, w, font + 8);
    ctx.fillStyle = "#fff";
    ctx.fillText(text, x1 + 6, y - 5);
  }
}
function pick(event: MouseEvent) {
  const el = canvas.value;
  if (!el || props.overlay === false) return;
  const rect = el.getBoundingClientRect();
  const x = ((event.clientX - rect.left) * el.width) / rect.width;
  const y = ((event.clientY - rect.top) * el.height) / rect.height;
  selected.value =
    [...props.detections]
      .reverse()
      .find(
        (d) =>
          !hidden.value.includes(d.class_id) &&
          x >= d.box[0] &&
          x <= d.box[2] &&
          y >= d.box[1] &&
          y <= d.box[3],
      ) || null;
  draw();
}
function toggle(id: number) {
  hidden.value = hidden.value.includes(id)
    ? hidden.value.filter((v) => v !== id)
    : [...hidden.value, id];
}
watch(
  () => [props.src, props.detections, props.overlay, hidden.value],
  async () => {
    await nextTick();
    draw();
  },
  { deep: true },
);
</script>
<template>
  <div class="detection-canvas">
    <div class="image-stage">
      <img ref="image" :src="src" alt="检测图像" @load="draw" /><canvas
        ref="canvas"
        aria-label="检测框画布，点击框查看目标详情"
        @click="pick"
      ></canvas>
    </div>
    <div v-if="overlay !== false && categories.length" class="overlay-legend">
      <span class="muted">显示类别</span
      ><button
        v-for="id in categories"
        :key="id"
        class="class-toggle"
        :class="{ inactive: hidden.includes(id) }"
        :style="{ '--class-color': colorFor(id) }"
        :aria-pressed="!hidden.includes(id)"
        @click="toggle(id)"
      >
        {{ classLabel(detections.find((d) => d.class_id === id)!.class_name) }}
      </button>
    </div>
    <div v-if="selected && overlay !== false" class="selection-info">
      已选目标：{{ classLabel(selected.class_name) }} · 置信度
      {{ (selected.confidence * 100).toFixed(1) }}% ·
      {{
        selected.track_id == null ? "无跟踪编号" : `跟踪 #${selected.track_id}`
      }}<el-button
        text
        size="small"
        @click="
          selected = null;
          draw();
        "
        >取消选择</el-button
      >
    </div>
  </div>
</template>
