import io
import requests
from PIL import Image

from .fetch import search_pins, CookiesError
from .model import TasteModel

__all__ = ["search", "rank_pins", "score_images", "CookiesError"]
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


def rank_pins(query, limit=60, cookies="cookies.txt", progress=None):
    """Return every successfully downloaded pin, ranked best first.

    Optional progress receives (stage, message). No score threshold is applied,
    so callers can compare the highest and lowest scoring images in one search.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    report = progress or (lambda stage, message: None)
    report("searching", "Searching Pinterest")
    pins = list(search_pins(query, limit=limit, cookies=cookies))
    report("downloading", f"Downloading {len(pins)} photos")
    imgs = [None] * len(pins)
    with ThreadPoolExecutor(8) as ex:
        pending = {ex.submit(_download, pin): i for i, pin in enumerate(pins)}
        for completed, future in enumerate(as_completed(pending), 1):
            imgs[pending[future]] = future.result()
            report("downloading", f"Downloaded {completed} of {len(pins)} photos")
    ok = [(p, im) for p, im in zip(pins, imgs) if im is not None]
    if not ok:
        return []
    report("loading", "Loading image models. The first run downloads about 5 GB; later runs use the local cache.")
    emb, model = _get()
    report("scoring", f"Comparing {len(ok)} photos with the learned taste")
    scores = model.score(emb([im for _, im in ok])).tolist()
    rows = [{"id": p["id"], "url": p["url"], "title": p["title"], "score": s, "image": im}
            for (p, im), s in zip(ok, scores)]
    return sorted(rows, key=lambda r: r["score"], reverse=True)


def search(query, limit=60, top=20, cookies="cookies.txt", min_score=0.0):
    """Search Pinterest and return the best `top` pins above `min_score`.

    Returns [{id, url, title, score, image: PIL.Image}], best first.
    """
    rows = rank_pins(query, limit=limit, cookies=cookies)
    return [row for row in rows if row["score"] >= min_score][:top]
