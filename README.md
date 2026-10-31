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

## Cookies: connect your Pinterest

Cookies are optional. Without them the search runs anonymously (it works, the feed is just generic and shorter).
With them you search as yourself: a longer, personalized feed.

### Easiest way (30 seconds, nothing to install)

1. Open your browser (Chrome, Safari, Firefox...) and make sure you are **logged in to pinterest.com**.
2. Tell the library which browser it is:
   ```python
   pt.search("aesthetic men gym", cookies="chrome")      # or "safari", "firefox", "edge", "brave"
   ```
   ```bash
   python -m pinterest_taste "aesthetic men gym" --cookies chrome
   ```
3. On a Mac a window may ask for permission to read the browser's data (Keychain, or "Full Disk Access" for Safari). Allow it.

That is all: the login is read straight from the browser, no files. Pinterest logged you out? Log in again in the browser.

### If that fails: cookies.txt

1. In Chrome, log in to pinterest.com and install the extension **"Get cookies.txt LOCALLY"**.
2. On a pinterest.com tab click the extension, press **Export**.
3. Rename the file to `cookies.txt` and put it in the project folder (or pass its path as `cookies=`).

`cookies.txt` is in `.gitignore`. **It is your login: never commit or share it.**
A wrong explicit path raises `CookiesError`; a missing default `cookies.txt` just means anonymous search.

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
