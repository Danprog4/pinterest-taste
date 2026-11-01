import numpy as np
from PIL import Image

import pinterest_taste as pt


def test_search_preserves_threshold_and_top_while_rank_pins_keeps_low_scores(monkeypatch):
    pins = [{"id": str(i), "url": f"https://example.invalid/{i}", "title": str(i)} for i in range(4)]
    monkeypatch.setattr(pt, "search_pins", lambda *args, **kwargs: iter(pins))
    monkeypatch.setattr(pt, "_download", lambda pin: None if pin["id"] == "1" else Image.new("RGB", (8, 8)))

    class Model:
        def score(self, embeddings):
            assert len(embeddings) == 3
            return np.array([0.4, 0.95, 0.1])

    monkeypatch.setattr(pt, "_get", lambda: (lambda images: images, Model()))
    progress = []
    rows = pt.rank_pins("gym", progress=lambda stage, message: progress.append(stage))
    assert [row["id"] for row in rows] == ["2", "0", "3"]
    assert progress[0] == "searching"
    assert progress[-1] == "scoring"
    assert [row["id"] for row in pt.search("gym", top=2, min_score=0.3)] == ["2", "0"]
    assert len(pt.search("gym", top=1)) == 1
