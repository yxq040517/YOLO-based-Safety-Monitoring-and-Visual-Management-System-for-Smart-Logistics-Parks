export interface User {
  id: number;
  username: string;
  display_name: string;
  role: "admin" | "operator" | "viewer";
}
export interface Detection {
  class_id: number;
  class_name: string;
  confidence: number;
  box: [number, number, number, number];
  track_id: number | null;
}
export interface SafetyEvent {
  id: string;
  job_id: string | null;
  camera_id: number | null;
  rule_type: string;
  severity: string;
  title: string;
  status: string;
  created_at: string;
  timestamp_seconds: number | null;
  snapshot_url: string | null;
  note: string;
  history: {
    status: string;
    note: string;
    username: string;
    created_at: string;
  }[];
}
export interface Job {
  id: string;
  kind: "image" | "video" | "camera";
  filename: string;
  status: string;
  progress: number;
  created_at: string;
  completed_at: string | null;
  error: string | null;
  confidence: number;
  source_url: string | null;
  result_url: string | null;
  preview_url: string | null;
  detections: Detection[];
  counts: Record<string, number>;
  events: SafetyEvent[];
  duration_ms: number | null;
  width: number;
  height: number;
}
export interface Frame {
  width: number;
  height: number;
  detections: Detection[];
  duration_ms: number;
  timestamp: number;
  events?: SafetyEvent[];
  error?: string;
}
export interface Camera {
  id: number;
  name: string;
  source: string;
  zone: string;
  status: string;
  error: string | null;
  created_at: string;
}
export interface ModelInfo {
  ready: boolean;
  weights: string | null;
  device: string;
  classes: string[];
  training: Record<string, unknown> | null;
  message: string;
}
export interface Settings {
  confidence: number;
  event_cooldown_seconds: number;
  consecutive_frames: number;
  enable_fire: boolean;
  enable_smoke: boolean;
  enable_ppe: boolean;
  enable_intrusion: boolean;
  enable_proximity: boolean;
  proximity_ratio: number;
  zone_polygon: [number, number][];
}
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export interface Dashboard {
  total_jobs: number;
  completed_jobs: number;
  active_jobs: number;
  total_detections: number;
  open_events: number;
  cameras_online: number;
  class_counts: { name: string; count: number }[];
  daily: { date: string; jobs: number; events: number }[];
  recent_events: SafetyEvent[];
  recent_jobs: Job[];
}
