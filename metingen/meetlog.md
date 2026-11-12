# Meetlog

Datum: 2026-11-11

Internetsnelheid woning (speedtest op desktop/server): download ±900 Mbit/s · upload ___ Mbit/s · ping ___ ms

Referentie-speedtest telefoon (Ookla Speedtest-app), locatie B:
* 5G: download ±30 Mbit/s · upload ±7 Mbit/s
* 4G: ___

Vergelijking met robotnet (5G, B): download 18,9 Mbit/s (±63 % van Ookla), upload 5,8 Mbit/s (±83 %). Bottleneck = mobiele verbinding op locatie B, niet de internetverbinding van de server.
Server: desktop, bekabeld (ja/nee): ___
5G-verbinding laptop: USB-tethering / WiFi-hotspot: ___ · provider: ___

Tailscale op telefoon: uitgeschakeld tijdens metingen.

## Netwerkroute (gecontroleerd vanaf de server)

| Tijd | Bevinding |
|---|---|
| 12:14 | WiFi: `tailscale ping laptopniek` → direct via IPv6 thuisnetwerk (LAN). |
| 12:40 | Na de 5G/4G-metingen op B: route via **DERP-relay Londen** ("direct connection not established"). `tailscale netcheck`: thuis-NAT eenvoudig (MappingVariesByDestIP: false), maar **geen PortMapping (UPnP/NAT-PMP)**; mobiel netwerk achter CGNAT. → Iteratie 1 (12:24–12:40) gemeten via relay. |
| 12:5x | Router: port forwarding **UDP 41641 → 192.168.0.65:41641** (Tailscale-poort server). |
| 12:5x | `tailscale ping laptopniek` (laptop op mobiel netwerk) → **direct** via IP van provider, 19 ms. Start iteratie 2. |

## Correcties op de data
* 5G-meting 12:24:30–12:30:07 per ongeluk gelabeld als locatie A; uitgevoerd op B → gecorrigeerd in `corrigeer.py` (ruwe data ongewijzigd in `metingen_ruw.csv`).
* Mobiele metingen vóór 12:40 gelabeld als `5g-relay` / `4g-relay` (iteratie 1).

## Metingen

| Tijd | Locatie | Netwerk | Signaal laptop (WiFi %) / telefoon (5G-type, balkjes/dBm) | WiFi band/kanaal | Tailscale-route (direct/relay) | Opmerkingen |
|---|---|---|---|---|---|---|
| | A | wifi | | | | |
| | A | 5g | | – | | |
| | B | wifi | | | | |
| | B | 5g | | – | | |
| | C | wifi | | | | |
| | C | 5g | | – | | |
