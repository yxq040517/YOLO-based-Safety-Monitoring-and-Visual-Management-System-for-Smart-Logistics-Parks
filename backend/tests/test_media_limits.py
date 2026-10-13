import json
import shutil
import subprocess

import pytest
from app import inference, media


@pytest.mark.parametrize("duration", [None, "0", "-1", "NaN", "Infinity", "not-a-number"])
def test_upload_rejects_unusable_video_duration(tmp_path, monkeypatch, duration):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16)
    metadata = {"streams": [{"width": 32, "height": 32}], "format": {}}
    if duration is not None:
        metadata["format"]["duration"] = duration

    def probe(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, json.dumps(metadata).encode(), b"")

    monkeypatch.setattr(media.subprocess, "run", probe)
    with pytest.raises(ValueError, match="时长"):
        media.validate_upload(source, "video/mp4")


def test_upload_accepts_positive_duration_within_limit(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16)
    metadata = {
        "streams": [{"width": 32, "height": 32}],
        "format": {"duration": "14399.5"},
    }
    monkeypatch.setattr(
        media.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, json.dumps(metadata).encode(), b""
        ),
    )
    assert media.validate_upload(source, "video/mp4") == "video"


def test_processing_stops_when_decoded_frames_exceed_time_limit(tmp_path, monkeypatch):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for the video processing integration test")
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=32x32:r=10:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        capture_output=True,
    )

    class Detector:
        def detect(self, frame, confidence, classes, tracker_id):
            return {"detections": [], "width": 32, "height": 32}

        def reset_tracker(self, tracker_id):
            pass

    monkeypatch.setattr(
        inference,
        "_probe",
        lambda path: {"width": 32, "height": 32, "fps": 10, "duration": 0.1},
    )
    monkeypatch.setattr(inference, "MAX_VIDEO_SECONDS", 0.2, raising=False)
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="时长"):
        inference.process_file(
            Detector(), source, "video", output, 0.5, None,
            lambda progress: None, lambda: False, lambda result, frame, seconds: None,
        )
    assert not list(output.iterdir())
