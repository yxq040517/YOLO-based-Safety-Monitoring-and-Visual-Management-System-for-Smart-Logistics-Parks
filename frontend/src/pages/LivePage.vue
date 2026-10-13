<script setup lang="ts">
import { ref } from "vue";
import { api } from "../api";
import { usePolling } from "../composables";
import type { ModelInfo } from "../types";
import ModelNotice from "../components/ModelNotice.vue";
import BrowserCamera from "../components/BrowserCamera.vue";
import CameraManager from "../components/CameraManager.vue";
const tab = ref("browser");
const model = ref<ModelInfo | null>(null);
const { error } = usePolling(async () => {
  model.value = (await api.get<ModelInfo>("/model")).data;
}, 10000);
</script>
<template>
  <ModelNotice :model="model" :error="error" /><el-tabs
    v-model="tab"
    class="workspace-tabs"
    ><el-tab-pane label="浏览器摄像头" name="browser" /><el-tab-pane
      label="园区 RTSP 设备"
      name="rtsp" /></el-tabs
  ><BrowserCamera v-if="tab === 'browser'" :model="model" /><CameraManager
    v-else
    :model="model"
  />
</template>
