export const classes = [
  ["barcode", "条形码"],
  ["car", "小汽车"],
  ["cardboard box", "纸箱"],
  ["fire", "火焰"],
  ["forklift", "叉车"],
  ["freight container", "集装箱"],
  ["gloves", "手套"],
  ["helmet", "安全帽"],
  ["ladder", "梯子"],
  ["license plate", "车牌"],
  ["person", "人员"],
  ["qr code", "二维码"],
  ["road sign", "道路标志"],
  ["safety vest", "反光背心"],
  ["smoke", "烟雾"],
  ["traffic cone", "交通锥"],
  ["traffic light", "交通信号灯"],
  ["truck", "卡车"],
  ["van", "厢式货车"],
  ["wood pallet", "木托盘"],
] as const;
export const classLabel = (name: string) =>
  classes.find((c) => c[0] === name)?.[1] ?? name;
export const labels: Record<string, string> = {
  queued: "排队中",
  running: "检测中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  pending: "待复核",
  confirmed: "有效风险",
  false_positive: "误报",
  processing: "处理中",
  closed: "已处理",
  online: "在线",
  offline: "离线",
  connecting: "连接中",
  error: "异常",
  image: "图片",
  video: "视频",
  camera: "实时摄像头",
  admin: "管理员",
  operator: "操作员",
  viewer: "观察员",
  high: "高风险",
  medium: "中风险",
  low: "低风险",
  fire: "火焰",
  smoke: "烟雾",
  ppe: "疑似防护缺失",
  intrusion: "区域入侵",
  proximity: "人员车辆接近",
};
export const label = (key: string) => labels[key] ?? key;
export const dateTime = (value?: string | null) =>
  value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
export const elapsed = (value?: number | null) =>
  value == null ? "—" : `${(value / 1000).toFixed(2)} 秒`;
export const timestamp = (seconds?: number | null) =>
  seconds == null
    ? "—"
    : `${Math.floor(seconds / 60)
        .toString()
        .padStart(2, "0")}:${Math.floor(seconds % 60)
        .toString()
        .padStart(2, "0")}`;
export const activeJob = (status: string) =>
  status === "queued" || status === "running";
export const colorFor = (id: number) =>
  ["#19b6a1", "#e9a23b", "#668cf0", "#e46b76", "#8c79d9", "#37a6bf"][id % 6]!;
