import io
import threading
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pinterest_taste.captions import clean_query
from pinterest_taste.references import MAX_UPLOAD_BYTES, decode_reference
from pinterest_taste.web import create_app

CHOICES = [
    {"label": "Topic", "query": "mens abs aesthetic"},
    {"label": "Aesthetic", "query": "mens gym aesthetic"},
    {"label": "Related", "query": "mens gym mirror selfie"},
]


def photo_bytes(format="PNG", orientation=None):
    image = Image.new("RGB", (8, 12), "navy")
    buffer = io.BytesIO()
    kwargs = {}
    if orientation is not None:
        exif = image.getexif()
        exif[274] = orientation
        kwargs["exif"] = exif
    image.save(buffer, format=format, **kwargs)
    return buffer.getvalue()


def upload(client, data=None, **kwargs):
    return client.post("/api/references", content=photo_bytes() if data is None else data,
                       headers={"Content-Type": "image/png", **kwargs})


def wait_reference(client, ref_id):
    for _ in range(200):
        job = client.get(f"/api/references/{ref_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(.01)
    raise AssertionError("Reference did not finish")


def test_reference_choices_feed_the_existing_search_without_uploading_again():
    received = {}
    def captioner(image, progress):
        received["image"] = (image.size, image.mode, dict(image.info))
        progress("describing", "Writing description 1 of 3")
        return CHOICES
    def ranker(query, **kwargs):
        received["query"] = query
        return []
    with TestClient(create_app(ranker, captioner=captioner), base_url="http://127.0.0.1") as client:
        result = upload(client)
        assert result.status_code == 202
        job = wait_reference(client, result.json()["id"])
        assert job["state"] == "done"
        assert job["suggestions"] == CHOICES
        assert received["image"] == ((8, 12), "RGB", {})
        assert client.get("/api/references").json()["references"][0]["id"] == job["id"]
        assert client.get("/api/references/unknown").status_code == 404
        assert not list(client.app.state.workbench.root.iterdir())
        assert client.post("/api/searches", json={"query": job["suggestions"][1]["query"]}).status_code == 202
        for _ in range(100):
            if "query" in received:
                break
            time.sleep(.01)
        assert received["query"] == CHOICES[1]["query"]


def test_invalid_oversized_and_cross_site_uploads_do_not_invoke_model():
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid image reached caption model")
    with TestClient(create_app(captioner=forbidden), base_url="http://127.0.0.1") as client:
        assert upload(client, b"not an image").status_code == 422
        assert upload(client, b"").status_code == 422
        assert upload(client, **{"Content-Type": "image/svg+xml"}).status_code == 415
        assert upload(client, photo_bytes("JPEG")).status_code == 422
        assert upload(client, b"x" * (MAX_UPLOAD_BYTES + 1)).status_code == 413
        assert upload(client, Origin="https://other.example").status_code == 403
        assert client.get("/api/references").json()["references"] == []


def test_photo_orientation_and_pixel_limit(monkeypatch):
    photo = decode_reference(photo_bytes("JPEG", orientation=6), "image/jpeg")
    assert photo.size == (12, 8)
    assert photo.info == {}
    photo.close()
    monkeypatch.setattr("pinterest_taste.references.MAX_PIXELS", 50)
    with pytest.raises(ValueError, match="megapixels"):
        decode_reference(photo_bytes(), "image/png")


@pytest.mark.parametrize("mode", ["error", "duplicates", "too_few"])
def test_caption_failures_are_visible_and_release_search_slot(mode):
    def captioner(*args, **kwargs):
        if mode == "error":
            raise RuntimeError("Model download failed")
        return CHOICES[:2] if mode == "too_few" else [CHOICES[0]] * 3
    with TestClient(create_app(lambda *args, **kwargs: [], captioner=captioner), base_url="http://127.0.0.1") as client:
        job = wait_reference(client, upload(client).json()["id"])
        assert job["state"] == "error"
        assert job["message"]
        assert client.post("/api/searches", json={"query": "gym"}).status_code == 202


def test_search_and_caption_cannot_overlap():
    gate = threading.Event()
    def captioner(*args, **kwargs):
        assert gate.wait(5)
        return CHOICES
    with TestClient(create_app(lambda *args, **kwargs: [], captioner=captioner), base_url="http://127.0.0.1") as client:
        ref_id = upload(client).json()["id"]
        try:
            assert upload(client).status_code == 409
            assert client.post("/api/searches", json={"query": "gym"}).status_code == 409
        finally:
            gate.set()
        assert wait_reference(client, ref_id)["state"] == "done"


def test_active_search_is_not_interrupted_by_reference_upload():
    gate = threading.Event()
    def ranker(*args, **kwargs):
        assert gate.wait(5)
        return []
    with TestClient(create_app(ranker, captioner=lambda *args, **kwargs: CHOICES), base_url="http://127.0.0.1") as client:
        job_id = client.post("/api/searches", json={"query": "gym"}).json()["id"]
        try:
            assert upload(client).status_code == 409
            assert client.get(f"/api/searches/{job_id}").json()["state"] == "running"
        finally:
            gate.set()


def test_caption_output_cleanup_keeps_short_search_phrases():
    assert clean_query('Assistant: "men at the gym"') == "men at the gym"
    assert clean_query("1. eggs on a breakfast plate\n2. ignored alternative") == "eggs on a breakfast plate"
    with pytest.raises(ValueError):
        clean_query("")


@pytest.mark.parametrize("query", ["abs aesthetic", "mens gym mirror selfie", "healthy breakfast eggs and avocado", "men running outdoors in the rain"])
def test_short_queries_preserve_useful_details(query):
    assert clean_query(query) == query


@pytest.mark.parametrize("query", ["gym", "man standing in a gym with dark lighting and weights", " "])
def test_invalid_queries_are_rejected_instead_of_cut_mid_phrase(query):
    with pytest.raises(ValueError, match="short search query"):
        clean_query(query)
