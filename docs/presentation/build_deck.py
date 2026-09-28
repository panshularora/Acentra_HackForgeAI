# Slide copy is long prose with real typography (multiplication sign, minus, en dash).
# ruff: noqa: E501
"""Build docs/presentation/ClaimsWatch.pptx from one data file.

Everything that can change lives in ``deck_data.json``:

* ``slides``: all slide copy (headlines and lines as templates) and the image
  path/crop used on each slide, relative to the repository root;
* ``facts``: every number, summary and log line quoted on the slides, written
  by ``evidence/make_evidence.py`` from real runs (replay benchmark, tests,
  masking, SNS read-back). Templates reference them as ``{outage[latency_s]}``.

To swap in new screenshots or benchmark numbers, edit ``deck_data.json`` (or
re-run ``make_evidence.py``) and rebuild; no code changes are needed. Colours
and fonts mirror ``frontend/src/theme.ts``. Markup: `backticks` = JetBrains
Mono, ``[[CRITICAL]]`` = severity word in its severity colour.

    pip install python-pptx pillow
    python docs/presentation/build_deck.py [--data deck_data.json]
    soffice --headless --convert-to pdf --outdir docs/presentation docs/presentation/ClaimsWatch.pptx
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = HERE / "deck_data.json"
OUT = HERE / "ClaimsWatch.pptx"

# frontend/src/theme.ts
BG = "111418"
SURFACE = "171B21"
BORDER = "262B33"
BORDER_STRONG = "343A44"
TEXT = "E6E8EB"
MUTED = "8A929C"
SEVERITY = {"WARNING": "E0A100", "HIGH": "E8590C", "CRITICAL": "E03131"}

UI = "Inter"
UI_MEDIUM = "Inter Medium"
UI_SEMI = "Inter SemiBold"
MONO = "JetBrains Mono"
MONO_SEMI = "JetBrains Mono SemiBold"

SLIDE_W, SLIDE_H = 13.333, 7.5
MARGIN = 0.6
RADIUS_IN = 4 / 96  # 4px at 96 dpi

# Phrases that must not wrap mid-way (set from deck_data.json "no_break").
NO_BREAK: list[str] = []


def keep_together(value: str) -> str:
    """Non-breaking hyphens/spaces inside NO_BREAK phrases (Inter has U+2011)."""
    for phrase in NO_BREAK:
        value = value.replace(phrase, phrase.replace("-", "\u2011").replace(" ", "\u00a0"))
    return value


# --------------------------------------------------------------------------- primitives


def rgb(hex_: str) -> RGBColor:
    return RGBColor.from_string(hex_)


def set_bg(slide) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = rgb(BG)


def panel(slide, x, y, w, h, fill=SURFACE, border=BORDER, border_pt=0.75):
    """Rounded 4px panel with a 1px border, no shadow."""
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h)
    )
    shape.adjustments[0] = min(0.5, RADIUS_IN / min(w, h))
    if fill is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = rgb(fill)
    if border is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = rgb(border)
        shape.line.width = Pt(border_pt)
    no_shadow(shape)
    shape.text_frame.text = ""
    return shape


def no_shadow(shape) -> None:
    sp_pr = shape._element.spPr
    if sp_pr.find(qn("a:effectLst")) is None:
        sp_pr.append(etree.SubElement(sp_pr, qn("a:effectLst")))


Run = tuple[str, dict]


def parse_markup(text: str, base: dict) -> list[Run]:
    """`backticks` switch to JetBrains Mono; [[WORD]] colours a severity word."""
    runs: list[Run] = []
    for part in re.split(r"(`[^`]*`|\[\[[A-Z]+\]\])", text):
        if not part:
            continue
        if part.startswith("`"):
            runs.append(
                (
                    part[1:-1],
                    {**base, "font": MONO if base.get("font") in (UI, UI_MEDIUM) else MONO_SEMI},
                )
            )
        elif part.startswith("[["):
            word = part[2:-2]
            runs.append((word, {**base, "font": MONO_SEMI, "color": SEVERITY[word]}))
        else:
            runs.append((part, base))
    return runs


def text(
    slide,
    x,
    y,
    w,
    h,
    paragraphs,
    *,
    size=14,
    color=TEXT,
    font=UI,
    align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP,
    spacing=1.15,
    space_after=0,
):
    """Text box; ``paragraphs`` is a str (lines split on \\n) or a list of str/run lists."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    if isinstance(paragraphs, str):
        paragraphs = paragraphs.split("\n")
    base = {"size": size, "color": color, "font": font}
    for index, para in enumerate(paragraphs):
        p = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        p.space_after = Pt(space_after)
        runs = parse_markup(para, base) if isinstance(para, str) else para
        for content, style in runs:
            style = {**base, **style}
            r = p.add_run()
            r.text = (
                keep_together(content) if style["font"] in (UI, UI_MEDIUM, UI_SEMI) else content
            )
            r.font.name = style["font"]
            r.font.size = Pt(style["size"])
            r.font.color.rgb = rgb(style["color"])
            r.font.bold = False
            r.font.italic = False
    return box


def headline(slide, sentence: str) -> None:
    text(
        slide, MARGIN, 0.5, SLIDE_W - 2 * MARGIN, 1.2, sentence, size=28, font=UI_SEMI, spacing=1.08
    )


def footer(slide, number: int, total: int, repo: str) -> None:
    y = SLIDE_H - 0.42
    text(slide, MARGIN, y, 7, 0.22, repo, size=9, color=MUTED, font=MONO)
    text(
        slide,
        SLIDE_W - MARGIN - 2,
        y,
        2,
        0.22,
        f"{number} / {total}",
        size=9,
        color=MUTED,
        font=MONO,
        align=PP_ALIGN.RIGHT,
    )


def picture(slide, path: Path, x, y, w=None, h=None, crop=None):
    """Picture with a 1px border; ``crop`` = (left, top, right, bottom) fractions."""
    with Image.open(path) as img:
        pw, ph = img.size
    crop = crop or (0, 0, 0, 0)
    vis_w = pw * (1 - crop[0] - crop[2])
    vis_h = ph * (1 - crop[1] - crop[3])
    aspect = vis_w / vis_h
    if w is None:
        w = h * aspect
    if h is None:
        h = w / aspect
    pic = slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))
    pic.crop_left, pic.crop_top, pic.crop_right, pic.crop_bottom = crop
    pic.line.color.rgb = rgb(BORDER)
    pic.line.width = Pt(0.75)
    return pic, w, h


def line(slide, x1, y1, x2, y2, arrow=False, color=MUTED, width=1.25):
    conn = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2)
    )
    conn.line.color.rgb = rgb(color)
    conn.line.width = Pt(width)
    if arrow:
        ln = conn.line._get_or_add_ln()
        tail = etree.SubElement(ln, qn("a:tailEnd"))
        tail.set("type", "triangle")
        tail.set("w", "med")
        tail.set("len", "med")
    return conn


def badge(slide, x, y, severity: str, size=11):
    """Outline badge like SeverityBadge.tsx: mono, severity colour, transparent fill."""
    w = 0.125 * len(severity) * size / 11 + 0.2
    h = 0.28 * size / 11
    shape = panel(slide, x, y, w, h, fill=None, border=SEVERITY[severity], border_pt=0.9)
    tf = shape.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = severity
    r.font.name = MONO_SEMI
    r.font.size = Pt(size)
    r.font.color.rgb = rgb(SEVERITY[severity])
    return w


def label(slide, x, y, w, content, size=11):
    text(slide, x, y, w, 0.3, content, size=size, color=MUTED, font=UI_MEDIUM)


def nb(value: str) -> str:
    """Keep "claim-adjudication" and "250 ms" on one line (Inter has U+2011)."""
    return value.replace("-", "\u2011")


# --------------------------------------------------------------------------- data


class Deck:
    """The data file plus template formatting against its facts."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.facts = data["facts"]
        self.repo = data["repo"]
        self.total = len(data["slides"])

    def f(self, template: Any) -> Any:
        """Format a template string (or list of them) with the facts."""
        if isinstance(template, list):
            return [self.f(t) for t in template]
        return template.format_map(self.facts) if isinstance(template, str) else template

    def image(self, spec: dict[str, Any]) -> tuple[Path, tuple[float, float, float, float] | None]:
        crop = spec.get("crop")
        return ROOT / spec["path"], tuple(crop) if crop else None


def new_slide(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    set_bg(s)
    return s


# --------------------------------------------------------------------------- slides


def slide_context(prs, d: Deck, c: dict, n: int):
    s = new_slide(prs)
    text(s, MARGIN, 0.32, 9, 0.25, d.f(c["kicker"]), size=11, color=MUTED, font=UI_MEDIUM)
    text(
        s,
        MARGIN,
        0.62,
        SLIDE_W - 2 * MARGIN,
        1.2,
        d.f(c["headline"]),
        size=28,
        font=UI_SEMI,
        spacing=1.08,
    )
    top, img_w = 2.05, 6.5
    path, crop = d.image(c["image"])
    _, _, ph = picture(s, path, SLIDE_W - MARGIN - img_w, top, w=img_w, crop=crop)
    col_w = SLIDE_W - 2 * MARGIN - img_w - 0.45
    text(s, MARGIN, top, col_w, 3.0, d.f(c["lines"]), size=15, spacing=1.2, space_after=14)
    label(s, MARGIN, top + ph - 0.72, col_w, d.f(c["team_label"]))
    text(
        s, MARGIN, top + ph - 0.45, col_w, 0.5, " · ".join(d.data["team"]), size=13, font=UI_MEDIUM
    )
    text(
        s,
        MARGIN,
        SLIDE_H - 0.78,
        SLIDE_W - 2 * MARGIN,
        0.3,
        "Sources: " + "  ·  ".join(d.data["sources"]),
        size=8,
        color=MUTED,
        font=MONO,
    )
    footer(s, n, d.total, d.repo)


def slide_gap(prs, d: Deck, c: dict, n: int):
    s = new_slide(prs)
    headline(s, d.f(c["headline"]))
    y, h, gap = 2.35, 3.55, 0.4
    w = (SLIDE_W - 2 * MARGIN - gap) / 2
    lx = MARGIN
    label(s, lx, y - 0.38, w, d.f(c["left_label"]))
    panel(s, lx, y, w, h)
    text(s, lx + 0.35, y + 0.35, w - 0.7, 0.3, d.f(c["left_title"]), size=13, font=MONO_SEMI)
    text(s, lx + 0.35, y + 0.95, w - 0.7, 0.9, d.f(c["left_big"]), size=24, font=UI_SEMI)
    text(
        s,
        lx + 0.35,
        y + h - 1.05,
        w - 0.7,
        0.7,
        d.f(c["left_note"]),
        size=14,
        color=MUTED,
        spacing=1.25,
    )
    rx = MARGIN + w + gap
    severity = d.f(c["right_severity"])
    label(s, rx, y - 0.38, w, d.f(c["right_label"]))
    panel(s, rx, y, w, h)
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(rx), Inches(y), Inches(0.05), Inches(h))
    bar.fill.solid()
    bar.fill.fore_color.rgb = rgb(SEVERITY[severity])
    bar.line.fill.background()
    no_shadow(bar)
    badge(s, rx + 0.35, y + 0.36, severity)
    text(
        s,
        rx + 0.35,
        y + 0.9,
        w - 0.7,
        1.4,
        d.f(c["right_summary"]),
        size=22,
        font=UI_SEMI,
        spacing=1.12,
    )
    stats = [
        [(d.f(k) + "  ", {"color": MUTED, "size": 13}), (d.f(v), {"font": MONO, "size": 13})]
        for k, v in c["right_stats"]
    ]
    text(s, rx + 0.35, y + h - 1.05, w - 0.7, 0.7, stats, size=13, spacing=1.35)
    text(
        s, MARGIN, y + h + 0.35, SLIDE_W - 2 * MARGIN, 0.35, d.f(c["caption"]), size=13, color=MUTED
    )
    footer(s, n, d.total, d.repo)


def slide_detection(prs, d: Deck, c: dict, n: int):
    s = new_slide(prs)
    headline(s, d.f(c["headline"]))
    top = 1.95
    path, crop = d.image(c["image"])
    _, pw, _ = picture(s, path, MARGIN, top, h=4.75, crop=crop)
    x = MARGIN + pw + 0.5
    w = SLIDE_W - MARGIN - x
    label(s, x, top, w, d.f(c["formula_label"]))
    panel(s, x, top + 0.34, w, 0.95)
    text(
        s,
        x,
        top + 0.34,
        w,
        0.95,
        d.f(c["formula"]),
        size=15,
        font=MONO_SEMI,
        align=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    ty = top + 1.6
    label(s, x, ty, w, d.f(c["thresholds_label"]))
    for i, (sev, cut) in enumerate(c["thresholds"]):
        ry = ty + 0.38 + i * 0.44
        badge(s, x, ry, sev)
        text(s, x + 1.45, ry - 0.01, 3, 0.3, d.f(cut), size=13, font=MONO)
    text(
        s,
        x,
        ty + 0.5 + 0.44 * len(c["thresholds"]),
        w,
        1.4,
        d.f(c["lines"]),
        size=13,
        color=MUTED,
        spacing=1.2,
        space_after=8,
    )
    footer(s, n, d.total, d.repo)


def stage_box(s, x, y, w, h, number, stage):
    panel(s, x, y, w, h)
    text(s, x + 0.18, y + 0.16, w - 0.36, 0.25, str(number), size=11, color=MUTED, font=MONO)
    text(s, x + 0.18, y + 0.42, w - 0.36, 0.32, stage["title"], size=15, font=UI_SEMI)
    text(s, x + 0.18, y + 0.78, w - 0.36, 0.25, stage["module"], size=9.5, color=MUTED, font=MONO)
    text(s, x + 0.18, y + 1.08, w - 0.36, h - 1.15, stage["detail"], size=11, spacing=1.15)


def slide_architecture(prs, d: Deck, c: dict, n: int):
    s = new_slide(prs)
    headline(s, d.f(c["headline"]))
    stages = c["stages"]
    gap = 0.34
    w = (SLIDE_W - 2 * MARGIN - gap * (len(stages) - 1)) / len(stages)
    y, h = 1.75, 2.0
    for i, stage in enumerate(stages):
        x = MARGIN + i * (w + gap)
        stage_box(s, x, y, w, h, i + 1, stage)
        if i:
            line(s, x - gap + 0.04, y + h / 2, x - 0.04, y + h / 2, arrow=True)
    py, ph = y + h + 0.45, 2.45
    last_cx = MARGIN + (len(stages) - 1) * (w + gap) + w / 2
    line(s, last_cx, y + h + 0.03, last_cx, py - 0.03, arrow=True)
    panel(s, MARGIN, py, SLIDE_W - 2 * MARGIN, ph, fill=BG, border=BORDER_STRONG)
    text(
        s, MARGIN + 0.25, py + 0.2, 1.2, 0.25, str(len(stages) + 1), size=11, color=MUTED, font=MONO
    )
    text(
        s, MARGIN + 0.25, py + 0.46, 1.5, 0.6, c["fanout_title"], size=15, font=UI_SEMI, spacing=1.1
    )
    bh = 0.78
    top_y, bot_y = py + 0.33, py + ph - 0.33 - bh
    mid_y = py + ph / 2
    fan = c["fanout"]

    def box(x, yy, ww, key):
        title, module = fan[key]
        panel(s, x, yy, ww, bh)
        text(s, x + 0.18, yy + 0.13, ww - 0.36, 0.3, title, size=13, font=UI_SEMI)
        text(s, x + 0.18, yy + 0.45, ww - 0.36, 0.25, module, size=9.5, color=MUTED, font=MONO)

    sx, sw = MARGIN + 1.75, 2.45
    box(sx, mid_y - bh / 2, sw, "store")
    bx, bw = sx + sw + 0.7, 3.2
    box(bx, top_y, bw, "ws")
    box(bx, bot_y, bw, "publisher")
    ex = bx + bw + 0.5
    ew = SLIDE_W - MARGIN - 0.25 - ex
    box(ex, top_y, ew, "dashboard")
    box(ex, bot_y, ew, "aws")
    jx = sx + sw + 0.35
    line(s, sx + sw, mid_y, jx, mid_y)
    line(s, jx, top_y + bh / 2, jx, bot_y + bh / 2)
    for yy in (top_y + bh / 2, bot_y + bh / 2):
        line(s, jx, yy, bx - 0.04, yy, arrow=True)
        line(s, bx + bw + 0.04, yy, ex - 0.04, yy, arrow=True)
    footer(s, n, d.total, d.repo)


def slide_incident(prs, d: Deck, c: dict, n: int):
    s = new_slide(prs)
    headline(s, d.f(c["headline"]))
    top = 1.95
    path, crop = d.image(c["image"])
    _, pw, _ = picture(s, path, MARGIN, top, h=4.85, crop=crop)
    x = MARGIN + pw + 0.5
    w = SLIDE_W - MARGIN - x
    big = [
        [
            (d.f(c["big"]), {"font": MONO_SEMI, "size": 54}),
            ("  " + d.f(c["big_unit"]), {"font": UI_MEDIUM, "size": 20, "color": MUTED}),
        ]
    ]
    text(s, x, top - 0.12, w, 1.05, big, size=54)
    text(
        s,
        x,
        top + 0.98,
        w,
        0.5,
        d.f(c["big_label"]),
        size=11,
        color=MUTED,
        font=UI_MEDIUM,
        spacing=1.2,
    )
    lines = d.f(c["lines"])
    body = list(lines)
    if c.get("note"):
        body.append([(d.f(c["note"]), {"color": MUTED, "size": 11})])
    text(s, x, top + 1.8, w, 3.0, body, size=13, spacing=1.22, space_after=12)
    footer(s, n, d.total, d.repo)


PHI_RAW = re.compile(r'(member_id=\S+|name="[^"]*"|email=\S+|dob=\S+|ssn=\S+|phone=\S+)')
PHI_TAG = re.compile(r"(<[A-Z_]+>)")


def highlighted(line_text: str, pattern: re.Pattern, size: float) -> list[Run]:
    runs: list[Run] = []
    for part in pattern.split(line_text):
        if part:
            hit = bool(pattern.fullmatch(part))
            runs.append(
                (
                    part,
                    {
                        "font": MONO_SEMI if hit else MONO,
                        "color": TEXT if hit else MUTED,
                        "size": size,
                    },
                )
            )
    return runs


def slide_masking(prs, d: Deck, c: dict, n: int):
    s = new_slide(prs)
    headline(s, d.f(c["headline"]))
    top, gap, ph = 2.05, 0.4, 3.9
    w = (SLIDE_W - 2 * MARGIN - gap) / 2

    def half(x, lbl, upper_label, upper, lower_label, lower):
        label(s, x, top - 0.38, w, d.f(lbl))
        panel(s, x, top, w, ph)
        text(
            s,
            x + 0.3,
            top + 0.25,
            w - 0.6,
            0.25,
            d.f(upper_label),
            size=10,
            color=MUTED,
            font=MONO_SEMI,
        )
        text(
            s,
            x + 0.3,
            top + 0.52,
            w - 0.6,
            1.4,
            upper,
            size=11,
            font=MONO,
            spacing=1.3,
            space_after=6,
        )
        line(s, x + 0.3, top + 1.97, x + w - 0.3, top + 1.97, color=BORDER, width=0.75)
        text(
            s,
            x + 0.3,
            top + 2.12,
            w - 0.6,
            0.25,
            d.f(lower_label),
            size=10,
            color=MUTED,
            font=MONO_SEMI,
        )
        text(s, x + 0.3, top + 2.39, w - 0.6, 1.4, lower, size=11, font=MONO, spacing=1.3)

    half(
        MARGIN,
        c["left_label"],
        c["raw_label"],
        [highlighted(d.f(c["raw"]), PHI_RAW, 11)],
        c["masked_label"],
        [highlighted(d.f(c["masked"]), PHI_TAG, 11)],
    )
    sev = d.f(c["sns_severity"])
    upper = [
        [("SNS MessageId ", {"color": MUTED}), (d.f(c["sns_id"]), {})],
        [
            ("Subject: [", {"color": MUTED}),
            (sev, {"font": MONO_SEMI, "color": SEVERITY.get(sev, TEXT)}),
            ("] " + d.f(c["sns_subject_rest"]), {}),
        ],
        [("Publisher: ", {"color": MUTED}), (d.f(c["publisher_line"]), {})],
    ]
    half(
        MARGIN + w + gap,
        c["right_label"],
        c["sns_label"],
        upper,
        c["sample_label"],
        [highlighted(d.f(c["sample_line"]), PHI_TAG, 11)],
    )
    text(
        s,
        MARGIN,
        top + ph + 0.2,
        SLIDE_W - 2 * MARGIN,
        0.7,
        d.f(c["lines"]),
        size=12,
        color=MUTED,
        spacing=1.2,
        space_after=4,
    )
    footer(s, n, d.total, d.repo)


def slide_results(prs, d: Deck, c: dict, n: int):
    s = new_slide(prs)
    headline(s, d.f(c["headline"]))
    table = d.facts[c["table"]]
    top = 2.3
    label(s, MARGIN, top - 0.38, 11, d.f(table["caption"]))
    header, rows = table["header"], table["rows"]
    first_w = 2.1
    cw = (SLIDE_W - 2 * MARGIN - first_w) / (len(header) - 1)
    rh = 0.52
    panel(s, MARGIN, top, SLIDE_W - 2 * MARGIN, rh * (len(rows) + 1))
    for ri, row in enumerate([header, *rows]):
        ry = top + ri * rh
        if ri:
            line(s, MARGIN, ry, SLIDE_W - MARGIN, ry, color=BORDER, width=0.75)
        text(
            s,
            MARGIN + 0.25,
            ry,
            first_w - 0.3,
            rh,
            row[0],
            size=12,
            color=MUTED if ri == 0 else TEXT,
            font=UI_MEDIUM,
            anchor=MSO_ANCHOR.MIDDLE,
        )
        for ci, value in enumerate(row[1:]):
            text(
                s,
                MARGIN + first_w + ci * cw,
                ry,
                cw,
                rh,
                value,
                size=13,
                color=MUTED if ri == 0 else TEXT,
                font=MONO,
                align=PP_ALIGN.CENTER,
                anchor=MSO_ANCHOR.MIDDLE,
            )
    by = top + rh * (len(rows) + 1) + 0.5
    text(s, MARGIN, by, 6.1, 1.8, d.f(c["lines"]), size=14, spacing=1.25, space_after=12)
    rx = MARGIN + 6.6
    rw = SLIDE_W - MARGIN - rx
    panel(s, rx, by, rw, 1.25)
    text(
        s,
        rx + 0.3,
        by + 0.22,
        rw - 0.6,
        0.3,
        d.f(c["repo_label"]),
        size=11,
        color=MUTED,
        font=UI_MEDIUM,
    )
    text(s, rx + 0.3, by + 0.55, rw - 0.6, 0.5, d.repo, size=13, font=MONO_SEMI)
    footer(s, n, d.total, d.repo)


LAYOUTS = {
    "context": slide_context,
    "gap": slide_gap,
    "detection": slide_detection,
    "architecture": slide_architecture,
    "incident": slide_incident,
    "masking": slide_masking,
    "results": slide_results,
}


def build(data_path: Path = DATA, out: Path = OUT) -> Path:
    data = json.loads(data_path.read_text())
    NO_BREAK[:] = data.get("no_break", [])
    deck = Deck(data)
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    for number, slide in enumerate(data["slides"], 1):
        LAYOUTS[slide["layout"]](prs, deck, slide, number)
    prs.core_properties.title = data.get("title", "ClaimsWatch")
    prs.core_properties.author = ", ".join(data["team"])
    prs.save(out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the ClaimsWatch deck.")
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    print(build(args.data, args.out))


if __name__ == "__main__":
    main()
