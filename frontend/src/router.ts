import { createRouter, createWebHistory } from "vue-router";
import { useAuth } from "./stores/auth";
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      component: () => import("./pages/LoginPage.vue"),
      meta: { public: true, title: "登录" },
    },
    {
      path: "/",
      component: () => import("./components/AppLayout.vue"),
      children: [
        {
          path: "",
          redirect: "/workbench",
        },
        {
          path: "overview",
          component: () => import("./pages/DashboardPage.vue"),
          meta: {
            title: "检测概览",
            subtitle: "查看检测任务与风险结果的汇总数据",
          },
        },
        {
          path: "workbench",
          component: () => import("./pages/WorkbenchPage.vue"),
          meta: {
            title: "开始检测",
            subtitle: "上传图片或视频，查看目标识别与风险判断结果",
          },
        },
        {
          path: "live",
          component: () => import("./pages/LivePage.vue"),
          meta: {
            title: "摄像头演示",
            subtitle: "使用浏览器摄像头或 RTSP 设备体验连续检测",
          },
        },
        {
          path: "history",
          component: () => import("./pages/HistoryPage.vue"),
          meta: { title: "检测记录", subtitle: "回看已提交素材与检测结果" },
        },
        {
          path: "history/:id",
          component: () => import("./pages/JobPage.vue"),
          meta: {
            title: "检测详情",
            subtitle: "原始素材、识别结果与事件时间线",
          },
        },
        {
          path: "events",
          component: () => import("./pages/EventsPage.vue"),
          meta: {
            title: "风险结果",
            subtitle: "复核检测触发的风险提示与证据",
          },
        },
        {
          path: "settings",
          component: () => import("./pages/SettingsPage.vue"),
          meta: {
            title: "规则与模型",
            subtitle: "配置检测规则，查看模型状态与账户设置",
          },
        },
      ],
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
router.beforeEach(async (to) => {
  const auth = useAuth();
  if (!(to.path === "/login" && auth.restoreError && !auth.restored))
    await auth.restore();
  if (!to.meta.public && (!auth.user || !auth.restored))
    return { path: "/login", query: { redirect: to.fullPath } };
  if (to.path === "/login" && auth.user && auth.restored) return "/";
});
