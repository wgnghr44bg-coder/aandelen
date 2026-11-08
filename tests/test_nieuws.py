"""Nieuws: RSS lezen (nagemaakte feeds, geen netwerk)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nieuws  # noqa: E402

NOS = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>NOS Economie</title>
<item><title><![CDATA[ECB houdt rente gelijk]]></title><link>https://nos.nl/l/1</link>
<pubDate>Sun, 8 Nov 2026 14:03:51 +0100</pubDate><enclosure url="https://cdn.nos.nl/a.jpg" type="image/jpeg"/></item>
<item><title>Zonder https</title><link>http://nos.nl/l/2</link></item>
</channel></rss>"""
NU = b"""<?xml version="1.0" encoding="utf-8"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item><title>Huizenprijzen stijgen</title><link>https://www.nu.nl/x.html</link>
<pubDate>Sun, 08 Nov 2026 11:12:38 +0100</pubDate><media:content url="https://media.nu.nl/b.jpg"/></item>
<item><title>ECB houdt rente gelijk</title><link>https://www.nu.nl/y.html</link>
<pubDate>Sun, 08 Nov 2026 09:00:00 +0100</pubDate></item>
</channel></rss>"""


def test_lees_feed():
    items = nieuws.lees_feed(NOS, "NOS")
    assert items == [{"t": "ECB houdt rente gelijk", "url": "https://nos.nl/l/1", "src": "NOS",
                      "ts": "2026-11-08T13:03:51Z", "img": "https://cdn.nos.nl/a.jpg"}]
    nu = nieuws.lees_feed(NU, "NU.nl")
    assert nu[0]["img"] == "https://media.nu.nl/b.jpg" and nu[1]["img"] is None


class _Resp:
    def __init__(self, b):
        self.b = b

    def read(self):
        return self.b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_haal_nieuws_sorteert_en_ontdubbelt(monkeypatch):
    feeds = {nieuws.FEEDS[0][1]: NOS, nieuws.FEEDS[1][1]: NU}
    monkeypatch.setattr(nieuws.urllib.request, "urlopen", lambda req, **k: _Resp(feeds[req.full_url]))
    uit = nieuws.haal_nieuws()
    assert [x["t"] for x in uit] == ["ECB houdt rente gelijk", "Huizenprijzen stijgen"]
    assert uit[0]["src"] == "NOS"


def test_haal_nieuws_terugval(monkeypatch):
    def fout(*a, **k):
        raise OSError("geen netwerk")
    monkeypatch.setattr(nieuws.urllib.request, "urlopen", fout)
    vorige = [{"t": "oud", "url": "https://x", "src": "NOS", "ts": None, "img": None}]
    assert nieuws.haal_nieuws(vorige) == vorige
