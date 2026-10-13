import assert from "node:assert/strict";
import test from "node:test";
import { deferred, environment, flush, loadModule, mount } from "./helpers.mjs";

const summary = {
  total_jobs: 7,
  completed_jobs: 7,
  active_jobs: 0,
  total_detections: 42,
  open_events: 28,
  cameras_online: 0,
  class_counts: [],
  daily: [],
  recent_events: [],
  recent_jobs: [],
};
const readyModel = {
  ready: true,
  weights: null,
  device: "cpu",
  classes: [],
  training: null,
  message: "ready",
};

function dashboard(api) {
  const env = environment();
  const component = loadModule(
    "src/pages/DashboardPage.vue",
    env.globals,
    {
      "../api": { api, errorText: (error) => error.message },
      "../composables": env.module,
      "../constants": loadModule("src/constants.ts"),
      "@element-plus/icons-vue": {},
      "../components/AnalyticsChart.vue": {},
      "../components/StatusBadge.vue": {},
    },
    { component: true },
  ).default;
  return mount(() => component.setup({}, { expose() {} }));
}

test("a model status failure does not hide successfully loaded dashboard data", async (t) => {
  const component = dashboard({
    get: (path) =>
      path === "/dashboard"
        ? Promise.resolve({ data: summary })
        : Promise.reject(new Error("model unavailable")),
  });
  t.after(component.unmount);
  await flush();
  assert.equal(component.result.data.value?.total_jobs, 7);
  assert.equal(component.result.error.value, "");
  assert.equal(component.result.modelError.value, "model unavailable");
  assert.ok(component.result.lastUpdated.value);
});

test("dashboard data appears while model status is still pending", async (t) => {
  const model = deferred();
  const component = dashboard({
    get: (path) =>
      path === "/dashboard"
        ? Promise.resolve({ data: summary })
        : model.promise,
  });
  t.after(component.unmount);
  await flush();
  assert.equal(component.result.data.value?.open_events, 28);
  assert.ok(component.result.lastUpdated.value);
  model.resolve({ data: readyModel });
  await flush();
  assert.equal(component.result.model.value.ready, true);
});
