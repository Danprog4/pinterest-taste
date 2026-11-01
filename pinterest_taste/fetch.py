"""Pinterest search through gallery-dl's Python API (no CLI, no browser)."""
import os
import urllib.parse

from gallery_dl import config, extractor
from gallery_dl.extractor.message import Message


BROWSERS = {"chrome", "firefox", "safari", "edge", "brave", "chromium", "opera", "vivaldi"}


class CookiesError(RuntimeError):
    pass


def search_pins(query, limit=60, cookies="cookies.txt"):
    """Yield {'id', 'url', 'title', 'meta'} for the first `limit` pins of a Pinterest search."""
    config.clear()
    if cookies in BROWSERS:  # read the login straight from the browser, nothing to export
        config.set(("extractor",), "cookies", [cookies])
    elif cookies:
        cookies = os.path.expanduser(cookies)
        if os.path.exists(cookies):
            config.set(("extractor",), "cookies", cookies)
        elif cookies != "cookies.txt":  # an explicit path that is missing is a mistake; the default just means "anonymous"
            raise CookiesError(f"{cookies} not found - see 'Cookies' in the README")
    config.set(("extractor", "pinterest"), "videos", False)
    url = "https://www.pinterest.com/search/pins/?q=" + urllib.parse.quote_plus(query)
    ex = extractor.find(url)
    if ex is None:
        raise RuntimeError("gallery-dl has no Pinterest search extractor")
    ex.initialize()
    n = 0
    for msg in ex:
        if msg[0] != Message.Url:
            continue
        _, file_url, meta = msg
        yield {"id": str(meta.get("id") or meta.get("pin_id") or n), "url": file_url,
               "title": meta.get("title") or meta.get("description") or "", "meta": meta}
        n += 1
        if n >= limit:
            break
