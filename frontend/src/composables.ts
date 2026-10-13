import { onMounted, onUnmounted, ref, shallowRef, watch } from "vue";
import type { Ref } from "vue";
import { api, errorText } from "./api";
export function usePolling(
  action: () => Promise<void>,
  interval = 5000,
  enabled?: Ref<boolean>,
) {
  const loading = ref(false);
  const error = ref("");
  let disposed = false;
  let timer: number | undefined;
  let refreshQueued = false;
  let active: Promise<void> | undefined;
  function canPoll() {
    return !disposed && !document.hidden && (enabled?.value ?? true);
  }
  function refresh(): Promise<void> {
    if (disposed) return Promise.resolve();
    clearTimeout(timer);
    timer = undefined;
    if (active) {
      refreshQueued = true;
      return active;
    }
    loading.value = true;
    active = (async () => {
      do {
        refreshQueued = false;
        try {
          await action();
          if (!disposed) error.value = "";
        } catch (e) {
          if (!disposed) error.value = errorText(e);
        }
      } while (refreshQueued && !disposed);
    })().finally(() => {
      active = undefined;
      loading.value = false;
      if (canPoll()) {
        timer = window.setTimeout(() => {
          timer = undefined;
          void refresh();
        }, interval);
      }
    });
    return active;
  }
  function updatePolling() {
    clearTimeout(timer);
    timer = undefined;
    if (canPoll()) void refresh();
    else refreshQueued = false;
  }
  onMounted(() => {
    document.addEventListener("visibilitychange", updatePolling);
    updatePolling();
  });
  if (enabled) watch(enabled, updatePolling);
  onUnmounted(() => {
    disposed = true;
    clearTimeout(timer);
    document.removeEventListener("visibilitychange", updatePolling);
  });
  return { loading, error, refresh };
}

export function useLatestRequest<T>(
  action: (id: string, signal: AbortSignal) => Promise<T>,
) {
  const data = shallowRef<T | null>(null);
  const loading = ref(false);
  const error = ref("");
  let controller: AbortController | undefined;
  let disposed = false;

  function clear() {
    controller?.abort();
    controller = undefined;
    data.value = null;
    error.value = "";
    loading.value = false;
  }

  async function load(id: string) {
    clear();
    if (disposed || !id) return;
    const request = new AbortController();
    controller = request;
    loading.value = true;
    try {
      const result = await action(id, request.signal);
      if (controller === request && !request.signal.aborted)
        data.value = result;
    } catch (e) {
      if (controller === request && !request.signal.aborted)
        error.value = errorText(e);
    } finally {
      if (controller === request) loading.value = false;
    }
  }

  onUnmounted(() => {
    disposed = true;
    clear();
  });
  return { data, loading, error, load, clear };
}

export function useMedia(source: Ref<string | null | undefined>) {
  const url = ref("");
  const error = ref("");
  const loading = ref(false);
  let controller: AbortController | undefined;
  let current = "";
  watch(
    source,
    async (value) => {
      controller?.abort();
      if (current) URL.revokeObjectURL(current);
      current = "";
      url.value = "";
      error.value = "";
      loading.value = false;
      if (!value) return;
      const request = new AbortController();
      controller = request;
      loading.value = true;
      try {
        const { data } = await api.get<Blob>(value, {
          responseType: "blob",
          signal: request.signal,
          timeout: 0,
        });
        if (request.signal.aborted) return;
        current = URL.createObjectURL(data);
        url.value = current;
      } catch (e) {
        if (!request.signal.aborted) error.value = errorText(e);
      } finally {
        if (!request.signal.aborted) loading.value = false;
      }
    },
    { immediate: true },
  );
  onUnmounted(() => {
    controller?.abort();
    if (current) URL.revokeObjectURL(current);
  });
  return { url, error, loading };
}
