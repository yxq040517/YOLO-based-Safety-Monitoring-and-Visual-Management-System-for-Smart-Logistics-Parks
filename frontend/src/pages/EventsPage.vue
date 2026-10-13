<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Search, Refresh } from "@element-plus/icons-vue";
import { api } from "../api";
import { useLatestRequest, usePolling } from "../composables";
import type { SafetyEvent, Page } from "../types";
import { dateTime, label } from "../constants";
import StatusBadge from "../components/StatusBadge.vue";
import EventDetail from "../components/EventDetail.vue";
const route = useRoute();
const router = useRouter();
const events = ref<SafetyEvent[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const q = ref("");
const search = ref("");
const status = ref("");
const severity = ref("");
const rule = ref("");
const openOnly = computed(() => route.query.scope === "open");
const statusOptions = computed(() =>
  openOnly.value
    ? ["pending", "confirmed", "processing"]
    : ["pending", "confirmed", "processing", "closed", "false_positive"],
);
const drawer = ref(false);
const detail = useLatestRequest<SafetyEvent>(async (id, signal) => {
  return (
    await api.get<SafetyEvent>(`/events/${encodeURIComponent(id)}`, { signal })
  ).data;
});
const { data: selected, error: detailError, loading: detailLoading } = detail;
const { loading, error, refresh } = usePolling(async () => {
  const { data } = await api.get<Page<SafetyEvent>>("/events", {
    params: {
      page: page.value,
      page_size: pageSize.value,
      q: search.value || undefined,
      status: status.value || undefined,
      severity: severity.value || undefined,
      rule_type: rule.value || undefined,
      job_id: route.query.job || undefined,
      open_only: openOnly.value || undefined,
    },
  });
  events.value = data.items;
  total.value = data.total;
}, 10000);
watch(
  [status, severity, rule, pageSize, () => route.query.job, openOnly],
  () => {
    if (openOnly.value && !statusOptions.value.includes(status.value))
      status.value = "";
    page.value = 1;
    void refresh();
  },
);
function clearOpenFilter() {
  const query = { ...route.query };
  delete query.scope;
  void router.replace({ query });
}
watch(page, () => void refresh());
function applySearch() {
  search.value = q.value.trim();
  page.value = 1;
  void refresh();
}
function open(event: SafetyEvent) {
  detail.clear();
  selected.value = event;
  drawer.value = true;
}
async function linkedDetail(id: unknown) {
  if (!id) {
    detail.clear();
    drawer.value = false;
    return;
  }
  drawer.value = true;
  await detail.load(String(id));
}
watch(
  () => route.query.event,
  (id) => void linkedDetail(id),
  { immediate: true },
);
watch(drawer, (visible) => {
  if (visible) return;
  detail.clear();
  if (route.query.event) {
    const query = { ...route.query };
    delete query.event;
    void router.replace({ query });
  }
});
function updated(event: SafetyEvent) {
  if (selected.value?.id === event.id) selected.value = event;
  events.value = events.value.map((item) =>
    item.id === event.id ? event : item,
  );
  void refresh();
}
</script>
<template>
  <section class="panel">
    <div class="section-heading">
      <div>
        <h3>风险结果</h3>
        <p>按检测规则汇总结果，查看证据并标记复核结论</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="refresh"
        >刷新</el-button
      >
    </div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      class="mb"
    /><el-alert
      v-if="openOnly"
      title="正在查看待处理风险：待复核、已确认和处理中"
      type="warning"
      show-icon
      :closable="false"
      class="mb"
      ><el-button text type="primary" @click="clearOpenFilter"
        >取消待处理筛选</el-button
      ></el-alert
    ><el-alert
      v-if="route.query.job"
      :title="`正在查看任务 ${route.query.job} 的关联事件`"
      type="info"
      class="mb"
      @close="router.replace('/events')"
    />
    <div class="filter-bar">
      <el-input
        v-model="q"
        :prefix-icon="Search"
        clearable
        placeholder="搜索事件标题 / 备注"
        class="search-input"
        @keyup.enter="applySearch"
        @clear="applySearch"
      /><el-button type="primary" plain @click="applySearch">查询</el-button
      ><el-select v-model="status" clearable placeholder="全部处置状态"
        ><el-option
          v-for="s in statusOptions"
          :key="s"
          :value="s"
          :label="label(s)" /></el-select
      ><el-select v-model="rule" clearable placeholder="全部规则"
        ><el-option
          v-for="s in ['fire', 'smoke', 'ppe', 'intrusion', 'proximity']"
          :key="s"
          :value="s"
          :label="label(s)" /></el-select
      ><el-select v-model="severity" clearable placeholder="全部风险等级"
        ><el-option
          v-for="s in ['high', 'medium', 'low']"
          :key="s"
          :value="s"
          :label="label(s)"
      /></el-select>
    </div>
    <el-table
      v-loading="loading && !events.length"
      :data="events"
      empty-text="未找到符合条件的安全事件"
      ><el-table-column label="事件信息" min-width="230"
        ><template #default="{ row }"
          ><button class="text-button table-link" @click="open(row)">
            {{ row.title }}</button
          ><small class="table-sub"
            >#{{ row.id }} · {{ label(row.rule_type) }}</small
          ></template
        ></el-table-column
      ><el-table-column label="风险等级" width="110"
        ><template #default="{ row }"
          ><StatusBadge :value="row.severity" /></template></el-table-column
      ><el-table-column label="处置状态" width="110"
        ><template #default="{ row }"
          ><StatusBadge :value="row.status" /></template></el-table-column
      ><el-table-column label="触发时间" min-width="180"
        ><template #default="{ row }">{{
          dateTime(row.created_at)
        }}</template></el-table-column
      ><el-table-column label="最新备注" min-width="180" show-overflow-tooltip
        ><template #default="{ row }">{{
          row.note || "暂无备注"
        }}</template></el-table-column
      ><el-table-column label="操作" width="100" fixed="right"
        ><template #default="{ row }"
          ><el-button text type="primary" @click="open(row)"
            >查看 / 处置</el-button
          ></template
        ></el-table-column
      ></el-table
    >
    <div class="pagination">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        background
      />
    </div>
  </section>
  <el-drawer
    v-model="drawer"
    title="风险结果详情"
    size="min(620px, 100vw)"
    destroy-on-close
    ><el-alert
      v-if="detailError"
      :title="detailError"
      type="error"
      :closable="false" /><el-skeleton
      v-if="detailLoading"
      :rows="8"
      animated /><EventDetail
      v-else-if="selected && !detailError"
      :event="selected"
      @updated="updated"
  /></el-drawer>
</template>
