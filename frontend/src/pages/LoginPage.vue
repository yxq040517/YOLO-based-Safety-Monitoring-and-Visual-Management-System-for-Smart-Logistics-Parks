<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Aim, Lock, User as UserIcon, Right } from "@element-plus/icons-vue";
import { api, errorText } from "../api";
import { useAuth } from "../stores/auth";
const auth = useAuth();
const router = useRouter();
const route = useRoute();
const initialized = ref<boolean | null>(null);
const busy = ref(false);
const error = ref("");
const form = reactive({ username: "", password: "", display_name: "" });
async function check() {
  error.value = "";
  try {
    initialized.value = (
      await api.get<{ initialized: boolean }>("/auth/status")
    ).data.initialized;
  } catch (e) {
    error.value = errorText(e);
  }
}
async function submit() {
  if (auth.restoreError) {
    await reconnect();
    return;
  }
  if (initialized.value === null) return;
  if (
    !form.username.trim() ||
    !form.password ||
    (!initialized.value &&
      (!form.display_name.trim() || form.password.length < 10))
  ) {
    error.value = "请完整填写信息；初始管理员密码至少 10 个字符。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    const credentials = {
      username: form.username.trim(),
      password: form.password,
    };
    await auth.signIn(
      initialized.value ? "login" : "setup",
      initialized.value
        ? credentials
        : { ...credentials, display_name: form.display_name.trim() },
    );
    await router.replace(destination());
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
function destination() {
  const redirect = String(route.query.redirect || "/");
  return redirect.startsWith("/") && !redirect.startsWith("//")
    ? redirect
    : "/";
}
async function reconnect() {
  busy.value = true;
  error.value = "";
  try {
    await auth.restore();
    if (auth.restoreError) return;
    if (auth.user) await router.replace(destination());
    else await check();
  } catch (reason) {
    error.value = errorText(reason);
  } finally {
    busy.value = false;
  }
}
async function passwordLogin() {
  auth.logout();
  initialized.value = null;
  await check();
}
onMounted(() => {
  if (!auth.restoreError) void check();
});
</script>
<template>
  <div class="login-page">
    <section class="login-story">
      <div class="brand">
        <span class="brand-symbol"
          ><el-icon><Aim /></el-icon></span
        ><span>物流智安<small>LOGISTICS SAFETY</small></span>
      </div>
      <div class="login-message">
        <div class="eyebrow">看见风险，先行一步</div>
        <h1>让每一次流转<br />都有安全守护。</h1>
        <p>
          多目标视觉检测与业务闭环协同<br />构建可感知、可追溯的园区安全体系
        </p>
        <div class="login-features">
          <span>01 / 智能识别</span><span>02 / 实时监测</span
          ><span>03 / 闭环处置</span>
        </div>
      </div>
      <div class="login-grid-art">
        <div class="art-box box-one"></div>
        <div class="art-box box-two"></div>
        <div class="art-box box-three"></div>
        <span class="art-caption">VISION · INSIGHT · ACTION</span>
      </div>
    </section>
    <section class="login-form-pane">
      <form class="login-form" @submit.prevent="submit">
        <div class="eyebrow">欢迎进入安全监测中心</div>
        <h2>
          {{
            auth.restoreError
              ? "恢复登录连接"
              : initialized === false
                ? "创建初始管理员"
                : "登录工作空间"
          }}
        </h2>
        <p>
          {{
            auth.restoreError
              ? "上次登录信息仍保留，重新连接后可继续原来的页面。"
              : initialized === false
                ? "首次部署需要创建管理员。系统不提供默认账户。"
                : "使用您的园区账户继续工作。"
          }}
        </p>
        <template v-if="auth.restoreError">
          <el-alert
            :title="auth.restoreError"
            type="warning"
            :closable="false"
            show-icon
            class="mb"
          />
          <el-alert
            v-if="error"
            :title="error"
            type="error"
            :closable="false"
            show-icon
            class="mb"
          />
          <el-button
            type="primary"
            size="large"
            :loading="busy"
            class="login-submit"
            @click="reconnect"
            >重新连接并继续<el-icon><Right /></el-icon
          ></el-button>
          <el-button text :disabled="busy" @click="passwordLogin"
            >使用账号密码登录</el-button
          >
        </template>
        <template v-else>
          <el-alert
            v-if="error"
            :title="error"
            type="error"
            :closable="false"
            show-icon
            class="mb"
          /><el-skeleton
            v-if="initialized === null && !error"
            :rows="3"
            animated
          /><template v-if="initialized !== null"
            ><label class="field-label">账户名称</label
            ><el-input
              v-model="form.username"
              :prefix-icon="UserIcon"
              autocomplete="username"
              size="large"
              maxlength="80"
              placeholder="请输入账户名称"
            /><template v-if="!initialized"
              ><label class="field-label">显示名称</label
              ><el-input
                v-model="form.display_name"
                autocomplete="name"
                size="large"
                maxlength="80"
                placeholder="例如：园区管理员" /></template
            ><label class="field-label">密码</label
            ><el-input
              v-model="form.password"
              :prefix-icon="Lock"
              type="password"
              show-password
              :autocomplete="initialized ? 'current-password' : 'new-password'"
              size="large"
              :placeholder="initialized ? '请输入密码' : '至少 10 个字符'"
            /><el-button
              native-type="submit"
              type="primary"
              size="large"
              :loading="busy"
              class="login-submit"
              >{{ initialized ? "安全登录" : "创建管理员并进入"
              }}<el-icon><Right /></el-icon
            ></el-button>
            <p class="privacy-note">
              <el-icon><Lock /></el-icon> 登录凭据仅在当前浏览器会话保存
            </p></template
          ><el-button v-else-if="error" @click="check">重新连接服务</el-button>
        </template>
      </form>
    </section>
  </div>
</template>
