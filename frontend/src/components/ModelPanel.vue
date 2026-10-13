<script setup lang="ts">
import { computed } from "vue";
import { classes, dateTime } from "../constants";
import type { ModelInfo } from "../types";
const props = defineProps<{
  model: ModelInfo | null;
  loading: boolean;
  error: string;
}>();
const emit = defineEmits<{ refresh: [] }>();
const stages: Record<string, string> = {
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  preparing: "准备数据",
  auditing: "数据审计",
  loading: "加载模型",
  training: "正在训练",
  deploying: "部署权重",
  interrupted: "已中断",
};
const metrics = computed(() => {
  const value = props.model?.training?.metrics;
  return value && typeof value === "object" ? Object.entries(value) : [];
});
const metricLabel: Record<string, string> = {
  "metrics/precision(B)": "精确率 Precision",
  "metrics/recall(B)": "召回率 Recall",
  "metrics/mAP50(B)": "mAP@0.50",
  "metrics/mAP50-95(B)": "mAP@0.50:0.95",
};
</script>
<template>
  <section class="panel">
    <div class="section-heading">
      <div>
        <h3>检测模型与训练状态</h3>
        <p>仅使用项目真实训练权重，不回退到通用模型</p>
      </div>
      <el-button :loading="loading" @click="emit('refresh')"
        >刷新模型状态</el-button
      >
    </div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      class="mb"
    /><template v-if="model"
      ><div class="model-summary">
        <div class="model-ready" :class="{ unready: !model.ready }">
          <span class="status-dot" :class="{ warning: !model.ready }"></span
          >{{ model.ready ? "检测模型已就绪" : "检测模型尚未就绪" }}
        </div>
        <div class="model-device">
          推理设备 <strong>{{ model.device }}</strong>
        </div>
      </div>
      <p class="hint">{{ model.message }}</p>
      <div class="weight-path">
        <span>部署权重</span
        ><code>{{ model.weights || "尚无已部署权重" }}</code>
      </div>
      <div v-if="model.training" class="training-status">
        <div class="section-heading">
          <h3>最近训练运行</h3>
          <span class="panel-kicker">{{
            stages[String(model.training.phase || model.training.status)] ||
            String(model.training.phase || model.training.status || "未知")
          }}</span>
        </div>
        <el-alert
          v-if="model.training.smoke"
          title="当前为真实小规模冒烟训练，仅证明训练链路，不等同于经过质量评估的生产模型。"
          type="warning"
          :closable="false"
          class="mb"
        /><el-alert
          v-if="model.training.error"
          :title="String(model.training.error)"
          type="error"
          :closable="false"
          class="mb"
        /><el-progress
          v-if="typeof model.training.progress === 'number'"
          :percentage="
            Math.max(
              0,
              Math.min(100, Number(model.training.progress.toFixed(1))),
            )
          "
          :status="
            model.training.status === 'failed'
              ? 'exception'
              : model.training.status === 'completed'
                ? 'success'
                : undefined
          "
        />
        <div class="detail-facts">
          <span
            >训练轮次<b
              >{{ model.training.epoch ?? "—" }} /
              {{ model.training.epochs ?? "—" }}</b
            ></span
          ><span
            >当前批次<b
              >{{ model.training.batch ?? "—" }} /
              {{ model.training.batches ?? "—" }}</b
            ></span
          ><span
            >训练设备<b>{{ model.training.device ?? "—" }}</b></span
          ><span
            >更新时间<b>{{
              dateTime(
                typeof model.training.updated_at === "string"
                  ? model.training.updated_at
                  : null,
              )
            }}</b></span
          >
        </div>
        <div v-if="metrics.length" class="training-metrics">
          <div v-for="[key, value] in metrics" :key="key">
            <span>{{ metricLabel[key] || key }}</span
            ><strong>{{
              typeof value === "number" ? value.toFixed(4) : String(value)
            }}</strong>
          </div>
        </div>
        <details class="technical-details">
          <summary>查看训练原始状态与数据集规模</summary>
          <pre>{{ JSON.stringify(model.training, null, 2) }}</pre>
        </details>
      </div>
      <el-empty
        v-else
        description="尚无训练状态记录。请由服务器管理员运行真实数据集训练流程。"
        :image-size="65"
      />
      <div class="section-heading mt">
        <h3>物流目标类别</h3>
        <span class="muted">数据集定义 · 20 类</span>
      </div>
      <div class="taxonomy-grid">
        <div v-for="(item, index) in classes" :key="item[0]">
          <span>{{ String(index).padStart(2, "0") }}</span
          ><strong>{{ item[1] }}</strong
          ><small>{{ item[0] }}</small>
        </div>
      </div>
      <p class="hint">
        安全帽、反光背心与手套是检测类别，而“疑似防护缺失”由规则推断；类别预测不能直接证明违规事实。训练指标应结合独立测试集和实际园区场景评估。
      </p></template
    ><el-skeleton v-else-if="loading" :rows="6" animated />
  </section>
</template>
