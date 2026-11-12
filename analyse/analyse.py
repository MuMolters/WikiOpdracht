"""analyse.py - data-analyse van de robotnet-metingen (WiFi vs 5G).

Leest de ruwe CSV van robotnet.exe en maakt:
  * genummerde figuren (PNG) voor de wiki
  * markdown-tabellen met statistiek (n, loss, gemiddelde, mediaan, p95, sd, jitter, Mbps)

Gebruik:
    py analyse.py ..\\metingen\\metingen.csv --out ..\\wiki\\.attachments
"""
import argparse
import csv
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402,F401

# Gevalideerd categorisch palet (dataviz-skill, light mode), vaste volgorde.
COLORS = {"wifi": "#2a78d6", "5g": "#eb6834", "4g": "#1baf7a"}
FALLBACK = ["#eda100", "#e87ba4", "#6250d6"]
LABEL = {"wifi": "WiFi", "5g": "5G", "4g": "4G"}
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

UDP_TESTS = ["commando_20hz", "sensor_10hz", "sensor_400hz"]
TCP_TESTS = ["camera_50kB", "kaart_1MB", "bulk_up", "bulk_down"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "axes.grid.axis": "y",
    "grid.color": GRID,
    "grid.linewidth": 0.8, "axes.axisbelow": True, "axes.spines.top": False,
    "axes.spines.right": False, "font.size": 10, "axes.titlesize": 11,
    "axes.titleweight": "bold", "legend.frameon": False,
})


def color(net, nets):
    return COLORS.get(net, FALLBACK[nets.index(net) % len(FALLBACK)])


def label(net):
    return LABEL.get(net, net)


def load(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            r["run"] = int(r["run"])
            r["lost"] = int(r["lost"])
            r["seq"] = int(r["seq"])
            r["ms"] = float(r["ms"]) if r["ms"] else None
            r["mbps"] = float(r["mbps"]) if r["mbps"] else None
            rows.append(r)
    return rows


def pct(values, p):
    if not values:
        return math.nan
    v = sorted(values)
    i = p * (len(v) - 1)
    lo, hi = math.floor(i), math.ceil(i)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def jitter(samples):
    """Gemiddelde |RTT_i - RTT_(i-1)| per meetreeks (RFC 3550-achtig), daarna gemiddeld.

    Een meetreeks = één run op één locatie; anders worden reeksen door elkaar gezet."""
    per_run = defaultdict(list)
    for s in sorted(samples, key=lambda s: (s["location"], s["run"], s["seq"])):
        if not s["lost"]:
            per_run[(s["location"], s["run"])].append(s["ms"])
    vals = []
    for rtts in per_run.values():
        d = [abs(b - a) for a, b in zip(rtts, rtts[1:])]
        if d:
            vals.append(sum(d) / len(d))
    return sum(vals) / len(vals) if vals else math.nan


def stats(samples):
    ms = [s["ms"] for s in samples if not s["lost"]]
    mbps = [s["mbps"] for s in samples if not s["lost"] and s["mbps"] is not None]
    n = len(samples)
    return {
        "n": n,
        "loss": 100.0 * sum(s["lost"] for s in samples) / n if n else math.nan,
        "mean": st.mean(ms) if ms else math.nan,
        "median": st.median(ms) if ms else math.nan,
        "p95": pct(ms, 0.95),
        "sd": st.stdev(ms) if len(ms) > 1 else math.nan,
        "jitter": jitter(samples),
        "mbps": st.mean(mbps) if mbps else math.nan,
        "mbps_sd": st.stdev(mbps) if len(mbps) > 1 else math.nan,
        "runs": len({s["run"] for s in samples}),
    }


def fmt(x, d=2):
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def group(rows, *keys):
    g = defaultdict(list)
    for r in rows:
        g[tuple(r[k] for k in keys)].append(r)
    return g


# ------------------------------------------------------------------ figuren

def grouped_box(ax, data, nets, locs, ylabel):
    width = 0.8 / max(len(nets), 1)
    for i, net in enumerate(nets):
        pos = [j + (i - (len(nets) - 1) / 2) * width for j in range(len(locs))]
        vals = [data.get((net, loc), []) or [math.nan] for loc in locs]
        bp = ax.boxplot(vals, positions=pos, widths=width * 0.8, patch_artist=True,
                        showfliers=True, flierprops=dict(marker="o", markersize=3, alpha=0.4,
                                                          markeredgecolor=color(net, nets)),
                        medianprops=dict(color=INK, linewidth=1.5),
                        whiskerprops=dict(color=INK2), capprops=dict(color=INK2))
        for b in bp["boxes"]:
            b.set(facecolor=color(net, nets), edgecolor=SURFACE, linewidth=2, alpha=0.9)
        ax.plot([], [], color=color(net, nets), linewidth=8, label=label(net))
    ax.set_xticks(range(len(locs)))
    ax.set_xticklabels([f"Locatie {l}" for l in locs])
    ax.set_ylabel(ylabel)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.legend(loc="upper left", ncol=len(nets))


def grouped_bar(ax, means, sds, nets, locs, ylabel):
    width = 0.8 / max(len(nets), 1)
    for i, net in enumerate(nets):
        pos = [j + (i - (len(nets) - 1) / 2) * width for j in range(len(locs))]
        m = [means.get((net, loc), math.nan) for loc in locs]
        e = None
        if sds:
            e = [sds.get((net, loc), 0) or 0 for loc in locs]
            e = [0 if math.isnan(x) else x for x in e]
        ax.bar(pos, m, width * 0.92, yerr=e, color=color(net, nets), label=label(net),
               edgecolor=SURFACE, linewidth=2, error_kw=dict(ecolor=INK2, capsize=3, lw=1))
        for x, y in zip(pos, m):
            if not math.isnan(y):
                ax.annotate(fmt(y, 1), (x, y), xytext=(0, 3), textcoords="offset points",
                            ha="center", va="bottom", fontsize=8, color=INK2)
    ax.set_xticks(range(len(locs)))
    ax.set_xticklabels([f"Locatie {l}" for l in locs])
    ax.set_ylabel(ylabel)


def make_figures(rows, out):
    nets = [n for n in ["wifi", "5g", "4g"] if any(r["network"] == n for r in rows)]
    nets += sorted({r["network"] for r in rows} - set(nets))
    locs = sorted({r["location"] for r in rows})
    by = group(rows, "network", "location", "test")
    made = []

    def ms_of(test):
        return {(n, l): [s["ms"] for s in by.get((n, l, test), []) if not s["lost"]]
                for n in nets for l in locs}

    # Figuur A: RTT commando's
    fig, ax = plt.subplots(figsize=(8, 4.2))
    grouped_box(ax, ms_of("commando_20hz"), nets, locs, "Round-trip time (ms, log-schaal)")
    ax.axhline(100, color=INK2, linestyle="--", linewidth=1)
    ax.annotate("eis p95: 100 ms", (ax.get_xlim()[1], 100), xytext=(-4, 4),
                textcoords="offset points", ha="right", fontsize=8, color=INK2)
    ax.set_title("Round-trip time van stuurcommando's (64 B, 20 Hz) per netwerk en locatie")
    fig.tight_layout()
    fig.savefig(out / "fig_rtt_commando.png", dpi=150)
    plt.close(fig)
    made.append("fig_rtt_commando.png")

    # Figuur B: doorvoer upload / download (zelfde eenheid -> gedeelde y-as)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
    for ax, test, title in [(axes[0], "bulk_up", "Upload robot → server"),
                            (axes[1], "bulk_down", "Download server → robot")]:
        means = {(n, l): stats(by[(n, l, test)])["mbps"] for n in nets for l in locs
                 if (n, l, test) in by}
        sds = {(n, l): stats(by[(n, l, test)])["mbps_sd"] for n in nets for l in locs
               if (n, l, test) in by}
        grouped_bar(ax, means, sds, nets, locs, "Doorvoer (Mbit/s)" if ax is axes[0] else "")
        ax.set_title(title)
    axes[0].legend(loc="upper right")
    fig.suptitle("Gemiddelde TCP-doorvoer (bulk, foutbalk = standaardafwijking)",
                 fontweight="bold", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "fig_doorvoer.png", dpi=150)
    plt.close(fig)
    made.append("fig_doorvoer.png")

    # Figuur C: packet loss per UDP-test
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), sharey=True)
    for ax, test in zip(axes, UDP_TESTS):
        means = {(n, l): stats(by[(n, l, test)])["loss"] for n in nets for l in locs
                 if (n, l, test) in by}
        grouped_bar(ax, means, {}, nets, locs, "Packet loss (%)" if ax is axes[0] else "")
        ax.set_title(test)
    axes[0].legend(loc="upper left")
    fig.suptitle("Packet loss per UDP-datastroom", fontweight="bold", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "fig_packetloss.png", dpi=150)
    plt.close(fig)
    made.append("fig_packetloss.png")

    # Figuur D: jitter commando's + sensor_400hz
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    for ax, test in zip(axes, ["commando_20hz", "sensor_400hz"]):
        means = {(n, l): stats(by[(n, l, test)])["jitter"] for n in nets for l in locs
                 if (n, l, test) in by}
        grouped_bar(ax, means, {}, nets, locs, "Jitter (ms)" if ax is axes[0] else "")
        ax.set_title(test)
    axes[0].legend(loc="upper left")
    fig.suptitle("Jitter (gemiddelde |ΔRTT| tussen opeenvolgende pakketten)",
                 fontweight="bold", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "fig_jitter.png", dpi=150)
    plt.close(fig)
    made.append("fig_jitter.png")

    # Figuur E: cameraframes vs eis (100 ms = 10 fps)
    fig, ax = plt.subplots(figsize=(8, 4.2))
    grouped_box(ax, ms_of("camera_50kB"), nets, locs, "Overdrachtstijd per frame (ms, log-schaal)")
    ax.axhline(100, color=INK2, linestyle="--", linewidth=1)
    ax.annotate("eis: 100 ms (10 fps)", (ax.get_xlim()[1], 100), xytext=(-4, 4),
                textcoords="offset points", ha="right", fontsize=8, color=INK2)
    ax.set_title("Overdrachtstijd cameraframe (50 kB, robot → server)")
    fig.tight_layout()
    fig.savefig(out / "fig_camera.png", dpi=150)
    plt.close(fig)
    made.append("fig_camera.png")
    return made, nets, locs


# ------------------------------------------------------------------ tabellen

def tables(rows, nets, locs):
    by = group(rows, "network", "location", "test")
    lines = ["### UDP-datastromen (RTT)", "",
             "| Netwerk | Locatie | Test | n | Loss (%) | Gem. (ms) | Mediaan (ms) | p95 (ms) | SD (ms) | Jitter (ms) |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for test in UDP_TESTS:
        for n in nets:
            for l in locs:
                if (n, l, test) not in by:
                    continue
                s = stats(by[(n, l, test)])
                lines.append(f"| {label(n)} | {l} | {test} | {s['n']} | {fmt(s['loss'])} | "
                             f"{fmt(s['mean'])} | {fmt(s['median'])} | {fmt(s['p95'])} | "
                             f"{fmt(s['sd'])} | {fmt(s['jitter'])} |")
    lines += ["", "### TCP-overdracht", "",
              "| Netwerk | Locatie | Test | n | Mislukt (%) | Gem. tijd (ms) | p95 (ms) | Doorvoer gem. (Mbit/s) | SD (Mbit/s) |",
              "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for test in TCP_TESTS:
        for n in nets:
            for l in locs:
                if (n, l, test) not in by:
                    continue
                s = stats(by[(n, l, test)])
                lines.append(f"| {label(n)} | {l} | {test} | {s['n']} | {fmt(s['loss'])} | "
                             f"{fmt(s['mean'])} | {fmt(s['p95'])} | {fmt(s['mbps'])} | "
                             f"{fmt(s['mbps_sd'])} |")

    # Totaaloverzicht per netwerk (input voor de MCA)
    byn = group(rows, "network", "test")
    lines += ["", "### Totaal per netwerk (alle locaties samen) – input voor MCA", "",
              "| Netwerk | RTT commando gem. (ms) | RTT commando p95 (ms) | Jitter commando (ms) | Loss sensor_400hz (%) | Camera p95 (ms) | Upload (Mbit/s) | Download (Mbit/s) |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for n in nets:
        c = stats(byn.get((n, "commando_20hz"), [])) if (n, "commando_20hz") in byn else None
        h = stats(byn[(n, "sensor_400hz")]) if (n, "sensor_400hz") in byn else None
        cam = stats(byn[(n, "camera_50kB")]) if (n, "camera_50kB") in byn else None
        up = stats(byn[(n, "bulk_up")]) if (n, "bulk_up") in byn else None
        dn = stats(byn[(n, "bulk_down")]) if (n, "bulk_down") in byn else None
        g = lambda s, k: s[k] if s else math.nan  # noqa: E731
        lines.append(f"| {label(n)} | {fmt(g(c, 'mean'))} | {fmt(g(c, 'p95'))} | "
                     f"{fmt(g(c, 'jitter'))} | {fmt(g(h, 'loss'))} | {fmt(g(cam, 'p95'))} | "
                     f"{fmt(g(up, 'mbps'))} | {fmt(g(dn, 'mbps'))} |")
    return "\n".join(lines) + "\n"


def iteration_figure(all_rows, out):
    """Iteratie 1 (via Tailscale DERP-relay) vs iteratie 2 (direct) voor de mobiele netwerken."""
    pairs = [("5g-relay", "5g"), ("4g-relay", "4g")]
    present = [p for p in pairs if any(r["network"] == p[0] for r in all_rows)
               and any(r["network"] == p[1] for r in all_rows)]
    if not present:
        return None, ""
    # Alleen locaties waar ook relay-metingen zijn gedaan, zodat de vergelijking eerlijk is.
    relay_locs = {r["location"] for r in all_rows if r["network"].endswith("-relay")}
    all_rows = [r for r in all_rows if r["location"] in relay_locs]
    by = group(all_rows, "network", "test")
    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    labels, boxes, colors, hatches = [], [], [], []
    for relay, direct in present:
        base = direct
        for net, h, suffix in [(relay, "///", "relay"), (direct, "", "direct")]:
            labels.append(f"{base.upper()}\n{suffix}")
            boxes.append([s["ms"] for s in by.get((net, "commando_20hz"), []) if not s["lost"]]
                         or [math.nan])
            colors.append(COLORS.get(base, FALLBACK[0]))
            hatches.append(h)
    bp = axes[0].boxplot(boxes, patch_artist=True, showfliers=True,
                         flierprops=dict(marker="o", markersize=2, alpha=0.3),
                         medianprops=dict(color=INK, linewidth=1.5))
    for b, c, h in zip(bp["boxes"], colors, hatches):
        b.set(facecolor=c, edgecolor=SURFACE, hatch=h, linewidth=1.5)
    axes[0].set_yscale("log")
    axes[0].set_xticks(range(1, len(labels) + 1))
    axes[0].set_xticklabels(labels)
    axes[0].set_ylabel("RTT commando (ms, log-schaal)")
    axes[0].set_title("RTT stuurcommando's")
    for ax, test, title in [(axes[1], "bulk_up", "Upload (Mbit/s)"),
                            (axes[2], "bulk_down", "Download (Mbit/s)")]:
        vals = []
        for relay, direct in present:
            for net in (relay, direct):
                v = [s["mbps"] for s in by.get((net, test), []) if not s["lost"] and s["mbps"]]
                vals.append(st.mean(v) if v else math.nan)
        x = range(len(vals))
        bars = ax.bar(x, vals, color=colors, edgecolor=SURFACE, linewidth=2)
        for b, h in zip(bars, hatches):
            b.set_hatch(h)
        for xi, y in zip(x, vals):
            if not math.isnan(y):
                ax.annotate(fmt(y, 1), (xi, y), xytext=(0, 3), textcoords="offset points",
                            ha="center", fontsize=8, color=INK2)
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels)
        ax.set_title(title)
    fig.suptitle("Iteratie 1 (via Tailscale-relay, gearceerd) vs iteratie 2 (directe verbinding)",
                 fontweight="bold", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "fig_iteratie_relay_vs_direct.png", dpi=150)
    plt.close(fig)

    lines = ["", f"### Iteratie 1 (relay) vs iteratie 2 (direct) – locatie {', '.join(sorted(relay_locs))}", "",
             "| Netwerk | Route | RTT commando mediaan (ms) | p95 (ms) | Loss sensor_400hz (%) | Upload (Mbit/s) | Download (Mbit/s) |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for relay, direct in present:
        for net, route in [(relay, "relay (DERP)"), (direct, "direct")]:
            c = stats(by[(net, "commando_20hz")])
            h = stats(by[(net, "sensor_400hz")])
            u = stats(by[(net, "bulk_up")])
            d = stats(by[(net, "bulk_down")])
            lines.append(f"| {label(direct)} | {route} | {fmt(c['median'])} | {fmt(c['p95'])} | "
                         f"{fmt(h['loss'])} | {fmt(u['mbps'])} | {fmt(d['mbps'])} |")
    return "fig_iteratie_relay_vs_direct.png", "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--out", default="figuren")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    all_rows = load(a.csv)
    rows = [r for r in all_rows if not r["network"].endswith("-relay")]
    made, nets, locs = make_figures(rows, out)
    md = tables(rows, nets, locs)
    it_fig, it_md = iteration_figure(all_rows, out)
    if it_fig:
        made.append(it_fig)
        md += it_md
    (out / "resultaten_tabellen.md").write_text(md, encoding="utf-8")
    print(f"{len(rows)} metingen | netwerken: {nets} | locaties: {locs}")
    print("Figuren:", ", ".join(made))
    print(md)


if __name__ == "__main__":
    main()
