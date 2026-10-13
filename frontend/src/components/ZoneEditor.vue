<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
const props = defineProps<{ disabled?: boolean }>();
const points = defineModel<[number, number][]>({ required: true });
const validation = defineModel<string>("error", { default: "" });
const canvas = ref<HTMLCanvasElement>();
const fileInput = ref<HTMLInputElement>();
const background = ref<HTMLImageElement | null>(null);
const imageError = ref("");
let objectUrl = "";
let dragging = -1;
function cross(a: number[], b: number[], c: number[]) {
  return (b[0]! - a[0]!) * (c[1]! - a[1]!) - (b[1]! - a[1]!) * (c[0]! - a[0]!);
}
function validate() {
  const p = points.value;
  if (!p.length) {
    validation.value = "";
    return;
  }
  if (p.length < 3) {
    validation.value = "区域至少需要 3 个顶点；不使用区域时请清空。";
    return;
  }
  if (
    p.some(
      (v) =>
        v.length !== 2 || v.some((n) => !Number.isFinite(n) || n < 0 || n > 1),
    )
  ) {
    validation.value = "每个坐标必须是 0–1 之间的有效数字。";
    return;
  }
  for (let i = 0; i < p.length; i++)
    for (let j = i + 1; j < p.length; j++)
      if (Math.hypot(p[i]![0] - p[j]![0], p[i]![1] - p[j]![1]) < 0.001) {
        validation.value = "区域顶点不能重复或重合。";
        return;
      }
  let area = 0;
  for (let i = 0; i < p.length; i++) {
    const a = p[i]!,
      b = p[(i + 1) % p.length]!;
    area += a[0] * b[1] - b[0] * a[1];
  }
  if (Math.abs(area) < 0.0001) {
    validation.value = "区域面积过小或顶点共线，请重新绘制。";
    return;
  }
  for (let i = 0; i < p.length; i++)
    for (let j = i + 1; j < p.length; j++) {
      if (j === i + 1 || (i === 0 && j === p.length - 1)) continue;
      const a = p[i]!,
        b = p[(i + 1) % p.length]!,
        c = p[j]!,
        d = p[(j + 1) % p.length]!;
      if (
        cross(a, b, c) * cross(a, b, d) <= 0 &&
        cross(c, d, a) * cross(c, d, b) <= 0 &&
        Math.max(a[0], b[0]) >= Math.min(c[0], d[0]) &&
        Math.max(c[0], d[0]) >= Math.min(a[0], b[0]) &&
        Math.max(a[1], b[1]) >= Math.min(c[1], d[1]) &&
        Math.max(c[1], d[1]) >= Math.min(a[1], b[1])
      ) {
        validation.value =
          "区域边界不能自相交，请按顺时针或逆时针顺序排列顶点。";
        return;
      }
    }
  validation.value = "";
}
function draw() {
  const el = canvas.value;
  if (!el) return;
  const img = background.value;
  if (img) {
    el.width = Math.min(img.naturalWidth, 1280);
    el.height = Math.round((el.width * img.naturalHeight) / img.naturalWidth);
  } else {
    el.width = 800;
    el.height = 450;
  }
  const ctx = el.getContext("2d");
  if (!ctx) return;
  ctx.fillStyle = "#eaf1f3";
  ctx.fillRect(0, 0, el.width, el.height);
  if (img) ctx.drawImage(img, 0, 0, el.width, el.height);
  else {
    ctx.strokeStyle = "#d8e4e8";
    ctx.lineWidth = 1;
    for (let x = 0; x < el.width; x += 40) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, el.height);
      ctx.stroke();
    }
    for (let y = 0; y < el.height; y += 40) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(el.width, y);
      ctx.stroke();
    }
  }
  if (!points.value.length) return;
  ctx.beginPath();
  points.value.forEach((p, i) => {
    if (i === 0) ctx.moveTo(p[0] * el.width, p[1] * el.height);
    else ctx.lineTo(p[0] * el.width, p[1] * el.height);
  });
  if (points.value.length > 2) ctx.closePath();
  ctx.fillStyle = "rgba(15,160,142,.2)";
  ctx.fill();
  ctx.strokeStyle = validation.value ? "#d66159" : "#0c9b89";
  ctx.lineWidth = 3;
  ctx.stroke();
  points.value.forEach((p, i) => {
    const x = p[0] * el.width,
      y = p[1] * el.height;
    ctx.beginPath();
    ctx.arc(x, y, 6, 0, Math.PI * 2);
    ctx.fillStyle = "#fff";
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#064b44";
    ctx.font = "bold 16px sans-serif";
    ctx.fillText(String(i + 1), x + 9, Math.max(18, y - 9));
  });
}
function position(event: PointerEvent): [number, number] {
  const el = canvas.value!;
  const rect = el.getBoundingClientRect();
  const scale = Math.min(rect.width / el.width, rect.height / el.height);
  const width = el.width * scale;
  const height = el.height * scale;
  return [
    Math.max(
      0,
      Math.min(
        1,
        (event.clientX - rect.left - (rect.width - width) / 2) / width,
      ),
    ),
    Math.max(
      0,
      Math.min(
        1,
        (event.clientY - rect.top - (rect.height - height) / 2) / height,
      ),
    ),
  ];
}
function down(event: PointerEvent) {
  if (props.disabled) return;
  const p = position(event);
  const el = canvas.value!;
  const rect = el.getBoundingClientRect();
  const scale = Math.min(rect.width / el.width, rect.height / el.height);
  dragging = points.value.findIndex(
    (v) =>
      Math.hypot(
        (v[0] - p[0]) * el.width * scale,
        (v[1] - p[1]) * el.height * scale,
      ) < 14,
  );
  if (dragging < 0) {
    points.value = [
      ...points.value,
      [Number(p[0].toFixed(4)), Number(p[1].toFixed(4))],
    ];
    dragging = points.value.length - 1;
  }
  canvas.value?.setPointerCapture(event.pointerId);
}
function move(event: PointerEvent) {
  if (dragging < 0 || props.disabled) return;
  const p = position(event);
  points.value = points.value.map((v, i) =>
    i === dragging ? [Number(p[0].toFixed(4)), Number(p[1].toFixed(4))] : v,
  );
}
function imageSelected(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  imageError.value = "";
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = URL.createObjectURL(file);
  const image = new Image();
  image.onload = () => {
    background.value = image;
    draw();
  };
  image.onerror = () => {
    imageError.value = "参考图片无法读取，请选择浏览器支持的图片。";
  };
  image.src = objectUrl;
}
watch(
  points,
  async () => {
    validate();
    await nextTick();
    draw();
  },
  { deep: true, immediate: true },
);
onMounted(draw);
onUnmounted(() => {
  if (objectUrl) URL.revokeObjectURL(objectUrl);
});
</script>
<template>
  <div class="zone-editor">
    <el-alert
      title="全局归一化区域（所有固定视角共用，非单设备配置）"
      type="info"
      :closable="false"
      show-icon
      ><template #default
        >坐标原点为画面左上角，范围
        0–1。请仅在固定摄像头视角明确且相容时启用入侵规则；浏览器移动摄像头不应用本区域。参考图仅在本地预览，不上传服务器。</template
      ></el-alert
    >
    <div class="zone-toolbar">
      <input
        ref="fileInput"
        type="file"
        accept="image/*"
        hidden
        @change="imageSelected"
      /><el-button size="small" @click="fileInput?.click()"
        >选择参考图片</el-button
      ><el-button
        v-if="background"
        size="small"
        @click="
          background = null;
          draw();
        "
        >移除参考图</el-button
      ><el-button
        size="small"
        :disabled="disabled || !points.length"
        @click="points = points.slice(0, -1)"
        >撤销末点</el-button
      ><el-button
        size="small"
        type="danger"
        plain
        :disabled="disabled || !points.length"
        @click="points = []"
        >清空区域</el-button
      ><span class="muted">点击添加 · 拖动顶点调整</span>
    </div>
    <el-alert
      v-if="imageError"
      :title="imageError"
      type="error"
      :closable="false"
      class="mb"
    /><canvas
      ref="canvas"
      class="zone-canvas"
      aria-label="区域编辑画布，也可以使用下方坐标输入框编辑"
      @pointerdown="down"
      @pointermove="move"
      @pointerup="dragging = -1"
      @pointercancel="dragging = -1"
    ></canvas
    ><el-alert
      v-if="validation"
      :title="validation"
      type="error"
      :closable="false"
      class="mt"
    />
    <div v-if="points.length" class="zone-coordinate-list">
      <div v-for="(point, index) in points" :key="index">
        <span>顶点 {{ index + 1 }}</span
        ><el-input-number
          v-model="point[0]"
          :min="0"
          :max="1"
          :step="0.01"
          :precision="4"
          :disabled="disabled"
          size="small"
          aria-label="归一化 X 坐标"
        /><el-input-number
          v-model="point[1]"
          :min="0"
          :max="1"
          :step="0.01"
          :precision="4"
          :disabled="disabled"
          size="small"
          aria-label="归一化 Y 坐标"
        /><el-button
          size="small"
          text
          type="danger"
          :disabled="disabled"
          @click="points = points.filter((_, i) => i !== index)"
          >移除</el-button
        >
      </div>
    </div>
    <p class="hint">
      {{
        points.length
          ? `已设置 ${points.length} 个顶点。预览不代表保存，需点击页面的“保存规则配置”。`
          : "未配置区域；可在画面上依次点击至少 3 个顶点。"
      }}
    </p>
  </div>
</template>
