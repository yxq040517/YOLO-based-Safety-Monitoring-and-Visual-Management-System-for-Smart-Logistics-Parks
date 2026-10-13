import { computed, ref } from "vue";
import { defineStore } from "pinia";
import axios from "axios";
import { api, errorText } from "../api";
import type { User } from "../types";
export const useAuth = defineStore("auth", () => {
  const user = ref<User | null>(null);
  const restored = ref(false);
  const restoreError = ref("");
  let pendingRestore: Promise<void> | undefined;
  let restoreController: AbortController | undefined;
  const canOperate = computed(
    () => user.value?.role === "admin" || user.value?.role === "operator",
  );
  const isAdmin = computed(() => user.value?.role === "admin");
  function cancelRestore() {
    restoreController?.abort();
    restoreController = undefined;
    pendingRestore = undefined;
  }
  function restore(): Promise<void> {
    if (restored.value) return Promise.resolve();
    if (pendingRestore) return pendingRestore;
    const savedToken = sessionStorage.getItem("logistics-token");
    if (!savedToken) {
      user.value = null;
      restored.value = true;
      restoreError.value = "";
      return Promise.resolve();
    }
    const request = new AbortController();
    restoreController = request;
    function isCurrent() {
      return (
        !request.signal.aborted &&
        sessionStorage.getItem("logistics-token") === savedToken
      );
    }
    pendingRestore = (async () => {
      try {
        const { data } = await api.get<User>("/auth/me", {
          signal: request.signal,
        });
        if (!isCurrent()) return;
        user.value = data;
        restored.value = true;
        restoreError.value = "";
      } catch (reason) {
        if (!isCurrent()) return;
        if (axios.isAxiosError(reason) && reason.response?.status === 401) {
          logout();
        } else {
          restored.value = false;
          restoreError.value = errorText(reason);
        }
      }
    })().finally(() => {
      if (restoreController === request) {
        restoreController = undefined;
        pendingRestore = undefined;
      }
    });
    return pendingRestore;
  }
  async function signIn(
    mode: "setup" | "login",
    payload: Record<string, string>,
  ) {
    const { data } = await api.post<{ access_token: string; user: User }>(
      `/auth/${mode}`,
      payload,
    );
    cancelRestore();
    sessionStorage.setItem("logistics-token", data.access_token);
    user.value = data.user;
    restored.value = true;
    restoreError.value = "";
  }
  function logout() {
    cancelRestore();
    sessionStorage.removeItem("logistics-token");
    user.value = null;
    restored.value = true;
    restoreError.value = "";
  }
  return {
    user,
    restored,
    restoreError,
    canOperate,
    isAdmin,
    restore,
    signIn,
    logout,
  };
});
