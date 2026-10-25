# /// script
# requires-python = ">=3.11"
# dependencies = ["fonttools", "brotli", "pillow"]
# ///
"""Build the profile README artwork in assets/ (paper-file style of novadev.tech).

GitHub renders README images through its image proxy, so every SVG is self-contained:
fonts are subset to the glyphs each file uses and embedded as WOFF2, screenshots as WebP.

    uv run tools/build.py [/path/to/portfolio]

Inter and JetBrains Mono come from the installed system fonts (fc-list); Courier Prime is
vendored in tools/fonts (OFL). Screenshots come from the portfolio repo's public/projects.
"""

import base64
import io
import json
import re
import subprocess
import sys
from html import escape
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
OUT = ROOT / "assets"
PORTFOLIO = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "portfolio"
ICONS = json.loads((TOOLS / "icons.json").read_text())

W = 840

# novadev.tech tokens (docs/architecture/2026-10-25-pages-mockup/base.css in the portfolio)
BG, FG, MUTED, PRIMARY, ACCENT, BORDER = "#0a0f18", "#edf0f6", "#a6b0c0", "#6f97ff", "#5be192", "#384354"
PAPER, CARD_PAPER, SHEET, INK, LINE, PMUTED = "#dddbd4", "#eeede7", "#f6f5f0", "#1d1d1b", "#aeaca4", "#5d5b54"
MANILA, MANILA_DK, MANILA_INK, KRAFT, KRAFT_DK = "#cdb68a", "#a99163", "#2a2418", "#b9976a", "#a3825a"
STAMP, STAMP_RED, RULE_RED = "#23409a", "#a3261c", "#b8483d"


def system_font(name: str) -> Path:
    out = subprocess.run(["fc-list", ":", "file"], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        path = line.split(":")[0].strip()
        if path.endswith("/" + name):
            return Path(path)
    sys.exit(f"font not found: {name}")


FONTS = {
    # family: (path, css weight range)
    "Inter": (system_font("InterVariable.ttf"), "100 900"),
    "JetBrains Mono": (system_font("JetBrainsMono[wght].ttf"), "100 800"),
    "Courier Prime": (TOOLS / "fonts/CourierPrime-Regular.ttf", "400"),
    "Courier Prime Bold": (TOOLS / "fonts/CourierPrime-Bold.ttf", "700"),
}
_metrics = {fam: TTFont(path) for fam, (path, _) in FONTS.items()}

SANS, MONO, TYPE = "Inter", "JetBrains Mono", "Courier Prime"


def measure(text: str, family: str, size: float, tracking: float = 0.0, weight: int = 400) -> float:
    """Advance width in px; weight > 500 widens Inter roughly as the wght axis does."""
    font = _metrics["Courier Prime Bold" if family == TYPE and weight >= 700 else family]
    cmap, hmtx, upm = font.getBestCmap(), font["hmtx"], font["head"].unitsPerEm
    units = sum(hmtx[cmap[ord(c)]][0] if ord(c) in cmap else upm * 0.5 for c in text)
    width = units / upm * size + tracking * size * len(text)
    if family == SANS and weight >= 600:
        width *= 1.04
    return width


def font_faces(svg_body: str) -> str:
    text = "".join(re.findall(r">([^<]+)<", svg_body))
    text = re.sub(r"&[a-z]+;|&#\d+;", lambda m: {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"'}.get(m.group(), " "), text)
    chars = set(text) | set(" ")
    faces = []
    for fam, (path, weight) in FONTS.items():
        font_name = fam.replace(" Bold", "")
        cmap = _metrics[fam].getBestCmap()
        missing = {c for c in chars if not c.isspace() and ord(c) not in cmap}
        if missing and fam.startswith("Courier"):
            used = re.findall(r'font-family="Courier Prime"[^>]*>([^<]+)<', svg_body)
            bad = {c for s in used for c in s if c in missing}
            if bad:
                sys.exit(f"Courier Prime lacks glyphs: {sorted(bad)}")
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["kern", "liga", "calt"]
        opts.name_IDs = []
        font = TTFont(path)
        sub = subset.Subsetter(opts)
        sub.populate(text="".join(chars))
        sub.subset(font)
        buf = io.BytesIO()
        font.flavor = "woff2"
        font.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        faces.append(
            f"@font-face{{font-family:'{font_name}';font-weight:{weight};"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}"
        )
    return "".join(faces)


def image_data(rel: str, width: int) -> str:
    img = Image.open(PORTFOLIO / "public/projects" / rel).convert("RGB")
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=82, method=6)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def t(x, y, s, family=SANS, size=14, weight=400, fill=INK, tracking=0.0, anchor="start", extra=""):
    ls = f' letter-spacing="{tracking * size:.2f}"' if tracking else ""
    fam = "Courier Prime" if family == TYPE else family
    return (
        f'<text x="{x}" y="{y}" font-family="{fam}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}"{ls} text-anchor="{anchor}"{extra}>{escape(s)}</text>'
    )


def arrow(x, y, size, color, stroke=1.8):
    """Up-right arrow (the site's ↗) as a path; Courier Prime has no arrow glyphs."""
    s = size
    return (
        f'<path d="M{x} {y + s}L{x + s} {y}M{x + s * 0.3} {y}H{x + s}V{y + s * 0.7}" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="square"/>'
    )


def icon(name, x, y, size, ink=True):
    data = ICONS[name]
    color = paper_ink(data["hex"]) if ink else data["hex"]
    paths = "".join(f'<path d="{d}"/>' for d in data["paths"])
    return f'<g transform="translate({x} {y}) scale({size / 24})" fill="{color}">{paths}</g>'


def paper_ink(hexcode: str) -> str:
    """Darken a brand colour to 3:1 against the paper, as components/skill-icon.tsx does."""

    def lum(rgb):
        def ch(v):
            c = v / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = map(ch, rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    paper = (239, 237, 230)
    rgb = [int(hexcode[i : i + 2], 16) for i in (1, 3, 5)]
    while (lum(paper) + 0.05) / (lum(rgb) + 0.05) < 3:
        rgb = [round(v * 0.9) for v in rgb]
    return "#" + "".join(f"{v:02x}" for v in rgb)


COMMON_CSS = """
.rise{animation:rise .9s cubic-bezier(.2,.8,.2,1) both}
.slam{transform-box:fill-box;transform-origin:center;animation:slam .42s cubic-bezier(.3,1.4,.5,1) both}
.pulse{animation:pulse 2.2s ease-in-out infinite}
.blink{animation:blink 1.1s steps(1) infinite}
@keyframes rise{from{opacity:0;transform:translateY(18px)}}
@keyframes slam{0%{opacity:0;transform:scale(1.9)}70%{opacity:.95;transform:scale(.96)}100%{opacity:.93;transform:scale(1)}}
@keyframes pulse{50%{opacity:.25}}
@keyframes blink{50%{opacity:0}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
"""

DEFS = f"""
<filter id="paperShadow" x="-20%" y="-20%" width="140%" height="160%">
  <feDropShadow dx="0" dy="16" stdDeviation="13" flood-color="#000" flood-opacity=".3"/>
</filter>
<filter id="softShadow" x="-10%" y="-10%" width="120%" height="140%">
  <feDropShadow dx="0" dy="6" stdDeviation="6" flood-color="#000" flood-opacity=".28"/>
</filter>
<pattern id="grain" width="3" height="3" patternUnits="userSpaceOnUse">
  <rect width="3" height="1" fill="#000" opacity=".022"/>
</pattern>
"""


def svg(height: int, body: str, title: str, extra_css: str = "") -> str:
    head = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" role="img">'
    style = f"<style>{font_faces(body)}{COMMON_CSS}{extra_css}</style>"
    return f"{head}<title>{escape(title)}</title><defs>{style}{DEFS}</defs>{body}</svg>\n"


def stamp(x, y, label, color=STAMP, size=11, rotate=-6, delay=0.9, family=TYPE, tracking=0.14, weight=700, double=False):
    """Rubber stamp: bordered label, slammed onto the paper once on load."""
    tw = measure(label, family, size, tracking, weight)
    pad_x, h = size * 0.85, size * 2.1
    w = tw + pad_x * 2
    inner = (
        f'<rect x="3" y="3" width="{w - 6:.1f}" height="{h - 6:.1f}" rx="3" fill="none" stroke="{color}" stroke-width="1.2"/>'
        if double
        else ""
    )
    return (
        f'<g transform="translate({x} {y}) rotate({rotate})"><g class="slam" style="animation-delay:{delay}s" opacity=".93">'
        f'<rect width="{w:.1f}" height="{h:.1f}" rx="5" fill="none" stroke="{color}" stroke-width="2.4"/>{inner}'
        + t(pad_x, h / 2 + size * 0.36, label, family, size, weight, color, tracking if family == TYPE else -0.02)
        + "</g></g>"
    )


def wrap(text: str, family: str, size: float, width: float, weight=400) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if measure(trial, family, size, 0, weight) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + [line]


# ---------------------------------------------------------------- hero


def hero() -> str:
    h = 452
    b = [
        f'<defs><pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="11" cy="11" r="1" fill="{MUTED}" opacity=".16"/></pattern></defs>',
        f'<rect x=".5" y=".5" width="{W - 1}" height="{h - 1}" rx="14" fill="{BG}" stroke="{BORDER}"/>',
        f'<rect x="1" y="72" width="{W - 2}" height="{h - 73}" rx="13" fill="url(#dots)"/>',
        # header: brand square, name, site
        f'<rect x="32" y="22" width="30" height="30" fill="{FG}"/>',
        t(47, 41.5, "NA", MONO, 10.5, 600, BG, anchor="middle"),
        t(74, 35, "Mohamed Abdelwahab", SANS, 13.5, 600, FG, -0.01),
        t(74, 49, "NOVADEV / UAE", MONO, 8, 400, MUTED, 0.18),
        t(W - 52, 41, "novadev.tech", MONO, 11, 400, MUTED, anchor="end"),
        arrow(W - 46, 32, 8, MUTED, 1.4),
        f'<line x1="0" y1="72.5" x2="{W}" y2="72.5" stroke="{BORDER}"/>',
    ]
    # availability pill
    pill = "OPEN TO UAE & INTERNATIONAL ENGINEERING ROLES"
    pw = measure(pill, MONO, 8.6, 0.14) + 40
    b += [
        f'<g class="rise" style="animation-delay:.05s"><rect x="32.5" y="98.5" width="{pw:.0f}" height="26" fill="{BG}" stroke="{BORDER}"/>',
        f'<circle class="pulse" cx="46" cy="111.5" r="3.2" fill="{ACCENT}"/>',
        t(58, 114.6, pill, MONO, 8.6, 400, FG, 0.14) + "</g>",
    ]
    # headline, as on the home page
    lines = [("I build software", FG), ("for work that", FG), ("cannot stay", PRIMARY), ("manual.", PRIMARY)]
    for i, (line, color) in enumerate(lines):
        b.append(f'<g class="rise" style="animation-delay:{0.12 + i * 0.08:.2f}s">' + t(30, 182 + i * 47, line, SANS, 50, 600, color, -0.05) + "</g>")
    caret_x = 30 + measure("manual.", SANS, 50, -0.05, 600) / 1.04 + 4
    b.append(f'<rect class="blink" x="{caret_x:.0f}" y="{182 + 3 * 47 - 36}" width="5" height="40" fill="{PRIMARY}"/>')
    lede = ["Full-stack TypeScript engineer building workflow software,", "automation, and internal systems from the UAE."]
    for i, line in enumerate(lede):
        b.append(t(32, 372 + i * 22, line, SANS, 14.5, 400, MUTED))
    b.append(t(32, 426, "TYPESCRIPT · REACT · NODE.JS · POSTGRESQL · DOCKER", MONO, 8.6, 400, "#6b778a", 0.16))

    # personnel ID sheet, clipped on the right
    cw, ch = 300, 318
    card = [
        f'<rect width="{cw}" height="{ch}" fill="{PAPER}" filter="url(#paperShadow)"/>',
        f'<rect width="{cw}" height="{ch}" fill="url(#grain)"/>',
        t(20, 34, "PERSONNEL FILE", TYPE, 11, 400, PMUTED, 0.12),
        t(cw - 20, 34, "No. 315", TYPE, 11, 400, PMUTED, 0.08, anchor="end"),
        f'<line x1="20" y1="46" x2="{cw - 20}" y2="46" stroke="{INK}" stroke-width="1.5"/>',
        # photo box
        f'<rect x="20" y="62" width="76" height="92" fill="{BG}"/>',
        f'<rect x="24" y="66" width="68" height="84" fill="none" stroke="{BORDER}"/>',
        t(58, 116, "NA", MONO, 24, 600, FG, anchor="middle"),
        t(20, 170, "FIG. 1", TYPE, 9, 400, PMUTED, 0.12),
    ]
    fields = [("NAME", "Mohamed Abdelwahab"), ("ROLE", "Full-Stack Software Engineer"), ("BASE", "Ras Al Khaimah, UAE")]
    for i, (label, value) in enumerate(fields):
        y = 72 + i * 38
        card.append(t(110, y, label, TYPE, 9, 400, PMUTED, 0.14))
        card.append(t(110, y + 17, value, SANS, 12.6, 500, INK, -0.01))
    card += [
        f'<line x1="20" y1="186" x2="{cw - 20}" y2="186" stroke="#b9b8b1" stroke-dasharray="3 3"/>',
        t(20, 208, "FOCUS", TYPE, 9, 400, PMUTED, 0.14),
        t(20, 227, "Workflow systems, internal tools,", SANS, 12.6, 500, INK, -0.01),
        t(20, 245, "developer tooling, and practical AI.", SANS, 12.6, 500, INK, -0.01),
        t(20, 298, "ISSUED 2026 · RAK", TYPE, 9, 400, PMUTED, 0.14),
        stamp(146, 262, "Open to work", STAMP, 19, -7, 1.15, SANS, 0, 700, double=True),
        # paper clip
        f'<path d="M140 -16 v44 a9 9 0 0 0 18 0 v-38 a6 6 0 0 0 -12 0 v32" fill="none" stroke="#9aa3b2" stroke-width="2.6" stroke-linecap="round"/>',
    ]
    b.append(f'<g transform="translate(506 104) rotate(2.4)"><g class="rise" style="animation-delay:.35s">{"".join(card)}</g></g>')
    return svg(h, "".join(b), "Mohamed Abdelwahab: I build software for work that cannot stay manual.")


# ---------------------------------------------------------------- project files

PROJECTS = [
    dict(
        n="01", slug="luna", name="Luna", status="PERSONAL PROJECT · LIVE",
        text="AI assistant app for my phone that helps me manage tasks, my calendar, and coding work. Every agent action waits for my approval.",
        fact="500+ COMMITS · 160+ TEST FILES",
        stack=["TypeScript", "React", "Bun", "SQLite", "Docker"],
        stamp=("Live · Oct 2026", STAMP), shot="luna/poster.webp", link="READ THE CASE STUDY",
    ),
    dict(
        n="02", slug="pdflover", name="PDFLover", status="PUBLIC REPOSITORY",
        text="Privacy-first PDF workspace for merging, redacting, and OCR, with browser-side processing where supported.",
        fact="TESTS AT COMMIT 9E3D858 · 5 SEP 2026",
        stack=["TypeScript", "React", "Vite", "Fastify"],
        stamp=("463 + 9 tests", STAMP), stamp_top=True, shot="pdflover/poster.webp", link="VIEW THE REPOSITORY",
    ),
    dict(
        n="03", slug="relay", name="Relay Client Delivery", status="PUBLIC REPOSITORY",
        text="Links client contracts to real-time delivery boards, with bilingual English/Arabic PDF and DOCX documents.",
        fact="INTEGRATION TESTS ON A DISPOSABLE MONGODB",
        stack=["Next.js", "Express", "MongoDB", "Socket.IO", "Redis"],
        stamp=("EN / AR", STAMP_RED), shot="relay/relay.webp", link="VIEW THE REPOSITORY",
    ),
    dict(
        n="04", slug="homelab", name="NexOS Homelab", status="PERSONAL INFRASTRUCTURE · ACTIVE",
        text="Self-hosted Proxmox infrastructure managed as code, with a Go CLI/TUI I wrote for deploys and operations.",
        fact="HOSTS LUNA · 440+ COMMITS ON THE GO TOOL",
        stack=["Proxmox", "Terraform", "Ansible", "NixOS", "Go"],
        stamp=("Run as code", STAMP), shot="nexos-homelab/nexos-homelab.webp", link="READ THE CASE STUDY",
    ),
]


def tag_row(names, x, y, max_w):
    out, cx, cy = [], x, y
    for name in names:
        w = 8 + 13 + 6 + measure(name, TYPE, 11, 0.02) + 8
        if cx + w > x + max_w:
            cx, cy = x, cy + 28
        out.append(f'<rect x="{cx + .5:.1f}" y="{cy + .5}" width="{w:.1f}" height="22" fill="none" stroke="#a9a79f"/>')
        out.append(icon(name, cx + 8, cy + 4.5, 13))
        out.append(t(cx + 27, cy + 15.2, name, TYPE, 11, 400, "#3d3c37", 0.02))
        cx += w + 7
    return "".join(out), cy + 22


def project(p, flip: bool) -> str:
    h = 386
    fx, fy, fw, fh = 16, 44, W - 32, h - 64
    tab_label = measure(f"FILE {p['n']} ", TYPE, 12, 0.14, 700) + 4 + measure(p["name"].upper(), TYPE, 12, 0.1)
    tab_w = tab_label + 18 + 34
    tab_x = W - 16 - tab_w - 10 if flip else 16
    b = [
        # folder back, tab, front
        f'<g filter="url(#paperShadow)"><path d="M{tab_x} {fy}V20a6 6 0 0 1 6-6h{tab_w - 29:.0f}a6 6 0 0 1 5 3l18 27Z" fill="{MANILA_DK}"/>'
        f'<rect x="{fx}" y="{fy}" width="{fw}" height="{fh}" rx="6" fill="{MANILA}"/></g>',
        f'<rect x="{fx}" y="{fy}" width="{fw}" height="{fh}" rx="6" fill="url(#grain)"/>',
        f'<rect x="{fx + 6}" y="{fy + 6}" width="{fw - 12}" height="{fh - 12}" rx="3" fill="none" stroke="{MANILA_DK}" stroke-opacity=".55"/>',
        t(tab_x + 18, 36, f"FILE {p['n']}", TYPE, 12, 700, MANILA_INK, 0.14),
        t(tab_x + 18 + measure(f"FILE {p['n']} ", TYPE, 12, 0.14, 700) + 4, 36, p["name"].upper(), TYPE, 12, 400, MANILA_INK, 0.1),
        t(
            (fx + 24) if flip else (W - 40), 36, f"SELECTED WORK · {p['n']}/04", TYPE, 10, 400, "#6f6450", 0.14,
            anchor="start" if flip else "end",
        ),
    ]
    # screenshot, taped to a white sheet
    sw, sh = 404, 262
    sx = (W - 16 - 30 - sw) if flip else 46
    shot = image_data(p["shot"], 820)
    rot = 1.4 if flip else -1.4
    photo = [
        f'<rect x="-10" y="-10" width="{sw + 20}" height="{sh + 20}" fill="{SHEET}" filter="url(#softShadow)"/>',
        f'<clipPath id="clip{p["n"]}"><rect width="{sw}" height="{sh}"/></clipPath>',
        f'<image href="{shot}" width="{sw}" height="{sh}" preserveAspectRatio="xMidYMin slice" clip-path="url(#clip{p["n"]})"/>',
        f'<rect width="{sw}" height="{sh}" fill="none" stroke="#000" stroke-opacity=".12"/>',
        f'<rect x="{sw / 2 - 50}" y="-22" width="100" height="26" fill="rgb(236 228 196)" fill-opacity=".72" transform="rotate(-3 {sw / 2} -9)"/>',
    ]
    label, color = p["stamp"]
    sw_stamp = measure(label.upper(), TYPE, 13, 0.14, 700) + 22
    stamp_y = 22 if p.get("stamp_top") else sh - 40
    photo.append(stamp(sw - sw_stamp - 16, stamp_y, label.upper(), color, 13, -6, 0.9))
    b.append(f'<g transform="translate({sx} {fy + 34}) rotate({rot} {sw / 2} {sh / 2})"><g>{"".join(photo)}</g></g>')

    # record sheet
    pw, ph = 322, 286
    px = 46 if flip else W - 16 - 30 - pw
    py = fy + 22
    lines = wrap(p["text"], SANS, 13.5, pw - 44)
    title_size = 27 if measure(p["name"], SANS, 27, -0.03, 600) < pw - 44 else 23
    sheet = [
        f'<rect width="{pw}" height="{ph}" fill="{CARD_PAPER}" filter="url(#softShadow)"/>',
        f'<rect width="{pw}" height="{ph}" fill="url(#grain)"/>',
        t(22, 32, p["status"], TYPE, 9.5, 400, PMUTED, 0.13),
        t(22, 68, p["name"], SANS, title_size, 600, INK, -0.03),
        f'<line x1="22" y1="82" x2="{pw - 22}" y2="82" stroke="{INK}" stroke-width="1.5"/>',
    ]
    for i, line in enumerate(lines):
        sheet.append(t(22, 106 + i * 20.5, line, SANS, 13.5, 400, "#2e2d29"))
    y = 106 + len(lines) * 20.5 + 2
    sheet.append(t(22, y, p["fact"], TYPE, 9, 400, PMUTED, 0.12))
    tags, end = tag_row(p["stack"], 22, y + 14, pw - 44)
    sheet.append(tags)
    link_y = max(end + 30, ph - 22)
    lw = measure(p["link"], TYPE, 11.5, 0.06, 700)
    sheet += [
        t(22, link_y, p["link"], TYPE, 11.5, 700, INK, 0.06),
        arrow(22 + lw + 6, link_y - 9, 8, INK, 1.6),
        f'<line x1="22" y1="{link_y + 5}" x2="{22 + lw + 16:.0f}" y2="{link_y + 5}" stroke="{INK}" stroke-width="1.5"/>',
    ]
    b.append(f'<g transform="translate({px} {py}) rotate({-0.8 if flip else 0.8} {pw / 2} {ph / 2})"><g>{"".join(sheet)}</g></g>')
    return svg(h, "".join(b), f"File {p['n']}: {p['name']}. {p['text']}")


# ---------------------------------------------------------------- stack index card

STACK = [
    ("FRONTEND", ["TypeScript", "React", "Next.js", "Tailwind CSS", "Vite", "Expo"]),
    ("BACKEND", ["Node.js", "NestJS", "Fastify", "Express", "Bun", "GraphQL"]),
    ("DATA", ["PostgreSQL", "MongoDB", "SQLite", "Redis", "Socket.IO"]),
    ("INFRA", ["Docker", "NixOS", "Proxmox", "Terraform", "Ansible", "Cloudflare", "Go"]),
]


def stack() -> str:
    h = 292
    cx, cy, cw, chh = 28, 22, W - 56, 244
    margin = 132
    card = [
        f'<rect width="{cw}" height="{chh}" fill="{CARD_PAPER}" filter="url(#paperShadow)"/>',
        f'<rect width="{cw}" height="{chh}" fill="url(#grain)"/>',
        f'<line x1="0" y1="52" x2="{cw}" y2="52" stroke="{RULE_RED}" stroke-opacity=".7"/>',
        f'<line x1="{margin - 14}" y1="0" x2="{margin - 14}" y2="{chh}" stroke="{RULE_RED}" stroke-opacity=".7"/>',
        t(22, 34, "CARD 05", TYPE, 11, 700, INK, 0.14),
        t(margin, 34, "TOOLS I SHIP WITH", TYPE, 11, 400, PMUTED, 0.14),
        t(cw - 22, 34, "INDEX · STACK", TYPE, 11, 400, PMUTED, 0.14, anchor="end"),
    ]
    for i in range(1, 7):
        card.append(f'<line x1="0" y1="{52 + i * 32}" x2="{cw}" y2="{52 + i * 32}" stroke="rgb(31 81 204)" stroke-opacity=".11"/>')
    for r, (group, names) in enumerate(STACK):
        base = 52 + r * 46 + 34
        card.append(t(22, base, group, TYPE, 10, 700, PMUTED, 0.16))
        x = margin
        for name in names:
            card.append(icon(name, x, base - 13, 16))
            card.append(t(x + 22, base, name, SANS, 13, 500, "#2e2d29", -0.01))
            x += 22 + measure(name, SANS, 13, -0.01, 500) + 22
    b = [f'<g transform="translate({cx} {cy}) rotate(-0.5 {cw / 2} {chh / 2})"><g>{"".join(card)}</g></g>']
    return svg(h, "".join(b), "Stack: " + "; ".join(f"{g.title()}: {', '.join(n)}" for g, n in STACK))


# ---------------------------------------------------------------- contact envelope


def envelope() -> str:
    h = 318
    ex, ey, ew, eh = 24, 18, W - 48, 268
    env = [
        f'<rect width="{ew}" height="{eh}" rx="4" fill="{KRAFT}" filter="url(#paperShadow)"/>',
        f'<rect width="{ew}" height="{eh}" rx="4" fill="url(#grain)"/>',
        f'<path d="M0 0L{ew / 2} {eh * 0.46}L{ew} 0" fill="none" stroke="{KRAFT_DK}" stroke-width="1.5"/>',
        f'<path d="M0 {eh}L{ew * 0.36} {eh * 0.5}M{ew} {eh}L{ew * 0.64} {eh * 0.5}" fill="none" stroke="{KRAFT_DK}" stroke-width="1.2" stroke-opacity=".7"/>',
        t(26, 38, "RE: FULL-STACK ENGINEERING ROLES", TYPE, 11.5, 700, MANILA_INK, 0.12),
        t(26, 56, "UAE ON-SITE / HYBRID / REMOTE · INTERNATIONAL REMOTE", TYPE, 9.5, 400, "#4a3f2a", 0.12),
    ]
    # address label
    lx, ly, lw, lh = ew / 2 - 170, 112, 340, 112
    env += [
        f'<rect x="{lx}" y="{ly}" width="{lw}" height="{lh}" fill="{SHEET}" filter="url(#softShadow)"/>',
        t(lx + 20, ly + 28, "TO", TYPE, 9.5, 400, PMUTED, 0.16),
        t(lx + 20, ly + 50, "MOHAMED ABDELWAHAB", TYPE, 15, 700, INK, 0.06),
        t(lx + 20, ly + 72, "mohamed@novadev.tech", TYPE, 14, 400, STAMP, 0.02),
        t(lx + 20, ly + 94, "RAS AL KHAIMAH · UAE", TYPE, 10.5, 400, PMUTED, 0.14),
    ]
    # postage stamp with perforated edge, then the postmark over it
    px, py, pw, ph = ew - 108, 22, 80, 96
    perf = "".join(
        f'<circle cx="{px + i}" cy="{py}" r="2.6" fill="{KRAFT}"/><circle cx="{px + i}" cy="{py + ph}" r="2.6" fill="{KRAFT}"/>'
        for i in range(0, pw + 1, 8)
    ) + "".join(
        f'<circle cx="{px}" cy="{py + i}" r="2.6" fill="{KRAFT}"/><circle cx="{px + pw}" cy="{py + i}" r="2.6" fill="{KRAFT}"/>'
        for i in range(0, ph + 1, 8)
    )
    env += [
        f'<g transform="rotate(3 {px + pw / 2} {py + ph / 2})"><rect x="{px}" y="{py}" width="{pw}" height="{ph}" fill="{SHEET}" filter="url(#softShadow)"/>{perf}',
        f'<rect x="{px + 8}" y="{py + 8}" width="{pw - 16}" height="{ph - 16}" fill="{BG}"/>',
        t(px + pw / 2, py + 50, "NA", MONO, 20, 600, FG, anchor="middle"),
        t(px + pw / 2, py + 72, "UAE · 2026", MONO, 7.5, 400, PRIMARY, 0.12, anchor="middle") + "</g>",
        '<g class="slam" style="animation-delay:.9s" opacity=".6">'
        f'<circle cx="{px - 18}" cy="{py + 62}" r="34" fill="none" stroke="{INK}" stroke-width="2"/>'
        f'<circle cx="{px - 18}" cy="{py + 62}" r="27" fill="none" stroke="{INK}" stroke-width="1"/>'
        + t(px - 18, py + 59, "RAK", TYPE, 11, 700, INK, 0.16, anchor="middle")
        + t(px - 18, py + 72, "2026", TYPE, 9, 400, INK, 0.16, anchor="middle")
        + "".join(
            f'<path d="M{px + 18} {py + 46 + k * 9}q10 -6 20 0t20 0t20 0" fill="none" stroke="{INK}" stroke-width="1.6"/>'
            for k in range(4)
        )
        + "</g>",
    ]
    lw2 = measure("WRITE TO ME", TYPE, 12, 0.12, 700)
    env += [
        t(26, eh - 26, "WRITE TO ME", TYPE, 12, 700, MANILA_INK, 0.12),
        arrow(26 + lw2 + 6, eh - 35, 8, MANILA_INK, 1.6),
        f'<line x1="26" y1="{eh - 21}" x2="{26 + lw2 + 16:.0f}" y2="{eh - 21}" stroke="{MANILA_INK}" stroke-width="1.5"/>',
        t(ew - 26, eh - 26, "NOVADEV.TECH · LINKEDIN/IN/NOVA315", TYPE, 9.5, 400, "#4a3f2a", 0.12, anchor="end"),
        stamp(ew - 300, eh - 92, "OPEN TO WORK", STAMP_RED, 13, -5, 1.2),
    ]
    b = [f'<g transform="translate({ex} {ey}) rotate(0.6 {ew / 2} {eh / 2})"><g>{"".join(env)}</g></g>']
    return svg(h, "".join(b), "Write to Mohamed Abdelwahab at mohamed@novadev.tech")


def main():
    OUT.mkdir(exist_ok=True)
    files = {"hero.svg": hero(), "stack.svg": stack(), "contact.svg": envelope()}
    for i, p in enumerate(PROJECTS):
        files[f"file-{p['n']}-{p['slug']}.svg"] = project(p, flip=i % 2 == 1)
    for name, content in files.items():
        (OUT / name).write_text(content)
        print(f"{name:28} {len(content.encode()) / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
