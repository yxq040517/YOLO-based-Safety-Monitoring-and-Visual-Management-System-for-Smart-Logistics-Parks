<script setup lang="ts">
import type { ModelInfo } from "../types";
defineProps<{ model: ModelInfo | null; error?: string }>();
</script>
<template>
  <el-alert
    v-if="error"
    :title="error"
    type="error"
    :closable="false"
    show-icon
    class="mb"
  /><el-alert
    v-else-if="model && !model.ready"
    title="模型尚未就绪，新的检测任务暂不可用"
    type="warning"
    :closable="false"
    show-icon
    class="mb"
    ><template #default
      >{{ model.message
      }}<router-link to="/settings" class="inline-link"
        >查看模型与训练状态</router-link
      >。历史记录与事件处置不受影响。</template
    ></el-alert
  ><el-alert
    v-else-if="!model"
    title="正在获取模型可用状态…"
    type="info"
    :closable="false"
    class="mb"
  />
</template>
