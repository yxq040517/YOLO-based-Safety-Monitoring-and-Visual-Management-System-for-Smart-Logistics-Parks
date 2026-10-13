<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  DataAnalysis,
  Monitor,
  VideoCamera,
  Files,
  Bell,
  Setting,
  SwitchButton,
  Menu,
  Aim,
  ArrowRight,
} from "@element-plus/icons-vue";
import { useAuth } from "../stores/auth";
import { label } from "../constants";
const auth = useAuth();
const route = useRoute();
const router = useRouter();
const menuOpen = ref(false);
const primaryNavigation = [
  { path: "/workbench", name: "开始检测", icon: Monitor },
  { path: "/history", name: "检测记录", icon: Files },
  { path: "/events", name: "风险结果", icon: Bell },
];
const secondaryNavigation = [
  { path: "/live", name: "摄像头演示", icon: VideoCamera },
  { path: "/overview", name: "检测概览", icon: DataAnalysis },
  { path: "/settings", name: "规则与模型", icon: Setting },
];
function logout() {
  auth.logout();
  void router.push("/login");
}
</script>
<template>
  <div class="app-shell">
    <div v-if="menuOpen" class="sidebar-scrim" @click="menuOpen = false"></div>
    <aside class="sidebar" :class="{ open: menuOpen }">
      <router-link to="/workbench" class="brand"
        ><span class="brand-symbol"
          ><el-icon><Aim /></el-icon></span
        ><span>物流智安<small>LOGISTICS SAFETY</small></span></router-link
      >
      <div class="nav-caption">检测流程</div>
      <nav>
        <router-link
          v-for="item in primaryNavigation"
          :key="item.path"
          :to="item.path"
          :class="{ selected: route.path.startsWith(item.path) }"
          @click="menuOpen = false"
          ><el-icon><component :is="item.icon" /></el-icon
          ><span>{{ item.name }}</span
          ><el-icon class="nav-arrow"><ArrowRight /></el-icon
        ></router-link>
      </nav>
      <div class="nav-caption nav-caption-secondary">辅助功能</div>
      <nav class="secondary-nav">
        <router-link
          v-for="item in secondaryNavigation"
          :key="item.path"
          :to="item.path"
          :class="{ selected: route.path.startsWith(item.path) }"
          @click="menuOpen = false"
          ><el-icon><component :is="item.icon" /></el-icon
          ><span>{{ item.name }}</span
          ><el-icon class="nav-arrow"><ArrowRight /></el-icon
        ></router-link>
      </nav>
      <div class="sidebar-bottom">
        <div class="system-mark">
          <span class="status-dot"></span> 本地部署 · 数据自主可控
        </div>
        <p>检测结果留有依据<br />风险提示方便复核</p>
      </div>
    </aside>
    <main class="workspace">
      <header class="topbar">
        <div class="topbar-left">
          <el-button
            class="mobile-menu"
            text
            aria-label="展开导航"
            @click="menuOpen = true"
            ><el-icon><Menu /></el-icon></el-button
          ><span class="breadcrumb"
            >物流安全检测 <span>/</span> {{ route.meta.title }}</span
          >
        </div>
        <div class="account">
          <span class="avatar">{{
            auth.user?.display_name?.slice(0, 1) || "安"
          }}</span
          ><span class="account-name"
            >{{ auth.user?.display_name
            }}<small>{{ label(auth.user?.role || "") }}</small></span
          ><el-button
            text
            title="退出登录"
            aria-label="退出登录"
            @click="logout"
            ><el-icon><SwitchButton /></el-icon
          ></el-button>
        </div>
      </header>
      <section class="page-content">
        <div
          class="page-heading"
          :class="{ 'overview-heading': route.path === '/overview' }"
        >
          <div>
            <div class="eyebrow">YOLO DETECTION / SAFETY RULES</div>
            <h1>{{ route.meta.title }}</h1>
            <p>{{ route.meta.subtitle }}</p>
          </div>
          <span class="workspace-label">检测与风险复核</span>
        </div>
        <router-view />
      </section>
      <footer class="page-footer">
        物流智安 <span>视觉辅助研判，不替代现场安全检查与应急处置</span>
      </footer>
    </main>
  </div>
</template>
