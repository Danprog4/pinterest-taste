import logging

import pytest
import requests
from gallery_dl import config, cookies
from gallery_dl.extractor import common

from pinterest_taste import fetch


@pytest.mark.parametrize("browser", ["chrome", "safari"])
def test_browser_option_reaches_gallery_dl_cookie_reader(monkeypatch, browser):
    calls = []
    def load(source):
        calls.append(source)
        return [requests.cookies.create_cookie("test_cookie", "test_value", domain=".pinterest.com")]

    class Extractor:
        log = logging.getLogger("cookie-test")
        def __init__(self):
            self.cookies = requests.cookies.RequestsCookieJar()
        def initialize(self):
            common.Extractor.cookies_load(self, config.get(("extractor",), "cookies"))
        def __iter__(self):
            return iter(())

    extractor = Extractor()
    monkeypatch.setattr(common, "CACHE_COOKIES", {})
    monkeypatch.setattr(cookies, "load_cookies", load)
    monkeypatch.setattr(fetch.extractor, "find", lambda url: extractor)
    assert list(fetch.search_pins("gym", cookies=browser)) == []
    assert calls == [[browser]]
    assert extractor.cookies.get("test_cookie") == "test_value"
