"""Phase 1b - region classification (plan.md §4, §7.2).

lines.jsonl + page geometry -> regions.jsonl. Every non-prose region on a
page gets a record, so Phase 2 only builds clause text from prose and the
other extractors (tables, figures, equations, glossaries) get clean input:

  toc          the document's own table of contents (dropped)
  table        a captioned table, or an uncaptioned ruled data table; its
               lines leave the clause text and become a Table node
  layout_table an uncaptioned ruled table holding numbered clauses (e.g. a
               form laid out as a grid) - lines stay in the text flow
  figure       a "Figure X" caption plus the graphic under/over it; text
               inside the graphic (flowchart box labels) is figure_labels
  equation     a display equation (math-font lines + fraction rules), an
               equation-sized image between a lead-in and a "where" line,
               or an inline relational math run (decision rules)
  glossary     the "where:" variable list that follows an equation

Regions never overlap in the line sets they claim, with one exception:
equations may sit inside a table (GTR 22 Annex 3 parameter tables), and
then both regions reference the same lines.
"""
import collections
import re
import sys

import pymupdf

from .common import write_jsonl
from .phase1_extract import MATH_FONT_RE, NUMBER_TOKEN_RE

DOT_LEADER_RE = re.compile(r"\.{4,}|…{2,}|(?:\. ){4,}")
TABLE_CAPTION_RE = re.compile(r"^Table\s+(?P<id>[A-Z]?\d+[A-Za-z]?(?:[/.\-]\d+[A-Za-z]?)*)\s*(?:[:.]\s*|\s+|$)(?P<title>.*)$")
FIGURE_CAPTION_RE = re.compile(r"^Figure\s+(?P<id>[A-Z]?[IVX\d]+[A-Za-z]?(?:[/.\-][A-Za-z]?\d+[a-z]?)*)\s*(?:[:.]\s*|\s+|$)(?P<title>.*)$")
RELATION_RE = re.compile(r"[=≤≥<>≦≧]")
MATH_OPERATOR_RE = re.compile(r"[=≤≥<>×∙·∑√∆∫±∗⋅÷∏∂]")
LEAD_IN_RE = re.compile(r"(?:follows|formula|equation|calculated|determined|given by|using)[^.]*:?\s*$|:\s*$", re.I)


def page_lines(lines):
    by_page = collections.defaultdict(list)
    for l in lines:
        by_page[l["page"]].append(l)
    return by_page


def overlaps(a, b, pad=0):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


def inside(line, bbox, pad=2):
    cx, cy = (line["x0"] + line["x1"]) / 2, (line["y0"] + line["y1"]) / 2
    return bbox[0] - pad <= cx <= bbox[2] + pad and bbox[1] - pad <= cy <= bbox[3] + pad


def union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def line_box(l):
    return [l["x0"], l["y0"], l["x1"], l["y1"]]


def rows_text(lines):
    """Cell text from geometry: group lines into rows by baseline, join the
    cells of a row with ' | ' and rows with newlines."""
    rows = []
    for l in sorted(lines, key=lambda l: (round(l["base"]), l["x0"])):
        if rows and abs(rows[-1][0] - l["base"]) <= 2.0:
            rows[-1][1].append(l)
        else:
            rows.append([l["base"], [l]])
    return "\n".join(" | ".join(c["text"] for c in sorted(r, key=lambda c: c["x0"])) for _, r in rows)


# ---------------------------------------------------------------------------
# TOC
# ---------------------------------------------------------------------------

def toc_regions(by_page, n_pages, limit=10):
    out = []
    for p, lines in by_page.items():
        leaders = sum(bool(DOT_LEADER_RE.search(l["text"])) for l in lines)
        has_contents = any(re.fullmatch(r"(?:Table of )?Contents", l["text"].strip(), re.I) for l in lines)
        if leaders >= 3 and (p <= limit or has_contents):
            out.append({"kind": "toc", "page": p, "bbox": union([line_box(l) for l in lines]),
                        "line_ids": [l["id"] for l in lines]})
    return out


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def find_captions(lines, regex):
    caps = []
    for l in lines:
        m = regex.match(l["text"])
        # a caption stands on its own line and isn't running prose
        if m and len(l["text"]) <= 200 \
                and not re.match(r"^(?:of|in|to|and|or|shall|is|are|above|below|thereof|thereto)\b|^[,;)]",
                                 m.group("title") or ""):
            caps.append((l, m))
    return caps


def caption_block(cap, lines, gap=24):
    """Caption line + the short title lines directly under it."""
    block = [cap]
    for l in sorted((l for l in lines if l["y0"] > cap["y0"]), key=lambda l: l["y0"]):
        if l["y0"] - block[-1]["y1"] > gap * 0.6 or len(l["text"]) > 150 or NUMBER_TOKEN_RE.match(l["text"]):
            break
        if l["size"] > cap["size"] + 0.5:
            break
        block.append(l)
        if len(block) >= 4:
            break
    return block


def table_regions(doc, by_page, page_meta, claimed):
    out = []
    for p, lines in by_page.items():
        page = doc[p]
        try:
            found = [list(t.bbox) for t in page.find_tables().tables]
        except Exception:                     # pymupdf table finder edge cases
            found = []
        caps = sorted(find_captions(lines, TABLE_CAPTION_RE), key=lambda cm: cm[0]["y0"])

        def span_end(cap):
            nxt = [c["y0"] for c, _ in caps if c["y0"] > cap["y1"]]
            return min(nxt + [page.rect.height])

        for cap, m in caps:
            if any(cap["y1"] <= b[1] + 4 and b[1] < span_end(cap) for b in found):
                continue
            # caption with no ruled table under it: retry under the caption,
            # rows ruled but columns aligned by text (GTR 22 Tables 1-2)
            clip = pymupdf.Rect(0, cap["y1"], page.rect.width, span_end(cap))
            try:
                tabs = page.find_tables(clip=clip, horizontal_strategy="lines", vertical_strategy="text").tables
            except Exception:
                tabs = []
            if tabs:
                found.append(list(tabs[0].bbox))
        used_caps = set()
        for bbox in sorted(found, key=lambda b: b[1]):
            bbox = [round(v, 1) for v in bbox]
            # the nearest caption above on this page owns the table - one
            # caption can head several detected blocks (Euro 7 Annex II
            # Table 1 = energy-based + range-based sub-tables)
            cap = None
            for c, m in caps:
                if c["y1"] <= bbox[1] + 4 and not (c["x1"] < bbox[0] - 40 or c["x0"] > bbox[2]):
                    cap = (c, m)
            members = [l for l in lines if inside(l, bbox) and l["id"] not in claimed]
            if cap:
                used_caps.add(cap[0]["id"])
                block_ids = {b["id"] for b in caption_block(cap[0], lines)}
                # short sub-header lines between the caption and the table
                members += [l for l in lines if l["id"] not in claimed and l["id"] not in block_ids
                            and cap[0]["y1"] <= l["y0"] and l["y1"] <= bbox[1] + 2
                            and bbox[1] - cap[0]["y1"] < 120 and len(l["text"]) < 120
                            and not inside(l, bbox) and l not in members
                            and not any(c["id"] == l["id"] for c, _ in caps)]
            if not members and not cap:
                continue
            numbered = sum(1 for l in members if NUMBER_TOKEN_RE.match(l["text"]) and re.match(r"\d", l["text"]))
            kind = "table"
            if not cap and numbered >= 3:
                kind = "layout_table"
            order = {l["id"]: i for i, l in enumerate(lines)}
            region = {"kind": kind, "page": p, "bbox": bbox,
                      "line_ids": [l["id"] for l in members], "cell_text": rows_text(members),
                      "flow_text": " ".join(l["text"] for l in sorted(members, key=lambda l: order[l["id"]]))}
            if cap:
                block = caption_block(cap[0], lines)
                block = [b for b in block if b["y1"] <= bbox[1] + 4]
                region["caption_id"] = f"Table {cap[1].group('id')}"
                region["caption"] = " ".join([cap[1].group("title")] + [b["text"] for b in block[1:]]).strip() or None
                region["caption_line_ids"] = [b["id"] for b in block]
            if kind == "table":
                claimed.update(region["line_ids"] + region.get("caption_line_ids", []))
            out.append(region)
        # a caption with no table found at all still yields a Table node
        for cap, m in caps:
            if cap["id"] in used_caps or cap["id"] in claimed:
                continue
            block = caption_block(cap, lines)
            region = {"kind": "table", "page": p, "bbox": union([line_box(b) for b in block]),
                      "line_ids": [], "cell_text": None, "caption_id": f"Table {m.group('id')}",
                      "caption": " ".join([m.group("title")] + [b["text"] for b in block[1:]]).strip() or None,
                      "caption_line_ids": [b["id"] for b in block], "caption_only": True}
            claimed.update(region["caption_line_ids"])
            out.append(region)
    # continuation: an uncaptioned table at the top of the page right after
    # a captioned one inherits its caption (one Table node, two regions)
    tables = [r for r in out if r["kind"] == "table"]
    tables.sort(key=lambda r: (r["page"], r["bbox"][1]))
    for prev, cur in zip(tables, tables[1:]):
        if "caption_id" not in cur and "caption_id" in prev and cur["page"] == prev["page"] + 1 \
                and cur["bbox"][1] < 0.2 * page_meta[cur["page"]]["height"]:
            cur["continues"] = prev.get("continues") or (prev["page"], prev["caption_id"])
            cur["caption_id"] = prev["caption_id"]
            cur["caption"] = prev.get("caption")
    return out


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def graphic_boxes(meta):
    boxes = [b for b in meta.get("images", []) if (b[2] - b[0]) > 40 and (b[3] - b[1]) > 40]
    return boxes + [b for b in meta.get("boxes", []) if (b[2] - b[0]) > 8 and (b[3] - b[1]) > 8]


def cluster_from(start_y, boxes, direction, max_gap=40):
    """Grow a vertical band of graphic boxes starting next to start_y."""
    if direction > 0:
        cand = sorted((b for b in boxes if b[1] >= start_y - 4), key=lambda b: b[1])
    else:
        cand = sorted((b for b in boxes if b[3] <= start_y + 4), key=lambda b: -b[3])
    picked, edge = [], start_y
    for b in cand:
        near = (b[1] - edge if direction > 0 else edge - b[3])
        if near > max_gap and picked:
            break
        if near > max_gap * 2:
            break
        picked.append(b)
        edge = max(edge, b[3]) if direction > 0 else min(edge, b[1])
    return union(picked) if picked else None


def figure_regions(by_page, page_meta, claimed):
    out = []
    for p, lines in by_page.items():
        meta = page_meta[p]
        boxes = graphic_boxes(meta)
        for cap, m in find_captions(lines, FIGURE_CAPTION_RE):
            if cap["id"] in claimed:
                continue
            block = caption_block(cap, lines)
            below = cluster_from(block[-1]["y1"], boxes, +1)
            above = cluster_from(cap["y0"], boxes, -1)
            gbox = below or above
            region = {"kind": "figure", "page": p, "caption_id": f"Figure {m.group('id')}",
                      "caption": " ".join([m.group("title")] + [b["text"] for b in block[1:]]).strip() or None,
                      "caption_line_ids": [b["id"] for b in block]}
            labels = []
            if gbox:
                region["bbox"] = [round(v, 1) for v in gbox]
                labels = [l for l in lines if inside(l, gbox) and l["id"] not in claimed
                          and l["id"] not in region["caption_line_ids"]]
            else:
                region["bbox"] = union([line_box(b) for b in block])
            region["line_ids"] = [l["id"] for l in labels]
            region["figure_labels"] = [l["text"] for l in labels]
            claimed.update(region["line_ids"] + region["caption_line_ids"])
            out.append(region)
    return out


# ---------------------------------------------------------------------------
# Equations + glossaries
# ---------------------------------------------------------------------------

def math_share(line, math_fonts):
    spans = line.get("spans")
    if not spans:
        return 0.0
    tot = mth = 0
    for s in spans:
        n = len(s["t"].strip())
        tot += n
        if MATH_FONT_RE.search(s["font"]) or any(f in s["font"] for f in math_fonts):
            mth += n
    return mth / tot if tot else 0.0


def math_runs(line, math_fonts):
    """Contiguous runs of math-font spans in a line, as (text, spans)."""
    runs, cur = [], []
    for s in line.get("spans") or []:
        if MATH_FONT_RE.search(s["font"]) or any(f in s["font"] for f in math_fonts):
            cur.append(s)
        else:
            if cur and s["t"].strip():
                runs.append(cur)
                cur = []
    if cur:
        runs.append(cur)
    return runs


def fraction_bar_beside(line, lines, rules):
    """A rule right of / under `line`'s '=' with a numerator above it and a
    denominator below it - i.e. a real fraction bar, not a table border."""
    for x0, y, x1 in rules:
        if not (line["y0"] - 4 <= y <= line["y1"] + 4 and x0 >= line["x0"] - 2):
            continue
        above = any(l["y1"] <= y + 1 and y - l["y1"] < 12 and l["x0"] < x1 and l["x1"] > x0 for l in lines)
        below = any(l["y0"] >= y - 1 and l["y0"] - y < 12 and l["x0"] < x1 and l["x1"] > x0 for l in lines)
        if above and below and x1 - x0 < 300:
            return True
    return False


def is_glossary_trigger(line, trigger_re):
    return bool(trigger_re.search(line["text"].strip()))


def equation_regions(by_page, page_meta, claimed, profile, stats):
    eq_cfg = (profile.get("equations") or {})
    fonts = eq_cfg.get("math_fonts", [])
    trigger_re = re.compile(eq_cfg.get("glossary_trigger", r"^[Ww]here\s*:?\s*$"))
    body = stats.get("body_size", 10)
    out = []
    for p, lines in by_page.items():
        meta = page_meta[p]
        order = {l["id"]: i for i, l in enumerate(lines)}
        cand = []
        for l in lines:
            if l.get("is_footnote"):
                continue
            share = math_share(l, fonts) if l.get("has_math") else 0.0
            txt = l["text"]
            words = re.findall(r"[A-Za-z]{3,}", txt)
            prose_like = len(words) >= 6 and share < 0.5
            if share >= 0.5 and not prose_like:
                cand.append(l)
            elif share == 0 and "=" in txt and len(words) <= 3 and fraction_bar_beside(l, lines, meta["rules"]):
                # Times-set fraction (no math font): "X =" next to a rule
                # that has text both above and below it
                cand.append(l)
        # cluster display-math lines into blocks
        cand.sort(key=lambda l: (l["y0"], l["x0"]))
        blocks = []
        for l in cand:
            if blocks:
                b = blocks[-1]
                bb = union([line_box(x) for x in b])
                close = l["y0"] - bb[3] <= 1.3 * max(l["size"], 6) and not (l["x0"] > bb[2] + 60 or l["x1"] < bb[0] - 60)
                # two stacked lines that each carry their own relation are
                # two equations (pass / fail rules), unless a fraction bar
                # between them makes them numerator and denominator
                bar_between = any(bb[3] - 4 <= r[1] <= l["y0"] + 4 for r in meta["rules"])
                separate = (RELATION_RE.search(l["text"]) and any(RELATION_RE.search(x["text"]) for x in b)
                            and not bar_between and l["y0"] >= bb[3] - 1)
                if close and not separate:
                    b.append(l)
                    continue
            blocks.append([l])
        # a fragment with no relation of its own (e.g. a '1/3600' factor set
        # apart) belongs to the equation on the same row
        merged = []
        for b in blocks:
            text = " ".join(x["text"] for x in b)
            bb = union([line_box(x) for x in b])
            host = None
            if not RELATION_RE.search(text):
                # same row first, else the nearest equation within 40pt
                host = next((m for m in merged if not (union([line_box(x) for x in m])[3] < bb[1]
                                                       or union([line_box(x) for x in m])[1] > bb[3])), None)
                own_rule = any(bb[1] - 3 <= r[1] <= bb[3] + 3 and r[0] < bb[2] and r[2] > bb[0] for r in meta["rules"])
                if host is None and merged and (own_rule or MATH_OPERATOR_RE.search(text)):
                    near = min(merged, key=lambda m: abs(bb[1] - union([line_box(x) for x in m])[3]))
                    nb = union([line_box(x) for x in near])
                    between = [x for x in lines if nb[3] - 1 < (x["y0"] + x["y1"]) / 2 < bb[1] + 1
                               and x not in near and x not in b]
                    if abs(bb[1] - nb[3]) < 40 and not between:
                        host = near
            elif len(text) <= 8 and re.fullmatch(r"\s*[A-Za-z]\s*=\s*\w{1,3}\s*", text) and merged:
                # lower limit of a sum/integral set on its own line ("i=1")
                prev = merged[-1]
                pb = union([line_box(x) for x in prev])
                if bb[1] - pb[3] < 10 and re.search(r"[∑∫∏]", " ".join(x["text"] for x in prev)):
                    host = prev
            if host is not None:
                host.extend(b)
                continue
            merged.append(b)
        for b in merged:
            bb = union([line_box(x) for x in b])
            text = " ".join(x["text"] for x in sorted(b, key=lambda x: (x["y0"], x["x0"])))
            has_rule = any(bb[1] - 3 <= r[1] <= bb[3] + 3 and r[0] < bb[2] and r[2] > bb[0] for r in meta["rules"])
            if not (MATH_OPERATOR_RE.search(text) or has_rule):
                continue          # a lone math-font symbol: inline notation, not an equation
            if len(b) == 1 and not RELATION_RE.search(text) and not has_rule:
                continue
            ids = [x["id"] for x in b]
            out.append({"kind": "equation", "page": p, "bbox": [round(v, 1) for v in bb],
                        "line_ids": ids, "source": "text_layer", "display": True,
                        "rules": [r for r in meta["rules"] if bb[1] - 3 <= r[1] <= bb[3] + 3 and r[0] < bb[2] + 2 and r[2] > bb[0] - 2]})
            claimed.update(ids)
        # inline relational math runs inside prose lines (GTR 22 6.3.3 decision rules)
        for l in lines:
            if l["id"] in claimed or not l.get("has_math") or l.get("is_footnote"):
                continue
            for run in math_runs(l, fonts):
                rt = "".join(s["t"] for s in run)
                if RELATION_RE.search(rt) and len(rt.strip()) >= 4:
                    out.append({"kind": "equation", "page": p, "line_ids": [l["id"]],
                                "bbox": [min(s["x0"] for s in run), l["y0"], max(s["x1"] for s in run), l["y1"]],
                                "source": "text_layer", "display": False, "inline": True,
                                "rules": []})
        # equation-sized images framed by a lead-in and/or a "where" line
        for img in meta.get("images", []):
            w, h = img[2] - img[0], img[3] - img[1]
            if not (h < 70 and w > 40 and h > 8):
                continue
            above = [l for l in lines if l["y1"] <= img[1] + 2]
            below = [l for l in lines if l["y0"] >= img[3] - 2]
            prev = max(above, key=lambda l: l["y1"]) if above else None
            nxt = min(below, key=lambda l: l["y0"]) if below else None
            lead = prev is not None and img[1] - prev["y1"] < 45 and LEAD_IN_RE.search(prev["text"])
            where = nxt is not None and nxt["y0"] - img[3] < 45 and is_glossary_trigger(nxt, trigger_re)
            if lead or where:
                out.append({"kind": "equation", "page": p, "bbox": [round(v, 1) for v in img],
                            "line_ids": [], "source": "image", "display": True,
                            "after_line": prev["id"] if prev else None, "rules": []})
        # glossary ("where:") blocks after display equations
        geo = sorted(lines, key=lambda l: (l["y0"], l["x0"]))
        for eq in [r for r in out if r["page"] == p and r["kind"] == "equation" and r.get("display")]:
            # the trigger is one of the first unclaimed lines under the equation
            below = [l for l in geo if l["y0"] >= eq["bbox"][3] - 2 and l["id"] not in claimed][:4]
            trig_line = next((l for l in below if is_glossary_trigger(l, trigger_re)
                              and l["y0"] - eq["bbox"][3] < 3 * max(l["size"], 6) + 20), None)
            if trig_line is None:
                continue
            trig = order[trig_line["id"]]
            members = glossary_lines(lines, trig, claimed, body, stats)
            if members:
                eq["glossary_line_ids"] = [l["id"] for l in members]
                claimed.update(eq["glossary_line_ids"])
    return out


QUOTED_ENTRY_RE = re.compile(r"^[\"“‘'].{1,90}?[\"”’']\s+(?:means|is|refers to)\b")
ENTRY_RE = re.compile(r"^\S{1,30}(?:\s+\S{1,14}){0,2}?\s*(?:\([^)]{0,20}\))?\s+(?:is|are|means|=|represents|denotes|:)\b")


def glossary_lines(lines, trig, claimed, body, stats):
    """The trigger line plus entry / continuation lines that follow it."""
    trigger = lines[trig]
    out = [trigger]
    text_left = min([trigger["x0"]] + [x for x in stats.get("text_left", [])[:1]])
    desc_x = None
    prev = trigger
    for l in lines[trig + 1: trig + 60]:
        if l["id"] in claimed or l.get("is_footnote"):
            break
        gap = l["y0"] - prev["y1"]
        if gap > 2.6 * max(l["size"], 6):
            break
        if NUMBER_TOKEN_RE.match(l["text"]) and l["x0"] < trigger["x0"] - 5:
            break       # next numbered clause in the numbering column
        same_row = abs(l["base"] - prev["base"]) <= 2
        indented = desc_x is not None and l["x0"] >= desc_x - 4
        entry = l.get("has_math") and l["x0"] <= trigger["x0"] + 25 or bool(ENTRY_RE.match(l["text"])) \
            or (l["x0"] <= trigger["x0"] + 25 and len(l["text"]) <= 40 and not l["text"].endswith("."))
        cont = l["text"].strip().lower() in ("and", "and:", "and;") \
            or (len(out) > 1 and not re.search(r"[.;:]\s*$", prev["text"]) and l["text"][:1].islower())
        entry = entry or bool(QUOTED_ENTRY_RE.match(l["text"]))
        if same_row and prev is not trigger:
            desc_x = desc_x or l["x0"]
        elif not (indented or entry or cont):
            break
        if l["x0"] <= text_left + 2 and not entry and not cont and len(re.findall(r"[A-Za-z]{3,}", l["text"])) > 8:
            break
        out.append(l)
        prev = l
        if desc_x is None and l["x0"] > trigger["x0"] + 25:
            desc_x = l["x0"]
    return out if len(out) > 1 else []


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def classify(doc, lines, page_meta, profile, stats):
    by_page = page_lines(lines)
    meta = {m["page"]: m for m in page_meta}
    claimed = set()
    regions = toc_regions(by_page, doc.page_count)
    for r in regions:
        claimed.update(r["line_ids"])
    # equations first: a fraction inside a table cell is still an equation,
    # but the table must not swallow display equations outside its box
    eq = equation_regions(by_page, meta, set(claimed), profile, stats)
    eq_claimed = {i for r in eq for i in r["line_ids"] + r.get("glossary_line_ids", [])}
    tables = table_regions(doc, by_page, meta, claimed | set())
    figures = figure_regions(by_page, meta, claimed | eq_claimed)
    regions += tables + figures + eq
    regions.sort(key=lambda r: (r["page"], r["bbox"][1] if r.get("bbox") else 0))
    counters = collections.Counter()
    for r in regions:
        counters[r["page"]] += 1
        r["id"] = f"p{r['page']}-r{counters[r['page']]}"
    return regions


def run(ctx):
    from .common import read_jsonl
    doc = pymupdf.open(ctx.pdf_path)
    lines = read_jsonl(ctx.path("lines.jsonl"))
    page_meta = read_jsonl(ctx.path("page_meta.jsonl"))
    regions = classify(doc, lines, page_meta, ctx.profile, ctx.manifest.get("layout", {}))
    write_jsonl(ctx.path("regions.jsonl"), regions)
    counts = collections.Counter(r["kind"] for r in regions)
    ctx.record("phase1b_regions", counts=dict(counts),
               captioned_tables=sum(1 for r in regions if r["kind"] == "table" and r.get("caption_id")),
               image_equations=sum(1 for r in regions if r["kind"] == "equation" and r.get("source") == "image"),
               glossaries=sum(1 for r in regions if r.get("glossary_line_ids")))
    print(f"[{ctx.doc_id}] phase1b: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
          file=sys.stderr)
    return regions
