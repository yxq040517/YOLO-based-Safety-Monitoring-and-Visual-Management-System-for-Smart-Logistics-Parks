<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import { api, errorText } from "../api";
import { usePolling } from "../composables";
import { useAuth } from "../stores/auth";
import { activeJob, label } from "../constants";
import type { Job } from "../types";
import JobViewer from "../components/JobViewer.vue";
import JobRiskReport from "../components/JobRiskReport.vue";
import StatusBadge from "../components/StatusBadge.vue";
const route = useRoute();
const auth = useAuth();
const job = ref<Job | null>(null);
const cancelling = ref(false);
const pollingEnabled = computed(
  () => job.value === null || activeJob(job.value.status),
);
const { loading, error, refresh } = usePolling(
  async () => {
    const id = String(route.params.id);
    const result = await api.get<Job>(`/jobs/${id}`);
    if (String(route.params.id) === id) job.value = result.data;
  },
  3000,
  pollingEnabled,
);
watch(
  () => route.params.id,
  () => {
    const wasPolling = pollingEnabled.value;
    job.value = null;
    if (wasPolling) void refresh();
  },
);
async function cancel() {
  if (!job.value) return;
  cancelling.value = true;
  try {
    job.value = (await api.post<Job>(`/jobs/${job.value.id}/cancel`)).data;
  } catch (e) {
    ElMessage.error(errorText(e));
  } finally {
    cancelling.value = false;
  }
}
</script>
<template>
  <div class="detail-back">
    <router-link to="/history">← 返回检测记录</router-link
    ><el-button size="small" :loading="loading" @click="refresh"
      >刷新状态</el-button
    >
  </div>
  <el-alert
    v-if="error"
    :title="error"
    type="error"
    :closable="false"
    class="mb"
  />
  <section v-if="job" class="panel">
    <div class="section-heading">
      <div>
        <h3>{{ job.filename }}</h3>
        <p>
          {{ label(job.kind) }}检测 · 置信度阈值
          {{ (job.confidence * 100).toFixed(0) }}%
        </p>
      </div>
      <div class="toolbar-group">
        <StatusBadge :value="job.status" /><el-button
          v-if="activeJob(job.status) && auth.canOperate"
          type="danger"
          plain
          size="small"
          :loading="cancelling"
          @click="cancel"
          >取消任务</el-button
        >
      </div>
    </div>
    <el-progress
      v-if="activeJob(job.status)"
      :percentage="Math.round(job.progress || 0)"
      class="mb"
    /><el-alert
      v-if="job.error"
      :title="job.error"
      type="error"
      :closable="false"
      class="mb"
    /><JobRiskReport :job="job" /><JobViewer :job="job" />
  </section>
  <el-skeleton v-else-if="loading" :rows="8" animated /><el-empty
    v-else-if="!error"
    description="检测记录不存在"
  />
</template>
