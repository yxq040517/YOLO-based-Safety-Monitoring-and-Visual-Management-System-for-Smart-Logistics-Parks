<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { UploadFilled, VideoPlay, Close } from "@element-plus/icons-vue";
import { api, errorText } from "../api";
import { usePolling } from "../composables";
import { useAuth } from "../stores/auth";
import { activeJob } from "../constants";
import type { Job, ModelInfo, Settings } from "../types";
import ModelNotice from "../components/ModelNotice.vue";
import DetectionControls from "../components/DetectionControls.vue";
import JobViewer from "../components/JobViewer.vue";
import StatusBadge from "../components/StatusBadge.vue";
const auth = useAuth();
const model = ref<ModelInfo | null>(null);
const job = ref<Job | null>(null);
const file = ref<File | null>(null);
const input = ref<HTMLInputElement>();
const localUrl = ref("");
const confidence = ref(0.35);
const classes = ref<number[]>([]);
const uploading = ref(false);
const uploadProgress = ref(0);
const actionError = ref("");
const cancelling = ref(false);
const dragging = ref(false);
let uploadController: AbortController | undefined;
const controller = new AbortController();
const busy = computed(
  () => uploading.value || !!(job.value && activeJob(job.value.status)),
);
const { error: modelError } = usePolling(async () => {
  const { data } = await api.get<ModelInfo>("/model", {
    signal: controller.signal,
  });
  if (!controller.signal.aborted) model.value = data;
}, 15000);
const jobPollingEnabled = computed(
  () => !!job.value && activeJob(job.value.status),
);
const {
  error: jobError,
  loading: jobRefreshing,
  refresh: refreshJob,
} = usePolling(
  async () => {
    const id = job.value?.id;
    if (!id) return;
    const isCurrent = () =>
      !controller.signal.aborted &&
      job.value?.id === id &&
      activeJob(job.value.status);
    try {
      const { data } = await api.get<Job>(`/jobs/${id}`, {
        signal: controller.signal,
      });
      if (isCurrent()) job.value = data;
    } catch (reason) {
      if (isCurrent()) throw reason;
    }
  },
  2000,
  jobPollingEnabled,
);
const canStart = computed(
  () =>
    auth.canOperate &&
    model.value?.ready &&
    !modelError.value &&
    !busy.value &&
    file.value,
);
onMounted(async () => {
  try {
    const { data } = await api.get<Settings>("/settings", {
      signal: controller.signal,
    });
    if (!controller.signal.aborted && !busy.value && confidence.value === 0.35)
      confidence.value = data.confidence;
  } catch (e) {
    if (!controller.signal.aborted)
      actionError.value = `默认检测参数读取失败：${errorText(e)}`;
  }
});
function choose(selected?: File) {
  if (!selected || busy.value || !auth.canOperate) return;
  if (!/\.(jpe?g|png|webp|bmp|mp4|mov|avi|mkv|webm)$/i.test(selected.name)) {
    actionError.value =
      "请选择 JPG、PNG、WEBP、BMP 图片或 MP4、MOV、AVI、MKV、WEBM 视频。";
    return;
  }
  if (localUrl.value) URL.revokeObjectURL(localUrl.value);
  file.value = selected;
  localUrl.value = URL.createObjectURL(selected);
  job.value = null;
  jobError.value = "";
  actionError.value = "";
}
function drop(event: DragEvent) {
  dragging.value = false;
  choose(event.dataTransfer?.files[0]);
}
async function submit() {
  if (!canStart.value || !file.value) return;
  uploading.value = true;
  actionError.value = "";
  uploadProgress.value = 0;
  const controller = new AbortController();
  uploadController = controller;
  const body = new FormData();
  body.append("file", file.value);
  body.append("confidence", String(confidence.value));
  body.append("classes", JSON.stringify(classes.value));
  try {
    job.value = (
      await api.post<Job>("/jobs", body, {
        timeout: 0,
        signal: controller.signal,
        onUploadProgress: (e) => {
          uploadProgress.value = e.total
            ? Math.round((e.loaded / e.total) * 100)
            : 0;
        },
      })
    ).data;
  } catch (e) {
    actionError.value = controller.signal.aborted
      ? "上传请求已取消。若服务端已接收完整素材，请在检测记录中检查并取消对应任务。"
      : errorText(e);
  } finally {
    uploading.value = false;
    uploadController = undefined;
  }
}
async function cancel() {
  if (!job.value) return;
  cancelling.value = true;
  try {
    job.value = (await api.post<Job>(`/jobs/${job.value.id}/cancel`)).data;
  } catch (e) {
    actionError.value = errorText(e);
  } finally {
    cancelling.value = false;
  }
}
onUnmounted(() => {
  controller.abort();
  uploadController?.abort();
  if (localUrl.value) URL.revokeObjectURL(localUrl.value);
});
</script>
<template>
  <ModelNotice :model="model" :error="modelError" />
  <el-alert
    v-if="jobError"
    :title="`任务进度查询失败：${jobError}`"
    type="error"
    :closable="false"
    show-icon
    class="mb"
  >
    <el-button text type="primary" :loading="jobRefreshing" @click="refreshJob"
      >重试读取进度</el-button
    >
  </el-alert>
  <el-alert
    v-if="!auth.canOperate"
    title="当前为观察员，只可查看记录；提交检测需要操作员或管理员权限。"
    type="info"
    :closable="false"
    class="mb"
  />
  <el-alert
    v-if="actionError"
    :title="actionError"
    type="error"
    :closable="false"
    class="mb"
  />
  <div class="workbench-grid">
    <aside class="panel workbench-controls">
      <div class="section-heading">
        <h3>创建检测任务</h3>
        <span class="panel-kicker">FILE INFERENCE</span>
      </div>
      <input
        ref="input"
        type="file"
        hidden
        accept=".jpg,.jpeg,.png,.webp,.bmp,.mp4,.mov,.avi,.mkv,.webm"
        @change="choose(($event.target as HTMLInputElement).files?.[0])"
      />
      <button
        class="upload-zone"
        :class="{ dragging }"
        :disabled="busy || !auth.canOperate"
        @click="input?.click()"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="drop"
      >
        <el-icon><UploadFilled /></el-icon
        ><strong>{{ file ? file.name : "点击或拖拽上传素材" }}</strong
        ><span>{{
          file
            ? `${(file.size / 1024 / 1024).toFixed(2)} MB · 点击更换`
            : "图片 / 视频 · 本地安全处理"
        }}</span>
      </button>
      <DetectionControls
        v-model:confidence="confidence"
        v-model:classes="classes"
        :disabled="busy || !auth.canOperate"
      />
      <el-button
        type="primary"
        :icon="VideoPlay"
        :disabled="!canStart"
        :loading="uploading"
        class="full-width start-button"
        @click="submit"
        >{{ uploading ? "正在上传…" : "开始检测" }}</el-button
      >
      <div v-if="uploading" class="mt">
        <el-progress :percentage="uploadProgress" /><el-button
          size="small"
          text
          type="danger"
          @click="uploadController?.abort()"
          >取消上传请求</el-button
        >
      </div>
      <p class="hint">
        检测在服务端后台执行。离开页面将中断未完成的上传，但不会取消已提交的任务，可在检测记录中继续查看。
      </p>
      <div class="rule-note">
        <strong>结果解读</strong>
        <p>
          安全帽 /
          背心等缺失仅为“疑似”提示，可能受到遮挡与检测误差影响。接近规则基于画面比例，不代表实际距离。单张图片无法进行连续帧确认。
        </p>
      </div>
    </aside>
    <section class="panel workbench-result">
      <div class="section-heading">
        <h3>检测预览</h3>
        <StatusBadge v-if="job" :value="job.status" /><span v-else class="muted"
          >原图与结果对照</span
        >
      </div>
      <template v-if="job"
        ><div v-if="activeJob(job.status)" class="job-progress">
          <el-progress :percentage="Math.round(job.progress || 0)" /><el-button
            size="small"
            :icon="Close"
            :loading="cancelling"
            @click="cancel"
            >取消任务</el-button
          >
        </div>
        <el-alert
          v-if="job.error"
          :title="job.error"
          type="error"
          :closable="false"
          class="mb" /><JobViewer :job="job"
      /></template>
      <div v-else-if="file" class="media-stage local-preview">
        <video
          v-if="/\.(mp4|mov|avi|mkv|webm)$/i.test(file.name)"
          :src="localUrl"
          controls
          playsinline
          @error="
            actionError =
              '浏览器无法预览该输入编码，仍可提交检测并播放 H.264 标注输出。'
          "
        /><img
          v-else
          :src="localUrl"
          alt="待检测图片"
          @error="actionError = '无法读取图片预览，请检查素材是否完整。'"
        />
      </div>
      <div v-else class="workbench-empty">
        <div class="scan-mark">
          <span></span><el-icon><UploadFilled /></el-icon>
        </div>
        <h3>让视觉成为安全的第一道防线</h3>
        <p>上传一张图片或一段视频，开始目标识别与风险分析。</p>
        <div class="empty-tags">
          <span>人员与车辆</span><span>火焰与烟雾</span><span>防护用品</span>
        </div>
      </div>
    </section>
  </div>
</template>
