"""Local browser workbench. Run with python -m pinterest_taste.web."""
import argparse
import io
import logging
import math
import re
import shutil
import socket
import tempfile
import threading
import uuid
import webbrowser
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import rank_pins
from .fetch import BROWSERS
from .captions import generate_queries
from .references import IMAGE_TYPES, MAX_UPLOAD_BYTES, decode_reference
from .model_downloads import model_progress

STATIC = Path(__file__).with_name("static")
log = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=60, ge=8, le=120, strict=True)
    top: int = Field(default=20, ge=1, le=120, strict=True)
    cookies: str = "anonymous"

    @field_validator("query")
    @classmethod
    def clean_query(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Enter a description to search for.")
        return value

    @field_validator("cookies")
    @classmethod
    def known_cookie_source(cls, value):
        if value not in BROWSERS | {"anonymous", "cookies.txt"}:
            raise ValueError("Choose a browser, cookies.txt, or anonymous search.")
        return value


class Workbench:
    """One search at a time: gallery-dl config and the GPU models are shared."""

    def __init__(self, storage, ranker, captioner):
        self.storage = storage
        self.root = Path(storage.name)
        self.ranker = ranker
        self.captioner = captioner
        self.jobs = {}
        self.references = {}
        self.lock = threading.RLock()
        self.active = None
        self.active_reference = None
        self.worker = None
        self.closed = False

    def close(self):
        with self.lock:
            self.closed = True
            if not self.active and not self.active_reference:
                self.storage.cleanup()

    def start(self, data):
        with self.lock:
            if self.active or self.active_reference:
                raise HTTPException(409, "A search or photo description is already running. Wait for it to finish.")
            # Keep the ten most recent searches for this server session.
            while len(self.jobs) >= 10:
                oldest = next(iter(self.jobs))
                del self.jobs[oldest]
                shutil.rmtree(self.root / oldest, ignore_errors=True)
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "query": data.query, "limit": data.limit,
                   "state": "running", "stage": "searching", "message": "Searching Pinterest",
                   "top": [], "bottom": [], "total": 0, "pick_count": data.top}
            self.jobs[job_id] = job
            self.active = job_id
            self.worker = threading.Thread(target=self.run, args=(job_id, data), daemon=True)
            self.worker.start()
            return dict(job)

    def update(self, job_id, **values):
        with self.lock:
            self.jobs[job_id].update(values)

    def run(self, job_id, data):
        result = {"state": "error", "stage": "error", "message": "Search interrupted."}
        try:
            cookies = None if data.cookies == "anonymous" else data.cookies
            if cookies == "cookies.txt" and not Path(cookies).is_file():
                raise ValueError("cookies.txt was not found in the folder where you started the app. Choose anonymous search or a browser.")
            with model_progress(lambda event: self.update(job_id, stage="loading", model_download=event)):
                rows = self.ranker(data.query, limit=data.limit, cookies=cookies,
                                   progress=lambda stage, message: self.update(job_id, stage=stage, message=message, model_download=None))
            if self.closed:
                return
            # Do not show duplicate Pinterest images in either comparison group.
            unique, seen_ids, seen_urls = [], set(), set()
            for row in rows:
                if row["id"] in seen_ids or row["url"] in seen_urls:
                    continue
                if not math.isfinite(float(row["score"])):
                    continue
                unique.append(row)
                seen_ids.add(row["id"])
                seen_urls.add(row["url"])
            unique.sort(key=lambda row: row["score"], reverse=True)
            # Match search(top=N, min_score=0): select by rank, not a score cutoff.
            # Keep the remaining candidates available for comparison.
            top = unique[:data.top]
            bottom = unique[data.top:]
            folder = self.root / job_id
            folder.mkdir()

            def save(row, index, group):
                filename = f"{group}-{index + 1}.jpg"
                row["image"].save(folder / filename, format="JPEG", quality=92)
                thumb = row["image"].copy()
                thumb.thumbnail((540, 720))
                thumb.save(folder / f"thumb-{filename}", format="JPEG", quality=85)
                pin_id = str(row["id"])
                return {"id": pin_id, "title": row["title"], "score": float(row["score"]),
                        "image": f"/api/searches/{job_id}/images/{filename}",
                        "thumbnail": f"/api/searches/{job_id}/images/thumb-{filename}",
                        "download": f"/api/searches/{job_id}/images/{filename}?download=true",
                        "source": f"https://www.pinterest.com/pin/{pin_id}/" if pin_id.isdecimal() else None}

            result = dict(state="done", stage="done", message="Search complete",
                          total=len(unique), top=[save(row, i, "top") for i, row in enumerate(top)],
                          bottom=[save(row, i, "bottom") for i, row in enumerate(bottom)])
        except Exception as exc:
            log.exception("Pinterest search failed")
            result = dict(state="error", stage="error", message=str(exc)[:800] or "Search failed. Check the terminal for details.")
        finally:
            with self.lock:
                self.jobs[job_id].update(result, model_download=None)
                self.active = None
                if self.closed:
                    self.storage.cleanup()

    def get(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise HTTPException(404, "This search has expired. Run the search again.")
            return dict(self.jobs[job_id])

    def start_reference(self, image):
        with self.lock:
            if self.active or self.active_reference:
                image.close()
                raise HTTPException(409, "A search or photo description is already running. Wait for it to finish.")
            while len(self.references) >= 5:
                del self.references[next(iter(self.references))]
            ref_id = uuid.uuid4().hex
            job = {"id": ref_id, "state": "running", "stage": "loading",
                   "message": "Preparing to describe your photo", "suggestions": []}
            self.references[ref_id] = job
            self.active_reference = ref_id
            threading.Thread(target=self.describe, args=(ref_id, image), daemon=True).start()
            return dict(job)

    def describe(self, ref_id, image):
        result = dict(state="error", stage="error", message="Photo description interrupted.")
        try:
            def progress(stage, message):
                with self.lock:
                    self.references[ref_id].update(stage=stage, message=message, model_download=None)
            def model_update(event):
                with self.lock:
                    self.references[ref_id].update(stage="loading", model_download=event)
            with model_progress(model_update):
                suggestions = self.captioner(image, progress=progress)
            if (len(suggestions) != 3
                    or any(not isinstance(row.get("query"), str) or not 1 <= len(row["query"].strip()) <= 180
                           or not isinstance(row.get("label"), str) for row in suggestions)
                    or len({row["query"].strip().casefold() for row in suggestions}) != 3):
                raise ValueError("The model did not return three distinct descriptions. Try again or enter a search manually.")
            result = dict(state="done", stage="done", message="Choose a description to use as your search.", suggestions=suggestions)
        except Exception as exc:
            log.exception("Photo description failed")
            result = dict(state="error", stage="error", message=str(exc)[:800] or "The photo could not be described. Try again.")
        finally:
            image.close()
            with self.lock:
                self.references[ref_id].update(result, model_download=None)
                self.active_reference = None
                if self.closed:
                    self.storage.cleanup()

    def get_reference(self, ref_id):
        with self.lock:
            if ref_id not in self.references:
                raise HTTPException(404, "This reference has expired. Attach the photo again.")
            return dict(self.references[ref_id])


def create_app(ranker=rank_pins, default_cookies="anonymous", captioner=generate_queries):
    if default_cookies not in BROWSERS | {"anonymous", "cookies.txt"}:
        raise ValueError("Unknown Pinterest cookie source")
    @asynccontextmanager
    async def lifespan(app):
        storage = tempfile.TemporaryDirectory(prefix="pinterest-taste-")
        app.state.workbench = Workbench(storage, ranker, captioner)
        try:
            yield
        finally:
            # An in-flight worker cleans up when it stops; shutdown never waits on a model download.
            app.state.workbench.close()

    app = FastAPI(title="Pinterest Taste", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Open the app from its local address."}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
        if request.method == "POST":
            upload = request.url.path == "/api/references"
            content_type = request.headers.get("content-type", "").split(";")[0]
            allowed_types = IMAGE_TYPES if upload else {"application/json"}
            if content_type not in allowed_types:
                detail = "Choose a JPG, PNG or WebP photo." if upload else "Send a JSON search request."
                return JSONResponse({"detail": detail}, status_code=415)
            max_bytes = MAX_UPLOAD_BYTES if upload else 4096
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > max_bytes:
                    detail = "Choose a photo smaller than 10 MB." if upload else "Search request is too large."
                    return JSONResponse({"detail": detail}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/api/config")
    def configuration():
        return {"default_cookies": default_cookies, "reference_upload": True,
                "rank_selection": True, "max_upload_bytes": MAX_UPLOAD_BYTES}

    @app.post("/api/references", status_code=202)
    async def reference(request: Request):
        from starlette.concurrency import run_in_threadpool
        data = await request.body()
        content_type = request.headers.get("content-type", "").split(";")[0]
        try:
            image = await run_in_threadpool(decode_reference, data, content_type)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return app.state.workbench.start_reference(image)

    @app.get("/api/references")
    def recent_references():
        wb = app.state.workbench
        with wb.lock:
            return {"references": [dict(job) for job in reversed(list(wb.references.values()))]}

    @app.get("/api/references/{ref_id}")
    def reference_status(ref_id: str):
        return app.state.workbench.get_reference(ref_id)

    @app.get("/api/searches")
    def searches():
        wb = app.state.workbench
        with wb.lock:
            return {"searches": [dict(job) for job in reversed(list(wb.jobs.values()))]}

    @app.post("/api/searches", status_code=202)
    def search(data: SearchRequest):
        return app.state.workbench.start(data)

    @app.get("/api/searches/{job_id}")
    def search_status(job_id: str):
        return app.state.workbench.get(job_id)

    @app.get("/api/searches/{job_id}/images/{filename}")
    def photo(job_id: str, filename: str, download: bool = False):
        wb = app.state.workbench
        job = wb.get(job_id)
        if job["state"] != "done" or not re.fullmatch(r"(?:thumb-)?(?:top|bottom)-[1-9][0-9]{0,2}\.jpg", filename):
            raise HTTPException(404, "Photo not found.")
        path = wb.root / job_id / filename
        if not path.is_file():
            raise HTTPException(404, "Photo not found.")
        return FileResponse(path, media_type="image/jpeg", filename=f"pinterest-taste-{filename}" if download else None)

    @app.get("/api/searches/{job_id}/download")
    def download_top(job_id: str):
        wb = app.state.workbench
        job = wb.get(job_id)
        if job["state"] != "done" or not job["top"]:
            raise HTTPException(404, "No photos to download.")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for row in job["top"]:
                filename = Path(urlsplit(row["image"]).path).name
                archive.write(wb.root / job_id / filename, filename)
            archive.writestr("sources.txt", "\n".join(f"{i + 1}. {row['source'] or 'Source unavailable'} | taste={row['score']:.4f}" for i, row in enumerate(job["top"])))
        return Response(output.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="pinterest-taste-picks.zip"'})

    @app.get("/")
    def home():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="Open Pinterest Taste in your browser")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--cookies", choices=["anonymous", "cookies.txt", *sorted(BROWSERS)],
                        default="anonymous", help="Pinterest connection selected when the app opens")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open a browser")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    # Bind before opening the browser, so an occupied port never opens another app.
    sock = socket.socket()
    # Allow restarting after a previous connection enters TIME_WAIT on macOS.
    # This does not allow taking over a port with an active listening server.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", args.port))
    except OSError as exc:
        parser.exit(1, f"Cannot use port {args.port}: {exc}. Try --port {args.port + 1}.\n")
    config = uvicorn.Config(create_app(default_cookies=args.cookies), host="127.0.0.1", port=args.port, log_level="info")
    server = uvicorn.Server(config)
    if not args.no_browser:
        def open_when_ready():
            import time
            while not server.started and not server.should_exit:
                time.sleep(0.1)
            if server.started:
                webbrowser.open(f"http://127.0.0.1:{args.port}")
        threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
