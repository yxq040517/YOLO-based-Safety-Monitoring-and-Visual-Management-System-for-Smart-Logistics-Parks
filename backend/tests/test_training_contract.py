import hashlib
import json
import multiprocessing
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml

import training
from app.inference import artifact_lock


def test_test_split_evaluation_uses_best_checkpoint_and_separate_metrics(tmp_path):
    best = tmp_path / "best.pt"
    best.write_bytes(b"best weights")
    generated = tmp_path / "dataset.generated.yaml"
    generated.write_text("test: test-images.txt\n", encoding="utf-8")
    calls = {}

    class Evaluator:
        def val(self, **kwargs):
            calls["val"] = kwargs
            return SimpleNamespace(results_dict={"metrics/mAP50(B)": 0.61, "loss": float("nan")})

    def factory(checkpoint, task):
        calls["checkpoint"] = checkpoint
        calls["task"] = task
        return Evaluator()

    metrics = training.evaluate_test_split(
        factory, best, generated, device="cpu", batch=2, imgsz=320, workers=0
    )

    assert calls["checkpoint"] == str(best)
    assert calls["task"] == "detect"
    assert calls["val"]["data"] == str(generated)
    assert calls["val"]["split"] == "test"
    assert metrics == {"metrics/mAP50(B)": 0.61}


@pytest.mark.parametrize("raw_metrics", [{}, {"metrics/mAP50(B)": float("nan")}])
def test_test_split_evaluation_rejects_missing_finite_map(tmp_path, raw_metrics):
    class Evaluator:
        def val(self, **kwargs):
            return SimpleNamespace(results_dict=raw_metrics)

    with pytest.raises(RuntimeError, match="test.*mAP"):
        training.evaluate_test_split(
            lambda checkpoint, task: Evaluator(),
            tmp_path / "best.pt",
            tmp_path / "dataset.generated.yaml",
            device="cpu",
            batch=2,
            imgsz=320,
            workers=0,
        )


def _fake_grouped_training(tmp_path, monkeypatch, *, test_score):
    dataset = tmp_path / "dataset"
    for split, filenames in {
        "train": ["shared_jpg.rf.111aaa.jpg"],
        "valid": ["shared_jpg.rf.222bbb.jpg", "valid_jpg.rf.333ccc.jpg"],
        "test": ["test_jpg.rf.444ddd.jpg"],
    }.items():
        images = dataset / split / "images"
        labels = dataset / split / "labels"
        images.mkdir(parents=True)
        labels.mkdir()
        for filename in filenames:
            (images / filename).write_bytes(b"image")
            (labels / f"{Path(filename).stem}.txt").write_text("", encoding="utf-8")
    data_yaml = dataset / "data.yaml"
    data_yaml.write_text(
        yaml.safe_dump({"nc": 20, "names": list(training.EXPECTED_CLASSES)}),
        encoding="utf-8",
    )
    calls = {}

    class FakeYOLO:
        def __init__(self, checkpoint, task):
            self.names = list(training.EXPECTED_CLASSES)
            calls.setdefault("checkpoints", []).append(checkpoint)

        def add_callback(self, name, callback):
            pass

        def train(self, **kwargs):
            run_dir = Path(kwargs["project"]) / kwargs["name"]
            best = run_dir / "weights" / "best.pt"
            best.parent.mkdir(parents=True, exist_ok=True)
            best.write_bytes(b"trained best checkpoint")
            self.trainer = SimpleNamespace(
                save_dir=run_dir, best=best, epoch=0, args=SimpleNamespace()
            )
            return SimpleNamespace(results_dict={"metrics/mAP50(B)": 0.72})

        def val(self, **kwargs):
            calls["test_val"] = kwargs
            if isinstance(test_score, Exception):
                raise test_score
            return SimpleNamespace(results_dict={"metrics/mAP50(B)": test_score})

    fake_module = ModuleType("ultralytics")
    fake_module.YOLO = FakeYOLO
    fake_module.__version__ = "test"
    monkeypatch.setitem(sys.modules, "ultralytics", fake_module)
    return data_yaml, calls


def test_grouped_run_persists_test_metrics_separately(tmp_path, monkeypatch):
    data_yaml, calls = _fake_grouped_training(tmp_path, monkeypatch, test_score=0.43)
    storage = tmp_path / "storage"

    code = training.main(
        ["--data", str(data_yaml), "--storage", str(storage), "--device", "cpu",
         "--name", "grouped-test", "--smoke", "--epochs", "1", "--group-splits"]
    )

    assert code == 0
    run_dir = storage / "training" / "smoke" / "grouped-test"
    manifest = json.loads((run_dir / "weights" / "manifest.json").read_text(encoding="utf-8"))
    status = json.loads((storage / "training" / "status.json").read_text(encoding="utf-8"))
    assert manifest["metrics"]["metrics/mAP50(B)"] == 0.72
    assert manifest["test_metrics"]["metrics/mAP50(B)"] == 0.43
    assert status["metrics"]["metrics/mAP50(B)"] == 0.72
    assert status["test_metrics"]["metrics/mAP50(B)"] == 0.43
    assert calls["checkpoints"][-1] == str(run_dir / "weights" / "best.pt")
    assert calls["test_val"]["split"] == "test"


def test_grouped_run_does_not_deploy_when_test_evaluation_fails(tmp_path, monkeypatch):
    data_yaml, _ = _fake_grouped_training(
        tmp_path, monkeypatch, test_score=RuntimeError("test evaluator failed")
    )
    storage = tmp_path / "storage"

    code = training.main(
        ["--data", str(data_yaml), "--storage", str(storage), "--device", "cpu",
         "--name", "grouped-test", "--epochs", "1", "--group-splits"]
    )

    assert code == 1
    status = json.loads((storage / "training" / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert "test evaluator failed" in status["error"]
    assert not (storage / "models" / "best.pt").exists()
    assert not (storage / "training" / "runs" / "grouped-test" / "weights" / "manifest.json").exists()


@pytest.fixture
def saved_run(tmp_path):
    run = tmp_path / "training" / "smoke" / "原始运行"
    run.mkdir(parents=True)
    image = tmp_path / "原始图片.jpg"
    image.write_bytes(b"original input")
    listing = run / "train-images.txt"
    listing.write_text(image.as_posix() + "\n", encoding="utf-8")
    generated = run / "dataset.generated.yaml"
    generated.write_text(
        yaml.safe_dump({"train": listing.as_posix()}), encoding="utf-8"
    )
    options = {
        "data": str(tmp_path / "data.yaml"),
        "model": "yolo11n.pt",
        "epochs": 8,
        "batch": 2,
        "imgsz": 320,
        "workers": 1,
        "device": "cpu",
        "fraction": 0.25,
        "smoke": True,
        "smoke_images": 6,
    }
    config = {
        "options": options,
        "train_args": {},
        "dataset": {"generated_yaml": str(generated)},
        "files": {str(path): training.digest(path) for path in (listing, generated)},
    }
    (run / "run-config.json").write_text(json.dumps(config), encoding="utf-8")
    return run, config, listing, generated


def test_resume_reuses_original_selection_and_training_options(saved_run):
    run, config, listing, generated = saved_run
    args = training.parser().parse_args(["--resume", "--name", run.name])
    before = {path: path.read_bytes() for path in (listing, generated)}
    restored = training.restore_run(args, {"resume", "name"}, run)
    assert (args.batch, args.imgsz, args.workers, args.epochs) == (2, 320, 1, 8)
    assert (args.fraction, args.smoke_images, args.smoke, args.device) == (
        0.25,
        6,
        True,
        "cpu",
    )
    assert restored["dataset"] == config["dataset"]
    assert all(path.read_bytes() == content for path, content in before.items())
    override = training.parser().parse_args(["--batch", "1", "--imgsz", "384"])
    training.restore_run(override, {"batch", "imgsz"}, run)
    assert (override.batch, override.imgsz, override.fraction) == (1, 384, 0.25)


@pytest.mark.parametrize(
    "option,value",
    [
        ("data", "different.yaml"),
        ("fraction", "1"),
        ("smoke_images", "12"),
        ("epochs", "100"),
    ],
)
def test_resume_rejects_changed_immutable_inputs_without_overwriting(
    saved_run, option, value
):
    run, _, listing, generated = saved_run
    before = {path: path.read_bytes() for path in (listing, generated)}
    args = training.parser().parse_args(["--" + option.replace("_", "-"), value])
    with pytest.raises(ValueError, match="--resume"):
        training.restore_run(args, {option}, run)
    assert all(path.read_bytes() == content for path, content in before.items())


def test_resume_rejects_modified_cached_selection(saved_run):
    run, _, listing, _ = saved_run
    listing.write_text("replacement.jpg\n", encoding="utf-8")
    with pytest.raises(ValueError, match="已丢失/被修改"):
        training.restore_run(training.parser().parse_args([]), set(), run)


def _read_pair(storage, attempting, result):
    attempting.set()
    with artifact_lock(Path(storage)):
        model = Path(storage) / "models"
        result.put(
            hashlib.sha256((model / "best.pt").read_bytes()).hexdigest()
            == json.loads((model / "manifest.json").read_text())["weights_sha256"]
        )


def test_artifact_reader_waits_for_complete_pair(tmp_path):
    model = tmp_path / "models"
    model.mkdir()
    (model / "manifest.json").write_text(json.dumps({"weights_sha256": "old"}))
    context = multiprocessing.get_context("spawn")
    attempting, result = context.Event(), context.Queue()
    process = context.Process(
        target=_read_pair, args=(str(tmp_path), attempting, result)
    )
    try:
        with artifact_lock(tmp_path):
            weights = b"new trained artifact"
            (model / "best.pt").write_bytes(weights)
            process.start()
            assert attempting.wait(15)
            # The child has started reading while only half the pair is published.
            from queue import Empty

            with pytest.raises(Empty):
                result.get(timeout=0.2)
            (model / "manifest.json").write_text(
                json.dumps({"weights_sha256": hashlib.sha256(weights).hexdigest()})
            )
        assert result.get(timeout=15) is True
        process.join(timeout=15)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        result.close()
