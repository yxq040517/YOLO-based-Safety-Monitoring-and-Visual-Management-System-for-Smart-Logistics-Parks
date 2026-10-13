<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";
import { ElMessage } from "element-plus";
import { useRouter } from "vue-router";
import { useAuth } from "./stores/auth";
import zhCn from "element-plus/es/locale/lang/zh-cn";
const auth = useAuth();
const router = useRouter();
function expired() {
  if (!auth.user) return;
  auth.logout();
  ElMessage.warning("登录已过期，请重新登录。");
  void router.replace("/login");
}
onMounted(() => window.addEventListener("auth-expired", expired));
onUnmounted(() => window.removeEventListener("auth-expired", expired));
</script>
<template>
  <el-config-provider :locale="zhCn"><router-view /></el-config-provider>
</template>
