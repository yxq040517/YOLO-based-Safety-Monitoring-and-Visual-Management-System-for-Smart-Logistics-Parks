<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { api, errorText } from "../api";
import { usePolling } from "../composables";
import { useAuth } from "../stores/auth";
import type { Settings, ModelInfo } from "../types";
import ZoneEditor from "../components/ZoneEditor.vue";
import UserManagement from "../components/UserManagement.vue";
import ModelPanel from "../components/ModelPanel.vue";
const auth = useAuth();
const tab = ref("rules");
const settings = ref<Settings | null>(null);
const model = ref<ModelInfo | null>(null);
const error = ref("");
const loading = ref(false);
const saving = ref(false);
const zoneError = ref("");
const {
  loading: modelLoading,
  error: modelError,
  refresh: refreshModel,
} = usePolling(async () => {
  model.value = (await api.get<ModelInfo>("/model")).data;
}, 10000);
async function load() {
  loading.value = true;
  error.value = "";
  try {
    settings.value = (await api.get<Settings>("/settings")).data;
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}
async function save() {
  if (!settings.value || !auth.isAdmin) return;
  if (zoneError.value) {
    error.value = zoneError.value;
    return;
  }
  if (
    settings.value.enable_intrusion &&
    settings.value.zone_polygon.length < 3
  ) {
    error.value = "启用区域入侵前，请设置至少三个顶点的有效全局区域。";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    settings.value = (
      await api.put<Settings>("/settings", settings.value)
    ).data;
    ElMessage.success(
      "规则已保存，将用于新任务。请重新启动正在运行的摄像头 / 实时会话以应用新规则。",
    );
  } catch (e) {
    error.value = errorText(e);
  } finally {
    saving.value = false;
  }
}
onMounted(load);
</script>
<template>
  <el-tabs v-model="tab" class="workspace-tabs"
    ><el-tab-pane label="检测与事件规则" name="rules" /><el-tab-pane
      label="模型与训练"
      name="model" /><el-tab-pane
      v-if="auth.isAdmin"
      label="账户与权限"
      name="users"
  /></el-tabs>
  <div v-if="tab === 'rules'">
    <el-alert
      v-if="!auth.isAdmin"
      title="当前为只读模式，修改系统规则需要管理员权限。"
      type="info"
      :closable="false"
      class="mb"
    /><el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      class="mb"
    /><el-skeleton v-if="loading" :rows="10" animated /><template
      v-else-if="settings"
      ><div class="settings-grid">
        <section class="panel">
          <div class="section-heading">
            <h3>基础检测策略</h3>
            <span class="panel-kicker">DETECTION</span>
          </div>
          <el-form label-position="top" :disabled="!auth.isAdmin || saving"
            ><el-form-item label="默认置信度阈值"
              ><el-slider
                v-model="settings.confidence"
                :min="0.05"
                :max="0.95"
                :step="0.05"
                show-input /></el-form-item
            ><el-form-item label="同类事件冷却时间（秒）"
              ><el-input-number
                v-model="settings.event_cooldown_seconds"
                :min="1"
                :max="3600"
                :step="5" /></el-form-item
            ><el-form-item label="连续触发帧数"
              ><el-input-number
                v-model="settings.consecutive_frames"
                :min="1"
                :max="120" /></el-form-item
            ><el-form-item label="人员车辆接近阈值（相对画面比例）"
              ><el-slider
                v-model="settings.proximity_ratio"
                :min="0.01"
                :max="0.5"
                :step="0.01"
                show-input /></el-form-item
          ></el-form>
          <p class="hint">
            视频与实时流通过连续帧与冷却时间控制重复告警。接近阈值为图像尺度比例，不具备米制距离意义。
          </p>
        </section>
        <section class="panel">
          <div class="section-heading">
            <h3>安全规则开关</h3>
            <span class="panel-kicker">EVENT RULES</span>
          </div>
          <div class="rule-switch">
            <div>
              <strong>火焰识别</strong>
              <p>检测到火焰目标时产生安全事件</p>
            </div>
            <el-switch
              v-model="settings.enable_fire"
              :disabled="!auth.isAdmin || saving"
            />
          </div>
          <div class="rule-switch">
            <div>
              <strong>烟雾识别</strong>
              <p>烟雾目标持续出现时提示人工核实</p>
            </div>
            <el-switch
              v-model="settings.enable_smoke"
              :disabled="!auth.isAdmin || saving"
            />
          </div>
          <div class="rule-switch">
            <div>
              <strong>疑似防护缺失</strong>
              <p>结合人员与安全帽 / 背心检测作启发式判断</p>
            </div>
            <el-switch
              v-model="settings.enable_ppe"
              :disabled="!auth.isAdmin || saving"
            />
          </div>
          <div class="rule-switch">
            <div>
              <strong>区域入侵</strong>
              <p>固定视角下人员进入全局配置区域</p>
            </div>
            <el-switch
              v-model="settings.enable_intrusion"
              :disabled="!auth.isAdmin || saving"
            />
          </div>
          <div class="rule-switch">
            <div>
              <strong>人员车辆接近</strong>
              <p>画面中的人员车辆相对接近提示</p>
            </div>
            <el-switch
              v-model="settings.enable_proximity"
              :disabled="!auth.isAdmin || saving"
            />
          </div>
          <el-alert
            title="疑似防护缺失可能因遮挡或漏检产生误报，所有事件均需人工研判。"
            type="warning"
            :closable="false"
            class="mt"
          />
        </section>
      </div>
      <section class="panel mt">
        <div class="section-heading">
          <h3>固定视角安全区域</h3>
          <span class="muted">归一化坐标 · 不绑定单个来源</span>
        </div>
        <ZoneEditor
          v-model="settings.zone_polygon"
          v-model:error="zoneError"
          :disabled="!auth.isAdmin || saving"
        />
      </section>
      <div class="settings-save">
        <span class="muted"
          >配置保存后由服务端应用；已提交文件任务保留其提交参数。</span
        ><el-button :loading="loading" :disabled="saving" @click="load"
          >重新加载</el-button
        ><el-button
          v-if="auth.isAdmin"
          type="primary"
          :disabled="!!zoneError"
          :loading="saving"
          @click="save"
          >保存规则配置</el-button
        >
      </div></template
    ><el-button v-else @click="load">重新加载配置</el-button>
  </div>
  <ModelPanel
    v-else-if="tab === 'model'"
    :model="model"
    :loading="modelLoading"
    :error="modelError"
    @refresh="refreshModel"
  /><UserManagement v-else-if="tab === 'users' && auth.isAdmin" />
</template>
