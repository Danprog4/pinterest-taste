import io
import threading
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pinterest_taste.web import create_app


def photos(count=12):
    return [{"id": str(1000 + i), "url": f"https://example.invalid/{i}.jpg",
             "title": f"Photo {i}", "score": 1 - i / max(1, count - 1),
             "image": Image.new("RGB", (48, 64), ((30 + i * 7) % 256, 80, 150))}
            for i in range(count)]


def client_for(ranker):
    return TestClient(create_app(ranker), base_url="http://127.0.0.1")


def test_startup_cookie_selection():
    with TestClient(create_app(default_cookies="chrome"), base_url="http://127.0.0.1") as client:
        config = client.get("/api/config").json()
        assert config["default_cookies"] == "chrome"
        assert config["reference_upload"] is True
    with client_for(lambda *args, **kwargs: []) as client:
        assert client.get("/api/config").json()["default_cookies"] == "anonymous"
    with pytest.raises(ValueError):
        create_app(default_cookies="/arbitrary/path")


def wait_for_job(client, job_id):
    for _ in range(200):
        job = client.get(f"/api/searches/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("Search did not finish")


def test_search_selects_original_top_20_and_keeps_remaining_photos():
    received = {}

    def ranker(query, **kwargs):
        received.update(query=query, **kwargs)
        kwargs["progress"]("scoring", "Scoring")
        rows = photos(30)
        return list(reversed(rows)) + [rows[0]]

    with client_for(ranker) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        response = client.post("/api/searches", json={"query": "  gym   photos ", "limit": 24})
        assert response.status_code == 202
        job = wait_for_job(client, response.json()["id"])
        assert received["query"] == "gym photos"
        assert received["cookies"] is None
        assert job["state"] == "done"
        assert job["total"] == 30
        assert job["pick_count"] == 20
        assert "threshold" not in job
        assert [row["id"] for row in job["top"]] == [str(i) for i in range(1000, 1020)]
        assert [row["id"] for row in job["bottom"]] == [str(i) for i in range(1020, 1030)]
        assert client.get(job["top"][14]["image"]).status_code == 200
        assert client.get(job["bottom"][9]["image"]).status_code == 200
        assert client.get(job["top"][0]["thumbnail"]).headers["content-type"] == "image/jpeg"
        download = client.get(job["top"][0]["download"])
        assert "attachment" in download.headers["content-disposition"]
        assert Image.open(io.BytesIO(download.content)).size == (48, 64)
        bundle = client.get(f"/api/searches/{job['id']}/download")
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            assert len(archive.namelist()) == 21
            assert "https://www.pinterest.com/pin/1000/" in archive.read("sources.txt").decode()
        assert client.get(f"/api/searches/{job['id']}/images/unknown.jpg").status_code == 404
        assert client.get("/api/searches").json()["searches"][0]["id"] == job["id"]


@pytest.mark.parametrize("count,expected", [(0, (0, 0)), (3, (3, 0)), (6, (6, 0)), (8, (8, 0))])
def test_short_searches_do_not_repeat_photos(count, expected):
    with client_for(lambda *args, **kwargs: photos(count)) as client:
        job_id = client.post("/api/searches", json={"query": "gym"}).json()["id"]
        job = wait_for_job(client, job_id)
        assert (len(job["top"]), len(job["bottom"])) == expected
        assert len(job["top"]) + len(job["bottom"]) == count
        assert not ({row["id"] for row in job["top"]} & {row["id"] for row in job["bottom"]})
        if count == 0:
            assert client.get(f"/api/searches/{job_id}/download").status_code == 404


@pytest.mark.parametrize("score", [0.1, 0.49, 0.5, 0.9])
def test_pick_count_works_for_both_high_and_low_scores(score):
    def ranker(*args, **kwargs):
        return [dict(row, score=score) for row in photos()]
    with client_for(ranker) as client:
        job_id = client.post("/api/searches", json={"query": "gym", "top": 5}).json()["id"]
        job = wait_for_job(client, job_id)
        assert (len(job["top"]), len(job["bottom"])) == (5, 7)
        assert job["pick_count"] == 5
        assert job["total"] == 12
        with zipfile.ZipFile(io.BytesIO(client.get(f"/api/searches/{job_id}/download").content)) as archive:
            assert len([name for name in archive.namelist() if name.endswith(".jpg")]) == 5


def test_rejects_cross_site_calls_invalid_input_and_arbitrary_cookie_paths():
    with client_for(lambda *args, **kwargs: photos()) as client:
        for body in [{"query": " "}, {"query": "x", "limit": 1000}, {"query": "x", "limit": "60"},
                     {"query": "x", "cookies": "/etc/passwd"}, {"query": "x", "extra": 1}, {"query": "x", "top": 0},
                     {"query": "x", "top": 121}, {"query": "x", "top": "20"}]:
            assert client.post("/api/searches", json=body).status_code == 422
        assert client.post("/api/searches", json={"query": "x"}, headers={"Origin": "https://other.example"}).status_code == 403
        assert client.get("/api/searches", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert client.get("/", headers={"Host": "other.example"}).status_code == 400
        assert client.post("/api/searches", content="query=x").status_code == 415
        assert client.post("/api/searches", json={"query": "x" * 5000}).status_code == 413
        response = client.post("/api/searches", json={"query": "x"}, headers={"Origin": "http://127.0.0.1"})
        assert response.status_code == 202
        wait_for_job(client, response.json()["id"])


def test_only_one_search_can_use_models_and_gallery_config():
    gate = threading.Event()

    def ranker(*args, **kwargs):
        assert gate.wait(5)
        return photos()

    with client_for(ranker) as client:
        job_id = client.post("/api/searches", json={"query": "gym"}).json()["id"]
        try:
            assert client.post("/api/searches", json={"query": "food"}).status_code == 409
            assert client.get(f"/api/searches/{job_id}").json()["state"] == "running"
        finally:
            gate.set()
        assert wait_for_job(client, job_id)["state"] == "done"


def test_failure_is_visible_and_does_not_block_future_searches():
    def ranker(*args, **kwargs):
        raise RuntimeError("Pinterest is unavailable")

    with client_for(ranker) as client:
        for _ in range(2):
            response = client.post("/api/searches", json={"query": "gym"})
            assert response.status_code == 202
            job = wait_for_job(client, response.json()["id"])
            assert job["state"] == "error"
            assert job["message"] == "Pinterest is unavailable"


def test_old_search_files_are_removed_and_missing_cookie_file_is_explicit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with client_for(lambda *args, **kwargs: photos()) as client:
        first_id = None
        for i in range(11):
            response = client.post("/api/searches", json={"query": f"gym {i}"})
            job_id = response.json()["id"]
            first_id = first_id or job_id
            wait_for_job(client, job_id)
        assert len(client.get("/api/searches").json()["searches"]) == 10
        assert client.get(f"/api/searches/{first_id}").status_code == 404
        assert not (client.app.state.workbench.root / first_id).exists()
        job_id = client.post("/api/searches", json={"query": "gym", "cookies": "cookies.txt"}).json()["id"]
        job = wait_for_job(client, job_id)
        assert job["state"] == "error"
        assert "cookies.txt was not found" in job["message"]
