import { onMounted, onUnmounted, ref, watch } from "vue";
import type { Ref } from "vue";
import { api, errorText } from "./api";

export async function videoMediaUrl(value: string, signal?: AbortSignal) {
  const prefix = "/api/media/";
  if (!value.startsWith(prefix)) throw new Error("无效的视频地址");
  const relative_path = decodeURIComponent(value.slice(prefix.length));
  const response = await api.get<{ url: string }>("/media-access", {
    params: { relative_path },
    signal,
  });
  return response.data.url;
}

export function useVideoMedia(source: Ref<string | null | undefined>) {
  const url = ref("");
  const error = ref("");
  const loading = ref(false);
  let controller: AbortController | undefined;
  let renewalTimer: number | undefined;

  function scheduleRenewal() {
    clearTimeout(renewalTimer);
    renewalTimer = window.setTimeout(() => void renew(), 10 * 60 * 1000);
  }

  async function renew() {
    const value = source.value;
    const active = controller;
    if (!value || !active || active.signal.aborted) return false;
    try {
      await videoMediaUrl(value, active.signal);
      if (active.signal.aborted || source.value !== value) return false;
      error.value = "";
      scheduleRenewal();
      return true;
    } catch (e) {
      if (!active.signal.aborted && source.value === value) {
        error.value = errorText(e);
        scheduleRenewal();
      }
      return false;
    }
  }

  function renewWhenVisible() {
    if (!document.hidden) void renew();
  }

  watch(
    source,
    async (value) => {
      controller?.abort();
      clearTimeout(renewalTimer);
      url.value = "";
      error.value = "";
      loading.value = false;
      if (!value) return;
      const request = new AbortController();
      controller = request;
      loading.value = true;
      try {
        const signedUrl = await videoMediaUrl(value, request.signal);
        if (!request.signal.aborted) {
          url.value = signedUrl;
          scheduleRenewal();
        }
      } catch (e) {
        if (!request.signal.aborted) error.value = errorText(e);
      } finally {
        if (!request.signal.aborted) loading.value = false;
      }
    },
    { immediate: true },
  );
  onMounted(() =>
    document.addEventListener("visibilitychange", renewWhenVisible),
  );
  onUnmounted(() => {
    controller?.abort();
    clearTimeout(renewalTimer);
    document.removeEventListener("visibilitychange", renewWhenVisible);
  });
  return { url, error, loading, renew };
}
