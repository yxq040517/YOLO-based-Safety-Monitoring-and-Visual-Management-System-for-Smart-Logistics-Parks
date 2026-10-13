import io
import json
import math
import subprocess
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .config import MAX_PIXELS

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
MAX_VIDEO_SECONDS = 4 * 3600
IMAGE_FORMATS = {
    "JPEG": {".jpg", ".jpeg"},
    "PNG": {".png"},
    "WEBP": {".webp"},
    "BMP": {".bmp"},
}
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def write_jpeg(path: Path, frame) -> None:
    import cv2

    ok, data = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError("标注图像编码失败")
    path.write_bytes(data.tobytes())


def inspect_image(source, suffix=None, jpeg_only=False):
    try:
        with Image.open(source) as image:
            width, height = image.size
            if width < 16 or height < 16 or width * height > MAX_PIXELS:
                raise ValueError("图像尺寸必须至少 16×16 且不超过 2400 万像素")
            if jpeg_only and image.format != "JPEG":
                raise ValueError("实时帧必须为 JPEG 格式")
            if image.format not in IMAGE_FORMATS or (
                suffix and suffix not in IMAGE_FORMATS[image.format]
            ):
                raise ValueError("图像实际编码与文件后缀不一致或不受支持")
            image.verify()
            return width, height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("图像无法解码或尺寸过大") from exc


def decode_jpeg(data):
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("单帧不得超过 2MB")
    inspect_image(io.BytesIO(data), jpeg_only=True)
    import cv2
    import numpy as np

    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("JPEG 帧解码失败")
    return frame


def validate_upload(path: Path, content_type: str):
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        if content_type not in {
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/bmp",
            "image/x-ms-bmp",
            "application/octet-stream",
        }:
            raise ValueError("文件 MIME 类型与图像不匹配")
        inspect_image(path, suffix=suffix)
        return "image"
    if suffix not in VIDEO_EXTENSIONS:
        raise ValueError("支持 JPG、PNG、WEBP、BMP、MP4、MOV、AVI、MKV 和 WEBM")
    if not (
        content_type.startswith("video/") or content_type == "application/octet-stream"
    ):
        raise ValueError("文件 MIME 类型与视频不匹配")
    # Disallow playlist/network formats and follow no external protocol references.
    magic = path.open("rb")
    try:
        header = magic.read(16)
    finally:
        magic.close()
    supported_magic = (
        header.startswith(b"\x1aE\xdf\xa3")
        or (header.startswith(b"RIFF") and header[8:12] == b"AVI ")
        or header[4:8] in {b"ftyp", b"moov", b"mdat", b"wide", b"free"}
    )
    if not supported_magic:
        raise ValueError("视频容器签名无效；不接受播放列表或远程引用文件")
    try:
        process = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,codec_type:format=duration,format_name",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            timeout=20,
            check=True,
        )
        metadata = json.loads(process.stdout)
        streams = metadata.get("streams", [])
        if not streams:
            raise ValueError("文件中没有视频轨道")
        width, height = streams[0].get("width", 0), streams[0].get("height", 0)
        if width < 16 or height < 16 or width * height > MAX_PIXELS:
            raise ValueError("视频画面尺寸超出限制（最大 2400 万像素）")
        try:
            duration = float(metadata.get("format", {}).get("duration"))
        except (TypeError, ValueError) as exc:
            raise ValueError("视频时长无效或缺失") from exc
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("视频时长无效或缺失")
        if duration > MAX_VIDEO_SECONDS:
            raise ValueError("单段视频不得超过四小时")
    except FileNotFoundError as exc:
        raise ValueError("服务器缺少 FFmpeg/ffprobe，请先安装并加入 PATH") from exc
    except (subprocess.SubprocessError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError("视频损坏或无法读取视频元数据") from exc
    return "video"
