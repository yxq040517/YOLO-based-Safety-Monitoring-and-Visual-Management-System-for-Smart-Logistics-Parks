from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
ROBOFLOW_VARIANT = re.compile(r"\.rf\.[0-9a-f]+$", re.IGNORECASE)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_dataset(config: Path) -> tuple[dict, dict[str, Path]]:
    import yaml

    config = config.resolve()
    original = yaml.safe_load(config.read_text(encoding="utf-8-sig"))
    if not isinstance(original, dict):
        raise ValueError("data.yaml 必须是映射")
    names = original.get("names", [])
    if isinstance(names, dict):
        names = [names[key] for key in sorted(names, key=lambda key: int(key))]
    if original.get("nc") != 20 or list(names) != list(EXPECTED_CLASSES):
        raise ValueError("data.yaml 必须包含原始物流数据集的准确 20 类顺序")
    # The Roboflow export contains ../train relative paths. Resolve the actual
    # project-local split directories without ever rewriting the original YAML.
    directories = {
        split: config.parent / folder / "images"
        for split, folder in (("train", "train"), ("val", "valid"), ("test", "test"))
    }
    for split, directory in directories.items():
        if not directory.is_dir() or not directory.with_name("labels").is_dir():
            raise ValueError(f"缺少 {split} 图像或标签目录：{directory}")
    return original, directories


def image_files(directory: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ),
        key=lambda path: path.name.casefold(),
    )


def sample_images(images: list[Path], count: int | None) -> list[Path]:
    if count is None or count >= len(images):
        return images
    if count < 1:
        raise ValueError("样本数量必须大于 0")
    return [images[index * len(images) // count] for index in range(count)]


def original_image_id(image: Path) -> str:
    """Group Roboflow variants by their source filename, not export hash."""
    return ROBOFLOW_VARIANT.sub("", image.stem).casefold()


def image_list_overlap(image_lists: dict[str, list[Path]]) -> dict:
    """Check that no source image identity appears in more than one list."""
    originals = {split: {} for split in ("train", "val", "test")}
    for split, images in image_lists.items():
        for image in images:
            originals[split].setdefault(original_image_id(image), []).append(image)

    pairs = (("train", "val"), ("train", "test"), ("val", "test"))
    pair_counts = {
        f"{left}_{right}": len(originals[left].keys() & originals[right].keys())
        for left, right in pairs
    }
    shared_ids = set().union(
        *(originals[left].keys() & originals[right].keys() for left, right in pairs)
    )
    affected_images = {
        split: sum(len(paths) for original, paths in groups.items() if original in shared_ids)
        for split, groups in originals.items()
    }
    examples = [
        {
            "original_id": original,
            "images": {
                split: [str(path) for path in originals[split].get(original, [])[:3]]
                for split in originals
                if original in originals[split]
            },
        }
        for original in sorted(shared_ids)[:20]
    ]
    return {
        "originals": len(shared_ids),
        "pair_counts": pair_counts,
        "affected_images": affected_images,
        "examples": examples,
        "examples_truncated": len(shared_ids) > len(examples),
    }


def cross_split_overlap(directories: dict[str, Path]) -> dict:
    """Inspect every source image, including those omitted by a sampled label audit."""
    return image_list_overlap(
        {split: image_files(directory) for split, directory in directories.items()}
    )


def grouped_image_lists(directories: dict[str, Path]) -> dict[str, list[Path]]:
    """Assign every source variant to one split using train > test > val."""
    source = {split: image_files(directory) for split, directory in directories.items()}
    owner = {}
    for split in ("val", "test", "train"):
        for image in source[split]:
            owner[original_image_id(image)] = split
    grouped = {split: [] for split in ("train", "val", "test")}
    for images in source.values():
        for image in images:
            grouped[owner[original_image_id(image)]].append(image)
    for images in grouped.values():
        images.sort(key=lambda path: path.as_posix().casefold())
    return grouped


def audit_dataset(
    config: Path,
    check_images: bool = False,
    max_errors: int = 100,
    sample_counts: dict[str, int] | None = None,
) -> dict:
    original, directories = resolve_dataset(config)
    issues: list[dict] = []
    error_count = 0
    totals = Counter()
    split_reports = {}

    def issue(split: str, path: Path, message: str, line: int | None = None) -> None:
        nonlocal error_count
        error_count += 1
        if len(issues) < max_errors:
            record = {"split": split, "path": str(path), "message": message}
            if line is not None:
                record["line"] = line
            issues.append(record)

    for split, directory in directories.items():
        images = image_files(directory)
        labels_dir = directory.with_name("labels")
        labels = sorted(labels_dir.glob("*.txt"))
        selected = sample_images(
            images, sample_counts.get(split) if sample_counts else None
        )
        selected_stems = {path.stem for path in selected}
        image_stems = {path.stem for path in images}
        label_stems = {path.stem for path in labels}
        class_counts = Counter()
        backgrounds = 0
        annotation_count = 0
        duplicate_stems = Counter(path.stem.casefold() for path in images)
        for stem, number in duplicate_stems.items():
            if number > 1:
                issue(
                    split,
                    directory / stem,
                    "图像名称不区分大小写时重复，或多种后缀共用标签",
                )
        if not images:
            issue(split, directory, "图像目录为空")
        missing = selected_stems - label_stems
        orphan = label_stems - image_stems
        for stem in sorted(missing):
            issue(split, labels_dir / f"{stem}.txt", "缺少对应标签文件")
        for stem in sorted(orphan):
            issue(split, labels_dir / f"{stem}.txt", "标签没有对应图像")
        for image in selected:
            if "\n" in image.name or "\r" in image.name:
                issue(split, image, "文件名含换行符，无法写入 YOLO 图像列表")
            label = labels_dir / f"{image.stem}.txt"
            if label.exists():
                try:
                    lines = label.read_text(encoding="utf-8-sig").splitlines()
                except (OSError, UnicodeError) as exc:
                    issue(split, label, f"无法读取标签：{exc}")
                    lines = []
                nonempty = False
                for number, line in enumerate(lines, start=1):
                    if not line.strip():
                        continue
                    nonempty = True
                    fields = line.split()
                    try:
                        if len(fields) != 5:
                            raise ValueError(
                                "检测标签必须为 class x_center y_center width height 共 5 列"
                            )
                        values = [float(value) for value in fields]
                        if not all(math.isfinite(value) for value in values):
                            raise ValueError("坐标或类别含非有限数值")
                        cls, x, y, width, height = values
                        if not cls.is_integer() or not 0 <= cls < 20:
                            raise ValueError("类别编号超出 0..19 或不是整数")
                        if (
                            not 0 <= x <= 1
                            or not 0 <= y <= 1
                            or not 0 < width <= 1
                            or not 0 < height <= 1
                        ):
                            raise ValueError("归一化坐标应在 0..1，宽高必须大于 0")
                        if (
                            min(x - width / 2, y - height / 2) < -1e-5
                            or max(x + width / 2, y + height / 2) > 1 + 1e-5
                        ):
                            raise ValueError("标注框超出图像边界")
                        class_counts[EXPECTED_CLASSES[int(cls)]] += 1
                        annotation_count += 1
                    except ValueError as exc:
                        issue(split, label, str(exc), number)
                if not nonempty:
                    backgrounds += 1
            if check_images:
                try:
                    from PIL import Image

                    with Image.open(image) as opened:
                        opened.verify()
                    with Image.open(image) as opened:
                        opened.load()
                        if opened.width < 1 or opened.height < 1:
                            raise ValueError("图像没有有效尺寸")
                except Exception as exc:
                    issue(split, image, f"图像损坏或无法解码：{exc}")
        totals.update(class_counts)
        split_reports[split] = {
            "images_path": str(directory.resolve()),
            "labels_path": str(labels_dir.resolve()),
            "images": len(images),
            "labels": len(labels),
            "audited_images": len(selected),
            "missing_labels": len(missing),
            "orphan_labels": len(orphan),
            "background_images": backgrounds,
            "annotations": annotation_count,
            "class_counts": {name: class_counts[name] for name in EXPECTED_CLASSES},
        }
    split_overlap = cross_split_overlap(directories)
    error_count += split_overlap["originals"]
    for example in split_overlap["examples"]:
        if len(issues) >= max_errors:
            break
        first_split = next(iter(example["images"]))
        issues.append(
            {
                "split": first_split,
                "path": example["images"][first_split][0],
                "message": f"Original image {example['original_id']} appears in multiple splits",
            }
        )
    return {
        "ok": error_count == 0,
        "dataset_yaml": str(config.resolve()),
        "original_paths": {split: original.get(split) for split in directories},
        "class_names": list(EXPECTED_CLASSES),
        "splits": split_reports,
        "split_overlap": split_overlap,
        "sampled": sample_counts is not None,
        "corruption_checked": check_images,
        "class_counts": {name: totals[name] for name in EXPECTED_CLASSES},
        "error_count": error_count,
        "errors": issues,
        "errors_truncated": error_count > len(issues),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="审计真实物流数据集，不修改原始图片、标签或 data.yaml"
    )
    parser.add_argument(
        "--data", type=Path, default=PROJECT_ROOT / "物流数据集" / "data.yaml"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "storage" / "training" / "dataset-audit.json",
    )
    parser.add_argument(
        "--check-images", action="store_true", help="逐张解码检查图像损坏（较慢）"
    )
    parser.add_argument("--max-errors", type=int, default=100)
    args = parser.parse_args(argv)
    if args.max_errors < 1:
        parser.error("--max-errors 必须大于 0")
    try:
        report = audit_dataset(args.data, args.check_images, args.max_errors)
    except Exception as exc:
        report = {
            "ok": False,
            "error_count": 1,
            "error": str(exc),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    atomic_json(args.output.resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
