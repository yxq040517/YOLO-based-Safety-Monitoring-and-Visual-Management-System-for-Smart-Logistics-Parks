import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { deferred, loadModule } from "./helpers.mjs";

const require = createRequire(import.meta.url);
const { createPinia } = require("pinia");
const user = {
  id: 1,
  username: "operator",
  display_name: "Operator",
  role: "operator",
};

function authentication(api) {
  const values = new Map([["logistics-token", "saved-session"]]);
  const sessionStorage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  const module = loadModule(
    "src/stores/auth.ts",
    { sessionStorage },
    {
      "../api": { api, errorText: (error) => error.message },
    },
  );
  return { store: module.useAuth(createPinia()), sessionStorage };
}

for (const failure of [
  new Error("network offline"),
  Object.assign(new Error("timeout"), { code: "ECONNABORTED" }),
  Object.assign(new Error("service unavailable"), {
    isAxiosError: true,
    response: { status: 503 },
  }),
]) {
  test(`temporary identity failure preserves the session: ${failure.message}`, async () => {
    const { store, sessionStorage } = authentication({
      get: () => Promise.reject(failure),
    });
    await store.restore();
    assert.equal(sessionStorage.getItem("logistics-token"), "saved-session");
    assert.equal(store.restored, false);
    assert.equal(store.user, null);
    assert.ok(store.restoreError);
  });
}

test("identity rejection clears the invalid session", async () => {
  const failure = Object.assign(new Error("expired"), {
    isAxiosError: true,
    response: { status: 401 },
  });
  const { store, sessionStorage } = authentication({
    get: () => Promise.reject(failure),
  });
  await store.restore();
  assert.equal(sessionStorage.getItem("logistics-token"), null);
  assert.equal(store.user, null);
  assert.equal(store.restored, true);
  assert.ok(!store.restoreError);
});

test("retrying after a temporary failure restores the same user", async () => {
  let requests = 0;
  const { store, sessionStorage } = authentication({
    get: () =>
      ++requests === 1
        ? Promise.reject(new Error("offline"))
        : Promise.resolve({ data: user }),
  });
  await store.restore();
  await store.restore();
  assert.equal(requests, 2);
  assert.equal(store.user.username, user.username);
  assert.equal(store.restored, true);
  assert.equal(store.restoreError, "");
  assert.equal(sessionStorage.getItem("logistics-token"), "saved-session");
});

test("concurrent identity checks share one request", async () => {
  const response = deferred();
  let requests = 0;
  const { store } = authentication({
    get: () => {
      requests++;
      return response.promise;
    },
  });
  const first = store.restore();
  const second = store.restore();
  assert.equal(requests, 1);
  response.resolve({ data: user });
  await Promise.all([first, second]);
  assert.equal(store.user.username, user.username);
});

test("a late identity response cannot log a user back in after logout", async () => {
  const response = deferred();
  let signal;
  const { store, sessionStorage } = authentication({
    get: (_path, options) => {
      signal = options?.signal;
      return response.promise;
    },
  });
  const pending = store.restore();
  store.logout();
  response.resolve({ data: user });
  await pending;
  assert.equal(store.user, null);
  assert.equal(sessionStorage.getItem("logistics-token"), null);
  assert.equal(signal.aborted, true);
});

test("an old identity rejection cannot remove a newly signed-in session", async () => {
  const response = deferred();
  const replacement = { ...user, id: 2, username: "replacement" };
  const { store, sessionStorage } = authentication({
    get: () => response.promise,
    post: () =>
      Promise.resolve({
        data: { access_token: "new-session", user: replacement },
      }),
  });
  const pending = store.restore();
  await store.signIn("login", {
    username: "replacement",
    password: "test-password",
  });
  response.reject(
    Object.assign(new Error("old token expired"), {
      isAxiosError: true,
      response: { status: 401 },
    }),
  );
  await pending;
  assert.equal(sessionStorage.getItem("logistics-token"), "new-session");
  assert.equal(store.user.username, "replacement");
  assert.equal(store.restoreError, "");
});
