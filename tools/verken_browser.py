"""Verkenning 3: zichtbare tekst (innerText) van rentepagina's na het laden van JavaScript."""
import socket
import sys
import urllib.robotparser

from playwright.sync_api import sync_playwright

socket.setdefaulttimeout(20)
UA = "Mozilla/5.0 (compatible; InvestMarket-verkenning/1.0)"
PAGINAS = [
    "https://www.nestr.nl/rente",
    "https://build.quantleap.nl/widgets/rates",
    "https://build-finance.com/rentes",
    "https://www.solidbriq.nl/actuele-rentetarieven/",
    "https://nibc.nl/vastgoed-hypotheek/rentes-vastgoed-hypotheek",
    "https://dcmf.nl/verhuurhypotheek/",
    "https://www.mogelijk.nl/verhuurhypotheek",
    "https://www.casarion.com/rente-residentieel",
    "https://www.casarion.com/rente-commercieel",
]
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(user_agent=UA, locale="nl-NL")
    for u in PAGINAS:
        host = u.split("/")[0] + "//" + u.split("/")[2] + "/robots.txt"
        rp = urllib.robotparser.RobotFileParser(host)
        try:
            rp.read()
            ok = rp.can_fetch(UA, u)
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"robots {host}: {e}")
        print(f"\n########## {u} (robots {'ok' if ok else 'NIET ok'})")
        if not ok:
            continue
        pg = ctx.new_page()
        try:
            pg.goto(u, wait_until="networkidle", timeout=45000)
            pg.wait_for_timeout(3000)
            txt = pg.inner_text("body")
            print(txt[:7000])
            if "nibc" in u:
                for tab in ("Tussen 1 en 2,5 miljoen", "Boven 2,5 miljoen"):
                    try:
                        pg.get_by_text(tab, exact=True).first.click(timeout=5000)
                        pg.wait_for_timeout(1500)
                        t2 = pg.inner_text("body")
                        i = t2.find("t/m 50 % MW")
                        print(f"--- NIBC na klik op {tab!r}:", t2[i - 200:i + 900])
                    except Exception as e:  # noqa: BLE001
                        print(f"--- NIBC klik {tab}: {e}")
            frames = [f.url for f in pg.frames]
            print("FRAMES:", frames)
        except Exception as e:  # noqa: BLE001
            print(f"fout: {e}")
        pg.close()
        sys.stdout.flush()
    b.close()
