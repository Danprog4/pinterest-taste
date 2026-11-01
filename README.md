# pinterest-taste

**Fresh photos for your next TikTok carousel.**

Start with a reference photo from a carousel you like, or describe the shot. Pinterest Taste finds alternative images on Pinterest and uses a local model to put candid, everyday photography first. Pick new photos for your slides without starting every search from scratch.

Built for TikTok creators making photo carousels, especially fitness, food and lifestyle content. The bundled taste favors phone-shot images over studio stock, 3D renders, infographics and heavily staged visuals.

**Free to run locally. No paid AI API, API key or per-image fee.** Your computer handles the photo descriptions and filtering; pretrained models download on first use.

## From one reference to your next set of visuals

1. **Bring the reference.** Attach or drop a photo, or type a short description of the image you need for a slide.
2. **Choose the search.** A reference photo produces three short search phrases. Pick one and adjust it if needed.
3. **Compare the options.** Browse the model's carousel picks alongside the other photos found. Try another description to explore a different set.
4. **Take your picks.** Download individual photos or the selected group as a ZIP with links to the original pins.

The side-by-side comparison shows what the taste model changes within the same search: the images it selects and those it ranks below the cutoff. It helps you see whether the selection fits the mood of your carousel.

This is a finder and filter for existing images. It does not generate images, verify that every result is a real photograph, or create finished carousel slides. The initial taste is tuned to men's fitness, food and lifestyle; other visual styles may need a different model.

The browser workbench follows the original rank selection: **Carousel picks** contains the highest ranked 20 photos by default, equivalent to `search(top=20, min_score=0)`. Change **Photos to pick** to choose a different count. **Other photos** contains the remaining candidates, still sorted highest first and available to download. There is no automatic good/bad cutoff.

## Run the local app

Requires Python 3.10 or newer. From this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[web]"
python -m pinterest_taste.web
```

On Windows, activate the environment with `.venv\Scripts\activate` instead.

The app opens at **http://127.0.0.1:7860**. No Node.js installation or frontend build is needed. Keep the terminal running while using the app; stop it with Ctrl+C.

```bash
python -m pinterest_taste.web --port 7861 --no-browser
```

To start with your Chrome Pinterest login selected:

```bash
python -m pinterest_taste.web --cookies chrome
```

Log in to Pinterest in Chrome first. Cookies are read when you start a search; macOS may ask for permission to access Chrome's saved cookies. You can change the selected browser in the interface.

Describe a photo with a short search phrase, choose how many candidates to fetch, then select **Find photos**. Search starts only when you click the button. The first search downloads about 5 GB of pretrained image models; opening the UI does not download them. Subsequent searches reuse the loaded models.

- Anonymous search is the default. Optionally select a browser where you are logged in to Pinterest, or place `cookies.txt` in the directory where you start the app.
- Progress reports searching, downloading, loading models, and scoring. One search runs at a time.
- Every successfully scored, unique image appears in exactly one group. The selected candidate limit still bounds the search; there is no additional display limit.
- If fewer photos are available than requested, all of them are picked. The remaining group can be empty. Scores express ranking preferences, not probabilities of photo quality.
- The ten most recent searches remain available for the server session. Photos are stored in a temporary directory and removed when the app closes or an old search expires. Download photos you want to keep.
- Photo descriptions and scoring happen locally. Search and image downloads contact Pinterest and its image servers. Model files download from Hugging Face on first use. The UI uses no external fonts, analytics, or paid AI API.

## Search from a reference photo

Click **Attach a photo** or drop one onto the upload area. The app automatically proposes three English search phrases, usually 3–5 words and at most 6. They combine the main topic with a useful detail or two, like `mens gym mirror selfie`, `running aesthetic men outdoors`, or `healthy breakfast eggs and avocado`. Choose one to fill the search box, edit it if needed, and select **Find photos** to run the existing Pinterest search and taste ranking.

- Accepts one still JPG, PNG or WebP at a time, up to 10 MB and 25 megapixels.
- Uses [SmolVLM-500M-Instruct](https://huggingface.co/HuggingFaceTB/SmolVLM-500M-Instruct), downloaded from Hugging Face on first attachment, roughly 1 GB in addition to the scoring models. Text-only searches do not download it. No API key or paid service is required.
- The photo is sent only to your local app. It is oriented, resized and stripped of metadata before description. It is not uploaded to Pinterest or a model provider, saved to disk, or used for training. Only your selected search text is sent to Pinterest.
- Model preparation shows the model name, downloaded MB/GB, percentage, speed and approximate time remaining. Download progress is measured separately for each model; cached files count toward completion. Once files are ready, the UI switches to **Loading into memory**. Speed and time estimates pause when no download progress is reported.
- The description model is released from memory after generating the suggestions. Search and description jobs run one at a time; an attachment never interrupts an active search.
- Model descriptions can be inaccurate. Review the proposed words before searching. Download or model errors appear next to the attachment; you can retry or keep using text search.
- Refreshing the page restores recent description results for the server session, but does not restore the original photo. Attach it again to generate new descriptions.

After updating an already-running app, let any current search finish and restart the app to enable the new upload endpoint. The updated UI detects an older server and keeps uploads disabled until that restart.

The presets are `mens abs aesthetic` and `mens gym aesthetic`. A training interface remains planned. The app does not generate slide copy or render text on photos.

## Python and terminal usage

Type a Pinterest query and get scored pins, best first:

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
git clone https://github.com/Danprog4/pinterest-taste.git
cd pinterest-taste
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
| `pt.rank_pins(query, limit=60, cookies="cookies.txt", progress=None)` | all successfully downloaded pins, scored and sorted; optional `progress(stage, message)` callback |
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

Loading a custom model returns a separate model object; it does not switch the model used by `pt.search()` or the web app. Those currently use the bundled `taste_model.npz`.

## Development

```bash
pip install -e ".[web,dev]"
pytest
```

The tests check ranking, non-overlapping comparison groups, short/empty results, background job state, downloads, bounded image uploads, reference-to-query handoff, request validation, and local access restrictions. They use synthetic images and stub models, so they do not download pretrained models or contact Pinterest. Live model quality and Pinterest access are separate integration checks.

The web app lives in `pinterest_taste/web.py`; its HTML, CSS, and JavaScript are in `pinterest_taste/static/`. The existing Python API and terminal command remain available. The web server binds to loopback only and is intended for local use.

## Status

Tested: scores identical to the original research pipeline; end-to-end `search` runs through gallery-dl.
Not tested here: a logged-in session (cookie steps above are the documented gallery-dl behaviour). Be gentle with limits;
Pinterest can rate-limit or log out an account that scrapes hard.

## Contributing

Contributions are welcome. Help improve photo ranking, add support for different visual styles, fix bugs, or make the local app easier to use. Bug reports and feedback are welcome too.

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and pull request guidance. For larger changes, open an issue first so we can agree on the scope.

## License

This project's code and bundled taste ranker are available under the [MIT License](LICENSE). Dependencies and downloaded pretrained models retain their own licences. Images found through Pinterest belong to their respective owners; the MIT licence does not cover those images.
