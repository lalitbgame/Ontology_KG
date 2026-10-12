"""Phase 1 - layout-aware, span-level text extraction (plan.md §3).

PDF -> lines.jsonl (one record per visual line, reading order) and
page_meta.jsonl (per-page geometry: thin rules, images, drawing boxes).

What this phase does, in order:
  1. Pull every PyMuPDF line with its spans (font, size, flags, baseline).
  2. Merge same-baseline fragments that PyMuPDF splits apart (justified
     text comes out one word per "line" in some PDFs) - but never merge a
     bare numbering token ("5.", "(23)", "II.") into the text after it,
     because Phase 2 relies on number-only lines.
  3. Build `text` (searchable, NFKC-normalised) from spans: subscripts
     become `_x`, superscripts `^x`, superscript digits right after a word
     are footnote references (recorded, removed from the text).
  4. Strip running headers/footers: a normalised text signature that sits
     in a page-edge band on >= 60% of the pages of its odd/even/landscape
     group (OJ acts alternate sides, landscape pages print them vertically).
  5. Tag footnotes: lines below a short separator rule whose first line
     starts with a marker or is set smaller than body text; plus the v1
     small-font-at-the-bottom fallback.
  6. Compute document body statistics (dominant body size, text column,
     numbering column) for Phase 2's relative heading tests.

Tracked-changes tagging stays a no-op (see output/PHASE1_2_NOTES.md,
Phase 0 spike): no PDF in the corpus carries usable markup.
"""
import collections
import re
import sys

import pymupdf

from .common import normalize_text, write_jsonl

# A chemical-formula span: starts/ends on a letter or digit, made only of
# uppercase letters, digits and single spaces (e.g. "CH 4", "C2 H 6").
_FORMULA_RE = re.compile(r"\b[A-Z][A-Z0-9 ]{0,15}[A-Z0-9]\b")
# One element+subscript piece within such a span, e.g. "CH", "2", "H6".
_PIECE_RE = re.compile(r"[A-Z]{0,2}\d{0,3}")
# EU vehicle categories / tyre classes look like formula pieces but must
# never be glued together ("M1 N1" is two categories, not a formula).
_CATEGORY_RE = re.compile(r"^(?:[MNOLC]\d|[MNO]\d[a-z]?)$")


def normalize_chem(text: str) -> str:
    """Collapse spacing artifacts in chemical formulas: 'CH 4' -> 'CH4',
    'C2 H 6' -> 'C2H6'. Piece letters are capped at 2 chars so real
    abbreviations (WLTC, REESS, ...) are never touched, and runs made only
    of vehicle-category tokens (M1, N1, C2 ...) are left alone."""
    def collapse(m):
        span = m.group(0)
        pieces = span.split(" ")
        if len(pieces) > 1 and all(p and _PIECE_RE.fullmatch(p) for p in pieces):
            if sum(bool(_CATEGORY_RE.match(p)) for p in pieces) >= 2:
                return span
            return "".join(pieces)
        return span
    return _FORMULA_RE.sub(collapse, text)


MATH_FONT_RE = re.compile(r"Math|Symbol|MT-Extra|Cambria", re.I)
# A bare numbering token PyMuPDF often emits as its own fragment.
NUMBER_TOKEN_RE = re.compile(
    r"^(?:\(?\d+(?:\.\d+)*\.?\)?|\([a-z]{1,4}\)|\([ivxlc]{1,6}\)|[a-z]\)|[IVXLC]+\.|[A-Z]\.)$")
FOOTNOTE_MARKER_RE = re.compile(r"^(?:\(\d{1,3}\)|\d{1,3}|\*{1,3}|†{1,2}|‡)(?=\s|$|[A-Z(‘\"“])")
FLAG_ITALIC, FLAG_BOLD, FLAG_SUPERSCRIPT = 2, 16, 1


# ---------------------------------------------------------------------------
# 1. Raw fragments
# ---------------------------------------------------------------------------

def _span(s):
    return {"t": s["text"], "x0": round(s["bbox"][0], 1), "x1": round(s["bbox"][2], 1),
            "y0": round(s["bbox"][1], 1), "y1": round(s["bbox"][3], 1),
            "base": round(s["origin"][1], 1), "size": round(s["size"], 1),
            "font": s["font"], "flags": s["flags"]}


def raw_fragments(page):
    """Every non-empty PyMuPDF line on the page as a fragment of spans."""
    frags = []
    d = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
    for block in d["blocks"]:
        for line in block.get("lines", []):
            spans = [_span(s) for s in line["spans"] if s["text"]]
            if not "".join(s["t"] for s in spans).strip():
                continue
            frags.append({"spans": spans, "dir": [round(v, 2) for v in line["dir"]]})
    return frags


def _dominant(spans, key):
    weights = collections.Counter()
    for s in spans:
        weights[s[key]] += len(s["t"].strip()) or 0.1
    return weights.most_common(1)[0][0]


def _geometry(frag):
    sp = frag["spans"]
    frag["x0"] = min(s["x0"] for s in sp)
    frag["x1"] = max(s["x1"] for s in sp)
    frag["y0"] = min(s["y0"] for s in sp)
    frag["y1"] = max(s["y1"] for s in sp)
    frag["size"] = _dominant(sp, "size")
    big = [s for s in sp if s["size"] >= frag["size"] - 0.05 and s["t"].strip()] or sp
    frag["base"] = collections.Counter(s["base"] for s in big).most_common(1)[0][0]
    return frag


# ---------------------------------------------------------------------------
# 2. Same-baseline merge
# ---------------------------------------------------------------------------

def _raw(frag):
    return "".join(s["t"] for s in frag["spans"]).strip()


def mergeable(prev, frag):
    if prev["dir"] != frag["dir"] or prev["dir"] != [1.0, 0.0]:
        return False
    if abs(prev["base"] - frag["base"]) > 1.5:
        return False
    gap = frag["x0"] - prev["x1"]
    if gap < -1 or gap > max(1.6 * prev["size"], 10):
        return False
    if NUMBER_TOKEN_RE.match(_raw(prev)):
        return False
    return True


def merge_fragments(frags):
    """Glue consecutive same-baseline fragments (extraction order only, so
    multi-column / table layouts aren't reshuffled)."""
    out = []
    for f in frags:
        _geometry(f)
        if out and mergeable(out[-1], f):
            prev = out[-1]
            gap = f["x0"] - prev["x1"]
            if gap > 0.15 * prev["size"] and not prev["spans"][-1]["t"].endswith(" ") \
                    and not f["spans"][0]["t"].startswith(" "):
                f["spans"][0] = {**f["spans"][0], "t": " " + f["spans"][0]["t"]}
            prev["spans"].extend(f["spans"])
            _geometry(prev)
        else:
            out.append(f)
    return out


# ---------------------------------------------------------------------------
# 3. Text with sub/superscript markup
# ---------------------------------------------------------------------------

def script_kind(span, base_size, base_line):
    """'sub' / 'sup' / None for a span relative to its line's base text."""
    if span["size"] >= 0.85 * base_size or not span["t"].strip():
        return None
    off = span["base"] - base_line
    if off > 0.8:
        return "sub"
    if off < -0.8 or span["flags"] & FLAG_SUPERSCRIPT:
        return "sup"
    return None


def base_style(spans, default_size, default_base):
    """Base text size/baseline of a line: the largest size carrying >= 20%
    of the characters - not simply the most common size, or a long
    subscript ('SOC' + 'read,i') would be taken as the base."""
    chars = collections.Counter()
    for s in spans:
        chars[s["size"]] += len(s["t"].strip())
    total = sum(chars.values()) or 1
    for size in sorted(chars, reverse=True):
        if chars[size] / total >= 0.2:
            bases = collections.Counter(s["base"] for s in spans if s["size"] == size and s["t"].strip())
            return size, bases.most_common(1)[0][0]
    return default_size, default_base


def build_text(frag):
    """(text, raw_text, footnote_refs, has_math)."""
    spans = frag["spans"]
    base_size, base_line = base_style(spans, frag["size"], frag["base"])
    text, raw, refs = "", "", []
    has_math = False
    for i, s in enumerate(spans):
        t = s["t"]
        raw += t
        if MATH_FONT_RE.search(s["font"]):
            has_math = True
        norm = normalize_text(t)
        kind = script_kind(s, base_size, base_line)
        if kind == "sup":
            mark = norm.strip()
            prev_char = text.rstrip()[-1:] if text.strip() else ""
            if prev_char == "(" and re.fullmatch(r"\d{1,3}", mark):
                # OJ style "(¹)": the marker is printed "(n)" in the text
                refs.append(mark)
                text += mark
                continue
            if re.fullmatch(r"\d{1,3}|\*{1,3}|†|‡", mark) and not MATH_FONT_RE.search(s["font"]) \
                    and prev_char and (prev_char.isalpha() or prev_char in ".,;:)") \
                    and not re.search(r"\d$", text.rstrip()):
                refs.append(mark)
                continue
            text += "^" + mark if text and not text.endswith(" ") else mark
            continue
        if kind == "sub":
            sub = norm.strip()
            if re.fullmatch(r"\d{1,2}|x", sub) and re.search(r"[A-Z][a-z]?$", text):
                text += sub          # chemical formula: CO2, CH4, N2O, NOx
            else:
                text += "_" + sub
            if norm.endswith(" "):
                text += " "
            continue
        text += norm
    text = re.sub(r"\s+", " ", text).strip()
    return text, raw.strip(), refs, has_math


# ---------------------------------------------------------------------------
# 4. Header / footer
# ---------------------------------------------------------------------------

def signature(text):
    t = re.sub(r"\d+", "#", text.lower())
    return re.sub(r"\s+", " ", t).strip()


def in_edge_band(line, w, h):
    side = 0.11 if line.get("dir", [1.0, 0.0]) != [1.0, 0.0] else 0.07   # vertical running heads (landscape OJ pages)
    return (line["y1"] < 0.11 * h or line["y0"] > 0.89 * h
            or line["x1"] < side * w or line["x0"] > (1 - side) * w)


def header_footer_signatures(pages_lines, page_dims, min_share=0.6):
    """Signatures repeating in the edge band on >= min_share of pages, either
    across the whole document or within one parity/orientation group."""
    groups = collections.defaultdict(set)
    for p, (w, h) in page_dims.items():
        groups[(p % 2, w > h)].add(p)
        groups["all"].add(p)
    seen = collections.defaultdict(set)   # signature -> pages
    for p, lines in pages_lines.items():
        w, h = page_dims[p]
        for l in lines:
            if in_edge_band(l, w, h) and len(l["text"]) <= 90:
                seen[signature(l["text"])].add(p)
    sigs = set()
    for sig, pages in seen.items():
        for key, members in groups.items():
            if len(members) >= 3 and len(pages & members) / len(members) >= min_share:
                sigs.add(sig)
                break
    return sigs


# ---------------------------------------------------------------------------
# 5. Footnotes
# ---------------------------------------------------------------------------

def page_rules(page):
    """Thin horizontal vector rules (fraction bars, footnote separators,
    table borders) and other drawing boxes, rounded."""
    rules, boxes = [], []
    for d in page.get_drawings():
        r = d["rect"]
        if r.width <= 0 and r.height <= 0:
            continue
        if r.height <= 1.6 and r.width >= 4:
            rules.append([round(r.x0, 1), round((r.y0 + r.y1) / 2, 1), round(r.x1, 1)])
        elif r.width >= 1 and r.height >= 1:
            boxes.append([round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)])
    return rules, boxes


def footnote_rule_y(lines, rules, w, h, body_size):
    """y of the footnote separator: the lowest short rule in the lower part
    of the page whose first text line below starts with a footnote marker
    or is set smaller than body text. None if the page has no footnotes."""
    if not lines:
        return None
    left = min(l["x0"] for l in lines)
    best = None
    for x0, y, x1 in rules:
        if not (20 <= x1 - x0 <= 0.45 * w and y > 0.45 * h and abs(x0 - left) < 40):
            continue
        # A table border has more rules under it; a footnote separator has
        # none until the footer band.
        if any(ry > y + 3 and ry < 0.92 * h and rx1 - rx0 >= 20 for rx0, ry, rx1 in rules):
            continue
        below = sorted((l for l in lines if l["y0"] >= y - 1), key=lambda l: l["y0"])
        if not below or below[0]["y0"] - y > 25:
            continue
        first = below[0]
        if FOOTNOTE_MARKER_RE.match(first["text"]) or (
                first["size"] < 0.92 * body_size and not first.get("has_math")):
            # footnote text is set smaller than body text in every family we
            # know; body-size lines under the rule mean it's a table border
            # with a table note, followed by normal text
            if all(l["size"] < body_size - 0.25 for l in below):
                best = y if best is None or y < best else best
    return best


# ---------------------------------------------------------------------------
# Body statistics
# ---------------------------------------------------------------------------

def body_statistics(lines):
    sizes, fonts, lefts, numx = (collections.Counter() for _ in range(4))
    for l in lines:
        n = len(l["text"])
        sizes[l["size"]] += n
        fonts[l["font"]] += n
        lefts[round(l["x0"])] += n
        if NUMBER_TOKEN_RE.match(l["text"]) and re.match(r"^\d", l["text"]):
            numx[round(l["x0"])] += 1
    body_size = sizes.most_common(1)[0][0] if sizes else 10.0
    return {
        "body_size": body_size,
        "body_font": fonts.most_common(1)[0][0] if fonts else None,
        "text_left": [x for x, _ in lefts.most_common(3)],
        "number_columns": [[x, c] for x, c in numx.most_common(4)],
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def extract(doc, profile=None):
    profile = profile or {}
    layout = profile.get("layout") or {}
    chem = layout.get("chem_normalize", False)
    pages_lines, page_dims, page_meta = {}, {}, []

    for page in doc:
        w, h = page.rect.width, page.rect.height
        page_dims[page.number] = (w, h)
        lines = []
        for frag in merge_fragments(raw_fragments(page)):
            text, raw, refs, has_math = build_text(frag)
            if not text:
                continue
            if chem:
                text = normalize_chem(text)
            spans = frag["spans"]
            line = {
                "page": page.number,
                "x0": frag["x0"], "y0": frag["y0"], "x1": frag["x1"], "y1": frag["y1"],
                "base": frag["base"], "size": frag["size"],
                "font": _dominant(spans, "font"),
                "bold": bool(_dominant(spans, "flags") & FLAG_BOLD) or "Bold" in _dominant(spans, "font"),
                "italic": bool(_dominant(spans, "flags") & FLAG_ITALIC) or "Ital" in _dominant(spans, "font"),
                "text": text, "raw_text": raw,
                "dir": frag["dir"],
            }
            if refs:
                line["footnote_refs"] = refs
            if has_math:
                line["has_math"] = True
            if has_math or len({(s["size"], s["base"], s["font"]) for s in spans}) > 1:
                line["spans"] = spans
            lines.append(line)
        pages_lines[page.number] = lines
        rules, boxes = page_rules(page)
        images = [[round(v, 1) for v in info["bbox"]] for info in page.get_image_info()]
        chars = sum(len(l["text"]) for l in lines)
        covered = max(((b[2] - b[0]) * (b[3] - b[1]) / (w * h) for b in images), default=0)
        page_meta.append({"page": page.number, "width": round(w, 1), "height": round(h, 1),
                          "rules": rules, "images": images, "n_boxes": len(boxes),
                          "boxes": boxes if len(boxes) <= 400 else [],
                          "needs_ocr": chars < 50 and covered > 0.8})

    hf = header_footer_signatures(pages_lines, page_dims, layout.get("header_min_share", 0.6))
    stripped = 0
    for p, lines in pages_lines.items():
        w, h = page_dims[p]
        keep = [l for l in lines if not (in_edge_band(l, w, h) and signature(l["text"]) in hf)]
        stripped += len(lines) - len(keep)
        pages_lines[p] = keep

    all_lines = [l for p in sorted(pages_lines) for l in pages_lines[p]]
    stats = body_statistics(all_lines)
    body_size = stats["body_size"]

    footnote_lines = 0
    page_sizes = {p: [l["size"] for l in ls] for p, ls in pages_lines.items()}
    for meta in page_meta:
        p = meta["page"]
        lines = pages_lines[p]
        w, h = page_dims[p]
        rule_y = footnote_rule_y(lines, meta["rules"], w, h, body_size)
        meta["footnote_rule_y"] = rule_y
        sizes = sorted(page_sizes[p]) or [body_size]
        median = sizes[len(sizes) // 2]
        for l in lines:
            below_rule = rule_y is not None and l["y0"] >= rule_y - 1
            v1 = (l["size"] < 0.85 * median and l["y0"] > 0.85 * h and not l.get("has_math")
                  and rule_y is None)
            l["is_footnote"] = bool(below_rule or v1)
            footnote_lines += l["is_footnote"]

    for i, l in enumerate(all_lines):
        l["id"] = f"p{l['page']}.{i}"
    return all_lines, page_meta, {
        **stats,
        "header_footer_signatures": sorted(hf),
        "lines": len(all_lines), "header_footer_lines_stripped": stripped,
        "footnote_lines": footnote_lines,
        "needs_ocr_pages": [m["page"] for m in page_meta if m["needs_ocr"]],
    }


def run(ctx):
    doc = pymupdf.open(ctx.pdf_path)
    ctx.init_manifest(doc)
    lines, page_meta, stats = extract(doc, ctx.profile)
    write_jsonl(ctx.path("lines.jsonl"), lines)
    write_jsonl(ctx.path("page_meta.jsonl"), page_meta)
    ctx.manifest["layout"] = {k: v for k, v in stats.items()
                              if k in ("body_size", "body_font", "text_left", "number_columns")}
    ctx.record("phase1_extract", **{k: v for k, v in stats.items()
                                    if k not in ("body_size", "body_font", "text_left", "number_columns")})
    print(f"[{ctx.doc_id}] phase1: {stats['lines']} lines, "
          f"{len(stats['header_footer_signatures'])} header/footer signatures "
          f"({stats['header_footer_lines_stripped']} lines stripped), "
          f"{stats['footnote_lines']} footnote lines, body {stats['body_size']}pt",
          file=sys.stderr)
    return lines
