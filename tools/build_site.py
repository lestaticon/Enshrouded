#!/usr/bin/env python3
"""Assemble the guide website's source folder and (optionally) build or serve it.

The knowledge base keeps its Markdown pages in top-level folders (locations/,
crafting/, ...) and its structured data in data/. MkDocs needs everything in
one folder, so this script:

1. copies the Markdown folders into .site-src/
2. generates player-friendly crafting pages from data/early-game-crafting.yaml
3. writes the home page

Usage:
    python tools/build_site.py          # assemble .site-src/ only
    python tools/build_site.py build    # assemble, then build the site into site/
    python tools/build_site.py serve    # assemble, then preview at http://127.0.0.1:8000
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".site-src"
CONTENT_DIRS = ["activities", "locations", "navigation", "items", "crafting"]
CRAFTING_DATA = ROOT / "data" / "early-game-crafting.yaml"

SECTIONS = [  # (yaml key, page file, page title, intro)
    ("stations", "stations.md", "Crafting stations",
     "Benches, kilns and furnaces you build at your base. Most need to sit inside a Flame Altar area."),
    ("materials", "materials.md", "Materials",
     "Refined materials and the chains behind them: charcoal, metal sheets, bars."),
    ("tools", "tools.md", "Tools",
     "Axes, pickaxes, the glider, the grappling hook and other gear."),
    ("weapons", "weapons.md", "Weapons",
     "Bows, melee weapons, staffs, wands and shields, from hand-crafted to bronze."),
]

CONFIDENCE = {
    "confirmed": '<span class="kb-badge kb-ok" title="Two sources agree">✅ Confirmed</span>',
    "single_source": '<span class="kb-badge kb-one" title="One source, nothing contradicts it">🟡 One source</span>',
    "uncertain": '<span class="kb-badge kb-warn" title="Sources disagree or are unclear">⚠️ Check in game</span>',
}

STATION_NAMES = {
    "hand": "By hand",
    "none": "Can't be crafted",
    "blacksmith": "Blacksmith (Oswald Anders)",
}

# Ids whose plain title-casing reads wrong.
NAME_FIXES = {
    "fenrigs": "Fenrig's",
    "pikemeads": "Pikemead's",
    "lupas": "Lupa's",
    "jezminas": "Jezmina's",
    "heros": "Hero's",
    "wolfs": "Wolf's",
    "or": "or",
    "of": "of",
}


def nice_name(item_id: str) -> str:
    """fenrigs_axe_11 -> Fenrig's Axe (Lvl 11); pikemeads_bulwark_copper -> Pikemead's Bulwark (Copper)."""
    parts = item_id.split("_")
    suffix = ""
    if parts[-1].isdigit():
        suffix = f" (Lvl {parts.pop()})"
    elif parts[-1] in {"scrap", "copper", "bronze"} and len(parts) > 2:
        suffix = f" ({parts.pop().title()})"
    words = [NAME_FIXES.get(p, p.capitalize()) for p in parts]
    return " ".join(words) + suffix


def anchor(item_id: str) -> str:
    return item_id.replace("_", "-")


def source_label(key: str) -> str:
    """atw_blacksmith -> AllThings.How (blacksmith); wiki_forge -> Enshrouded Wiki (forge)."""
    prefix, _, rest = key.partition("_")
    site = {"atw": "AllThings.How", "wiki": "Enshrouded Wiki"}.get(prefix)
    return f"{site} ({rest.replace('_', ' ')})" if site and rest else key


def md_escape(text: str) -> str:
    return str(text).replace("|", "\\|")


def copy_content() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    for name in CONTENT_DIRS:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, OUT / name, ignore=shutil.ignore_patterns("_*"))
    shutil.copytree(ROOT / "site-assets", OUT / "assets")


def station_link(station: str, where: dict[str, str]) -> str:
    if station in STATION_NAMES:
        return STATION_NAMES[station]
    if station in where:
        return f"[{nice_name(station)}]({where[station]}#{anchor(station)})"
    return nice_name(station)


def item_link(item_id: str, where: dict[str, str], here: str) -> str:
    if item_id in where:
        page = where[item_id]
        target = f"#{anchor(item_id)}" if page == here else f"{page}#{anchor(item_id)}"
        return f"[{nice_name(item_id)}]({target})"
    return nice_name(item_id)


def render_entry(item_id: str, e: dict, *, page: str, where: dict, used_in: dict, sources: dict) -> str:
    out = [f"### {nice_name(item_id)} {{#{anchor(item_id)}}}", ""]
    out.append(CONFIDENCE.get(e.get("confidence", ""), ""))
    out.append("")

    facts = []
    stations = e.get("crafted_at")
    if stations:
        stations = stations if isinstance(stations, list) else [stations]
        facts.append(("Made at", " or ".join(station_link(s, where) for s in stations)))
    if "level" in e:
        facts.append(("Level", str(e["level"])))
    if e.get("output", 1) != 1:
        facts.append(("Makes", f"{e['output']} per craft"))
    if "craft_time_s" in e:
        secs = int(e["craft_time_s"])
        facts.append(("Craft time", f"{secs // 60} min {secs % 60} s" if secs >= 60 else f"{secs} s"))
    if e.get("unlock"):
        facts.append(("Unlock", md_escape(e["unlock"])))
    if e.get("purpose"):
        facts.append(("Used for", md_escape(e["purpose"])))

    ingredients = e.get("ingredients") or {}
    if ingredients:
        out += ["| You need | Amount |", "|---|---:|"]
        for ing, qty in ingredients.items():
            out.append(f"| {item_link(ing, where, page)} | {qty} |")
        out.append("")

    if e.get("obtain"):
        out.append("**Where to get it:**")
        out.append("")
        out += [f"- {md_escape(x)}" for x in e["obtain"]]
        out.append("")

    if facts:
        out += [f"- **{k}:** {v}" for k, v in facts]
        out.append("")

    if used_in.get(item_id):
        links = ", ".join(item_link(u, where, page) for u in sorted(used_in[item_id], key=nice_name))
        out += [f"**Used in:** {links}", ""]

    if e.get("note"):
        kind = "warning" if e.get("confidence") == "uncertain" else "note"
        out += [f'!!! {kind} "Note"', f"    {e['note']}", ""]

    if e.get("sources"):
        refs = ", ".join(f"[{source_label(s)}]({sources[s]})" if s in sources else s for s in e["sources"])
        out += [f'<small class="kb-sources">Sources: {refs}</small>', ""]

    return "\n".join(out)


def generate_crafting() -> None:
    if not CRAFTING_DATA.exists():
        return
    data = yaml.safe_load(CRAFTING_DATA.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    sources = meta.get("sources", {})
    target = OUT / "crafting"
    target.mkdir(exist_ok=True)

    where: dict[str, str] = {}
    for key, page, _, _ in SECTIONS:
        for item_id in data.get(key, {}) or {}:
            where[item_id] = page

    used_in: dict[str, set[str]] = defaultdict(set)
    for key, *_ in SECTIONS:
        for item_id, e in (data.get(key) or {}).items():
            for ing in (e.get("ingredients") or {}):
                used_in[ing].add(item_id)

    header = (
        f"!!! info \"About this data\"\n"
        f"    Enshrouded {meta.get('game_version', '?')}, compiled {meta.get('compiled', '?')} from community guides. "
        f"Same recipes on PS5 and PC. ✅ = two sources agree, 🟡 = one source, ⚠️ = check in game.\n"
    )

    for key, page, title, intro in SECTIONS:
        entries = data.get(key) or {}
        body = [f"---\ntitle: {title}\n---", f"# {title}", "", intro, "", header]
        # Short jump list so you don't have to scroll on a phone.
        body.append("**Jump to:** " + " · ".join(f"[{nice_name(i)}](#{anchor(i)})" for i in entries))
        body.append("")
        for item_id, e in entries.items():
            body.append(render_entry(item_id, e, page=page, where=where, used_in=used_in, sources=sources))
        (target / page).write_text("\n".join(body), encoding="utf-8")

    # Overview page: the order things unlock in, plus open questions.
    lines = [
        "---\ntitle: Crafting progression\n---",
        "# Crafting progression",
        "",
        "The order the early game unlocks things, from the Cinder Vault to bronze. "
        "Tap any item to see what it costs.",
        "",
        header,
        "| Pages | |",
        "|---|---|",
    ]
    for _, page, title, intro in SECTIONS:
        lines.append(f"| [{title}]({page}) | {intro} |")
    lines.append("")
    lines.append("## Step by step")
    lines.append("")
    for step in data.get("progression", []):
        lines.append(f"### {step['step']}. {md_escape(step['action'])}")
        lines.append("")
        lines.append(CONFIDENCE.get(step.get("confidence", ""), ""))
        lines.append("")
        lines.append(f"- **Where:** {md_escape(step['where'])}")
        if step.get("npc"):
            lines.append(f"- **Who:** {md_escape(step['npc'])}")
        if step.get("then"):
            lines.append(f"- **Then:** {md_escape(step['then'])}")
        unlocks = step.get("unlocks") or []
        if unlocks:
            lines.append("- **Unlocks:** " + ", ".join(item_link(u, where, "index.md") for u in unlocks))
        if step.get("note"):
            lines.append(f"- *{md_escape(step['note'])}*")
        lines.append("")
    if data.get("open_questions"):
        lines += ["## Still to check in game", ""]
        lines += [f"- [ ] {q}" for q in data["open_questions"]]
        lines.append("")
    (target / "index.md").write_text("\n".join(lines), encoding="utf-8")


def write_home() -> None:
    sections = []
    if (OUT / "locations").is_dir():
        pages = sorted(p for p in (OUT / "locations").glob("*.md") if p.name.lower() not in {"readme.md", "index.md"})
        for p in pages:
            sections.append(f"- :material-map-marker: **[{title_of(p)}](locations/{p.name})**")
    home = f"""---
title: Home
hide:
  - toc
---

# Enshrouded field guide

A player-friendly guide for **Enshrouded** (PS5 and PC): where to go, what to craft, and how it all unlocks.
Keep it open on your phone next to the console.

<div class="grid cards" markdown>

-   :material-map: **Locations**

    ---

    Regions, bosses, shrines and points of interest.

{chr(10).join('    ' + s for s in sections) or '    Coming soon.'}

-   :material-hammer-wrench: **Crafting**

    ---

    What to build first, and what every recipe costs.

    [:octicons-arrow-right-24: Crafting progression](crafting/index.md)

</div>

## How to use this on a phone

- Tap **:material-magnify: search** at the top and type any item, for example *charcoal* or *glider*.
- Tap **:material-menu: the menu** (top left) to browse by section.
- Tap the **:material-brightness-6: sun/moon** icon to switch between dark and light.
- Add it to your home screen: in your phone browser, use *Share → Add to Home Screen* (iPhone) or *⋮ → Add to Home screen* (Android).

## How sure is this?

Everything here comes from community guides for **Enshrouded 1.0** (released 15 October 2026) and has not all been checked in game yet.

| Mark | Meaning |
|---|---|
| ✅ Confirmed | Two independent sources agree |
| 🟡 One source | One up-to-date source, nothing contradicts it |
| ⚠️ Check in game | Sources disagree or are unclear |
"""
    (OUT / "index.md").write_text(home, encoding="utf-8")


def title_of(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^title:\s*(.+)$", text, re.M)
    if m:
        return m.group(1).strip().strip("\"'")
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else path.stem.replace("-", " ").title()


def main() -> int:
    copy_content()
    generate_crafting()
    write_home()
    print(f"Assembled site source in {OUT.relative_to(ROOT)}/")
    if len(sys.argv) > 1 and sys.argv[1] in {"build", "serve"}:
        cmd = [sys.executable, "-m", "mkdocs", sys.argv[1], "-f", str(ROOT / "mkdocs.yml")]
        return subprocess.call(cmd, cwd=ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
