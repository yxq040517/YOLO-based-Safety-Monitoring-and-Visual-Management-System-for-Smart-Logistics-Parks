<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { Plus } from "@element-plus/icons-vue";
import { api, errorText } from "../api";
import { label } from "../constants";
import { useAuth } from "../stores/auth";
import type { User } from "../types";
const auth = useAuth();
const users = ref<User[]>([]);
const loading = ref(false);
const error = ref("");
const dialog = ref(false);
const saving = ref(false);
const formError = ref("");
const editing = ref<User | null>(null);
const form = reactive({
  username: "",
  display_name: "",
  password: "",
  role: "viewer",
});
async function load() {
  loading.value = true;
  error.value = "";
  try {
    users.value = (await api.get<User[]>("/users")).data;
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}
function open(user?: User) {
  editing.value = user || null;
  Object.assign(form, {
    username: user?.username || "",
    display_name: user?.display_name || "",
    password: "",
    role: user?.role || "viewer",
  });
  formError.value = "";
  dialog.value = true;
}
async function save() {
  if (!form.display_name.trim() || (!editing.value && !form.username.trim())) {
    formError.value = "请填写账户名称与显示名称。";
    return;
  }
  if ((!editing.value || form.password) && form.password.length < 10) {
    formError.value = "密码至少 10 个字符。";
    return;
  }
  saving.value = true;
  formError.value = "";
  try {
    const payload: Record<string, string> = {
      display_name: form.display_name.trim(),
      role: form.role,
    };
    if (form.password) payload.password = form.password;
    if (editing.value) {
      const { data } = await api.patch<User>(
        `/users/${editing.value.id}`,
        payload,
      );
      if (data.id === auth.user?.id) auth.user = data;
    } else
      await api.post("/users", { ...payload, username: form.username.trim() });
    dialog.value = false;
    await load();
    ElMessage.success("用户信息已保存");
  } catch (e) {
    formError.value = errorText(e);
  } finally {
    saving.value = false;
  }
}
onMounted(load);
</script>
<template>
  <section class="panel">
    <div class="section-heading">
      <div>
        <h3>账户与权限</h3>
        <p>管理员：全部权限 · 操作员：检测与事件处置 · 观察员：只读访问</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="open()"
        >新增用户</el-button
      >
    </div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      class="mb"
    /><el-table v-loading="loading" :data="users" empty-text="暂无账户"
      ><el-table-column
        prop="display_name"
        label="显示名称"
        min-width="150"
      /><el-table-column
        prop="username"
        label="账户名称"
        min-width="150"
      /><el-table-column label="角色" width="120"
        ><template #default="{ row }"
          ><el-tag
            :type="row.role === 'admin' ? 'success' : 'info'"
            effect="light"
            >{{ label(row.role) }}</el-tag
          ></template
        ></el-table-column
      ><el-table-column label="操作" width="140"
        ><template #default="{ row }"
          ><el-button text type="primary" @click="open(row)"
            >编辑 / 重置密码</el-button
          ></template
        ></el-table-column
      ></el-table
    >
    <p class="hint">
      系统会保护最后一名管理员，禁止降级导致无人管理。角色变更和密码变更由服务端校验。
    </p>
  </section>
  <el-dialog
    v-model="dialog"
    :title="editing ? '编辑用户' : '新增用户'"
    width="480px"
    destroy-on-close
    ><el-alert
      v-if="formError"
      :title="formError"
      type="error"
      :closable="false"
      class="mb"
    /><el-form label-position="top"
      ><el-form-item label="账户名称"
        ><el-input
          v-model="form.username"
          :disabled="!!editing"
          maxlength="80"
          autocomplete="off" /></el-form-item
      ><el-form-item label="显示名称"
        ><el-input v-model="form.display_name" maxlength="80" /></el-form-item
      ><el-form-item label="角色"
        ><el-select v-model="form.role" class="full-width"
          ><el-option
            v-for="role in ['admin', 'operator', 'viewer']"
            :key="role"
            :value="role"
            :label="label(role)" /></el-select></el-form-item
      ><el-form-item
        :label="
          editing ? '新密码（留空保持不变）' : '初始密码（至少 10 个字符）'
        "
        ><el-input
          v-model="form.password"
          type="password"
          show-password
          autocomplete="new-password" /></el-form-item></el-form
    ><template #footer
      ><el-button @click="dialog = false">取消</el-button
      ><el-button type="primary" :loading="saving" @click="save"
        >保存用户</el-button
      ></template
    ></el-dialog
  >
</template>
