<script setup lang="ts">
import { ref, watch } from "vue";
import { Search, Refresh } from "@element-plus/icons-vue";
import { api } from "../api";
import { usePolling } from "../composables";
import type { Job, Page } from "../types";
import { dateTime, elapsed, label } from "../constants";
import StatusBadge from "../components/StatusBadge.vue";
const jobs = ref<Job[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const q = ref("");
const search = ref("");
const kind = ref("");
const status = ref("");
const { loading, error, refresh } = usePolling(async () => {
  const { data } = await api.get<Page<Job>>("/jobs", {
    params: {
      page: page.value,
      page_size: pageSize.value,
      q: search.value || undefined,
      kind: kind.value || undefined,
      status: status.value || undefined,
    },
  });
  jobs.value = data.items;
  total.value = data.total;
}, 8000);
watch([kind, status, pageSize], () => {
  page.value = 1;
  void refresh();
});
watch(page, () => void refresh());
function applySearch() {
  search.value = q.value.trim();
  page.value = 1;
  void refresh();
}
</script>
<template>
  <section class="panel">
    <div class="section-heading">
      <div>
        <h3>全部检测记录</h3>
        <p>任务进度自动刷新，支持素材名称检索</p>
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
    />
    <div class="filter-bar">
      <el-input
        v-model="q"
        class="search-input"
        :prefix-icon="Search"
        clearable
        placeholder="搜索素材名称"
        @keyup.enter="applySearch"
        @clear="applySearch"
      /><el-button type="primary" plain @click="applySearch">查询</el-button
      ><el-select v-model="kind" clearable placeholder="全部素材类型"
        ><el-option
          v-for="k in ['image', 'video', 'camera']"
          :key="k"
          :value="k"
          :label="label(k)" /></el-select
      ><el-select v-model="status" clearable placeholder="全部任务状态"
        ><el-option
          v-for="s in ['queued', 'running', 'completed', 'failed', 'cancelled']"
          :key="s"
          :value="s"
          :label="label(s)" /></el-select
      ><span class="filter-total">共 {{ total }} 个任务</span>
    </div>
    <el-table
      v-loading="loading && !jobs.length"
      :data="jobs"
      empty-text="未找到符合条件的检测记录"
      class="compact-table"
      ><el-table-column label="素材名称" min-width="220"
        ><template #default="{ row }"
          ><router-link :to="`/history/${row.id}`" class="table-link">{{
            row.filename
          }}</router-link
          ><small class="table-sub">任务 #{{ row.id }}</small></template
        ></el-table-column
      ><el-table-column label="类型" width="100"
        ><template #default="{ row }">{{
          label(row.kind)
        }}</template></el-table-column
      ><el-table-column label="状态 / 进度" width="150"
        ><template #default="{ row }"
          ><StatusBadge :value="row.status" /><el-progress
            v-if="['queued', 'running'].includes(row.status)"
            :percentage="Math.round(row.progress || 0)"
            :stroke-width="3" /></template></el-table-column
      ><el-table-column label="检测耗时" width="120"
        ><template #default="{ row }">{{
          elapsed(row.duration_ms)
        }}</template></el-table-column
      ><el-table-column label="创建时间" min-width="170"
        ><template #default="{ row }">{{
          dateTime(row.created_at)
        }}</template></el-table-column
      ><el-table-column label="操作" width="90" fixed="right"
        ><template #default="{ row }"
          ><router-link :to="`/history/${row.id}`"
            >查看详情</router-link
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
</template>
