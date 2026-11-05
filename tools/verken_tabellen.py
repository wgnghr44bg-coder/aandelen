"""Verkenning 2: volledige tekstvolgorde en tabelstructuur van de rentepagina's, plus scripts/API-adressen
bij pagina's die hun rentes met JavaScript laden. Alleen pagina's die robots.txt toestaat."""
import re
import sys
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

UA = "Mozilla/5.0 (compatible; InvestMarket-verkenning/1.0)"
PAGINAS = [
    "https://nibc.nl/vastgoed-hypotheek/rentes-vastgoed-hypotheek",
    "https://dcmf.nl/verhuurhypotheek/",
    "https://www.mogelijk.nl/verhuurhypotheek",
    "https://www.casarion.com/rente-residentieel",
    "https://www.casarion.com/rente-commercieel",
    "https://www.solidbriq.nl/actuele-rentetarieven/",
    "https://www.solidbriq.nl/vaststelling-variabele-rente/",
    "https://www.nestr.nl/rente",
    "https://build-finance.com/rentes",
    "https://www.domivest.nl/",
    "https://domivest.nl/",
    "https://hyra.nl/nl-nl",
]


class P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip, self.scripts, self.links = [], 0, [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self.skip += 1
            if tag == "script" and a.get("src"):
                self.scripts.append(a["src"])
        if tag in ("table", "tr", "thead", "tbody", "h1", "h2", "h3", "h4", "li", "p"):
            self.out.append(f"<{tag}>")
        if tag in ("td", "th"):
            self.out.append("|")
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip and d.strip():
            self.out.append(" ".join(d.split()))


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nl-NL,nl"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.geturl(), r.read(1500000).decode("utf-8", "replace")


robots = {}
for u in PAGINAS:
    print(f"\n########## {u}")
    host = "{0.scheme}://{0.netloc}/".format(urllib.parse.urlparse(u))
    if host not in robots:
        rp = urllib.robotparser.RobotFileParser(host + "robots.txt")
        try:
            rp.read()
        except Exception as e:  # noqa: BLE001
            print(f"robots: {e}")
        robots[host] = rp
    if not robots[host].can_fetch(UA, u):
        print("robots.txt: NIET toegestaan")
        continue
    try:
        final, html = get(u)
    except Exception as e:  # noqa: BLE001
        print(f"fout: {e}")
        continue
    p = P()
    p.feed(html)
    tekst = " ".join(p.out)
    print(f"final: {final} · {len(html)} bytes")
    print("TEKST:", tekst[:9000])
    print("SCRIPTS:", p.scripts[:30])
    api = sorted(set(re.findall(r"""["'](https?://[^"']*(?:api|rente|rate|tarie|json|graphql)[^"']*)["']""", html, re.I)))[:30]
    rel = sorted(set(re.findall(r"""["'](/[^"' ]*(?:api|rente|rate|tarie|\.json)[^"' ]*)["']""", html, re.I)))[:30]
    print("API/JSON-ADRESSEN:", api, rel)
    if "domivest" in u or "hyra" in u:
        print("LINKS:", sorted(set(p.links))[:80])
    sys.stdout.flush()
