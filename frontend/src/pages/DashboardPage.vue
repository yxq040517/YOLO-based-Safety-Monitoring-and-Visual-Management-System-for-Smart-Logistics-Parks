<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import type { EChartsOption } from "echarts";
import {
  DataAnalysis,
  Warning,
  VideoCamera,
  View,
  Right,
  Refresh,
  ArrowDown,
} from "@element-plus/icons-vue";
import { api, errorText } from "../api";
import { usePolling } from "../composables";
import type { Dashboard, ModelInfo } from "../types";
import { classLabel, dateTime, label } from "../constants";
import AnalyticsChart from "../components/AnalyticsChart.vue";
import StatusBadge from "../components/StatusBadge.vue";
const data = ref<Dashboard | null>(null);
const model = ref<ModelInfo | null>(null);
const modelError = ref("");
const lastUpdated = ref<Date | null>(null);
const controller = new AbortController();
const modelLabel = computed(() =>
  modelError.value
    ? "模型状态待确认"
    : model.value
      ? model.value.ready
        ? "模型已就绪"
        : "模型未就绪"
      : "正在连接模型",
);
const updatedText = computed(() =>
  lastUpdated.value
    ? lastUpdated.value.toLocaleTimeString("zh-CN", { hour12: false })
    : "等待数据",
);
const recentEvents = computed(
  () => data.value?.recent_events.slice(0, 5) || [],
);
const recentJobs = computed(() => data.value?.recent_jobs.slice(0, 5) || []);
const { loading, error, refresh } = usePolling(async () => {
  const [overview] = await Promise.allSettled([
    api
      .get<Dashboard>("/dashboard", { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) {
          data.value = response.data;
          lastUpdated.value = new Date();
        }
      }),
    api
      .get<ModelInfo>("/model", { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) {
          model.value = response.data;
          modelError.value = "";
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) modelError.value = errorText(reason);
      }),
  ]);
  if (overview.status === "rejected") throw overview.reason;
}, 15000);
onUnmounted(() => controller.abort());
const trend = computed<EChartsOption>(() => ({
  color: ["#149c8b", "#e7a24a"],
  tooltip: { trigger: "axis" },
  legend: {
    right: 0,
    top: 0,
    itemWidth: 12,
    itemHeight: 8,
    textStyle: { color: "#526272", fontSize: 12 },
  },
  grid: { left: 40, right: 15, top: 45, bottom: 30 },
  xAxis: {
    type: "category",
    data: data.value?.daily.map((d) => d.date) || [],
    axisLine: { lineStyle: { color: "#e5ebef" } },
    axisTick: { show: false },
    axisLabel: { color: "#627383", fontSize: 12 },
  },
  yAxis: {
    type: "value",
    minInterval: 1,
    splitLine: { lineStyle: { color: "#eef2f5", type: "dashed" } },
    axisLabel: { color: "#627383", fontSize: 12 },
  },
  series: [
    {
      name: "检测任务",
      type: "line",
      smooth: true,
      symbolSize: 6,
      data: data.value?.daily.map((d) => d.jobs) || [],
      areaStyle: { opacity: 0.08 },
    },
    {
      name: "安全事件",
      type: "bar",
      barMaxWidth: 14,
      itemStyle: { borderRadius: [3, 3, 0, 0] },
      data: data.value?.daily.map((d) => d.events) || [],
    },
  ],
}));
const distribution = computed<EChartsOption>(() => ({
  color: ["#139b8b", "#62b7a6", "#83b5d3", "#8099c8", "#b6cdd9", "#e3b66a"],
  tooltip: { trigger: "item" },
  legend: {
    bottom: 0,
    type: "scroll",
    itemWidth: 10,
    itemHeight: 10,
    textStyle: { color: "#526272", fontSize: 12 },
  },
  series: [
    {
      type: "pie",
      radius: ["48%", "73%"],
      center: ["50%", "43%"],
      itemStyle: { borderRadius: 4, borderColor: "#fff", borderWidth: 3 },
      label: { show: false },
      data:
        data.value?.class_counts.map((c) => ({
          name: classLabel(c.name),
          value: c.count,
        })) || [],
    },
  ],
}));
</script>
<template>
  <div class="overview-page">
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
      class="mb"
    />
    <section class="overview-status" aria-label="系统运行状态">
      <div class="overview-status-items">
        <details class="overview-model-status">
          <summary :class="{ warning: modelError || (model && !model.ready) }">
            <span
              class="status-dot"
              :class="{ warning: modelError || !model?.ready }"
            ></span>
            <strong>{{ modelLabel }}</strong
            ><el-icon><ArrowDown /></el-icon>
          </summary>
          <div class="overview-status-details">
            <p>
              {{ modelError || model?.message || "正在获取模型状态，请稍候。" }}
            </p>
            <router-link to="/settings">查看模型与训练状态 →</router-link>
          </div>
        </details>
        <span class="overview-activity"
          >进行中任务 <strong>{{ data?.active_jobs ?? "—" }}</strong></span
        >
        <span class="overview-updated"
          >最近更新
          <time :datetime="lastUpdated?.toISOString()">{{
            updatedText
          }}</time></span
        >
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="refresh"
        >刷新概览</el-button
      >
    </section>

    <div class="stats-grid">
      <section
        class="stat-card risk-priority"
        :class="{ 'has-risk': (data?.open_events || 0) > 0 }"
        aria-label="待处理风险"
      >
        <div class="stat-icon amber">
          <el-icon><Warning /></el-icon>
        </div>
        <div class="stat-content">
          <span>待处理风险</span><strong>{{ data?.open_events ?? "—" }}</strong>
          <small>待复核 · 已确认 · 处理中</small>
          <router-link
            :to="{ path: '/events', query: { scope: 'open' } }"
            class="risk-card-action"
            >查看待处理<el-icon><Right /></el-icon
          ></router-link>
        </div>
      </section>
      <section class="stat-card">
        <div class="stat-icon teal">
          <el-icon><DataAnalysis /></el-icon>
        </div>
        <div class="stat-content">
          <span>累计检测任务</span><strong>{{ data?.total_jobs ?? "—" }}</strong
          ><small>{{
            data ? `${data.completed_jobs} 已完成` : "正在获取数据"
          }}</small>
        </div>
      </section>
      <section class="stat-card">
        <div class="stat-icon blue">
          <el-icon><VideoCamera /></el-icon>
        </div>
        <div class="stat-content">
          <span>在线摄像头</span
          ><strong>{{ data?.cameras_online ?? "—" }}</strong
          ><small>RTSP 实时连接状态</small>
        </div>
      </section>
      <section class="stat-card">
        <div class="stat-icon violet">
          <el-icon><View /></el-icon>
        </div>
        <div class="stat-content">
          <span>累计目标观测</span
          ><strong>{{ data?.total_detections ?? "—" }}</strong
          ><small>逐帧观测，非独立人数</small>
        </div>
      </section>
    </div>

    <div class="overview-main-grid">
      <section class="panel overview-events">
        <div class="section-heading">
          <div>
            <h3>最近安全事件</h3>
            <p>查看最新风险与复核进展</p>
          </div>
          <router-link to="/events">全部事件 →</router-link>
        </div>
        <el-table
          :data="recentEvents"
          empty-text="暂无安全事件"
          class="overview-table"
        >
          <el-table-column label="事件" min-width="160"
            ><template #default="{ row }"
              ><div class="overview-event-label">
                <router-link
                  :to="{ path: '/events', query: { event: row.id } }"
                  class="table-link"
                  >{{ row.title }}</router-link
                ><time
                  class="overview-event-time"
                  :datetime="row.created_at"
                  :title="dateTime(row.created_at)"
                  >{{ dateTime(row.created_at) }}</time
                >
              </div></template
            ></el-table-column
          >
          <el-table-column label="风险" width="88"
            ><template #default="{ row }"
              ><StatusBadge :value="row.severity" /></template
          ></el-table-column>
          <el-table-column label="状态" width="96"
            ><template #default="{ row }"
              ><StatusBadge :value="row.status" /></template
          ></el-table-column>
        </el-table>
        <p class="overview-list-note">
          仅展示最近 5 条，完整记录可在风险结果中查看。
        </p>
      </section>
      <section class="panel overview-trend">
        <div class="section-heading">
          <div>
            <h3>检测与事件趋势</h3>
            <p>最近 7 天 · 按日汇总</p>
          </div>
        </div>
        <AnalyticsChart v-if="data?.daily.length" :option="trend" /><el-empty
          v-else
          description="完成检测后将显示趋势"
        />
      </section>
    </div>

    <div class="overview-secondary-grid">
      <section class="panel overview-jobs">
        <div class="section-heading">
          <div>
            <h3>最近检测任务</h3>
            <p>回看素材与检测结果</p>
          </div>
          <router-link to="/history">全部记录 →</router-link>
        </div>
        <el-table
          :data="recentJobs"
          empty-text="暂无检测记录"
          class="overview-table"
        >
          <el-table-column label="素材名称" min-width="160"
            ><template #default="{ row }"
              ><router-link :to="`/history/${row.id}`" class="table-link">{{
                row.filename
              }}</router-link
              ><small class="table-sub"
                >{{ label(row.kind) }} · {{ dateTime(row.created_at) }}</small
              ></template
            ></el-table-column
          >
          <el-table-column label="状态" width="110"
            ><template #default="{ row }"
              ><StatusBadge :value="row.status" /></template
          ></el-table-column>
        </el-table>
        <p class="overview-list-note">
          仅展示最近 5 条，任务进度在检测记录中自动更新。
        </p>
      </section>
      <section class="panel overview-distribution">
        <div class="section-heading">
          <div>
            <h3>目标类型分布</h3>
            <p>累计观测次数</p>
          </div>
        </div>
        <AnalyticsChart
          v-if="data?.class_counts.length"
          :option="distribution"
        /><el-empty v-else description="暂无目标统计" />
      </section>
    </div>
  </div>
</template>
