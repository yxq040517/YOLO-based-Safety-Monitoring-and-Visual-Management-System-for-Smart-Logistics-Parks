import assert from "node:assert/strict";
import test from "node:test";
import { deferred, environment, flush, loadModule, mount } from "./helpers.mjs";

const readyModel = {
  ready: true,
  weights: null,
  device: "cpu",
  classes: [],
  training: null,
  message: "ready",
};
const settings = {
  confidence: 0.35,
  event_cooldown_seconds: 30,
  consecutive_frames: 3,
  enable_fire: true,
  enable_smoke: true,
  enable_ppe: false,
  enable_intrusion: false,
  enable_proximity: false,
  proximity_ratio: 0.15,
  zone_polygon: [],
};
function job(id, progress = 0) {
  return {
    id,
    kind: "video",
    filename: "sample.mp4",
    status: "running",
    progress,
    created_at: "2026-10-12T00:00:00Z",
    completed_at: null,
    error: null,
    confidence: 0.35,
    source_url: null,
    result_url: null,
    preview_url: null,
    detections: [],
    counts: {},
    events: [],
    duration_ms: 0,
    width: 640,
    height: 360,
  };
}

function workbench(get) {
  const env = environment();
  const component = loadModule(
    "src/pages/WorkbenchPage.vue",
    env.globals,
    {
      "../api": {
        api: {
          get: (path, options) =>
            path === "/settings"
              ? Promise.resolve({ data: settings })
              : get(path, options),
        },
        errorText: (error) => error.message,
      },
      "../composables": env.module,
      "../constants": loadModule("src/constants.ts"),
      "../stores/auth": { useAuth: () => ({ canOperate: true }) },
      "@element-plus/icons-vue": {},
      "../components/ModelNotice.vue": {},
      "../components/DetectionControls.vue": {},
      "../components/JobViewer.vue": {},
      "../components/StatusBadge.vue": {},
    },
    { component: true },
  ).default;
  return { ...mount(() => component.setup({}, { expose() {} })), env };
}

test("task progress keeps polling while the model status request is pending", async (t) => {
  const model = deferred();
  let requests = 0;
  const page = workbench((path) =>
    path === "/model"
      ? model.promise
      : Promise.resolve({ data: job("current", ++requests * 30) }),
  );
  t.after(page.unmount);
  page.result.job.value = job("current");
  await flush();
  assert.equal(page.result.job.value.progress, 30);
  await page.env.fireTimer();
  await flush();
  assert.equal(page.result.job.value.progress, 60);
  model.resolve({ data: readyModel });
});

test("a failed model status request does not prevent progress updates", async (t) => {
  const page = workbench((path) =>
    path === "/model"
      ? Promise.reject(new Error("model unavailable"))
      : Promise.resolve({ data: job("current", 65) }),
  );
  t.after(page.unmount);
  page.result.job.value = job("current");
  await flush();
  assert.equal(page.result.job.value.progress, 65);
  assert.equal(page.result.modelError.value, "model unavailable");
  assert.equal(page.result.jobError.value, "");
});

test("a task query failure is separate from model availability", async (t) => {
  const page = workbench((path) =>
    path === "/model"
      ? Promise.resolve({ data: readyModel })
      : Promise.reject(new Error("progress unavailable")),
  );
  t.after(page.unmount);
  page.result.job.value = job("current");
  await flush();
  assert.equal(page.result.model.value.ready, true);
  assert.equal(page.result.modelError.value, "");
  assert.equal(page.result.jobError.value, "progress unavailable");
});

test("a late task response cannot overwrite a different current task", async (t) => {
  const response = deferred();
  const page = workbench((path) =>
    path === "/model"
      ? Promise.resolve({ data: readyModel })
      : response.promise,
  );
  t.after(page.unmount);
  page.result.job.value = job("old");
  await flush();
  page.result.job.value = job("new");
  response.resolve({ data: job("old", 80) });
  await flush();
  assert.equal(page.result.job.value.id, "new");
});

test("leaving the workbench cancels requests and ignores late progress", async () => {
  const response = deferred();
  let signal;
  const page = workbench((path, options) => {
    if (path === "/model") return Promise.resolve({ data: readyModel });
    signal = options?.signal;
    return response.promise;
  });
  page.result.job.value = job("current");
  await flush();
  page.unmount();
  response.resolve({ data: job("current", 90) });
  await flush();
  assert.equal(page.result.job.value.progress, 0);
  assert.equal(signal.aborted, true);
  assert.equal(page.env.timers.size, 0);
});

test("a late query failure cannot be attributed to a different task", async (t) => {
  const response = deferred();
  const page = workbench((path) =>
    path === "/model"
      ? Promise.resolve({ data: readyModel })
      : response.promise,
  );
  t.after(page.unmount);
  page.result.job.value = job("old");
  await flush();
  page.result.job.value = job("new");
  response.reject(new Error("old task unavailable"));
  await flush();
  assert.equal(page.result.jobError.value, "");
});

test("completed tasks stop progress polling while model polling remains", async (t) => {
  const page = workbench((path) =>
    Promise.resolve({
      data:
        path === "/model"
          ? readyModel
          : { ...job("current", 100), status: "completed" },
    }),
  );
  t.after(page.unmount);
  page.result.job.value = job("current");
  await flush();
  assert.equal(page.result.job.value.status, "completed");
  assert.deepEqual(
    [...page.env.timers.values()].map((timer) => timer.delay),
    [15000],
  );
});
