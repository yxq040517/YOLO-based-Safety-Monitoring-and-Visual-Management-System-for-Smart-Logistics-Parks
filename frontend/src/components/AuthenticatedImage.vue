<script setup lang="ts">
import { toRef } from "vue";
import { useMedia } from "../composables";
const props = defineProps<{
  source: string | null | undefined;
  alt?: string;
}>();
const { url, error, loading } = useMedia(toRef(props, "source"));
</script>
<template>
  <div v-loading="loading" class="authenticated-image">
    <el-alert v-if="error" :title="error" type="error" :closable="false" /><img
      v-else-if="url"
      :src="url"
      :alt="alt || '事件现场快照'"
    /><el-empty
      v-else-if="!loading"
      description="暂无现场快照"
      :image-size="60"
    />
  </div>
</template>
