"""corrigeer.py - past gedocumenteerde labelcorrecties toe op de ruwe meetdata.

De ruwe CSV (metingen_ruw.csv) blijft ongewijzigd; het resultaat gaat naar metingen.csv.
Elke correctie staat hieronder met reden, zodat de bewerking controleerbaar is.

Gebruik:
    py corrigeer.py <ruwe_csv> <uit_csv>
"""
import csv
import sys

# (netwerk, verkeerde locatie, tijd van, tijd tot) -> juiste locatie, reden
CORRECTIES = [
    (("5g", "A", "2026-11-11 12:24:30", "2026-11-11 12:30:07"), "B",
     "Bij het starten per ongeluk --location A ingevoerd; meting is uitgevoerd op locatie B "
     "(direct na WiFi-B en vóór 4G-B, zonder te verplaatsen)."),
]

# Iteratie 1: mobiele metingen liepen via een Tailscale DERP-relay (Londen) i.p.v. direct.
# Deze worden niet weggegooid maar als aparte 'netwerken' gelabeld, zodat ze vergeleken
# kunnen worden met iteratie 2 (direct, na port forwarding UDP 41641).
ITERATIE1_TOT = "2026-11-11 12:40:00"
RELAY_LABEL = {"5g": "5g-relay", "4g": "4g-relay"}


def main(src, dst):
    with open(src, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fields = list(rows[0].keys())
    changed = [0] * len(CORRECTIES)
    relabeled = 0
    for r in rows:
        for i, ((net, loc, t0, t1), new_loc, _) in enumerate(CORRECTIES):
            if r["network"] == net and r["location"] == loc and t0 <= r["timestamp"] <= t1:
                r["location"] = new_loc
                changed[i] += 1
        if r["network"] in RELAY_LABEL and r["timestamp"] <= ITERATIE1_TOT:
            r["network"] = RELAY_LABEL[r["network"]]
            relabeled += 1
    print(f"Iteratie 1 (relay): {relabeled} rijen gelabeld als *-relay")
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    for (key, new_loc, why), n in zip(CORRECTIES, changed):
        print(f"{key} -> locatie {new_loc}: {n} rijen gecorrigeerd ({why})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
