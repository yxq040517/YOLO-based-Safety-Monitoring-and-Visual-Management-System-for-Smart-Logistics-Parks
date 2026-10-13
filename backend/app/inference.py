from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from .media import MAX_VIDEO_SECONDS, write_jpeg

EXPECTED_CLASSES = (
    "barcode",
    "car",
    "cardboard box",
    "fire",
    "forklift",
    "freight container",
    "gloves",
    "helmet",
    "ladder",
    "license plate",
    "person",
    "qr code",
    "road sign",
    "safety vest",
    "smoke",
    "traffic cone",
    "traffic light",
    "truck",
    "van",
    "wood pallet",
)
_ENGINE_LOCK = threading.RLock()
_MAX_PIXELS = 40_000_000
_MAX_RETAINED_DETECTIONS = 2000


class ModelUnavailableError(RuntimeError):
    pass


class InferenceCancelled(RuntimeError):
    pass


def _names(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(value[k]) for k in sorted(value, key=lambda key: int(key))]
    return list(value) if isinstance(value, (list, tuple)) else []


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def artifact_lock(storage: Path):
    """Serialize model readers and paired artifact publication across processes."""
    path = Path(storage).resolve() / "runtime" / "gpu.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _ENGINE_LOCK, path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class Detector:
    """One serialized YOLO predictor, with independently owned ByteTrack state per source."""

    def __init__(self, weights: Path):
        self.weights = Path(weights).resolve()
        self.manifest_path = self.weights.with_name("manifest.json")
        self.device = os.environ.get("INFERENCE_DEVICE", "auto")
        self._model = None
        self._fingerprint = None
        self._trackers: dict[str, Any] = {}
        self._smoke = False
        storage = (
            self.weights.parent.parent
            if self.weights.parent.name == "models"
            else Path(
                os.environ.get(
                    "STORAGE_DIR", str(Path(__file__).resolve().parents[2] / "storage")
                )
            )
        )
        self._storage = storage.resolve()

    def _ensure_model(self) -> None:
        try:
            weight_stat = self.weights.stat()
            manifest_stat = self.manifest_path.stat()
            fingerprint = (
                weight_stat.st_mtime_ns,
                weight_stat.st_size,
                weight_stat.st_ino,
                manifest_stat.st_mtime_ns,
                manifest_stat.st_size,
                manifest_stat.st_ino,
            )
            if self._model is not None and fingerprint == self._fingerprint:
                return
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if manifest.get("artifact_type") != "trained":
                raise ValueError("模型元数据不是已训练产物")
            if (
                manifest.get("smoke")
                and not manifest.get("deployment_approved")
                and self.weights.parent.name == "models"
            ):
                raise ValueError("冒烟训练产物未获准部署至生产模型目录")
            if _names(manifest.get("class_names")) != list(EXPECTED_CLASSES):
                raise ValueError("模型元数据类别与物流数据集的 20 类不一致")
            if not manifest.get("finished_at") or not manifest.get("metrics"):
                raise ValueError("缺少真实训练完成时间或验证指标")
            if manifest.get("weights_size") != weight_stat.st_size:
                raise ValueError("模型文件大小与训练清单不匹配，请等待部署完成")
            if manifest.get("weights_sha256") != _sha256(self.weights):
                raise ValueError("模型校验和与训练清单不匹配，请等待部署完成")
            import torch
            from ultralytics import YOLO

            device = self.device
            if device == "auto":
                device = "0" if torch.cuda.is_available() else "cpu"
            candidate = YOLO(str(self.weights), task="detect")
            if candidate.task != "detect" or _names(candidate.names) != list(
                EXPECTED_CLASSES
            ):
                raise ValueError("权重本身不是物流 20 类检测模型，拒绝使用通用模型")
            # Check that no deployment replaced the files during load.
            current_weight, current_manifest = (
                self.weights.stat(),
                self.manifest_path.stat(),
            )
            current = (
                current_weight.st_mtime_ns,
                current_weight.st_size,
                current_weight.st_ino,
                current_manifest.st_mtime_ns,
                current_manifest.st_size,
                current_manifest.st_ino,
            )
            if current != fingerprint:
                raise ValueError("模型正在更新，请重试")
            self._model = candidate
            self.device = device
            self._fingerprint = fingerprint
            self._trackers.clear()
            self._smoke = bool(manifest.get("smoke"))
        except ModelUnavailableError:
            raise
        except Exception as exc:
            raise ModelUnavailableError(
                f"物流检测模型不可用：{exc}。请先运行真实数据集训练。"
            ) from exc

    def status(self) -> dict:
        training = None
        status_file = self._storage / "training" / "status.json"
        try:
            training = json.loads(status_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        with artifact_lock(self._storage):
            try:
                self._ensure_model()
                ready, message = True, "物流 20 类训练模型已就绪"
                if self._smoke:
                    message = (
                        "真实数据冒烟训练模型，仅用于链路验证，不代表检测质量已达标"
                    )
            except ModelUnavailableError as exc:
                ready, message = False, str(exc)
            return {
                "ready": ready,
                "weights": str(self.weights) if self.weights.exists() else None,
                "device": self.device,
                "classes": list(EXPECTED_CLASSES),
                "training": training,
                "message": message,
            }

    def detect(
        self,
        frame: Any,
        confidence: float = 0.35,
        classes: list[int] | None = None,
        tracker_id: str | None = None,
    ) -> dict:
        import numpy as np

        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("检测输入必须为 BGR 三通道图像")
        height, width = frame.shape[:2]
        if (
            height < 1
            or width < 1
            or height * width > _MAX_PIXELS
            or frame.dtype != np.uint8
        ):
            raise ValueError("图像尺寸或像素格式无效")
        if not math.isfinite(confidence) or not 0 < confidence <= 1:
            raise ValueError("置信度必须大于 0 且不超过 1")
        if classes and any(
            type(c) is not int or not 0 <= c < len(EXPECTED_CLASSES) for c in classes
        ):
            raise ValueError("类别编号必须为 0 至 19")
        started = time.perf_counter()
        with artifact_lock(self._storage):
            self._ensure_model()
            prediction = self._model.predict(
                source=frame,
                conf=min(confidence, 0.1) if tracker_id else confidence,
                classes=classes or None,
                device=self.device,
                verbose=False,
                max_det=300,
            )[0]
            boxes = prediction.boxes.cpu().numpy()
            track_ids: dict[int, int] = {}
            if tracker_id:
                from ultralytics.trackers.byte_tracker import BYTETracker

                tracker = self._trackers.get(tracker_id)
                if tracker is None:
                    # BYTETracker.__init__ normally resets a global counter, corrupting
                    # IDs in other sources. Keep a global monotonic counter instead.
                    class SourceTracker(BYTETracker):
                        @staticmethod
                        def reset_id():
                            pass

                    tracker = SourceTracker(
                        SimpleNamespace(
                            track_high_thresh=0.25,
                            track_low_thresh=0.1,
                            new_track_thresh=0.25,
                            track_buffer=30,
                            match_thresh=0.8,
                            fuse_score=True,
                        ),
                        frame_rate=30,
                    )
                    self._trackers[tracker_id] = tracker
                tracks = tracker.update(boxes, frame)
                track_ids = {int(row[-1]): int(row[4]) for row in tracks}
            detections = []
            for index, (box, score, cls) in enumerate(
                zip(boxes.xyxy, boxes.conf, boxes.cls)
            ):
                if float(score) < confidence:
                    continue
                class_id = int(cls)
                detections.append(
                    {
                        "class_id": class_id,
                        "class_name": EXPECTED_CLASSES[class_id],
                        "confidence": float(score),
                        "box": [float(v) for v in box],
                        "track_id": track_ids.get(index),
                    }
                )
        return {
            "width": width,
            "height": height,
            "detections": detections,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "timestamp": time.time(),
        }

    def reset_tracker(self, tracker_id: str) -> None:
        with _ENGINE_LOCK:
            self._trackers.pop(tracker_id, None)


def _annotate(frame: Any, detections: list[dict]) -> Any:
    import cv2

    image = frame.copy()
    for detection in detections:
        x1, y1, x2, y2 = [int(round(v)) for v in detection["box"]]
        cls = detection["class_id"]
        color = (40, 60, 235) if cls in (3, 14) else (90, 215, 35)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        label = f"{detection['class_name']} {detection['confidence']:.2f}"
        if detection["track_id"] is not None:
            label += f" #{detection['track_id']}"
        cv2.putText(
            image,
            label,
            (max(0, x1), max(16, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )
    return image


def _probe(source: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("未找到 FFprobe，请安装 FFmpeg 并加入 PATH")
    command = [
        ffprobe,
        "-v",
        "error",
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        "mov,matroska,avi,mpegts,mpeg,asf,flv,ogg",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration:format=duration",
        "-of",
        "json",
        str(source),
    ]
    result = subprocess.run(command, capture_output=True, timeout=45, check=False)
    if result.returncode:
        raise ValueError(
            "无法读取视频：" + result.stderr.decode("utf-8", errors="replace")[-2000:]
        )
    data = json.loads(result.stdout)
    if not data.get("streams"):
        raise ValueError("文件中没有视频流")
    stream = data["streams"][0]
    width, height = int(stream["width"]), int(stream["height"])
    if not width or not height or width * height > _MAX_PIXELS:
        raise ValueError("视频分辨率超过安全上限")
    fps = 0.0
    for rate in (stream.get("avg_frame_rate"), stream.get("r_frame_rate")):
        try:
            numerator, denominator = str(rate).split("/")
            fps = float(numerator) / float(denominator)
            if math.isfinite(fps) and fps > 0:
                break
        except (ValueError, ZeroDivisionError):
            continue
    if not math.isfinite(fps) or not 0 < fps <= 240:
        raise ValueError("视频帧率无效或超过 240 FPS")
    try:
        duration = float(
            stream.get("duration") or data.get("format", {}).get("duration") or 0
        )
    except ValueError:
        duration = 0.0
    return {
        "width": width,
        "height": height,
        "fps": fps,
        "duration": duration if math.isfinite(duration) else 0.0,
    }


def process_file(
    detector: Detector,
    source: Path,
    kind: str,
    output_dir: Path,
    confidence: float,
    classes: list[int] | None,
    progress: Callable[[float], None],
    should_cancel: Callable[[], bool],
    on_frame: Callable[[dict, Any, float], None],
) -> dict:
    """Stream media and JSONL; the response sample is bounded, counts are exhaustive."""
    import cv2
    import numpy as np

    if kind not in ("image", "video"):
        raise ValueError("文件检测仅支持图像或视频")
    source, output_dir = Path(source).resolve(), Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    result_path = output_dir / f"{token}.{'jpg' if kind == 'image' else 'mp4'}"
    preview_path = output_dir / f"{token}-preview.jpg"
    jsonl_path = output_dir / "frames.jsonl"
    json_path = output_dir / "result.json"
    created = [result_path, preview_path, jsonl_path, json_path]
    tracker_id = f"file:{token}"
    started = time.perf_counter()
    counts: Counter = Counter()
    retained: list[dict] = []
    frames = 0
    best_preview = -1
    processes: list[subprocess.Popen] = []
    stop_monitor = threading.Event()
    cancel_seen = threading.Event()
    errors: list[Any] = []
    monitor = None

    def check_cancel() -> None:
        if cancel_seen.is_set() or should_cancel():
            raise InferenceCancelled("检测任务已取消")

    def monitor_cancel() -> None:
        while not stop_monitor.wait(0.2):
            if should_cancel():
                cancel_seen.set()
                for process in list(processes):
                    if process.poll() is None:
                        try:
                            process.kill()
                        except OSError:
                            pass
                return

    def process_frame(frame: Any, seconds: float, stream: Any) -> Any:
        nonlocal frames, best_preview
        check_cancel()
        result = detector.detect(
            frame, confidence, classes, tracker_id if kind == "video" else None
        )
        result["timestamp"] = seconds
        on_frame(result, frame, seconds)
        check_cancel()
        detections = result["detections"]
        counts.update(item["class_name"] for item in detections)
        remaining = _MAX_RETAINED_DETECTIONS - len(retained)
        if remaining > 0:
            retained.extend(detections[:remaining])
        stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
        annotated = _annotate(frame, detections)
        if len(detections) > best_preview:
            write_jpeg(preview_path, annotated)
            best_preview = len(detections)
        frames += 1
        return annotated

    try:
        check_cancel()
        progress(0.0)
        with jsonl_path.open("w", encoding="utf-8") as stream:
            if kind == "image":
                from PIL import Image

                with Image.open(source) as header:
                    if header.width * header.height > _MAX_PIXELS:
                        raise ValueError("图像分辨率超过安全上限")
                frame = cv2.imdecode(
                    np.fromfile(str(source), dtype=np.uint8), cv2.IMREAD_COLOR
                )
                if frame is None:
                    raise ValueError("无法解码图像")
                height, width = frame.shape[:2]
                write_jpeg(result_path, process_frame(frame, 0.0, stream))
            else:
                ffmpeg = shutil.which("ffmpeg")
                if not ffmpeg:
                    raise RuntimeError("未找到 FFmpeg，无法生成浏览器兼容的 H.264 视频")
                info = _probe(source)
                width, height, fps = info["width"], info["height"], info["fps"]
                if info["duration"] > MAX_VIDEO_SECONDS:
                    raise ValueError("单段视频不得超过四小时")
                decode_log, encode_log = (
                    tempfile.TemporaryFile(),
                    tempfile.TemporaryFile(),
                )
                errors.extend([decode_log, encode_log])
                decoder = subprocess.Popen(
                    [
                        ffmpeg,
                        "-nostdin",
                        "-v",
                        "error",
                        "-protocol_whitelist",
                        "file,pipe",
                        "-format_whitelist",
                        "mov,matroska,avi,mpegts,mpeg,asf,flv,ogg",
                        "-noautorotate",
                        "-i",
                        str(source),
                        "-map",
                        "0:v:0",
                        "-an",
                        "-vf",
                        f"fps={fps:.9f}",
                        "-f",
                        "rawvideo",
                        "-pix_fmt",
                        "bgr24",
                        "pipe:1",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=decode_log,
                )
                processes.append(decoder)
                encoder = subprocess.Popen(
                    [
                        ffmpeg,
                        "-nostdin",
                        "-y",
                        "-v",
                        "error",
                        "-f",
                        "rawvideo",
                        "-pix_fmt",
                        "bgr24",
                        "-s",
                        f"{width}x{height}",
                        "-r",
                        f"{fps:.9f}",
                        "-i",
                        "pipe:0",
                        "-an",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "23",
                        "-pix_fmt",
                        "yuv420p",
                        "-vf",
                        "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                        "-movflags",
                        "+faststart",
                        str(result_path),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=encode_log,
                )
                processes.append(encoder)
                monitor = threading.Thread(
                    target=monitor_cancel, name=f"cancel-{token}", daemon=True
                )
                monitor.start()
                frame_bytes = width * height * 3
                buffer = bytearray(frame_bytes)
                view = memoryview(buffer)
                while True:
                    check_cancel()
                    offset = 0
                    while offset < frame_bytes:
                        read = decoder.stdout.readinto(view[offset:])
                        if not read:
                            break
                        offset += read
                    if offset == 0:
                        break
                    if offset != frame_bytes:
                        check_cancel()
                        raise ValueError("视频解码得到不完整帧")
                    if frames / fps >= MAX_VIDEO_SECONDS:
                        raise ValueError("视频解码时长超过四小时")
                    frame = np.frombuffer(buffer, dtype=np.uint8).reshape(
                        height, width, 3
                    )
                    annotated = process_frame(frame, frames / fps, stream)
                    encoder.stdin.write(memoryview(annotated))
                    if info["duration"] > 0:
                        progress(min(99.0, frames / fps / info["duration"] * 100))
                    else:
                        progress(min(95.0, frames / (frames + 100) * 95))
                encoder.stdin.close()
                decoder.stdout.close()
                decode_code = decoder.wait(timeout=60)
                encode_code = encoder.wait(timeout=120)
                check_cancel()
                if decode_code or encode_code:
                    messages = []
                    for log in (decode_log, encode_log):
                        log.seek(0, os.SEEK_END)
                        log.seek(max(0, log.tell() - 8192))
                        messages.append(log.read().decode("utf-8", errors="replace"))
                    raise RuntimeError("FFmpeg 视频处理失败：" + " ".join(messages))
                if not frames:
                    raise ValueError("视频没有可解码的画面")
        check_cancel()
        summary = {
            "result_path": str(result_path),
            "preview_path": str(preview_path),
            "json_path": str(json_path),
            "frames_path": str(jsonl_path),
            "width": width,
            "height": height,
            "detections": retained,
            "counts": dict(counts),
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "frames": frames,
            "observations_total": sum(counts.values()),
            "detections_truncated": sum(counts.values()) > len(retained),
        }
        json_path.write_text(
            json.dumps(summary, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        progress(100.0)
        return summary
    except BaseException as exc:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait()
        for path in created:
            path.unlink(missing_ok=True)
        if cancel_seen.is_set() and not isinstance(exc, InferenceCancelled):
            raise InferenceCancelled("检测任务已取消") from exc
        raise
    finally:
        stop_monitor.set()
        if monitor is not None:
            monitor.join(timeout=2)
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait()
            for handle in (process.stdin, process.stdout):
                if handle is not None and not handle.closed:
                    try:
                        handle.close()
                    except OSError:
                        # A killed FFmpeg process can invalidate its pipe on Windows.
                        pass
        for log in errors:
            log.close()
        detector.reset_tracker(tracker_id)
