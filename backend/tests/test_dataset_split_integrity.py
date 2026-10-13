import json
from pathlib import Path

import pytest
import yaml

import training


def _dataset(tmp_path: Path, filenames: dict[str, list[str]]) -> Path:
    for split, names in filenames.items():
        folder = "valid" if split == "val" else split
        images = tmp_path / folder / "images"
        labels = tmp_path / folder / "labels"
        images.mkdir(parents=True)
        labels.mkdir()
        for name in names:
            (images / name).write_bytes(b"image")
            (labels / f"{Path(name).stem}.txt").write_text("", encoding="utf-8")
    config = tmp_path / "data.yaml"
    config.write_text(
        yaml.safe_dump({"nc": 20, "names": list(training.EXPECTED_CLASSES)}),
        encoding="utf-8",
    )
    return config


def test_audit_detects_roboflow_original_across_splits_even_when_sampled(tmp_path):
    config = _dataset(
        tmp_path,
        {
            "train": ["shared_jpg.rf.111aaa.jpg", "train-only_jpg.rf.222bbb.jpg"],
            "val": ["shared_jpg.rf.333ccc.jpg", "valid-only_jpg.rf.444ddd.jpg"],
            "test": ["test-only_jpg.rf.555eee.jpg"],
        },
    )

    report = training.audit_dataset(
        config, sample_counts={"train": 1, "val": 1, "test": 1}
    )

    assert report["ok"] is False
    assert report["split_overlap"]["pair_counts"] == {
        "train_val": 1,
        "train_test": 0,
        "val_test": 0,
    }
    assert report["split_overlap"]["affected_images"] == {
        "train": 1,
        "val": 1,
        "test": 0,
    }
    assert report["split_overlap"]["examples"][0]["original_id"] == "shared_jpg"
    assert report["error_count"] >= 1


def test_audit_accepts_disjoint_roboflow_originals(tmp_path):
    config = _dataset(
        tmp_path,
        {
            "train": ["train_jpg.rf.111aaa.jpg"],
            "val": ["valid_jpg.rf.222bbb.jpg"],
            "test": ["test_jpg.rf.333ccc.jpg"],
        },
    )

    report = training.audit_dataset(config)

    assert report["ok"] is True
    assert report["split_overlap"]["pair_counts"] == {
        "train_val": 0,
        "train_test": 0,
        "val_test": 0,
    }


def test_training_rejects_cross_split_originals_before_loading_model(tmp_path):
    config = _dataset(
        tmp_path,
        {
            "train": ["same_jpg.rf.111aaa.jpg"],
            "val": ["same_jpg.rf.222bbb.jpg"],
            "test": ["different_jpg.rf.333ccc.jpg"],
        },
    )
    report = training.audit_dataset(config)

    with pytest.raises(ValueError, match="cross-split.*1"):
        training.require_split_integrity(report)


def test_grouped_lists_keep_all_variants_and_prefer_train_then_test(tmp_path):
    config = _dataset(
        tmp_path,
        {
            "train": ["shared_jpg.rf.111aaa.jpg", "train_jpg.rf.222bbb.jpg"],
            "val": [
                "shared_jpg.rf.333ccc.jpg",
                "test-shared_jpg.rf.444ddd.jpg",
                "valid_jpg.rf.555eee.jpg",
            ],
            "test": ["shared_jpg.rf.666fff.jpg", "test-shared_jpg.rf.777aaa.jpg"],
        },
    )
    _, directories = training.resolve_dataset(config)

    grouped = training.grouped_image_lists(directories)

    assert {split: len(images) for split, images in grouped.items()} == {
        "train": 4,
        "val": 1,
        "test": 2,
    }
    assert {path for images in grouped.values() for path in images} == {
        path for directory in directories.values() for path in training.image_files(directory)
    }
    assert training.image_list_overlap(grouped)["originals"] == 0


def test_grouped_mode_ignores_only_source_overlap_errors(tmp_path):
    config = _dataset(
        tmp_path,
        {
            "train": ["shared_jpg.rf.111aaa.jpg"],
            "val": ["shared_jpg.rf.222bbb.jpg"],
            "test": ["test_jpg.rf.333ccc.jpg"],
        },
    )
    report = training.audit_dataset(config)
    assert report["ok"] is False

    training.validate_source_audit(report, group_splits=True)
    with pytest.raises(ValueError, match="cross-split"):
        training.validate_source_audit(report, group_splits=False)
    report["error_count"] += 1
    with pytest.raises(ValueError, match="审计发现"):
        training.validate_source_audit(report, group_splits=True)


def test_grouped_lists_reject_empty_holdout_split(tmp_path):
    config = _dataset(
        tmp_path,
        {
            "train": ["shared_jpg.rf.111aaa.jpg"],
            "val": ["shared_jpg.rf.222bbb.jpg"],
            "test": ["test_jpg.rf.333ccc.jpg"],
        },
    )
    _, directories = training.resolve_dataset(config)
    grouped = training.grouped_image_lists(directories)

    with pytest.raises(ValueError, match="val.*empty"):
        training.require_image_list_integrity(grouped)


def test_resume_grouped_run_validates_saved_lists_not_source_dirs(tmp_path):
    source_config = _dataset(
        tmp_path / "source",
        {
            "train": ["same_jpg.rf.111aaa.jpg"],
            "val": ["same_jpg.rf.999aaa.jpg", "valid_jpg.rf.222bbb.jpg"],
            "test": ["test_jpg.rf.333ccc.jpg"],
        },
    )
    _, directories = training.resolve_dataset(source_config)
    grouped = training.grouped_image_lists(directories)
    run = tmp_path / "training" / "smoke" / "grouped"
    run.mkdir(parents=True)
    listings = {}
    for split, images in grouped.items():
        listing = run / f"{split}-images.txt"
        listing.write_text(
            "\n".join(image.as_posix() for image in images) + "\n",
            encoding="utf-8",
        )
        listings[split] = listing
    val_list = run / "val-images.txt"
    generated = run / "dataset.generated.yaml"
    generated.write_text(
        yaml.safe_dump(
            {split: listing.as_posix() for split, listing in listings.items()}
        ),
        encoding="utf-8",
    )
    config = {
        "options": {
            "data": str(source_config),
            "model": "yolo11n.pt",
            "epochs": 1,
            "batch": 2,
            "imgsz": 320,
            "workers": 0,
            "device": "cpu",
            "fraction": 1.0,
            "smoke": True,
            "smoke_images": 4,
            "group_splits": True,
        },
        "train_args": {},
        "dataset": {
            "generated_yaml": str(generated),
            "audit": str(run / "dataset-audit.json"),
            "sizes": {split: len(images) for split, images in grouped.items()},
            "paths": {split: str(path) for split, path in directories.items()},
            "split_policy": "original_id_train_test_val",
        },
        "files": {
            str(path): training.digest(path)
            for path in (*listings.values(), generated)
        },
    }
    (run / "run-config.json").write_text(json.dumps(config), encoding="utf-8")

    args = training.parser().parse_args(["--resume", "--name", run.name])
    training.restore_run(args, {"resume", "name"}, run)
    assert args.group_splits is True

    duplicate_source = directories["val"] / "same_jpg.rf.999aaa.jpg"
    val_list.write_text(duplicate_source.as_posix() + "\n", encoding="utf-8")
    config["files"][str(val_list)] = training.digest(val_list)
    (run / "run-config.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="cross-split"):
        training.restore_run(args, {"resume", "name"}, run)
