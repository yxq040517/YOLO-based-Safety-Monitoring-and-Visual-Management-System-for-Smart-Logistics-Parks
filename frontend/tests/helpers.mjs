import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(resolve(root, "package.json"));
const ts = require("typescript");
export const vue = require("vue");

export function loadModule(
  relative,
  globals = {},
  dependencies = {},
  options = {},
) {
  let source = readFileSync(resolve(root, relative), "utf8");
  if (relative.endsWith(".vue")) {
    const compiler = require("@vue/compiler-sfc");
    const descriptor = compiler.parse(source).descriptor;
    source = options.component
      ? compiler.compileScript(descriptor, { id: relative }).content
      : descriptor.scriptSetup.content;
  }
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const exports = {};
  runInNewContext(compiled, {
    exports,
    require: (name) => dependencies[name] ?? require(name),
    AbortController,
    ...globals,
  });
  return exports;
}

export function environment() {
  const document = new EventTarget();
  document.hidden = false;
  const timers = new Map();
  let sequence = 0;
  const globals = {
    document,
    window: {
      setTimeout(callback, delay) {
        const id = ++sequence;
        timers.set(id, { callback, delay });
        return id;
      },
    },
    clearTimeout: (id) => timers.delete(id),
  };
  const module = loadModule("src/composables.ts", globals, {
    "./api": { errorText: (error) => error.message ?? String(error) },
  });
  return {
    module,
    globals,
    timers,
    visibility(hidden) {
      document.hidden = hidden;
      document.dispatchEvent(new Event("visibilitychange"));
    },
    fireTimer() {
      const [id, timer] = timers.entries().next().value;
      timers.delete(id);
      return timer.callback();
    },
  };
}

export function mount(setup) {
  const renderer = vue.createRenderer({
    insert() {},
    remove() {},
    createElement: () => ({}),
    createText: () => ({}),
    createComment: () => ({}),
    setText() {},
    setElementText() {},
    parentNode: () => null,
    nextSibling: () => null,
    patchProp() {},
  });
  let result;
  const app = renderer.createApp({
    setup() {
      result = setup();
      return () => null;
    },
  });
  app.mount({});
  let mounted = true;
  return {
    result,
    unmount() {
      if (mounted) {
        mounted = false;
        app.unmount();
      }
    },
  };
}

export function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

export const flush = () => new Promise(setImmediate);
