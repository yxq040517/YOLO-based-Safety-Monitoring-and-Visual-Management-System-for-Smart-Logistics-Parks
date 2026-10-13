from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dataset_audit import (
    EXPECTED_CLASSES,
    atomic_json,
    audit_dataset,
    grouped_image_lists,
    image_files,
    image_list_overlap,
    resolve_dataset,
    sample_images,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def numeric_metrics(values: dict | None) -> dict:
    output = {}
    for key, value in (values or {}).items():
        try:
            number = float(value)
            if math.isfinite(number):
                output[str(key)] = number
        except (ValueError, TypeError):
            continue
    return output


def evaluate_test_split(
    model_factory: Any,
    best: Path,
    generated_yaml: Path,
    *,
    device: str,
    batch: int,
    imgsz: int,
    workers: int,
) -> dict:
    """Evaluate the held-out test list with the best trained checkpoint."""
    evaluator = model_factory(str(best), task="detect")
    results = evaluator.val(
        data=str(generated_yaml),
        split="test",
        device=device,
        batch=batch,
        imgsz=imgsz,
        workers=workers,
        project=str(best.parent.parent),
        name="test-evaluation",
        exist_ok=True,
        plots=False,
    )
    metrics = numeric_metrics(getattr(results, "results_dict", None))
    if not any("mAP" in key for key in metrics):
        raise RuntimeError("test split evaluation returned no finite mAP; weights will not be deployed")
    return metrics


def require_split_integrity(report: dict) -> None:
    overlap = report["split_overlap"]
    if overlap["originals"]:
        raise ValueError(
            "cross-split original image leakage: "
            f"{overlap['originals']} original IDs overlap; "
            f"train/val={overlap['pair_counts']['train_val']}, "
            f"train/test={overlap['pair_counts']['train_test']}, "
            f"val/test={overlap['pair_counts']['val_test']}"
        )


def validate_source_audit(report: dict, group_splits: bool) -> None:
    if not group_splits:
        require_split_integrity(report)
    other_errors = report["error_count"] - report["split_overlap"]["originals"]
    if other_errors:
        raise ValueError(f"数据集审计发现 {other_errors} 个非划分重叠错误")


def require_image_list_integrity(image_lists: dict[str, list[Path]]) -> None:
    for split in ("train", "val", "test"):
        if not image_lists.get(split):
            raise ValueError(f"{split} image list is empty after split assignment")
    require_split_integrity({"split_overlap": image_list_overlap(image_lists)})


def copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as reader, temporary.open("wb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="使用项目真实物流 20 类数据集训练 YOLO；只有成功完成且具备验证指标的产物才可部署。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    command.add_argument(
        "--data", type=Path, default=PROJECT_ROOT / "物流数据集" / "data.yaml"
    )
    command.add_argument("--storage", type=Path, default=PROJECT_ROOT / "storage")
    command.add_argument(
        "--model", default="yolo11n.pt", help="训练起点；仅训练命令允许下载预训练权重"
    )
    command.add_argument(
        "--epochs", type=int, default=None, help="常规训练默认 100；--smoke 默认 1"
    )
    command.add_argument("--batch", type=int, default=4)
    command.add_argument("--imgsz", type=int, default=640)
    command.add_argument("--workers", type=int, default=0)
    command.add_argument(
        "--device", default="auto", help="auto 要求 CUDA；无 GPU 时显式使用 cpu"
    )
    command.add_argument(
        "--fraction",
        type=float,
        default=1.0,
        help="默认完整训练集；小于 1 为显式抽样训练",
    )
    command.add_argument(
        "--name", default=None, help="默认 logistics-时间戳；已有目录必须 --resume"
    )
    command.add_argument(
        "--resume",
        nargs="?",
        const="auto",
        default=None,
        help="恢复给定 last.pt；不提供路径时需 --name",
    )
    command.add_argument(
        "--check-images", action="store_true", help="审计时逐张解码检查损坏"
    )
    command.add_argument(
        "--group-splits",
        action="store_true",
        help="按原图标识重组运行专属图像列表；原文件保持不变，train > test > val",
    )
    command.add_argument(
        "--smoke",
        action="store_true",
        help="真实数据最小训练，使用隔离产物且默认不部署",
    )
    command.add_argument(
        "--smoke-images",
        type=int,
        default=12,
        help="冒烟训练图像数；valid/test 各最多 4 张",
    )
    command.add_argument(
        "--deploy-smoke",
        action="store_true",
        help="明确批准将冒烟产物部署；不能声称已充分训练",
    )
    return command


def restore_run(args: argparse.Namespace, explicit: set[str], run_dir: Path) -> dict:
    """Read and validate saved inputs before any run files can be changed."""
    import yaml

    config_path = run_dir / "run-config.json"
    saved_args_path = run_dir / "args.yaml"
    saved_args = (
        yaml.safe_load(saved_args_path.read_text(encoding="utf-8"))
        if saved_args_path.is_file()
        else {}
    )
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        # Older interrupted runs already have Ultralytics options and generated data.
        manifest_path = run_dir / "weights" / "manifest.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file()
            else {}
        )
        audit_path = run_dir / "dataset-audit.json"
        report = json.loads(audit_path.read_text(encoding="utf-8"))
        source = manifest.get("dataset", {}).get("source_yaml") or report.get(
            "dataset_yaml"
        )
        if not source or not saved_args:
            raise ValueError("无法恢复：缺少原始数据来源或训练参数，请创建新运行")
        generated_yaml = Path(saved_args["data"]).resolve()
        generated = yaml.safe_load(generated_yaml.read_text(encoding="utf-8"))
        sizes, files, paths = {}, {str(generated_yaml): digest(generated_yaml)}, {}
        for split in ("train", "val", "test"):
            listing = Path(generated[split])
            if not listing.is_file() or listing.suffix != ".txt":
                raise ValueError(
                    "旧运行未保存固定图像列表，无法保证恢复数据一致；请创建新运行"
                )
            sizes[split] = len(listing.read_text(encoding="utf-8").splitlines())
            files[str(listing)] = digest(listing)
            paths[split] = report["splits"][split]["images_path"]
        smoke = run_dir.parent.name == "smoke"
        config = {
            "options": {
                "data": source,
                "model": manifest.get("initial_model", saved_args["model"]),
                "smoke": smoke,
                "smoke_images": sizes["train"] if smoke else 12,
                "group_splits": False,
                **{
                    key: saved_args[key]
                    for key in (
                        "epochs",
                        "batch",
                        "imgsz",
                        "workers",
                        "device",
                        "fraction",
                    )
                },
            },
            "train_args": saved_args,
            "dataset": {
                "generated_yaml": str(generated_yaml),
                "sizes": sizes,
                "paths": paths,
                "audit": str(audit_path),
            },
            "files": files,
        }
    original = config["options"]
    # Resume always uses the policy and fixed lists saved by the original run.
    args.group_splits = original.get("group_splits", False)
    for key in ("data", "model", "epochs", "fraction", "smoke", "smoke_images"):
        value, saved = getattr(args, key), original[key]
        if key == "data":
            value, saved = Path(value).resolve(), Path(saved).resolve()
        if key in explicit and value != saved:
            raise ValueError(
                f"--resume 不允许修改 --{key.replace('_', '-')}；请创建新运行"
            )
        setattr(args, key, saved)
    for key in ("batch", "imgsz", "workers", "device"):
        if key not in explicit:
            setattr(args, key, saved_args.get(key, original[key]))
    for filename, expected in config["files"].items():
        path = Path(filename)
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"恢复所需数据配置或图像列表已丢失/被修改：{path}")
        if path.suffix == ".txt":
            for image in path.read_text(encoding="utf-8").splitlines():
                if not Path(image).is_file():
                    raise ValueError(f"恢复所需原始图像已丢失：{image}")
    generated = yaml.safe_load(
        Path(config["dataset"]["generated_yaml"]).read_text(encoding="utf-8")
    )
    if all(split in generated for split in ("train", "val", "test")):
        require_image_list_integrity(
            {
                split: [Path(image) for image in Path(generated[split]).read_text(encoding="utf-8").splitlines()]
                for split in ("train", "val", "test")
            }
        )
    elif args.group_splits:
        raise ValueError("分组划分运行缺少完整的已保存图像列表")
    return config


def main(argv: list[str] | None = None) -> int:
    command = parser()
    args = command.parse_args(argv)
    explicit_parser = parser()
    for action in explicit_parser._actions:
        action.default = argparse.SUPPRESS
    explicit = set(vars(explicit_parser.parse_args(argv)))
    if args.resume == "auto" and not args.name:
        command.error("无路径 --resume 需要 --name")
    storage = args.storage.resolve()
    training_root = storage / "training"
    resume_path = (
        Path(args.resume).resolve() if args.resume and args.resume != "auto" else None
    )
    name = args.name or (resume_path.parent.parent.name if resume_path else None)
    name = (
        name
        or f"logistics-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    )
    if (
        Path(name).name != name
        or any(char in name for char in "/\\:")
        or name in (".", "..")
    ):
        command.error("--name 只能是运行名称，不能包含路径")
    if args.resume and "smoke" not in explicit:
        if resume_path:
            args.smoke = resume_path.parent.parent.parent.name == "smoke"
        else:
            candidates = [
                root
                for root in ("runs", "smoke")
                if (training_root / root / name).is_dir()
            ]
            if len(candidates) != 1:
                command.error("无法唯一确定恢复目录；请明确提供 --resume 检查点路径")
            args.smoke = candidates[0] == "smoke"
    runs_root = training_root / ("smoke" if args.smoke else "runs")
    run_dir = runs_root / name
    if resume_path and resume_path != (run_dir / "weights" / "last.pt").resolve():
        command.error(
            "恢复路径必须属于同一 storage 下匹配的 runs/smoke 运行目录，并指向 weights/last.pt"
        )
    if run_dir.exists() and not args.resume:
        command.error(f"运行目录已存在，请更换 --name 或使用 --resume：{run_dir}")
    config = None
    checkpoint = (run_dir / "weights" / "last.pt") if args.resume else None
    if checkpoint:
        if not checkpoint.is_file():
            command.error(f"无法恢复，不存在检查点：{checkpoint}")
        try:
            config = restore_run(args, explicit, run_dir)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            command.error(f"无法恢复：{exc}")
    epochs = args.epochs if args.epochs is not None else (1 if args.smoke else 100)
    if epochs < 1 or args.batch < 1 or args.imgsz < 32 or args.workers < 0:
        command.error("epochs/batch 必须为正，imgsz 至少 32，workers 不能为负")
    if not 0 < args.fraction <= 1 or args.smoke_images < 1:
        command.error("fraction 必须在 (0, 1]；smoke-images 必须为正")
    if args.deploy_smoke and not args.smoke:
        command.error("--deploy-smoke 必须与 --smoke 一起使用")
    status_path = training_root / "status.json"
    production_weights = storage / "models" / "best.pt"
    lock_path = training_root / "training.lock"
    training_root.mkdir(parents=True, exist_ok=True)
    # OS advisory lock is released even after termination; a stale file is harmless.
    lock = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            if not lock.read(1):
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        print("已有训练进程运行；拒绝覆盖其状态。", file=sys.stderr)
        return 2
    state: dict[str, Any] = {
        "status": "running",
        "phase": "preparing",
        "started_at": utcnow(),
        "updated_at": utcnow(),
        "finished_at": None,
        "epoch": 0,
        "epochs": epochs,
        "progress": 0.0,
        "smoke": args.smoke,
        "run_dir": str(run_dir),
        "name": name,
        "device": args.device,
        "metrics": {},
        "error": None,
        "model": {
            "deployed": False,
            "weights": str(production_weights),
            "existing_weights": production_weights.exists(),
        },
    }
    model = None
    actual_run_dir = run_dir
    last_batch_write = 0.0
    batch_index = 0

    def publish(**updates: Any) -> None:
        state.update(updates)
        state["updated_at"] = utcnow()
        atomic_json(status_path, state)
        if actual_run_dir.is_dir():
            atomic_json(actual_run_dir / "status.json", state)

    def train_start(trainer: Any) -> None:
        nonlocal actual_run_dir
        actual_run_dir = Path(trainer.save_dir).resolve()
        publish(
            phase="training",
            run_dir=str(actual_run_dir),
            epochs=int(trainer.epochs),
            device=str(trainer.device),
            checkpoint=str(trainer.last),
        )

    def epoch_start(trainer: Any) -> None:
        nonlocal batch_index
        batch_index = 0
        publish(
            phase="training",
            epoch=int(trainer.epoch),
            epoch_in_progress=int(trainer.epoch) + 1,
            batch=0,
            batches=len(trainer.train_loader),
        )

    def batch_end(trainer: Any) -> None:
        nonlocal batch_index, last_batch_write
        batch_index += 1
        now = time.monotonic()
        if now - last_batch_write < 2:
            return
        last_batch_write = now
        batches = max(1, len(trainer.train_loader))
        progress = min(
            99.0, (trainer.epoch + batch_index / batches) / max(1, trainer.epochs) * 100
        )
        losses = numeric_metrics(
            trainer.label_loss_items(trainer.tloss, prefix="train")
        )
        publish(
            phase="training",
            batch=batch_index,
            batches=batches,
            progress=progress,
            losses=losses,
        )

    def epoch_end(trainer: Any) -> None:
        publish(
            phase="training",
            epoch=int(trainer.epoch) + 1,
            progress=min(99.0, (trainer.epoch + 1) / max(1, trainer.epochs) * 100),
            metrics=numeric_metrics(trainer.metrics),
            checkpoint=str(trainer.last),
            best_checkpoint=str(trainer.best),
        )

    def terminate(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt("termination requested")

    previous_sigterm = signal.signal(signal.SIGTERM, terminate)
    try:
        publish()
        run_dir.mkdir(parents=True, exist_ok=True)
        import torch
        import yaml
        from ultralytics import YOLO

        if args.device == "auto":
            if not torch.cuda.is_available():
                raise RuntimeError(
                    "当前 PyTorch 未检测到 CUDA。请安装匹配的 CUDA 版 PyTorch；若确需 CPU 训练，请显式指定 --device cpu。"
                )
            device = "0"
        else:
            device = args.device
        audit_path = run_dir / "dataset-audit.json"
        generated_yaml = run_dir / "dataset.generated.yaml"
        if config is not None:
            dataset = config["dataset"]
            generated_yaml, audit_path = (
                Path(dataset["generated_yaml"]),
                Path(dataset["audit"]),
            )
            report = json.loads(audit_path.read_text(encoding="utf-8"))
            directories = {
                split: Path(path) for split, path in dataset["paths"].items()
            }
            selected_sizes = dataset["sizes"]
        else:
            publish(phase="auditing", device=device)
            sample_counts = (
                {
                    "train": args.smoke_images,
                    "val": min(4, args.smoke_images),
                    "test": min(4, args.smoke_images),
                }
                if args.smoke and not args.group_splits
                else None
            )
            report = audit_dataset(
                args.data.resolve(),
                check_images=args.check_images,
                sample_counts=sample_counts,
            )
            atomic_json(audit_path, report)
            validate_source_audit(report, args.group_splits)
            _, directories = resolve_dataset(args.data.resolve())
            generated = {
                "path": str(args.data.resolve().parent),
                "nc": 20,
                "names": list(EXPECTED_CLASSES),
            }
            selected_sizes, input_files = {}, {str(audit_path): digest(audit_path)}
            source_lists = (
                grouped_image_lists(directories)
                if args.group_splits
                else {split: image_files(directory) for split, directory in directories.items()}
            )
            selected_lists = {}
            for split, images in source_lists.items():
                selected = images
                if args.smoke:
                    count = args.smoke_images if split == "train" else min(4, args.smoke_images)
                    selected = sample_images(selected, count)
                selected_lists[split] = selected
            require_image_list_integrity(selected_lists)
            for split, selected in selected_lists.items():
                listing = run_dir / f"{split}-images.txt"
                listing.write_text(
                    "\n".join(path.resolve().as_posix() for path in selected) + "\n",
                    encoding="utf-8",
                )
                generated[split] = listing.resolve().as_posix()
                selected_sizes[split] = len(selected)
                input_files[str(listing)] = digest(listing)
            generated_yaml.write_text(
                yaml.safe_dump(generated, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            input_files[str(generated_yaml)] = digest(generated_yaml)
        publish(
            phase="loading",
            device=device,
            generated_data=str(generated_yaml),
            audit_path=str(audit_path),
            selected_sizes=selected_sizes,
            dataset_sizes={
                split: info["images"] for split, info in report["splits"].items()
            },
        )
        model = YOLO(str(checkpoint) if checkpoint else args.model, task="detect")
        model.add_callback("on_train_start", train_start)
        model.add_callback("on_train_epoch_start", epoch_start)
        model.add_callback("on_train_batch_end", batch_end)
        model.add_callback("on_fit_epoch_end", epoch_end)
        training_args = {
            "data": str(generated_yaml),
            "epochs": epochs,
            "batch": args.batch,
            "imgsz": args.imgsz,
            "workers": args.workers,
            "device": device,
            "fraction": args.fraction,
            "project": str(runs_root),
            "name": name,
            "exist_ok": True,
            "save": True,
            "save_period": 1,
            "plots": False,
            "val": True,
            "cache": False,
            "seed": 0,
            "deterministic": True,
            "amp": device != "cpu",
            "close_mosaic": 0 if args.smoke else 10,
        }
        if checkpoint:
            # The checkpoint restores immutable optimizer/data/epoch settings itself.
            training_args = {
                "resume": str(checkpoint),
                "data": str(generated_yaml),
                "batch": args.batch,
                "imgsz": args.imgsz,
                "workers": args.workers,
                "device": device,
            }
            if not (run_dir / "run-config.json").is_file():
                atomic_json(run_dir / "run-config.json", config)
        else:
            atomic_json(
                run_dir / "run-config.json",
                {
                    "schema_version": 1,
                    "options": {
                        "data": str(args.data.resolve()),
                        "model": args.model,
                        "epochs": epochs,
                        "batch": args.batch,
                        "imgsz": args.imgsz,
                        "workers": args.workers,
                        "device": device,
                        "fraction": args.fraction,
                        "smoke": args.smoke,
                        "smoke_images": args.smoke_images,
                        "group_splits": args.group_splits,
                    },
                    "train_args": training_args,
                    "files": input_files,
                    "dataset": {
                        "generated_yaml": str(generated_yaml),
                        "audit": str(audit_path),
                        "sizes": selected_sizes,
                        "paths": {
                            split: str(path.resolve())
                            for split, path in directories.items()
                        },
                        "split_policy": "original_id_train_test_val" if args.group_splits else "source",
                    },
                },
            )
        results = model.train(**training_args)
        trainer = model.trainer
        actual_run_dir = Path(trainer.save_dir).resolve()
        best = Path(trainer.best).resolve()
        if not best.is_file():
            raise RuntimeError("训练没有产生 best.pt，不会部署任何权重")
        metrics = numeric_metrics(getattr(results, "results_dict", None))
        if not metrics or not any("mAP" in key for key in metrics):
            raise RuntimeError("训练没有返回真实验证 mAP 指标，不会部署权重")
        actual_names = model.names
        actual_names = (
            [actual_names[index] for index in sorted(actual_names)]
            if isinstance(actual_names, dict)
            else list(actual_names)
        )
        if actual_names != list(EXPECTED_CLASSES):
            raise RuntimeError("训练产物类别顺序错误，不会部署权重")
        test_metrics = None
        if args.group_splits:
            publish(phase="testing", metrics=metrics)
            test_metrics = evaluate_test_split(
                YOLO,
                best,
                generated_yaml,
                device=device,
                batch=args.batch,
                imgsz=args.imgsz,
                workers=args.workers,
            )
            publish(test_metrics=test_metrics)
        actual_args = vars(trainer.args)
        hyperparameters = {
            key: actual_args.get(key)
            for key in (
                "epochs",
                "batch",
                "imgsz",
                "workers",
                "device",
                "fraction",
                "seed",
                "deterministic",
                "optimizer",
                "lr0",
                "lrf",
                "momentum",
                "weight_decay",
                "patience",
                "amp",
                "close_mosaic",
            )
        }
        manifest = {
            "schema_version": 1,
            "artifact_type": "trained",
            "class_names": list(EXPECTED_CLASSES),
            "smoke": args.smoke,
            "deployment_approved": not args.smoke or args.deploy_smoke,
            "finished_at": utcnow(),
            "started_at": state["started_at"],
            "weights_sha256": digest(best),
            "weights_size": best.stat().st_size,
            "source_checkpoint": str(best),
            "initial_model": args.model,
            "resumed_from": str(checkpoint) if checkpoint else None,
            "dataset": {
                "source_yaml": str(args.data.resolve()),
                "generated_yaml": str(generated_yaml),
                "paths": {
                    split: str(directory.resolve())
                    for split, directory in directories.items()
                },
                "sizes": selected_sizes,
                "full_sizes": {
                    split: item["images"] for split, item in report["splits"].items()
                },
                "audit": str(audit_path),
                "split_policy": "original_id_train_test_val" if args.group_splits else "source",
            },
            "hyperparameters": hyperparameters,
            "metrics": metrics,
            "test_metrics": test_metrics,
            "epochs_completed": int(trainer.epoch) + 1,
            "validation_split": "val",
            "torch_version": str(torch.__version__),
        }
        import ultralytics

        manifest["ultralytics_version"] = ultralytics.__version__
        atomic_json(best.with_name("manifest.json"), manifest)
        deploy = not args.smoke or args.deploy_smoke
        if deploy:
            publish(phase="deploying")
            from app.inference import artifact_lock

            with artifact_lock(storage):
                copy_atomic(best, production_weights)
                atomic_json(production_weights.with_name("manifest.json"), manifest)
        publish(
            status="completed",
            phase="completed",
            finished_at=utcnow(),
            progress=100.0,
            metrics=metrics,
            test_metrics=test_metrics,
            epoch=int(trainer.epoch) + 1,
            artifact=str(best),
            manifest=str(best.with_name("manifest.json")),
            model={
                "deployed": deploy,
                "weights": str(production_weights if deploy else best),
                "smoke": args.smoke,
                "deployment_approved": manifest["deployment_approved"],
            },
        )
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    except BaseException as exc:
        interrupted = isinstance(exc, (KeyboardInterrupt, SystemExit))
        checkpoint_path = actual_run_dir / "weights" / "last.pt"
        publish(
            status="failed",
            phase="interrupted" if interrupted else "failed",
            finished_at=utcnow(),
            interrupted=interrupted,
            error="训练被中断；已完成 epoch 的检查点予以保留，可使用 --resume 恢复。"
            if interrupted
            else str(exc),
            checkpoint=str(checkpoint_path) if checkpoint_path.exists() else None,
        )
        print(json.dumps(state, ensure_ascii=False, indent=2), file=sys.stderr)
        return 130 if interrupted else 1
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
