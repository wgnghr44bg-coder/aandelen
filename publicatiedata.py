"""Zoekt (dagelijks, buiten de gewone update) op welke dag de ECB elk maandcijfer heeft bijgewerkt en
bewaart dat in docs/publicatie.json: {reeks: {"period": JJJJ-MM, "upd": JJJJ-MM-DD}}.
De ECB API is soms traag; daarom hier met ruime tijd in plaats van in de update van elke 30 minuten.
Een al gevonden datum voor dezelfde periode wordt niet opnieuw gezocht."""
import json

import macro

REEKSEN = [  # (naam in data.json, ECB-sleutel)
    ("euribor3m", "FM/M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA"),
    ("nl10y", "IRS/M.NL.L.L40.CI.0000.EUR.N.Z"),
    ("nfc_loans_nl", "MIR/M.NL.B.A2A.A.R.A.2240.EUR.N"),
    ("mortgage_nl", macro.HYP_KEY),
    ("business_nl", macro.BIZ_KEY),
]


def main():
    m = json.loads((macro.PUBLICATIE.parent / "data.json").read_text()).get("macro") or {}
    try:
        pub = json.loads(macro.PUBLICATIE.read_text())
    except Exception:  # noqa: BLE001
        pub = {}
    macro.UPD_BUDGET["s"] = 600.0
    macro.HTTP_TIMEOUT["s"] = 120
    for naam, key in REEKSEN:
        x = m.get(naam)
        x = x[0] if isinstance(x, list) and x else x
        periode = (x or {}).get("date")
        if not periode:
            continue
        oud = pub.get(key) or {}
        if oud.get("period") == periode and oud.get("upd"):
            print(f"{naam}: {periode} al bekend ({oud['upd']})")
            continue
        upd = macro.ecb_bijgewerkt(key, periode)
        print(f"{naam}: {periode} bijgewerkt op {upd}")
        if upd:
            pub[key] = {"period": periode, "upd": upd}
    macro.PUBLICATIE.write_text(json.dumps(pub, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
