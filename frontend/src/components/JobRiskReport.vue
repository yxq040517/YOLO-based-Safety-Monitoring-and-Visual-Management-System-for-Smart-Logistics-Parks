<script setup lang="ts">
import { computed } from "vue";
import { activeJob, label, timestamp } from "../constants";
import type { Job, SafetyEvent } from "../types";
import StatusBadge from "./StatusBadge.vue";

const props = defineProps<{ job: Job }>();

const events = computed(() =>
  [...(props.job.events || [])].sort((a, b) => {
    const first = a.timestamp_seconds ?? Number.POSITIVE_INFINITY;
    const second = b.timestamp_seconds ?? Number.POSITIVE_INFINITY;
    return first - second || a.id.localeCompare(b.id);
  }),
);

const ruleCounts = computed(() =>
  Object.entries(
    events.value.reduce<Record<string, number>>((counts, event) => {
      counts[event.rule_type] = (counts[event.rule_type] || 0) + 1;
      return counts;
    }, {}),
  ),
);

const severityCounts = computed(() =>
  ["high", "medium", "low"]
    .map((severity) => ({
      severity,
      count: events.value.filter((event) => event.severity === severity).length,
    }))
    .filter((item) => item.count > 0),
);

function timepoint(event: SafetyEvent) {
  if (props.job.kind === "image") return "图片";
  return event.timestamp_seconds == null
    ? "时间点未记录"
    : timestamp(event.timestamp_seconds);
}
</script>

<template>
  <section class="risk-report" aria-labelledby="risk-report-heading">
    <div class="risk-heading">
      <div>
        <h4 id="risk-report-heading">规则判定摘要</h4>
        <p>根据检测结果触发的规则事件，需人工复核。</p>
      </div>
      <router-link :to="{ path: '/events', query: { job: job.id } }">
        查看全部事件
      </router-link>
    </div>

    <template v-if="events.length">
      <p class="risk-total">
        本页已载入 <strong>{{ events.length }}</strong> 条规则事件<span
          v-if="activeJob(job.status)"
          >，检测仍在进行</span
        ><span v-if="events.length >= 100">；更多事件请在事件页查看</span>
      </p>
      <div class="risk-breakdown">
        <div>
          <span class="risk-label">触发规则</span>
          <span
            v-for="[rule, count] in ruleCounts"
            :key="rule"
            class="risk-chip"
          >
            {{ label(rule) }} {{ count }}
          </span>
        </div>
        <div>
          <span class="risk-label">风险等级</span>
          <span
            v-for="item in severityCounts"
            :key="item.severity"
            class="risk-chip"
          >
            {{ label(item.severity) }} {{ item.count }}
          </span>
        </div>
      </div>
      <ol class="risk-events">
        <li v-for="event in events" :key="event.id">
          <span class="risk-time">{{ timepoint(event) }}</span>
          <span class="risk-title">{{ event.title }}</span>
          <StatusBadge :value="event.severity" />
          <StatusBadge :value="event.status" />
          <router-link
            v-if="job.kind === 'video' && event.timestamp_seconds != null"
            :to="{
              path: `/history/${job.id}`,
              query: { seek: event.timestamp_seconds },
            }"
            :aria-label="`定位视频中的 ${event.title}`"
          >
            定位
          </router-link>
          <router-link
            :to="{
              path: '/events',
              query: { job: job.id, event: event.id },
            }"
            :aria-label="`复核事件 ${event.title}`"
          >
            复核
          </router-link>
        </li>
      </ol>
    </template>
    <p v-else class="risk-empty">
      {{
        activeJob(job.status)
          ? "检测进行中，暂未触发规则事件。"
          : "当前规则未触发风险事件，请结合标注结果人工复核。"
      }}
    </p>
  </section>
</template>

<style scoped>
.risk-report {
  margin: 18px 0 24px;
  padding: 16px 18px;
  border: 1px solid #e4ebef;
  border-radius: 8px;
  background: #fbfcfd;
}
.risk-heading,
.risk-breakdown > div,
.risk-events li {
  display: flex;
  align-items: center;
  gap: 10px;
}
.risk-heading {
  justify-content: space-between;
}
.risk-heading h4 {
  margin: 0;
  font-size: 14px;
  color: #314b57;
}
.risk-heading p,
.risk-empty {
  margin: 5px 0 0;
  color: #7f929d;
  font-size: 11px;
}
.risk-heading a,
.risk-events a {
  color: #168c7a;
  font-size: 11px;
  white-space: nowrap;
}
.risk-total {
  margin: 15px 0 12px;
  color: #526b78;
  font-size: 12px;
}
.risk-total strong {
  color: #168c7a;
}
.risk-breakdown {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
}
.risk-breakdown > div {
  flex-wrap: wrap;
  gap: 7px;
}
.risk-label {
  color: #7f929d;
  font-size: 11px;
}
.risk-chip {
  padding: 4px 8px;
  border-radius: 4px;
  background: #eaf5f1;
  color: #4b766d;
  font-size: 11px;
}
.risk-events {
  display: grid;
  gap: 6px;
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
  max-height: 240px;
  overflow: auto;
}
.risk-events li {
  padding: 8px 10px;
  border: 1px solid #edf1f4;
  border-radius: 5px;
  background: #fff;
}
.risk-time {
  min-width: 78px;
  color: #168c7a;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.risk-title {
  flex: 1;
  min-width: 120px;
  color: #526b78;
  font-size: 11px;
}
@media (max-width: 720px) {
  .risk-events li {
    flex-wrap: wrap;
  }
  .risk-title {
    flex-basis: calc(100% - 90px);
  }
}
</style>
