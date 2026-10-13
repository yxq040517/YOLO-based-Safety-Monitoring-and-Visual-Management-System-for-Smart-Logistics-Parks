<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { Download } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { download, errorText } from "../api";
import { useMedia } from "../composables";
import { useVideoMedia, videoMediaUrl } from "../useVideoMedia";
import { classLabel, dateTime, elapsed } from "../constants";
import type { Job } from "../types";
import DetectionCanvas from "./DetectionCanvas.vue";
const props = defineProps<{ job: Job }>();
const route = useRoute();
const mode = ref("source");
const overlay = ref(true);
const video = ref<HTMLVideoElement>();
const pendingSeek = ref<number | null>(null);
const downloading = ref(false);
const playbackError = ref("");
const videoRetried = ref(false);
const source = computed(() =>
  mode.value === "result"
    ? props.job.result_url
    : props.job.source_url || props.job.preview_url,
);
const imageSource = computed(() =>
  props.job.kind === "video" ? null : source.value,
);
const videoSource = computed(() =>
  props.job.kind === "video" ? source.value : null,
);
const imageMedia = useMedia(imageSource);
const videoMedia = useVideoMedia(videoSource);
const url = computed(() =>
  props.job.kind === "video" ? videoMedia.url.value : imageMedia.url.value,
);
const error = computed(() =>
  props.job.kind === "video" ? videoMedia.error.value : imageMedia.error.value,
);
const loading = computed(() =>
  props.job.kind === "video"
    ? videoMedia.loading.value
    : imageMedia.loading.value,
);
watch(url, () => {
  playbackError.value = "";
  videoRetried.value = false;
});
watch(
  () => props.job.id,
  () => {
    mode.value = "source";
    pendingSeek.value = null;
    videoRetried.value = false;
  },
);
async function seek(seconds: number | null) {
  if (seconds === null) return;
  pendingSeek.value = seconds;
  await nextTick();
  if (video.value?.readyState) {
    video.value.currentTime = seconds;
    pendingSeek.value = null;
    void video.value.play().catch(() => {});
  }
}
function loaded() {
  if (video.value && pendingSeek.value !== null) {
    video.value.currentTime = pendingSeek.value;
    pendingSeek.value = null;
  }
}
async function videoError() {
  if (!videoRetried.value) {
    const failedJob = props.job.id;
    const failedSource = source.value;
    videoRetried.value = true;
    const position = video.value?.currentTime;
    const renewed = await videoMedia.renew();
    if (props.job.id !== failedJob || source.value !== failedSource) return;
    if (renewed) {
      pendingSeek.value =
        position && Number.isFinite(position) ? position : null;
      video.value?.load();
      return;
    }
  }
  playbackError.value =
    mode.value === "source"
      ? "原始视频无法播放。可刷新页面后重试、下载原素材，或切换 H.264 标注结果。"
      : "标注视频无法播放。可刷新页面后重试，或下载结果检查。";
}
watch(
  () => [props.job.id, route.query.seek],
  () => {
    const seconds = Number(route.query.seek);
    if (route.query.seek != null && Number.isFinite(seconds) && seconds >= 0)
      void seek(seconds);
  },
  { immediate: true },
);
async function save(kind: "json" | "media" | "source") {
  downloading.value = true;
  const target =
    kind === "json"
      ? `/jobs/${props.job.id}/export`
      : kind === "source"
        ? props.job.source_url!
        : props.job.result_url!;
  const filename =
    kind === "json"
      ? `检测结果-${props.job.id}.json`
      : kind === "source"
        ? props.job.filename
        : `检测结果-${props.job.id}.${props.job.kind === "video" ? "mp4" : "jpg"}`;
  try {
    if (kind !== "json" && props.job.kind === "video") {
      const link = document.createElement("a");
      link.href = await videoMediaUrl(target);
      link.download = filename;
      link.click();
    } else {
      await download(target, filename);
    }
  } catch (e) {
    ElMessage.error(errorText(e));
  } finally {
    downloading.value = false;
  }
}
defineExpose({ seek });
</script>
<template>
  <div class="job-viewer">
    <div class="viewer-toolbar">
      <div class="toolbar-group">
        <el-radio-group v-model="mode" size="small"
          ><el-radio-button value="source">原始素材</el-radio-button
          ><el-radio-button value="result" :disabled="!job.result_url"
            >标注结果</el-radio-button
          ></el-radio-group
        ><el-switch
          v-if="job.kind === 'image' && mode === 'source'"
          v-model="overlay"
          active-text="交互检测框"
        />
      </div>
      <div class="toolbar-group">
        <el-button
          size="small"
          :icon="Download"
          :loading="downloading"
          @click="save('json')"
          >导出 JSON</el-button
        ><el-button
          v-if="job.source_url"
          size="small"
          :loading="downloading"
          @click="save('source')"
          >下载原素材</el-button
        ><el-button
          v-if="job.result_url"
          size="small"
          :loading="downloading"
          @click="save('media')"
          >下载标注结果</el-button
        >
      </div>
    </div>
    <el-alert
      v-if="error || playbackError"
      :title="error || playbackError"
      type="error"
      :closable="false"
      class="mb"
    />
    <div v-loading="loading" class="media-stage">
      <video
        v-if="url && job.kind === 'video'"
        ref="video"
        :src="url"
        referrerpolicy="no-referrer"
        controls
        playsinline
        preload="metadata"
        @loadedmetadata="loaded"
        @error="videoError"
      ></video>
      <DetectionCanvas
        v-else-if="url"
        :src="url"
        :detections="job.detections || []"
        :width="job.width"
        :height="job.height"
        :overlay="job.kind === 'image' && mode === 'source' && overlay"
      />
      <el-empty
        v-else-if="!loading"
        description="素材尚未就绪"
        :image-size="70"
      />
    </div>
    <p v-if="job.kind === 'video'" class="hint">
      原始素材能否播放取决于浏览器对输入编码的支持；标注结果统一为 H.264
      MP4。类别筛选用于提交检测，视频中的标注已写入输出文件。
    </p>
    <div class="job-meta">
      <span
        >任务编号 <b>{{ job.id }}</b></span
      ><span
        >创建时间 <b>{{ dateTime(job.created_at) }}</b></span
      ><span
        >检测耗时 <b>{{ elapsed(job.duration_ms) }}</b></span
      ><span
        >尺寸
        <b>{{
          job.width && job.height ? `${job.width} × ${job.height}` : "—"
        }}</b></span
      >
    </div>
    <div class="result-grid">
      <section>
        <div class="section-heading">
          <h3>目标观测统计</h3>
          <span class="muted">非独立人员数量</span>
        </div>
        <div v-if="Object.keys(job.counts || {}).length" class="count-list">
          <div v-for="(count, name) in job.counts" :key="name">
            <span>{{ classLabel(String(name)) }}</span
            ><strong>{{ count }}</strong>
          </div>
        </div>
        <el-empty v-else description="暂无目标观测" :image-size="50" />
      </section>
    </div>
  </div>
</template>
