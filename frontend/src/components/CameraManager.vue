<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Plus, Refresh, VideoCamera } from "@element-plus/icons-vue";
import { api, errorText } from "../api";
import { usePolling } from "../composables";
import { useAuth } from "../stores/auth";
import type { Camera, ModelInfo } from "../types";
import StatusBadge from "./StatusBadge.vue";
defineProps<{ model: ModelInfo | null }>();
const auth = useAuth();
const cameras = ref<Camera[]>([]);
const selectedId = ref<number | null>(null);
const selected = computed(() =>
  cameras.value.find((c) => c.id === selectedId.value),
);
const preview = ref("");
const previewError = ref("");
const dialog = ref(false);
const editingId = ref<number | null>(null);
const form = reactive({ name: "", source: "", zone: "" });
const formError = ref("");
const saving = ref(false);
const busy = ref<number | null>(null);
let controller: AbortController | undefined;
function clearPreview() {
  controller?.abort();
  controller = undefined;
  if (preview.value) URL.revokeObjectURL(preview.value);
  preview.value = "";
}
const { loading, error, refresh } = usePolling(async () => {
  cameras.value = (await api.get<Camera[]>("/cameras")).data;
  if (selectedId.value === null && cameras.value.length)
    selectedId.value = cameras.value[0]!.id;
}, 5000);
async function loadFrame() {
  const camera = selected.value;
  if (!camera || camera.status !== "online") {
    clearPreview();
    return;
  }
  const request = new AbortController();
  controller = request;
  const id = camera.id;
  try {
    const { data } = await api.get<Blob>(`/cameras/${id}/frame`, {
      responseType: "blob",
      signal: request.signal,
    });
    if (request.signal.aborted || selectedId.value !== id) return;
    if (preview.value) URL.revokeObjectURL(preview.value);
    preview.value = URL.createObjectURL(data);
    previewError.value = "";
  } catch (e) {
    if (!request.signal.aborted) {
      clearPreview();
      previewError.value = errorText(e);
    }
  }
}
usePolling(loadFrame, 2000);
watch(
  [selectedId, () => selected.value?.status],
  ([id, status], [previousId]) => {
    if (id !== previousId || status !== "online") {
      clearPreview();
      previewError.value = "";
    }
  },
);
function edit(camera?: Camera) {
  editingId.value = camera?.id ?? null;
  Object.assign(form, {
    name: camera?.name || "",
    source: camera?.source || "",
    zone: camera?.zone || "",
  });
  formError.value = "";
  dialog.value = true;
}
async function save() {
  if (!form.name.trim() || !/^rtsps?:\/\//i.test(form.source.trim())) {
    formError.value = "请填写设备名称与有效的 rtsp:// 或 rtsps:// 地址。";
    return;
  }
  saving.value = true;
  formError.value = "";
  try {
    const body = {
      name: form.name.trim(),
      source: form.source.trim(),
      zone: form.zone.trim(),
    };
    if (editingId.value !== null)
      await api.patch(`/cameras/${editingId.value}`, body);
    else await api.post("/cameras", body);
    dialog.value = false;
    await refresh();
    ElMessage.success("设备配置已保存");
  } catch (e) {
    formError.value = errorText(e);
  } finally {
    saving.value = false;
  }
}
async function action(camera: Camera, verb: "start" | "stop" | "delete") {
  if (verb === "delete") {
    try {
      await ElMessageBox.confirm(
        `确认删除设备「${camera.name}」？运行中的检测将停止。`,
        "删除设备",
        {
          type: "warning",
          confirmButtonText: "确认删除",
          cancelButtonText: "取消",
        },
      );
    } catch {
      return;
    }
  }
  busy.value = camera.id;
  try {
    if (verb === "delete") {
      await api.delete(`/cameras/${camera.id}`);
      if (selectedId.value === camera.id) selectedId.value = null;
    } else await api.post(`/cameras/${camera.id}/${verb}`);
    await refresh();
    if (verb !== "start") {
      clearPreview();
    }
  } catch (e) {
    ElMessage.error(errorText(e));
  } finally {
    busy.value = null;
  }
}
onUnmounted(() => {
  clearPreview();
});
</script>
<template>
  <el-alert
    v-if="error"
    :title="error"
    type="error"
    :closable="false"
    class="mb"
  />
  <div class="camera-grid">
    <section class="panel">
      <div class="section-heading">
        <div>
          <h3>园区设备</h3>
          <p>仅管理员可维护摄像头地址与凭据</p>
        </div>
        <div>
          <el-button
            text
            :icon="Refresh"
            :loading="loading"
            aria-label="刷新设备"
            @click="refresh"
          /><el-button
            v-if="auth.isAdmin"
            type="primary"
            :icon="Plus"
            size="small"
            @click="edit()"
            >新增设备</el-button
          >
        </div>
      </div>
      <div v-if="cameras.length" class="camera-list">
        <div
          v-for="camera in cameras"
          :key="camera.id"
          class="camera-card"
          :class="{ selected: selectedId === camera.id }"
        >
          <button class="camera-select" @click="selectedId = camera.id">
            <span class="camera-icon"
              ><el-icon><VideoCamera /></el-icon></span
            ><span
              ><strong>{{ camera.name }}</strong
              ><small>{{ camera.zone || "未设置区域标签" }}</small></span
            ><StatusBadge :value="camera.status" />
          </button>
          <p v-if="camera.error" class="inline-error">{{ camera.error }}</p>
          <div class="camera-actions">
            <el-button
              v-if="
                auth.canOperate &&
                ['online', 'connecting'].includes(camera.status)
              "
              size="small"
              :loading="busy === camera.id"
              @click="action(camera, 'stop')"
              >停止检测</el-button
            ><el-button
              v-else-if="auth.canOperate"
              type="primary"
              plain
              size="small"
              :disabled="!model?.ready"
              :loading="busy === camera.id"
              @click="action(camera, 'start')"
              >启动检测</el-button
            ><el-button
              v-if="auth.isAdmin"
              size="small"
              :disabled="busy !== null"
              @click="edit(camera)"
              >编辑</el-button
            ><el-button
              v-if="auth.isAdmin"
              text
              type="danger"
              size="small"
              :disabled="busy !== null"
              @click="action(camera, 'delete')"
              >删除</el-button
            >
          </div>
        </div>
      </div>
      <el-empty v-else description="尚未配置 RTSP 设备" />
    </section>
    <section class="panel">
      <div class="section-heading">
        <h3>{{ selected?.name || "设备画面预览" }}</h3>
        <span class="muted">最新标注帧 · 2 秒刷新</span>
      </div>
      <el-alert
        v-if="previewError"
        :title="previewError"
        type="warning"
        :closable="false"
        class="mb"
      />
      <div class="rtsp-stage">
        <img v-if="preview" :src="preview" alt="RTSP 最新标注帧" /><el-empty
          v-else
          :description="
            selected?.status === 'online'
              ? '等待最新检测画面…'
              : '选择并启动设备后显示实时画面'
          "
        />
      </div>
      <div v-if="selected" class="job-meta">
        <span>设备状态 <StatusBadge :value="selected.status" /></span
        ><span
          >所属区域 <b>{{ selected.zone || "未设置" }}</b></span
        >
      </div>
      <p class="hint">
        仅保留最新帧，不在浏览器排队播放。后台设备检测不会随离开本页面停止；请使用“停止检测”结束任务。
      </p>
      <p class="hint">
        区域入侵使用系统配置中的全局归一化区域，多设备共用；请确保各固定视角的区域含义一致。
      </p>
    </section>
  </div>
  <el-dialog
    v-model="dialog"
    :title="editingId === null ? '新增 RTSP 设备' : '编辑 RTSP 设备'"
    width="560px"
    destroy-on-close
    ><el-alert
      v-if="formError"
      :title="formError"
      type="error"
      :closable="false"
      class="mb"
    /><el-form label-position="top" @submit.prevent="save"
      ><el-form-item label="设备名称"
        ><el-input
          v-model="form.name"
          maxlength="100"
          placeholder="例如：一号仓装卸区" /></el-form-item
      ><el-form-item label="RTSP 地址（含所需凭据）"
        ><el-input
          v-model="form.source"
          type="password"
          show-password
          placeholder="rtsp://用户名:密码@摄像头地址:554/stream"
          autocomplete="off" /></el-form-item
      ><el-form-item label="区域标签"
        ><el-input
          v-model="form.zone"
          maxlength="100"
          placeholder="例如：东区 / 装卸口"
      /></el-form-item>
      <p class="hint">
        摄像头必须可从服务端网络访问。凭据仅向管理员展示；不要使用不受信任的流地址。
      </p></el-form
    ><template #footer
      ><el-button @click="dialog = false">取消</el-button
      ><el-button type="primary" :loading="saving" @click="save"
        >保存设备</el-button
      ></template
    ></el-dialog
  >
</template>
