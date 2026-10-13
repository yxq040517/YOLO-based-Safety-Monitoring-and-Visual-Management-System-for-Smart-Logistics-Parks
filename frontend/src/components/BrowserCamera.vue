<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { VideoCamera, VideoPause } from "@element-plus/icons-vue";
import { api, errorText } from "../api";
import { useAuth } from "../stores/auth";
import { classLabel, colorFor } from "../constants";
import type { Frame, ModelInfo, SafetyEvent, Settings } from "../types";
import DetectionControls from "./DetectionControls.vue";
const props = defineProps<{ model: ModelInfo | null }>();
const auth = useAuth();
const confidence = ref(0.35);
const classes = ref<number[]>([]);
const video = ref<HTMLVideoElement>();
const overlay = ref<HTMLCanvasElement>();
const state = ref<"idle" | "starting" | "live">("idle");
const error = ref("");
const frame = ref<Frame | null>(null);
const events = ref<SafetyEvent[]>([]);
const visibleClasses = ref<number[]>([]);
const canvas = document.createElement("canvas");
let stream: MediaStream | undefined;
let socket: WebSocket | undefined;
let sendTimer: number | undefined;
let timeout: number | undefined;
let inFlight = false;
let generation = 0;
const detectedClasses = computed(() => [
  ...new Set(frame.value?.detections.map((d) => d.class_id) || []),
]);
onMounted(async () => {
  try {
    const { data } = await api.get<Settings>("/settings");
    if (state.value === "idle" && confidence.value === 0.35)
      confidence.value = data.confidence;
  } catch (e) {
    error.value = `默认检测参数读取失败：${errorText(e)}`;
  }
});
function draw() {
  const el = overlay.value;
  const result = frame.value;
  if (!el || !result) return;
  el.width = result.width;
  el.height = result.height;
  const ctx = el.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, el.width, el.height);
  ctx.lineWidth = 2;
  const font = Math.max(14, Math.round(el.width / 70));
  ctx.font = `600 ${font}px sans-serif`;
  for (const d of result.detections) {
    if (visibleClasses.value.includes(d.class_id)) continue;
    const [x1, y1, x2, y2] = d.box;
    ctx.strokeStyle = colorFor(d.class_id);
    ctx.fillStyle = colorFor(d.class_id);
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    const text = `${classLabel(d.class_name)} ${(d.confidence * 100).toFixed(0)}%`;
    const y = Math.max(font + 8, y1);
    ctx.fillRect(x1, y - font - 8, ctx.measureText(text).width + 10, font + 8);
    ctx.fillStyle = "#fff";
    ctx.fillText(text, x1 + 5, y - 5);
  }
}
function stop() {
  generation++;
  clearTimeout(sendTimer);
  clearTimeout(timeout);
  inFlight = false;
  if (socket) {
    socket.onopen = null;
    socket.onclose = null;
    socket.onerror = null;
    socket.onmessage = null;
    socket.close();
    socket = undefined;
  }
  stream?.getTracks().forEach((track) => track.stop());
  stream = undefined;
  if (video.value) video.value.srcObject = null;
  state.value = "idle";
  const ctx = overlay.value?.getContext("2d");
  if (ctx && overlay.value)
    ctx.clearRect(0, 0, overlay.value.width, overlay.value.height);
}
function capture() {
  const el = video.value;
  const connection = socket;
  if (
    inFlight ||
    state.value !== "live" ||
    !el ||
    !connection ||
    connection.readyState !== WebSocket.OPEN
  )
    return;
  if (!el.videoWidth) {
    sendTimer = window.setTimeout(capture, 100);
    return;
  }
  const ratio = Math.min(1, 1280 / el.videoWidth, 720 / el.videoHeight);
  canvas.width = Math.round(el.videoWidth * ratio);
  canvas.height = Math.round(el.videoHeight * ratio);
  canvas.getContext("2d")!.drawImage(el, 0, 0, canvas.width, canvas.height);
  inFlight = true;
  const current = generation;
  canvas.toBlob(
    (blob) => {
      if (current !== generation) return;
      if (!blob || blob.size > 2 * 1024 * 1024) {
        error.value = "无法编码摄像头帧或帧超过 2 MB 限制。";
        stop();
        return;
      }
      if (connection.readyState !== WebSocket.OPEN) {
        stop();
        return;
      }
      connection.send(blob);
      timeout = window.setTimeout(() => {
        error.value = "推理响应超过 30 秒，连接已关闭。请检查模型服务后重试。";
        stop();
      }, 30000);
    },
    "image/jpeg",
    0.8,
  );
}
async function start() {
  if (!auth.canOperate || !props.model?.ready || state.value !== "idle") return;
  if (!navigator.mediaDevices?.getUserMedia) {
    error.value =
      "浏览器不支持摄像头访问。请通过 localhost 或 HTTPS 打开系统。";
    return;
  }
  error.value = "";
  frame.value = null;
  events.value = [];
  state.value = "starting";
  const current = ++generation;
  try {
    const acquired = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
    if (current !== generation) {
      acquired.getTracks().forEach((track) => track.stop());
      return;
    }
    acquired.getVideoTracks().forEach((track) =>
      track.addEventListener("ended", () => {
        if (current === generation) {
          error.value = "摄像头已断开或权限被撤销。";
          stop();
        }
      }),
    );
    stream = acquired;
    await nextTick();
    if (!video.value) throw new Error("摄像头预览未能初始化");
    video.value.srcObject = stream;
    await video.value.play();
    if (current !== generation) return;
    const connection = new WebSocket(
      `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/live/browser`,
    );
    socket = connection;
    timeout = window.setTimeout(() => {
      error.value = "实时检测连接超时。";
      stop();
    }, 15000);
    connection.onopen = () => {
      clearTimeout(timeout);
      connection.send(
        JSON.stringify({
          token: sessionStorage.getItem("logistics-token"),
          confidence: confidence.value,
          classes: classes.value,
        }),
      );
      state.value = "live";
      capture();
    };
    connection.onmessage = (message) => {
      try {
        const result = JSON.parse(String(message.data));
        if (result.error || result.detail) {
          error.value = String(result.error || result.detail);
          stop();
          return;
        }
        if (!Array.isArray(result.detections)) return;
        clearTimeout(timeout);
        inFlight = false;
        frame.value = result as Frame;
        if (result.events?.length)
          events.value = [...result.events, ...events.value].slice(0, 30);
        draw();
        sendTimer = window.setTimeout(capture, 150);
      } catch {
        error.value = "实时服务返回了无法解析的数据。";
        stop();
      }
    };
    connection.onerror = () => {
      error.value = "实时连接失败，请检查服务状态与网络。";
      stop();
    };
    connection.onclose = (e) => {
      if (state.value !== "idle") {
        error.value = e.reason || `实时连接已断开（${e.code}），请重新开始。`;
        stop();
      }
    };
  } catch (e) {
    if (current === generation) {
      const cameraErrors: Record<string, string> = {
        NotAllowedError: "摄像头权限被拒绝，请在浏览器站点设置中允许访问。",
        NotFoundError: "未找到可用摄像头，请连接设备后重试。",
        NotReadableError: "摄像头被其他应用占用或设备无法读取。",
        OverconstrainedError: "摄像头不支持请求的采集参数。",
        SecurityError: "当前页面不能访问摄像头，请使用 HTTPS 或 localhost。",
      };
      error.value =
        e instanceof Error
          ? cameraErrors[e.name] || `无法访问摄像头：${e.message}`
          : "无法访问摄像头";
      stop();
    }
  }
}
onUnmounted(stop);
</script>
<template>
  <div class="workbench-grid">
    <aside class="panel">
      <div class="section-heading">
        <h3>浏览器摄像头</h3>
        <span class="panel-kicker">LIVE</span>
      </div>
      <DetectionControls
        v-model:confidence="confidence"
        v-model:classes="classes"
        :disabled="state !== 'idle' || !auth.canOperate"
      /><el-button
        v-if="state === 'idle'"
        class="full-width start-button"
        type="primary"
        :icon="VideoCamera"
        :disabled="!model?.ready || !auth.canOperate"
        @click="start"
        >开启实时检测</el-button
      ><el-button
        v-else
        class="full-width start-button"
        type="danger"
        plain
        :icon="VideoPause"
        @click="stop"
        >{{ state === "starting" ? "取消连接" : "结束实时检测" }}</el-button
      >
      <p class="hint">
        需要浏览器摄像头权限。每次只发送一帧，上一帧完成后才会采集下一帧，避免排队延迟。离开页面会关闭摄像头。
      </p>
      <div class="rule-note">
        <strong>移动视角使用说明</strong>
        <p>
          浏览器摄像头不应用固定视角区域入侵规则。疑似防护缺失需人工复核；图像接近度不等于真实距离。
        </p>
      </div>
    </aside>
    <section class="panel">
      <div class="section-heading">
        <h3>实时画面</h3>
        <span class="live-state"
          ><i class="status-dot" :class="{ warning: state !== 'live' }"></i
          >{{
            state === "live"
              ? "正在检测"
              : state === "starting"
                ? "正在连接"
                : "未连接"
          }}</span
        >
      </div>
      <el-alert
        v-if="error"
        :title="error"
        type="error"
        :closable="false"
        class="mb"
      />
      <div class="live-stage">
        <video ref="video" muted playsinline autoplay></video
        ><canvas ref="overlay"></canvas>
        <div v-if="state === 'idle'" class="live-placeholder">
          <el-icon><VideoCamera /></el-icon
          ><span>开启摄像头，获取实时安全洞察</span>
        </div>
      </div>
      <div v-if="frame" class="live-metrics">
        <span
          >本帧目标 <strong>{{ frame.detections.length }}</strong></span
        ><span
          >推理耗时 <strong>{{ frame.duration_ms.toFixed(0) }} ms</strong></span
        ><span
          >输入尺寸
          <strong>{{ frame.width }} × {{ frame.height }}</strong></span
        >
      </div>
      <div v-if="detectedClasses.length" class="overlay-legend">
        <span class="muted">显示类别</span
        ><button
          v-for="id in detectedClasses"
          :key="id"
          class="class-toggle"
          :class="{ inactive: visibleClasses.includes(id) }"
          :style="{ '--class-color': colorFor(id) }"
          @click="
            visibleClasses = visibleClasses.includes(id)
              ? visibleClasses.filter((v) => v !== id)
              : [...visibleClasses, id];
            draw();
          "
        >
          {{
            classLabel(
              frame!.detections.find((d) => d.class_id === id)!.class_name,
            )
          }}
        </button>
      </div>
      <div class="section-heading mt">
        <h3>本次触发事件</h3>
        <router-link to="/events">查看全部 →</router-link>
      </div>
      <div v-if="events.length" class="live-events">
        <router-link
          v-for="event in events"
          :key="event.id"
          :to="{ path: '/events', query: { event: event.id } }"
          ><span>{{ event.title }}</span
          ><span>{{
            new Date(event.created_at).toLocaleTimeString("zh-CN")
          }}</span></router-link
        >
      </div>
      <el-empty v-else description="本次尚无触发事件" :image-size="45" />
    </section>
  </div>
</template>
