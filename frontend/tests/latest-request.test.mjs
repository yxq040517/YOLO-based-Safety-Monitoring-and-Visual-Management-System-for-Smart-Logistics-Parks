import assert from "node:assert/strict";
import test from "node:test";
import { deferred, environment, mount } from "./helpers.mjs";

test("switching detail cancels the old request and ignores its late response", async (t) => {
  const env = environment();
  const responses = { old: deferred(), current: deferred() };
  const signals = {};
  const component = mount(() =>
    env.module.useLatestRequest((id, signal) => {
      signals[id] = signal;
      return responses[id].promise;
    }),
  );
  t.after(component.unmount);
  const old = component.result.load("old");
  const current = component.result.load("current");
  assert.equal(signals.old.aborted, true);
  responses.old.resolve({ id: "old" });
  await old;
  assert.equal(component.result.loading.value, true);
  assert.equal(component.result.data.value, null);
  responses.current.resolve({ id: "current" });
  await current;
  assert.equal(component.result.data.value.id, "current");
  assert.equal(component.result.loading.value, false);
});

test("clearing the detail prevents an old error or result from reopening it", async (t) => {
  const env = environment();
  const response = deferred();
  let signal;
  const component = mount(() =>
    env.module.useLatestRequest((_id, request) => {
      signal = request;
      return response.promise;
    }),
  );
  t.after(component.unmount);
  const pending = component.result.load("event");
  component.result.clear();
  assert.equal(signal.aborted, true);
  response.reject(new Error("late failure"));
  await pending;
  assert.equal(component.result.loading.value, false);
  assert.equal(component.result.data.value, null);
  assert.equal(component.result.error.value, "");
});

test("new detail requests clear previous content and recover from failure", async (t) => {
  const env = environment();
  let fail = false;
  const component = mount(() =>
    env.module.useLatestRequest(async (id) => {
      if (fail) throw new Error("unavailable");
      return { id };
    }),
  );
  t.after(component.unmount);
  await component.result.load("first");
  fail = true;
  await component.result.load("second");
  assert.equal(component.result.data.value, null);
  assert.equal(component.result.error.value, "unavailable");
  fail = false;
  await component.result.load("third");
  assert.equal(component.result.data.value.id, "third");
  assert.equal(component.result.error.value, "");
});

test("leaving the page cancels a detail request and ignores its completion", async () => {
  const env = environment();
  const response = deferred();
  let signal;
  let requests = 0;
  const component = mount(() =>
    env.module.useLatestRequest((_id, request) => {
      requests++;
      signal = request;
      return response.promise;
    }),
  );
  const pending = component.result.load("event");
  component.unmount();
  assert.equal(signal.aborted, true);
  response.resolve({ id: "event" });
  await pending;
  await component.result.load("another");
  assert.equal(component.result.data.value, null);
  assert.equal(requests, 1);
});
