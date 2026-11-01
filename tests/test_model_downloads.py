from types import SimpleNamespace
import threading

import pytest
from fastapi.testclient import TestClient

from pinterest_taste.model_downloads import (
    DownloadProgress, ModelFiles, _progress_bar, model_progress, prepare_model, _sink,
)
from pinterest_taste.web import create_app

SPEC = ModelFiles("Test model", "test/model", ("config.json", "model.safetensors"))


def test_cached_and_resumed_bytes_are_not_counted_as_download_speed():
    now = [0.0]
    events = []
    tracker = DownloadProgress(SPEC, events.append, clock=lambda: now[0])
    tracker.plan({"config.json": 100, "model.safetensors": 900}, ["config.json"])
    tracker.position("model.safetensors", 400, initial=True)
    now[0] = 2
    tracker.position("model.safetensors", 600)
    tracker.emit()
    assert events[-1]["downloaded_bytes"] == 700
    assert events[-1]["percent"] == 70
    assert events[-1]["bytes_per_second"] == 100
    assert events[-1]["eta_seconds"] == 3
    now[0] = 9
    tracker.emit()
    assert events[-1]["bytes_per_second"] == 0
    assert events[-1]["eta_seconds"] is None
    tracker.complete("model.safetensors")
    tracker.memory()
    assert events[-1]["phase"] == "loading_memory"
    assert events[-1]["percent"] == 100
    assert events[-1]["bytes_per_second"] is None


def test_hub_http_and_xet_counters_do_not_double_count():
    from huggingface_hub.utils._xet_progress_reporting import XetDownloadProgressReporter
    tracker = DownloadProgress(SPEC, lambda event: None)
    tracker.plan({"model.safetensors": 1000}, [])
    cls = _progress_bar(tracker, "model.safetensors")
    with cls(desc="model.safetensors", total=1000, initial=100, unit="B") as bar:
        bar.update(200)
    assert tracker.positions["model.safetensors"] == 300
    with XetDownloadProgressReporter(reconstruction_desc="model.safetensors", total=1000,
                                   log_level=20, tqdm_class=cls) as reporter:
        reporter.update_progress(SimpleNamespace(total_bytes_completed=500,
            total_transfer_bytes_completed=400, total_bytes_completion_rate=200,
            total_transfer_bytes_completion_rate=180, total_bytes=1000))
    assert tracker.positions["model.safetensors"] == 500


def test_complete_cached_snapshot_works_without_network(tmp_path, monkeypatch):
    import huggingface_hub as hub
    for name in SPEC.files:
        (tmp_path / name).write_bytes(b"cached")
    monkeypatch.setattr(hub, "snapshot_download", lambda *args, **kwargs: str(tmp_path))
    def forbidden(*args, **kwargs):
        raise AssertionError("Cached model must not contact the network")
    monkeypatch.setattr(hub, "HfApi", forbidden)
    events = []
    with model_progress(events.append):
        assert prepare_model(SPEC) == str(tmp_path)
    assert events[-1]["phase"] == "loading_memory"
    assert events[-1]["downloaded_bytes"] == 12
    assert _sink.get() is None


@pytest.mark.parametrize("fail", [False, True])
def test_missing_files_download_at_one_revision_and_errors_do_not_report_memory(tmp_path, monkeypatch, fail):
    import huggingface_hub as hub
    from huggingface_hub.errors import LocalEntryNotFoundError
    monkeypatch.setattr(hub, "snapshot_download", lambda *args, **kwargs: str(tmp_path))
    (tmp_path / "config.json").write_bytes(b"cached")
    monkeypatch.setattr(hub, "HfApi", lambda: SimpleNamespace(model_info=lambda *args, **kwargs:
        SimpleNamespace(sha="fixed-revision", siblings=[SimpleNamespace(rfilename=name, size=6) for name in SPEC.files])))
    requests = []
    def download(repo, name, **kwargs):
        assert kwargs["revision"] == "fixed-revision"
        if name == "config.json":
            return str(tmp_path / name)
        if kwargs.get("local_files_only"):
            raise LocalEntryNotFoundError("Missing")
        requests.append(name)
        if fail:
            raise RuntimeError("Connection lost")
        with kwargs["tqdm_class"](desc=name, total=6, unit="B") as bar:
            bar.update(6)
        (tmp_path / name).write_bytes(b"weight")
        return str(tmp_path / name)
    monkeypatch.setattr(hub, "hf_hub_download", download)
    events = []
    with model_progress(events.append):
        if fail:
            with pytest.raises(RuntimeError, match="Connection lost"):
                prepare_model(SPEC)
        else:
            assert prepare_model(SPEC) == str(tmp_path)
    assert requests == ["model.safetensors"]
    assert (events[-1]["phase"] == "loading_memory") is not fail
    assert _sink.get() is None


@pytest.mark.parametrize("reference", [False, True])
def test_web_exposes_model_progress_and_clears_it_when_job_finishes(reference):
    from tests.test_references import CHOICES, photo_bytes
    gate = threading.Event()
    reported = threading.Event()
    def worker(*args, **kwargs):
        tracker = DownloadProgress(SPEC, _sink.get())
        tracker.plan({"model.safetensors": 1000}, [])
        tracker.memory()
        reported.set()
        assert gate.wait(5)
        return CHOICES if reference else []
    with TestClient(create_app(ranker=worker, captioner=worker), base_url="http://127.0.0.1") as client:
        if reference:
            response = client.post("/api/references", content=photo_bytes(), headers={"Content-Type": "image/png"})
            prefix = "/api/references/"
        else:
            response = client.post("/api/searches", json={"query": "gym"})
            prefix = "/api/searches/"
        try:
            assert reported.wait(5)
            job = client.get(prefix + response.json()["id"]).json()
            assert job["model_download"]["model"] == "Test model"
            assert job["model_download"]["phase"] == "loading_memory"
        finally:
            gate.set()
        import time
        for _ in range(200):
            job = client.get(prefix + response.json()["id"]).json()
            if job["state"] != "running":
                break
            time.sleep(.01)
        assert job["state"] == "done"
        assert job["model_download"] is None
