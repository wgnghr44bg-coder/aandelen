"""Eenmalige verkenning: welke vastgoedfinanciers publiceren rentes, en waar? Print robots.txt-regels en
tekstregels met een %-teken van pagina's die over rente/tarieven gaan. Wordt niet op de site gebruikt."""
import re
import sys
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

AANBIEDERS = {
    "RNHB": ["https://www.rnhb.nl/"],
    "NIBC": ["https://www.nibc.nl/", "https://www.nibc.nl/hypotheken/"],
    "Domivest": ["https://www.domivest.nl/"],
    "Nestr": ["https://www.nestr.nl/"],
    "DCMF": ["https://www.dcmf.nl/"],
    "SolidBriq": ["https://www.solidbriq.nl/", "https://www.solidbriq.com/"],
    "Mogelijk": ["https://www.mogelijk.nl/"],
    "Build": ["https://www.build.nl/", "https://www.buildhypotheek.nl/"],
    "Hyra": ["https://www.hyra.nl/"],
    "Casarion": ["https://www.casarion.nl/"],
}
UA = "Mozilla/5.0 (compatible; InvestMarket-verkenning/1.0)"
KEY = re.compile(r"rente|tarie|rates|voorwaarden|verhuur|belegg|financier|kosten", re.I)


class P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.text, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip and d.strip():
            self.text.append(" ".join(d.split()))


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nl-NL,nl"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.geturl(), r.read(600000).decode("utf-8", "replace")


def main():
    for naam, starts in AANBIEDERS.items():
        print(f"\n========== {naam} ==========")
        for start in starts:
            try:
                final, html = get(start)
            except Exception as e:  # noqa: BLE001
                print(f"  {start}: {e}")
                continue
            base = "{0.scheme}://{0.netloc}/".format(urllib.parse.urlparse(final))
            rp = urllib.robotparser.RobotFileParser(base + "robots.txt")
            try:
                rp.read()
            except Exception as e:  # noqa: BLE001
                print(f"  robots.txt: {e}")
            print(f"  site: {final} (robots: homepage {'toegestaan' if rp.can_fetch(UA, final) else 'NIET toegestaan'})")
            p = P()
            p.feed(html)
            host = urllib.parse.urlparse(final).netloc
            links = []
            for h in p.links:
                u = urllib.parse.urljoin(final, h).split("#")[0]
                if urllib.parse.urlparse(u).netloc == host and KEY.search(u) and u not in links:
                    links.append(u)
            print(f"  relevante links ({len(links)}): {links[:25]}")
            for u in [final] + links[:12]:
                if not rp.can_fetch(UA, u):
                    print(f"  -- {u}: robots.txt staat dit niet toe, overgeslagen")
                    continue
                try:
                    _, h2 = get(u) if u != final else (final, html)
                except Exception as e:  # noqa: BLE001
                    print(f"  -- {u}: {e}")
                    continue
                q = P()
                q.feed(h2)
                regels = [t for t in q.text if "%" in t and re.search(r"\d", t)][:40]
                ruwe = sorted(set(re.findall(r"\d{1,2}[,.]\d{1,2}\s?%", h2)))[:30]
                print(f"  -- {u}\n     tekst met %: {regels}\n     alle x,xx% in html: {ruwe}")
            break
        sys.stdout.flush()


if __name__ == "__main__":
    main()
