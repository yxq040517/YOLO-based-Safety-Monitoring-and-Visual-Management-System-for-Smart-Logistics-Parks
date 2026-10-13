import assert from "node:assert/strict";
import test from "node:test";
import { deferred, environment, flush, mount, vue } from "./helpers.mjs";

test("returning to a visible page keeps one polling chain and cleans it on unmount", async (t) => {
  const env = environment();
  const gate = deferred();
  let requests = 0;
  const component = mount(() =>
    env.module.usePolling(async () => {
      requests++;
      await gate.promise;
    }),
  );
  t.after(component.unmount);
  env.visibility(true);
  env.visibility(false);
  await flush();
  assert.equal(
    env.timers.size,
    0,
    "an active request must not schedule another chain",
  );
  gate.resolve();
  await flush();
  assert.equal(requests, 2, "returning to the page requests one fresh result");
  assert.equal(env.timers.size, 1);
  component.unmount();
  assert.equal(env.timers.size, 0);
});

test("overlapping manual refreshes wait for one coalesced follow-up", async (t) => {
  const env = environment();
  const first = deferred();
  const second = deferred();
  let requests = 0;
  const component = mount(() =>
    env.module.usePolling(() =>
      ++requests === 1 ? first.promise : second.promise,
    ),
  );
  t.after(component.unmount);
  let settled = false;
  const refresh = component.result.refresh().then(() => {
    settled = true;
  });
  const another = component.result.refresh();
  await flush();
  assert.equal(settled, false, "refresh must await the follow-up result");
  first.resolve();
  await flush();
  assert.equal(requests, 2);
  assert.equal(settled, false);
  second.resolve();
  await Promise.all([refresh, another]);
  assert.equal(settled, true);
  assert.equal(env.timers.size, 1);
});

test("disabled and hidden pages pause polling without leaking a timer", async (t) => {
  const env = environment();
  const enabled = vue.ref(true);
  const gate = deferred();
  let requests = 0;
  const component = mount(() =>
    env.module.usePolling(
      async () => {
        requests++;
        await gate.promise;
      },
      100,
      enabled,
    ),
  );
  t.after(component.unmount);
  enabled.value = false;
  await vue.nextTick();
  gate.resolve();
  await flush();
  assert.equal(env.timers.size, 0);
  enabled.value = true;
  await vue.nextTick();
  await flush();
  assert.equal(requests, 2);
  assert.equal(env.timers.size, 1);
  env.visibility(true);
  assert.equal(env.timers.size, 0);
});

test("manual refresh replaces a scheduled tick and recovers after an error", async (t) => {
  const env = environment();
  let fail = true;
  let requests = 0;
  const component = mount(() =>
    env.module.usePolling(async () => {
      requests++;
      if (fail) throw new Error("offline");
    }),
  );
  t.after(component.unmount);
  await flush();
  assert.equal(component.result.error.value, "offline");
  fail = false;
  await component.result.refresh();
  assert.equal(component.result.error.value, "");
  assert.equal(requests, 2);
  assert.equal(env.timers.size, 1);
  await env.fireTimer();
  await flush();
  assert.equal(requests, 3);
  assert.equal(env.timers.size, 1);
});

test("an in-flight request cannot resume polling after the page unmounts", async () => {
  const env = environment();
  const gate = deferred();
  const component = mount(() => env.module.usePolling(() => gate.promise));
  component.unmount();
  gate.resolve();
  await flush();
  assert.equal(env.timers.size, 0);
});
