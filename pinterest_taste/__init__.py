import io
import numpy as np
import requests
from PIL import Image

from .fetch import search_pins, CookiesError
from .model import TasteModel

__all__ = ["search", "score_images", "CookiesError"]
_state = {}


def _get():
    if "emb" not in _state:
        from .features import Embedder
        _state["emb"], _state["model"] = Embedder(), TasteModel.load()
    return _state["emb"], _state["model"]


def score_images(images):
    """images: list of PIL images -> list of floats in 0..1."""
    emb, model = _get()
    return model.score(emb(images)).tolist()


def _download(pin):
    try:
        r = requests.get(pin["url"], timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def search(query, limit=60, top=20, cookies="cookies.txt", min_score=0.0):
    """Search Pinterest for `query`, score every pin, return the best `top`:
    [{'id', 'url', 'title', 'score', 'image': PIL.Image}, ...] sorted by score, best first."""
    from concurrent.futures import ThreadPoolExecutor
    pins = list(search_pins(query, limit=limit, cookies=cookies))
    with ThreadPoolExecutor(8) as ex:
        imgs = list(ex.map(_download, pins))
    ok = [(p, im) for p, im in zip(pins, imgs) if im is not None]
    if not ok:
        return []
    scores = score_images([im for _, im in ok])
    rows = [{"id": p["id"], "url": p["url"], "title": p["title"], "score": s, "image": im}
            for (p, im), s in zip(ok, scores) if s >= min_score]
    return sorted(rows, key=lambda r: r["score"], reverse=True)[:top]
