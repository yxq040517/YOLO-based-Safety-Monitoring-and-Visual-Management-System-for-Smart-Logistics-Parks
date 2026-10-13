<script setup lang="ts">
import { label } from "../constants";
defineProps<{ value: string }>();
</script>
<template>
  <span class="status-badge" :class="`status-${value}`"
    ><i></i>{{ label(value) }}</span
  >
</template>
