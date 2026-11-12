# robotnet-onderzoek

Praktijkonderzoek *"Hoe beïnvloeden WiFi en 5G de datadoorvoer en stabiliteit van de communicatie tussen zorglogistieke robots en hun vlootserver in een zorginstelling met meerdere verdiepingen?"* (casus Zorglogistiek, INNO-WAY).

| Map | Inhoud |
|---|---|
| `prototype/` | `robotnet.cpp` – C++17 meetopstelling (client = robot, server = vlootserver), `build.bat` |
| `analyse/` | `corrigeer.py` – gedocumenteerde labelcorrecties · `analyse.py` – statistiek, figuren, tabellen |
| `metingen/` | `metingen_ruw.csv` (onbewerkt) · `metingen.csv` (na correctie) · `meetlog.md` |

De onderzoeksverslaglegging (probleemanalyse, resultaten, MCA, conclusie) staat in de wiki van het project in Azure DevOps, niet in deze repository. Figuren en tabellen zijn te reproduceren met `analyse.py` (zie stap 4).

## Reproduceren

```bash
# 1. Bouwen
prototype\build.bat    # Windows, Visual Studio 2022 (MSVC)

# 2. Server (bekabeld, poort 5201 TCP+UDP open in firewall)
robotnet server

# 3. Client per locatie en netwerk (controleer eerst: tailscale ping <server> -> 'direct')
robotnet client --host <server> --network wifi --location B --runs 3 --out metingen.csv
robotnet client --host <server> --network 5g   --location B --runs 3 --out metingen.csv

# 4. Analyse (Python 3 + matplotlib)
py analyse/corrigeer.py metingen/metingen_ruw.csv metingen/metingen.csv
py analyse/analyse.py metingen/metingen.csv --out figuren
```

Let op: bij een mobiele verbinding achter CGNAT moet de server direct bereikbaar zijn (bijv. port forwarding UDP 41641 voor Tailscale), anders loopt het verkeer via een relay en zijn de metingen niet valide (zie de wiki, Resultaten §4.2).
