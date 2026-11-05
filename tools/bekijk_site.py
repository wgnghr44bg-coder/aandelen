"""Tijdelijk: bekijkt een website met een echte browser (techniek, tekst, schermafdrukken). Niet voor de site."""
import json
import re
import socket
import sys
import urllib.robotparser
from pathlib import Path

from playwright.sync_api import sync_playwright

socket.setdefaulttimeout(20)
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
OUT = Path("tmp_bekijk")
OUT.mkdir(exist_ok=True)
for url in sys.argv[1:]:
    host = "/".join(url.split("/")[:3])
    rp = urllib.robotparser.RobotFileParser(host + "/robots.txt")
    try:
        rp.read()
        print(f"robots.txt {host}: {'toegestaan' if rp.can_fetch(UA, url) else 'NIET toegestaan'}")
        if not rp.can_fetch(UA, url):
            continue
    except Exception as e:  # noqa: BLE001
        print(f"robots.txt {host}: {e}")
    with sync_playwright() as p:
        b = p.chromium.launch()
        for naam, opts in (("mobiel", p.devices["iPhone 13"]), ("desktop", {"viewport": {"width": 1366, "height": 900}})):
            ctx = b.new_context(**opts)
            pg = ctx.new_page()
            reqs = []
            pg.on("request", lambda r: reqs.append(r.url))
            try:
                pg.goto(url, wait_until="networkidle", timeout=45000)
            except Exception as e:  # noqa: BLE001
                print(f"{url}: {e}")
            pg.wait_for_timeout(3000)
            slug = re.sub(r"\W+", "_", url)[8:40]
            pg.screenshot(path=str(OUT / f"{slug}_{naam}.png"), full_page=True)
            if naam == "mobiel":
                print("FINAL URL:", pg.url, "| TITEL:", pg.title())
                html = pg.content()
                print("META:", re.findall(r'<meta[^>]+(?:generator|description|application-name|theme-color)[^>]*>', html)[:8])
                print("SCRIPTS:", sorted(set(re.findall(r'<script[^>]+src="([^"]+)"', html)))[:25])
                tech = {k: k.lower() in html.lower() for k in ("__NEXT_DATA__", "_next/", "data-reactroot", "ng-version",
                        "__nuxt", "data-v-", "flutter", "svelte", "vite", "tailwind", "webflow", "framer", "bubble", "wix")}
                print("TECH-HINTS:", {k: v for k, v in tech.items() if v})
                hosts = sorted({r.split('/')[2] for r in reqs if r.startswith('http')})
                print("VERZOEKEN NAAR:", hosts[:40])
                print("TEKST:", re.sub(r"\s+", " ", pg.inner_text("body"))[:3000])
            ctx.close()
        b.close()
