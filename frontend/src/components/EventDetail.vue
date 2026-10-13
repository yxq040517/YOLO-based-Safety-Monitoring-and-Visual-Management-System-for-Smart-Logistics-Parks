<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { api, errorText } from "../api";
import { useAuth } from "../stores/auth";
import { dateTime, label, timestamp } from "../constants";
import type { SafetyEvent } from "../types";
import AuthenticatedImage from "./AuthenticatedImage.vue";
import StatusBadge from "./StatusBadge.vue";
const props = defineProps<{ event: SafetyEvent | null }>();
const emit = defineEmits<{ updated: [event: SafetyEvent] }>();
const auth = useAuth();
const selected = ref("");
const note = ref("");
const busy = ref(false);
const error = ref("");
const transitions: Record<string, string[]> = {
  pending: ["confirmed", "false_positive"],
  confirmed: ["closed", "false_positive"],
  processing: ["closed", "false_positive"],
  false_positive: ["confirmed"],
  closed: ["confirmed"],
};
const allowed = computed(() =>
  props.event
    ? [
        ...(props.event.status === "pending" ||
        props.event.status === "processing"
          ? []
          : [props.event.status]),
        ...(transitions[props.event.status] || []),
      ]
    : [],
);
watch(
  () => props.event,
  (event) => {
    selected.value =
      event?.status === "pending"
        ? "confirmed"
        : event?.status === "processing"
          ? "closed"
          : event?.status || "";
    note.value = "";
    error.value = "";
  },
  { immediate: true },
);
async function save() {
  if (!props.event || !selected.value) return;
  if (!note.value.trim()) {
    error.value = "请填写本次研判或处理备注，确保操作可追溯。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    const { data } = await api.patch<SafetyEvent>(`/events/${props.event.id}`, {
      status: selected.value,
      note: note.value.trim(),
    });
    emit("updated", data);
    note.value = "";
    ElMessage.success("事件处置已保存");
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div v-if="event" class="event-detail">
    <div class="event-detail-title">
      <StatusBadge :value="event.severity" /><StatusBadge
        :value="event.status"
      /><span class="muted">事件 #{{ event.id }}</span>
    </div>
    <h2>{{ event.title }}</h2>
    <div class="detail-facts">
      <span
        >规则类型<b>{{ label(event.rule_type) }}</b></span
      ><span
        >触发时间<b>{{ dateTime(event.created_at) }}</b></span
      ><span
        >素材时间点<b>{{ timestamp(event.timestamp_seconds) }}</b></span
      ><span
        >关联设备<b>{{ event.camera_id ?? "文件 / 浏览器摄像头" }}</b></span
      >
    </div>
    <el-alert
      v-if="event.rule_type === 'ppe'"
      title="仅为疑似防护用品缺失，不构成违规事实，请结合遮挡、视角与现场情况人工核实。"
      type="warning"
      :closable="false"
      class="mb"
    /><el-alert
      v-if="event.rule_type === 'proximity'"
      title="人车交叉提示仅依据画面相对位置，不判断实际距离或违规。"
      type="info"
      :closable="false"
      class="mb"
    /><AuthenticatedImage :source="event.snapshot_url" /><router-link
      v-if="event.job_id"
      :to="{
        path: `/history/${event.job_id}`,
        query: { seek: event.timestamp_seconds ?? undefined },
      }"
      class="detail-source-link"
      >打开关联检测与视频时间点 →</router-link
    >
    <div v-if="auth.canOperate" class="event-action-form">
      <h3>风险结果复核</h3>
      <p class="hint">
        待复核 → 有效风险或误报；有效风险处理完成后标记为已处理。
      </p>
      <el-alert
        v-if="error"
        :title="error"
        type="error"
        :closable="false"
        class="mb"
      /><el-form label-position="top"
        ><el-form-item label="目标状态"
          ><el-select v-model="selected" class="full-width"
            ><el-option
              v-for="s in allowed"
              :key="s"
              :value="s"
              :label="
                s === event.status ? `${label(s)}（仅追加备注）` : label(s)
              " /></el-select></el-form-item
        ><el-form-item label="本次研判 / 处理备注"
          ><el-input
            v-model="note"
            type="textarea"
            :rows="3"
            maxlength="2000"
            show-word-limit
            placeholder="请记录核实依据、现场处置结果或误报原因" /></el-form-item
        ><el-button type="primary" :loading="busy" @click="save"
          >保存处置记录</el-button
        ></el-form
      >
    </div>
    <p v-else class="hint">
      观察员可查看事件，修改状态需要操作员或管理员权限。
    </p>
    <section class="mt">
      <h3>复核记录</h3>
      <el-timeline v-if="event.history?.length" class="event-history"
        ><el-timeline-item
          v-for="(item, index) in event.history"
          :key="index"
          :timestamp="dateTime(item.created_at)"
          placement="top"
          ><strong>{{ label(item.status) }} · {{ item.username }}</strong>
          <p>{{ item.note || "无备注" }}</p></el-timeline-item
        ></el-timeline
      ><el-empty v-else description="尚无人工处置记录" :image-size="45" />
    </section>
  </div>
</template>
