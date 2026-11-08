"""Financieel nieuws: echte koppen uit gratis RSS-feeds (NOS Economie, NU.nl Economie).

Alleen titel, link, bron, tijd en (als de feed die geeft) een afbeelding. Geen eigen teksten.
Lukt ophalen niet, dan blijven de koppen van de vorige run staan.
"""
import re
import ssl
import urllib.request
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime

FEEDS = [
    ("NOS", "https://feeds.nos.nl/nosnieuwseconomie"),
    ("NU.nl", "https://www.nu.nl/rss/Economie"),
]
MAX = 8
MEDIA = "{http://search.yahoo.com/mrss/}"


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _tekst(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def lees_feed(xml, bron):
    """[{t, url, src, ts, img}] uit RSS-xml (bytes of str)."""
    root = ET.fromstring(xml)
    uit = []
    for it in root.iter("item"):
        titel, link = _tekst(it.findtext("title")), _tekst(it.findtext("link"))
        if not titel or not link.startswith("https://"):
            continue
        ts = None
        try:
            ts = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:  # noqa: BLE001
            pass
        img = None
        for el in (it.find("enclosure"), it.find(MEDIA + "content"), it.find(MEDIA + "thumbnail")):
            if el is not None and (el.get("url") or "").startswith("https://") \
                    and (el.get("type") or "image").startswith("image"):
                img = el.get("url")
                break
        uit.append({"t": titel, "url": link, "src": bron, "ts": ts, "img": img})
    return uit


def haal_nieuws(vorige=None):
    alle, ok = [], False
    for bron, url in FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (investmarket; nieuwsoverzicht)"})
            with urllib.request.urlopen(req, timeout=20, context=_ctx()) as r:
                items = lees_feed(r.read(), bron)
            print(f"nieuws {bron}: {len(items)} koppen")
            alle += items
            ok = ok or bool(items)
        except Exception as e:  # noqa: BLE001
            print(f"nieuws {bron} mislukt: {e}")
    if not ok:
        return vorige or []
    # nieuwste eerst, dubbele koppen eruit, per bron hoogstens de helft (zodat één drukke feed niet alles vult)
    gezien, per_bron, uit = set(), {}, []
    for x in sorted(alle, key=lambda x: x["ts"] or "", reverse=True):
        k = x["t"].lower()
        if k in gezien or per_bron.get(x["src"], 0) >= MAX // 2:
            continue
        gezien.add(k)
        per_bron[x["src"]] = per_bron.get(x["src"], 0) + 1
        uit.append(x)
    if len(uit) < MAX:  # een bron leverde te weinig: aanvullen met de rest
        rest = [x for x in sorted(alle, key=lambda x: x["ts"] or "", reverse=True) if x["t"].lower() not in gezien]
        for x in rest:
            if x["t"].lower() not in gezien:
                gezien.add(x["t"].lower())
                uit.append(x)
        uit.sort(key=lambda x: x["ts"] or "", reverse=True)
    return uit[:MAX]
