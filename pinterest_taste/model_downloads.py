"""Model downloads with per-job progress; never patch global Hub callbacks."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from collections import deque
from pathlib import Path
import threading
import time

_sink = ContextVar("model_progress", default=None)


@contextmanager
def model_progress(callback):
    token = _sink.set(callback)
    try:
        yield
    finally:
        _sink.reset(token)


@dataclass(frozen=True)
class ModelFiles:
    name: str
    repo: str
    files: tuple[str, ...]


SIGLIP = ModelFiles("SigLIP 2", "google/siglip2-so400m-patch14-384", (
    "config.json", "model.safetensors", "preprocessor_config.json",
    "special_tokens_map.json", "tokenizer.json", "tokenizer.model", "tokenizer_config.json",
))
DINO = ModelFiles("DINOv2", "timm/vit_base_patch14_dinov2.lvd142m", ("model.safetensors",))
CAPTION = ModelFiles("SmolVLM 500M", "HuggingFaceTB/SmolVLM-500M-Instruct", (
    "added_tokens.json", "chat_template.json", "config.json", "generation_config.json",
    "merges.txt", "model.safetensors", "preprocessor_config.json", "processor_config.json",
    "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "vocab.json",
))


class DownloadProgress:
    def __init__(self, spec, callback, clock=time.monotonic):
        self.spec, self.callback, self.clock = spec, callback, clock
        self.lock = threading.RLock()
        self.total = None
        self.sizes, self.completed, self.positions = {}, set(), {}
        self.samples = deque()
        self.transferred = 0
        self.phase = "checking"
        self.filename = None
        self.last_change = self.clock()

    def plan(self, sizes, cached):
        with self.lock:
            self.sizes = sizes
            self.total = sum(sizes.values())
            self.completed = set(cached)
            self.phase = "downloading"
            self.samples.append((self.clock(), 0))
        self.emit()

    def position(self, filename, count, initial=False):
        with self.lock:
            count = min(self.sizes[filename], max(0, count))
            old = self.positions.get(filename, 0)
            self.positions[filename] = count
            self.filename = filename
            if not initial and count > old:
                self.transferred += count - old
                self.last_change = self.clock()

    def complete(self, filename):
        with self.lock:
            self.completed.add(filename)
            self.positions.pop(filename, None)
        self.emit()

    def memory(self):
        with self.lock:
            self.phase = "loading_memory"
            self.filename = None
        self.emit()

    def emit(self):
        if not self.callback:
            return
        with self.lock:
            now = self.clock()
            self.samples.append((now, self.transferred))
            while len(self.samples) > 2 and self.samples[1][0] < now - 10:
                self.samples.popleft()
            elapsed = now - self.samples[0][0]
            rate = (self.transferred - self.samples[0][1]) / elapsed if elapsed > 0 else 0
            if now - self.last_change > 5:
                rate = 0
            done = sum(self.sizes[f] for f in self.completed) + sum(
                n for f, n in self.positions.items() if f not in self.completed)
            percent = 100 * done / self.total if self.total else None
            eta = (self.total - done) / rate if self.total and rate > 0 else None
            event = dict(model=self.spec.name, repo=self.spec.repo, phase=self.phase,
                         filename=self.filename, downloaded_bytes=done, total_bytes=self.total,
                         percent=percent, bytes_per_second=rate if self.phase == "downloading" else None,
                         eta_seconds=eta if self.phase == "downloading" else None)
        self.callback(event)


def _progress_bar(tracker, filename):
    from tqdm import tqdm

    class FileProgress(tqdm):
        def __init__(self, *args, **kwargs):
            # Xet reports both wire bytes and reconstructed file bytes. Count only
            # the latter so compressed transfer bytes are not added a second time.
            self.track = kwargs.get("desc") != "Downloading bytes" and kwargs.get("unit") == "B"
            kwargs["disable"] = True
            super().__init__(*args, **kwargs)
            if self.track:
                tracker.position(filename, self.n, initial=True)
                tracker.emit()

        def update(self, n=1):
            self.n += n or 0
            if self.track:
                tracker.position(filename, self.n)

    return FileProgress


def prepare_model(spec):
    """Fetch declared assets, then return a complete local snapshot for loading."""
    from huggingface_hub import HfApi, hf_hub_download, snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    tracker = DownloadProgress(spec, _sink.get())
    tracker.emit()
    # A complete cached snapshot must work offline, without metadata requests.
    try:
        cached_path = Path(snapshot_download(spec.repo, local_files_only=True))
    except LocalEntryNotFoundError:
        cached_path = None
    if cached_path and all((cached_path / name).is_file() for name in spec.files):
        tracker.plan({name: (cached_path / name).stat().st_size for name in spec.files}, spec.files)
        tracker.memory()
        return str(cached_path)

    info = HfApi().model_info(spec.repo, files_metadata=True)
    sizes = {entry.rfilename: entry.size for entry in info.siblings if entry.rfilename in spec.files}
    if set(sizes) != set(spec.files) or any(size is None for size in sizes.values()):
        raise ValueError(f"Could not read the download size for {spec.name}. Please try again.")
    # Resolve cache entries at this exact revision, so updates cannot mix versions.
    paths = {}
    for name in spec.files:
        try:
            paths[name] = hf_hub_download(spec.repo, name, revision=info.sha, local_files_only=True)
        except LocalEntryNotFoundError:
            pass
    tracker.plan(sizes, paths)
    stopped = threading.Event()

    def heartbeat():
        while not stopped.wait(1):
            tracker.emit()

    ticker = threading.Thread(target=heartbeat, daemon=True)
    ticker.start()
    try:
        for name in spec.files:
            if name in paths:
                continue
            tracker.filename = name
            tracker.emit()
            paths[name] = hf_hub_download(spec.repo, name, revision=info.sha,
                                         tqdm_class=_progress_bar(tracker, name) if tracker.callback else None)
            tracker.complete(name)
    finally:
        stopped.set()
        ticker.join()
    tracker.memory()
    return str(Path(paths[spec.files[0]]).parent)
