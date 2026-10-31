# pinterest-taste

Type a Pinterest query, get back pins **already scored** by a learned visual taste. Best first.

```python
import pinterest_taste as pt

for pin in pt.search("aesthetic men gym", limit=60, top=10):
    print(pin["score"], pin["url"])      # pin["image"] is a PIL image
```

or from a terminal:

```bash
python -m pinterest_taste "aesthetic men gym" --limit 60 --top 10 --save out/
```

Pinterest is fetched with [gallery-dl](https://github.com/mikf/gallery-dl) used as a Python library (no browser, no CLI).
Scoring is SigLIP 2 + DINOv2 embeddings fed to a pairwise ranker. The trained model (10 MB) ships in the repo.

> **Whose taste?** The bundled model was trained on one person's votes: raw, phone-shot, "real" men's gym / food / lifestyle photos
> **up**; studio stock, 3D renders, bokeh and infographics **down** (337 A/B pairs, ~260 liked and ~670 rejected examples).
> On held-out same-query pairs it picks the preferred pin **78.6%** of the time (**90.7%** on the more confident half).
> For a different taste, retrain on your own votes (see the last section).

## Install

```bash
git clone <this repo> && cd pinterest-taste
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

The first run downloads SigLIP 2 and DINOv2 from Hugging Face (about 5 GB, once). It uses Apple GPU (mps), CUDA or CPU,
whichever is found. Scoring is ~3 ms per pin after the models are loaded; loading takes ~10 s.

## Cookies: connect your Pinterest (step by step)

Pinterest search works without login, but only returns a thin generic slice. With your cookies you get your own,
personalized and much longer feed. The cookies file is a plain text file called `cookies.txt` in the folder you run from.

1. Open **Chrome** and log in to https://www.pinterest.com as usual.
2. Install the extension **"Get cookies.txt LOCALLY"** from the Chrome Web Store (it works offline, nothing is uploaded).
3. Stay on a pinterest.com tab, click the extension icon, press **Export** (format: *Netscape*). A `.txt` file downloads.
4. Rename it to `cookies.txt` and put it in the project folder (or pass `cookies="/path/to/file.txt"` / `--cookies /path/to/file.txt`).
5. Check:
   ```bash
   python -m pinterest_taste "aesthetic men gym" --limit 10 --top 3
   ```
   You should see 3 lines with a score and an `i.pinimg.com` link.

Notes:
- `cookies.txt` is in `.gitignore`. **It is your login: never commit or share it.**
- If it stops working after a few weeks, Pinterest logged the session out: log in again and re-export.
- No extension? gallery-dl can read cookies straight from a browser: in `pinterest_taste/fetch.py` replace
  `config.set(("extractor",), "cookies", cookies)` with `config.set(("extractor",), "cookies", ("chrome",))` (or `"firefox"`, `"safari"`).
  On macOS, Chrome will ask for Keychain access.
- If `search()` raises `CookiesError`, the file path is wrong.

## API

| call | what it does |
| --- | --- |
| `pt.search(query, limit=60, top=20, cookies="cookies.txt", min_score=0.0)` | fetch `limit` pins, download, score, return the best `top` as `[{id, url, title, score, image}]` |
| `pt.score_images([PIL.Image, ...])` | scores in 0..1 for your own images |
| `pinterest_taste.fetch.search_pins(query, limit, cookies)` | just the gallery-dl part: yields `{id, url, title, meta}` without scoring |

The gallery-dl hooks live in one small file, `pinterest_taste/fetch.py`; change options there (image size, videos, sleep between requests).

## Retrain on your own taste

Collect pairs "image A is better than image B", embed them and fit:

```python
import numpy as np
from PIL import Image
from pinterest_taste.features import Embedder
from pinterest_taste.model import TasteModel

emb = Embedder()
load = lambda ps: emb([Image.open(p).convert("RGB") for p in ps])
win, lose = load(winner_paths), load(loser_paths)            # same length, row i beats row i
model = TasteModel().fit(win, lose, banger=load(liked_paths), slop=load(rejected_paths))  # banger/slop optional
model.save("my_taste.npz")
```

Then `from pinterest_taste.model import TasteModel; TasteModel.load("my_taste.npz")`. A few hundred pairs from the same
search query work well (that is how the bundled model was made).

## Status

Tested: scores identical to the original research pipeline; end-to-end `search` runs through gallery-dl.
Not tested here: a logged-in session (cookie steps above are the documented gallery-dl behaviour). Be gentle with limits;
Pinterest can rate-limit or log out an account that scrapes hard.
