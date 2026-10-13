import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { flush, loadModule, mount } from "./helpers.mjs";

const require = createRequire(import.meta.url);
const pinia = require("pinia");
const vueRouter = require("vue-router");
const operator = {
  id: 1,
  username: "operator",
  display_name: "Operator",
  role: "operator",
};

function sessionNavigation() {
  const values = new Map([["logistics-token", "saved-session"]]);
  const globals = {
    sessionStorage: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    },
  };
  let online = false;
  let identityChecks = 0;
  const api = {
    get: (path) => {
      if (path === "/auth/status")
        return Promise.resolve({ data: { initialized: true } });
      identityChecks++;
      return online
        ? Promise.resolve({ data: operator })
        : Promise.reject(new Error("temporarily offline"));
    },
  };
  const store = loadModule("src/stores/auth.ts", globals, {
    "../api": { api, errorText: (error) => error.message },
  }).useAuth(pinia.createPinia());
  const dependencies = {
    "vue-router": {
      ...vueRouter,
      createWebHistory: vueRouter.createMemoryHistory,
    },
    "./stores/auth": { useAuth: () => store },
  };
  for (const path of [
    "./components/AppLayout.vue",
    ...[
      "Login",
      "Workbench",
      "Dashboard",
      "Live",
      "History",
      "Job",
      "Events",
      "Settings",
    ].map((name) => `./pages/${name}Page.vue`),
  ]) {
    dependencies[path] = { __esModule: true, default: { render: () => null } };
  }
  const router = loadModule("src/router.ts", globals, dependencies).router;
  function loginPage() {
    const page = loadModule(
      "src/pages/LoginPage.vue",
      globals,
      {
        "vue-router": {
          useRoute: () => router.currentRoute.value,
          useRouter: () => router,
        },
        "../stores/auth": { useAuth: () => store },
        "../api": { api, errorText: (error) => error.message },
        "@element-plus/icons-vue": {},
      },
      { component: true },
    ).default;
    return mount(() => page.setup({}, { expose() {} }));
  }
  return {
    router,
    store,
    loginPage,
    globals,
    setOnline: () => {
      online = true;
    },
    checks: () => identityChecks,
  };
}

test("temporary verification failure goes to recovery without verifying twice", async () => {
  const navigation = sessionNavigation();
  await navigation.router.push("/history/current?seek=4");
  assert.equal(navigation.router.currentRoute.value.path, "/login");
  assert.equal(
    navigation.router.currentRoute.value.query.redirect,
    "/history/current?seek=4",
  );
  assert.equal(
    navigation.globals.sessionStorage.getItem("logistics-token"),
    "saved-session",
  );
  assert.equal(navigation.checks(), 1);
});

test("reconnecting continues the original protected page without a new login", async (t) => {
  const navigation = sessionNavigation();
  await navigation.router.push("/history/current?seek=4");
  const page = navigation.loginPage();
  t.after(page.unmount);
  navigation.setOnline();
  await page.result.reconnect();
  await flush();
  assert.equal(
    navigation.router.currentRoute.value.fullPath,
    "/history/current?seek=4",
  );
  assert.equal(navigation.store.user.username, "operator");
  assert.equal(navigation.store.restoreError, "");
});

test("choosing password login explicitly clears the saved session", async (t) => {
  const navigation = sessionNavigation();
  await navigation.router.push("/workbench");
  const page = navigation.loginPage();
  t.after(page.unmount);
  await page.result.passwordLogin();
  assert.equal(
    navigation.globals.sessionStorage.getItem("logistics-token"),
    null,
  );
  assert.equal(navigation.store.restoreError, "");
  assert.equal(page.result.initialized.value, true);
});
