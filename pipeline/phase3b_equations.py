"""Phase 3b - equations and variables as nodes (plan.md §7).

regions.jsonl (equation regions + glossary lines) + lines.jsonl (spans) +
anchors.jsonl (owning unit, node id) -> equations.jsonl, variables.jsonl,
equations/<id>.png crops.

Reconstruction is deterministic and works on span geometry only:
  * a thin vector rule with text above and below it is a fraction bar
    (numerator / denominator by position); a rule just right of a '√'
    glyph is a radical's overline (radicand underneath);
  * '∑' / '∫' / '∏' take the small items stacked above / below as limits;
  * a span smaller than its group's base size and shifted off the baseline
    is a subscript (down) or superscript (up).
The result is a `linear` form (SOCE_measured = (UBE_measured)/(UBE_certified)*100)
and best-effort `latex`; sympy validation decides `parse_status`.

The "where:" glossary under an equation becomes DESCRIBED_AS data (symbol,
description, unit). Equations whose right-hand side uses a symbol another
equation defines get DEPENDS_ON links - the computation chain.
"""
import collections
import re
import sys
import unicodedata

from .common import join_lines, normalize_text, read_jsonl, write_jsonl

RELATIONS = "=≤≥<>≦≧"
REL_RE = re.compile(r"(<=|>=|[=≤≥<>≦≧])")
BIG_OPS = "∑∫∏"
CHAR_MAP = {"∗": "*", "−": "-", "–": "-", "∙": "*", "⋅": "*", "·": "*", "×": "*", "÷": "/",
            "≤": "<=", "≥": ">=", "≦": "<=", "≧": ">=", "⋯": "...", "…": "...", "∆": "Δ"}
LATEX_MAP = {"*": r" \cdot ", "<=": r" \le ", ">=": r" \ge ", "Δ": r"\Delta ", "...": r"\dots ",
             "π": r"\pi ", "ρ": r"\rho ", "σ": r"\sigma ", "ω": r"\omega "}
UNIT_RE = re.compile(r"(?:\[\s*(?P<b>[^\]]{1,15})\]|\((?P<p>(?:Wh|kWh|km|m|g/km|mg/km|#/km|litres|l|kg|s|K|°C|%|per cent|Wh/km|km/h|N|W|kW|V|A|Ah)[^)]{0,6})\)|,\s*(?P<c>(?:Wh|kWh|km|m|g/km|mg/km|#/km|litres|kg|s|K|°C|%|per cent|Wh/km|km/h|N|W|kW|V|A|Ah))\s*[;.]?\s*$)")
PROSE_WORD_RE = re.compile(r"[A-Za-z]{3,}")
DECISION_RE = re.compile(r"\b(Pass|Fail|Take another measurement|another measurement)\b", re.I)
CONDITION_RE = re.compile(r"^(?:In (?:the )?cases? (?:where|that)|For |If |When |In case )", re.I)
TABLE_USE_RE = re.compile(r"\b(?:taken|given|obtained|specified|read) (?:from|in) (Table\s+[A-Z]?[\w/.\-]+)", re.I)


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

def norm(t):
    t = normalize_text(t)
    for a, b in CHAR_MAP.items():
        t = t.replace(a, b)
    return t


def line_items(line, x_range=None):
    spans = line.get("spans") or [{"t": line.get("raw_text") or line["text"], "x0": line["x0"], "x1": line["x1"],
                                   "y0": line["y0"], "y1": line["y1"], "base": line["base"],
                                   "size": line["size"], "font": line.get("font", ""), "flags": 0}]
    out = []
    for s in spans:
        if not s["t"].strip():
            continue
        if x_range and not (x_range[0] - 1 <= (s["x0"] + s["x1"]) / 2 <= x_range[1] + 1):
            continue
        out.append({"kind": "text", "t": norm(s["t"]).strip(), "raw": s["t"], "x0": s["x0"], "x1": s["x1"],
                    "y0": s["y0"], "y1": s["y1"], "base": s["base"], "size": s["size"]})
    return out


def split_big_ops(items):
    """'∑ΔE_REESS,i' -> '∑' + 'ΔE_REESS,i' so the operator can take limits."""
    out = []
    for it in items:
        t = it["t"]
        if it["kind"] == "text" and len(t) > 1 and any(op in t for op in BIG_OPS):
            pos = [i for i, c in enumerate(t) if c in BIG_OPS]
            w = (it["x1"] - it["x0"]) / max(len(t), 1)
            cuts = sorted(set([0] + [p for p in pos] + [p + 1 for p in pos] + [len(t)]))
            for a, b in zip(cuts, cuts[1:]):
                if t[a:b].strip():
                    out.append({**it, "t": t[a:b].strip(), "x0": it["x0"] + a * w, "x1": it["x0"] + b * w})
        else:
            out.append(it)
    return out


def center_y(it):
    return (it["y0"] + it["y1"]) / 2


def center_x(it):
    return (it["x0"] + it["x1"]) / 2


# ---------------------------------------------------------------------------
# 2-D layout -> tree
# ---------------------------------------------------------------------------

def make_struct(kind, children, x0, x1, base, size, y0, y1, **kw):
    return {"kind": kind, "children": children, "x0": x0, "x1": x1, "base": base, "size": size,
            "y0": y0, "y1": y1, "t": "", **kw}


def collapse_rules(items, rules):
    """Turn fraction bars and radical overlines into structural items,
    innermost (narrowest) first."""
    # 1. radical overlines: a rule starting inside a '√' glyph's box, at or
    #    above its top. The glyph is stripped now (it would otherwise be
    #    swallowed into an inner fraction's numerator) and the radical is
    #    wrapped around whatever sits under the rule once fractions are done.
    radicals = []
    for r in sorted(rules, key=lambda r: r[1]):
        rad = next((it for it in items if it["kind"] == "text" and "√" in it["t"]
                    and it["x0"] - 3 <= r[0] <= it["x1"] + 3 and r[1] <= it["y0"] + 4), None)
        if rad is not None:
            rad["t"] = rad["t"].replace("√", "", 1).strip()
            radicals.append((r, rad["x0"]))
    rad_rules = {tuple(r) for r, _ in radicals}
    items = [it for it in items if it["kind"] != "text" or it["t"]]
    # 2. fraction bars, narrowest (innermost) first
    for x0, y, x1 in sorted((r for r in rules if tuple(r) not in rad_rules), key=lambda r: (round(r[2] - r[0]), -r[1])):
        size = max([it["size"] for it in items] or [10])
        reach = 1.9 * size
        num = [it for it in items if x0 - 3 <= center_x(it) <= x1 + 3 and y - reach < center_y(it) < y]
        den = [it for it in items if x0 - 3 <= center_x(it) <= x1 + 3 and y < center_y(it) < y + reach]
        if num and den:
            f = make_struct("frac", [layout(num, []), layout(den, [])], min(x0, *(i["x0"] for i in num + den)),
                            max(x1, *(i["x1"] for i in num + den)), y + 0.32 * size, size,
                            min(i["y0"] for i in num), max(i["y1"] for i in den))
            items = [it for it in items if it not in num and it not in den] + [f]
    # 3. radicals, narrowest first, over everything under their overline
    for (x0, y, x1), gx0 in sorted(radicals, key=lambda rr: rr[0][2] - rr[0][0]):
        radicand = [it for it in items if x0 - 14 <= center_x(it) <= x1 + 2 and center_y(it) > y and it["y0"] < y + 40]
        if radicand:
            s = make_struct("sqrt", [layout(radicand, [])], gx0, x1, main_baseline(radicand),
                            max(i["size"] for i in radicand), y, max(i["y1"] for i in radicand))
            items = [it for it in items if it not in radicand] + [s]
    return items


def main_baseline(items):
    rel = [it for it in items if it["kind"] == "text" and any(c in it["t"] for c in RELATIONS)]
    if rel:
        return rel[0]["base"]
    big = max((it["size"] for it in items), default=10)
    cands = collections.Counter()
    for it in items:
        if it["size"] >= big - 0.3:
            cands[round(it["base"])] += max(len(it.get("t") or ""), 1)   # weight by characters, not spans
    return cands.most_common(1)[0][0] if cands else items[0]["base"]


def attach_limits(items):
    out = []
    used = set()
    for op in items:
        if op["kind"] == "text" and op["t"] in BIG_OPS:
            near = [it for it in items if it is not op and id(it) not in used
                    and op["x0"] - 8 <= center_x(it) <= op["x1"] + 8 and it["kind"] == "text"]
            upper = [it for it in near if center_y(it) < op["y0"] + 1]
            lower = [it for it in near if center_y(it) > op["y1"] - 1]
            for it in upper + lower:
                used.add(id(it))
            out.append(make_struct("op", [layout(lower, []) if lower else [], layout(upper, []) if upper else []],
                                   op["x0"], op["x1"], op["base"], op["size"], op["y0"], op["y1"], sym=op["t"]))
            used.add(id(op))
    return [it for it in items if id(it) not in used] + out


def layout(items, rules):
    """Items + rules -> ordered list of atoms (text / script / structs)."""
    if not items:
        return []
    items = split_big_ops(items)
    items = collapse_rules(items, rules)
    items = attach_limits(items)
    base = main_baseline(items)
    size = max((it["size"] for it in items if abs(it["base"] - base) < 1.5), default=10)
    seq = []
    prev_base = None
    for it in sorted(items, key=lambda i: (i["x0"], i["base"])):
        role = "base"
        if it["kind"] == "text" and it["size"] < 0.86 * size:
            if it["base"] - base > 0.7:
                role = "sub"
            elif base - it["base"] > 0.7:
                role = "sup"
            elif prev_base is not None:
                # baseline unreliable (some PDFs give sub and base text one
                # baseline): compare boxes with the preceding base item
                if it["y0"] > prev_base["y0"] + 1.2 and it["y1"] >= prev_base["y1"] - 1:
                    role = "sub"
                elif it["y1"] < prev_base["y1"] - 1.2:
                    role = "sup"
        if role == "base" and it["kind"] == "text":
            prev_base = it
        seq.append({**it, "role": role})
    return seq


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render(seq, mode):
    out = []
    for it in seq:
        if it["kind"] == "frac":
            n, d = (render(c, mode) for c in it["children"])
            out.append(f"\\frac{{{n}}}{{{d}}}" if mode == "latex" else f"({n})/({d})")
        elif it["kind"] == "sqrt":
            r = render(it["children"][0], mode)
            out.append(f"\\sqrt{{{r}}}" if mode == "latex" else f"sqrt({r})")
        elif it["kind"] == "op":
            lo, up = (render(c, mode) if c else "" for c in it["children"])
            name = {"∑": "sum", "∫": "int", "∏": "prod"}[it["sym"]]
            s = f"\\{name}" if mode == "latex" else name
            if lo:
                s += f"_{{{lo}}}"
            if up:
                s += f"^{{{up}}}"
            out.append(s + " ")
        else:
            t = it["t"]
            if mode == "latex":
                for a, b in LATEX_MAP.items():
                    t = t.replace(a, b)
            if it["role"] == "sub":
                t = t.strip()
                out.append(f"_{{{t}}}" if mode == "latex" or not re.fullmatch(r"[A-Za-z0-9]+", t) else f"_{t}")
            elif it["role"] == "sup":
                out.append(f"^{{{t.strip()}}}")
            else:
                if out and out[-1] and not out[-1].endswith((" ", "(")) and t[:1].isalnum() and out[-1][-1:].isalnum():
                    out.append(" ")
                out.append(t)
    s = "".join(out)
    return re.sub(r"\s+", " ", s).strip()


SYMBOL_RE = re.compile(
    r"(?<![\w.])(?:Δ\s?)?[A-Za-zα-ωΑ-Ω][A-Za-z0-9]*(?:_\{[^}]*\}|_[A-Za-z0-9][A-Za-z0-9,.\-]*)?(?:\([a-z]\))?(?:_\{[^}]*\}|_[A-Za-z0-9][A-Za-z0-9,.\-]*)?")
NOT_SYMBOLS = {"sqrt", "sum", "int", "prod", "dt", "d", "if", "and", "or", "the", "of", "for", "max", "min", "ln", "log", "exp"}


def symbol_key(sym):
    """Canonical variable key: 'SOC_{read,i}' -> 'SOC_read,i'; Δ kept as 'Delta'."""
    s = normalize_text(sym).replace("Δ", "Delta_").replace("∆", "Delta_")
    s = re.sub(r"[{}]", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    s = s.replace("−", "-").replace("Delta__", "Delta_")
    return s.strip("_")


def phrase_symbols(text):
    """Prose-named quantities ('Virtual distance (km)') become one symbol."""
    out = []
    for part in re.split(r"[=*/()+\-\[\]]|\s{2,}", text):
        words = PROSE_WORD_RE.findall(part)
        if len(words) >= 2:
            out.append("_".join(part.split()).strip("_"))
    return out


def extract_symbols(linear):
    syms = []
    plain = re.sub(r"\[[^\]]*\]", " ", linear)
    for m in SYMBOL_RE.finditer(plain):
        s = m.group(0).strip()
        if s.lower() in NOT_SYMBOLS or len(s) > 40:
            continue
        syms.append(s)
    return list(dict.fromkeys(syms))


def lhs_of(linear):
    m = REL_RE.search(linear)
    if not m or m.group(1) != "=":
        return None
    left = re.sub(r"\[[^\]]*\]|\((?:km|Wh|kWh|g/km|%|s|kg|litres)\)", "", linear[:m.start()]).strip(" (")
    syms = extract_symbols(left)
    if len(syms) == 1 and re.fullmatch(re.escape(syms[0]) + r"\s*", left.strip()):
        return syms[0]
    words = PROSE_WORD_RE.findall(left)
    if 1 <= len(words) <= 5 and not re.search(r"[+*/]", left):
        return "_".join(left.split())
    return None


def validate(linear):
    """sympy round-trip on the relation sides, symbols swapped for x0..xn."""
    try:
        import sympy
        from sympy.parsing.sympy_parser import parse_expr, standard_transformations, \
            implicit_multiplication_application
    except ImportError:
        return "unparsed"
    expr = re.sub(r"\[[^\]]*\]", "", linear)
    syms = sorted(extract_symbols(expr), key=len, reverse=True)
    for i, s in enumerate(syms):
        expr = re.sub(r"(?<![\w.])" + re.escape(s) + r"(?![\w])", f" x{i} ", expr)
    expr = expr.replace("^", "**").replace("{", "(").replace("}", ")").replace("...", "")
    expr = re.sub(r"\bsum_\([^)]*\)\*\*\([^)]*\)|\bsum_\([^)]*\)|\bint_\([^)]*\)\*\*\([^)]*\)", " ", expr)
    expr = expr.replace("sqrt", "sqrt")
    parts = [p for p in re.split(r"<=|>=|=|<|>", expr) if p.strip()]
    if not parts:
        return "unparsed"
    tr = standard_transformations + (implicit_multiplication_application,)
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for p in parts:
                e = parse_expr(p, transformations=tr, evaluate=False)
                if isinstance(e, tuple) or getattr(e, "is_Tuple", False):
                    return "partial"
        return "parsed"
    except Exception:
        return "partial"


# ---------------------------------------------------------------------------
# Glossaries
# ---------------------------------------------------------------------------

UNIT_ONLY_RE = re.compile(r"^(?:Wh|kWh|km|g/km|mg/km|Wh/km|V|A|s|K|kg|litres|per cent|%)\s*[;.,]?\s*$")
DESC_SPLIT_RE = re.compile(r"\s+(?:is|are|means|represents|denotes)\s+|\s*[:=]\s+")


def parse_unit(desc, symbol_text=""):
    for txt in (symbol_text, desc):
        m = UNIT_RE.search(txt or "")
        if m:
            return (m.group("b") or m.group("p") or m.group("c")).strip()
    return None


def parse_glossary(glines, trigger_x):
    """Glossary lines -> [{symbol, description, unit}]."""
    entries = []
    sym_col = None
    for l in glines[1:]:
        text = l["text"].strip()
        if text.lower().rstrip(":;") in ("and", "where", "with"):
            continue
        starts_entry = l["x0"] <= trigger_x + 30 and (sym_col is None or l["x0"] <= sym_col + 30)
        if entries and entries[-1].get("_desc_x") and l["x0"] >= entries[-1]["_desc_x"] - 4:
            starts_entry = False
        if entries and abs(l["base"] - entries[-1]["_base"]) <= 2 and l["x0"] > entries[-1]["_x1"]:
            entries[-1]["desc"].append(text)          # description on the symbol's row
            entries[-1]["_desc_x"] = entries[-1].get("_desc_x") or l["x0"]
            entries[-1]["_x1"] = l["x1"]
            continue
        looks_symbol = bool(DESC_SPLIT_RE.search(text[:60])) or bool(re.match(r"^[\"“‘]", text)) or (
            len(text) <= 30 and (not text[:1].islower() or len(text) <= 8) and not UNIT_ONLY_RE.match(text))
        has_split = bool(DESC_SPLIT_RE.search(text[:60]))
        prose_cont = text[:1].islower() and not has_split and len(text) > 6
        if starts_entry and entries and (prose_cont or UNIT_ONLY_RE.match(text) or not looks_symbol):
            starts_entry = False
        if starts_entry:
            sym_col = sym_col or l["x0"]
            m = re.match(r"^[\"“‘](.+?)[\"”’]\s+(?:means|is)\s+(.*)$", text)
            if m:
                sym, desc = m.group(1), m.group(2)
            else:
                parts = DESC_SPLIT_RE.split(text, maxsplit=1)
                if len(parts) == 2 and len(parts[0]) <= 45:
                    sym, desc = parts
                else:
                    sym, desc = text, ""
            entries.append({"symbol_text": sym.strip(), "desc": [desc] if desc else [],
                            "_base": l["base"], "_x1": l["x1"]})
        elif entries:
            entries[-1]["desc"].append(text)
            entries[-1]["_desc_x"] = entries[-1].get("_desc_x") or l["x0"]
    out = []
    for e in entries:
        desc = join_lines(e["desc"]).strip(" ;,")
        desc = re.sub(r"^(?:is|are|means)\s+", "", desc)
        sym = e["symbol_text"]
        unit = parse_unit(desc, sym)
        sym_clean = re.sub(r"\s*\((?:litres|km|Wh|kWh|g/km|kg|s|%)\)\s*$", "", sym).strip()
        if not sym_clean or len(sym_clean) > 60:
            continue
        out.append({"symbol": symbol_key(sym_clean), "symbol_text": sym_clean,
                    "description": desc or None, "unit": unit})
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def crop(doc, page, bbox, path, pad=4):
    import pymupdf
    pg = doc[page]
    r = pymupdf.Rect(bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad) & pg.rect
    if r.is_empty:
        return False
    pg.get_pixmap(clip=r, dpi=144).save(path)
    return True


def split_row_equations(items):
    """Two equations side by side (GTR 22 Annex 3: STP | CCP columns) ->
    two item groups, split at a wide x gap, each with its own relation."""
    xs = sorted(items, key=lambda i: i["x0"])
    groups, cur, edge = [], [], None
    for it in xs:
        if cur and it["x0"] - edge > 45:
            groups.append(cur)
            cur = []
        cur.append(it)
        edge = max(edge or it["x1"], it["x1"]) if cur[:-1] else it["x1"]
    if cur:
        groups.append(cur)
    if len(groups) > 1 and all(any(c in it["t"] for it in g for c in RELATIONS) for g in groups):
        return groups
    return [items]


def build_equation(region, items, rules, context):
    seq = layout(items, [r for r in rules])
    linear = render(seq, "linear")
    latex = render(seq, "latex")
    rels = REL_RE.findall(linear)
    own = DECISION_RE.search(linear)
    if own:
        context = linear
        linear = re.sub(r"^.*?\bif\b:?\s*", "", linear)
        latex = re.sub(r"^.*?\bif\b:?\s*", "", latex)
    if any(r in ("<=", ">=", "<", ">", "≤", "≥") for r in rels):
        kind = "decision_rule" if DECISION_RE.search(context or "") else "inequality"
    elif "=" in rels:
        kind = "equation"
    else:
        kind = "expression"
    syms = extract_symbols(linear) + phrase_symbols(linear)
    syms = [s for s in dict.fromkeys(syms) if not re.fullmatch(r"[a-z]{2,}", s) or len(s) <= 2]
    lhs = lhs_of(linear)
    outcome = None
    if kind == "decision_rule":
        m = DECISION_RE.search(context or "")
        outcome = {"pass": "pass", "fail": "fail"}.get(m.group(1).lower(), "continue")
    return {"kind": kind, "linear": linear, "latex": latex, "lhs": symbol_key(lhs) if lhs else None,
            "symbols": [symbol_key(s) for s in syms], "outcome": outcome,
            "parse_status": validate(linear) if kind != "expression" or linear else "unparsed"}


def run(ctx):
    import pymupdf
    doc = pymupdf.open(ctx.pdf_path)
    lines = read_jsonl(ctx.path("lines.jsonl"))
    regions = read_jsonl(ctx.path("regions.jsonl"))
    anchors = {a["region_id"]: a for a in read_jsonl(ctx.path("anchors.jsonl"))}
    units = {u["qualified_id"]: u for u in read_jsonl(ctx.path("units.jsonl"))}
    by_id = {l["id"]: l for l in lines}
    index = {l["id"]: i for i, l in enumerate(lines)}
    crop_dir = ctx.path("equations")
    crop_dir.mkdir(exist_ok=True)
    for old in crop_dir.glob("*.png"):
        old.unlink()

    equations = []
    dropped = 0
    for r in regions:
        if r["kind"] != "equation" or r["id"] not in anchors:
            continue
        a = anchors[r["id"]]
        unit = units.get(a["unit_id"])
        rlines = [by_id[i] for i in r["line_ids"] if i in by_id]
        first_idx = min((index[l["id"]] for l in rlines), default=None)
        ctx_line = None
        if first_idx is not None:
            j = first_idx - 1
            while j >= 0 and lines[j]["id"] in set(r["line_ids"]):
                j -= 1
            ctx_line = lines[j]["text"] if j >= 0 else None
        elif r.get("after_line") in by_id:
            ctx_line = by_id[r["after_line"]]["text"]
        context = ctx_line
        if r.get("inline") and rlines:
            context = rlines[0]["text"]
        glines = [by_id[i] for i in r.get("glossary_line_ids", []) if i in by_id]
        glossary = parse_glossary(glines, glines[0]["x0"]) if glines else []
        base = {"region_id": r["id"], "unit_id": a["unit_id"], "page": r["page"], "bbox": r["bbox"],
                "source": r.get("source", "text_layer"), "inline": bool(r.get("inline")),
                "context_before": context,
                "condition": context if context and CONDITION_RE.match(context) else None,
                "glossary": glossary, "normative": (unit or {}).get("normative", True)}
        m = TABLE_USE_RE.search((unit or {}).get("body_text", ""))
        base["uses_table_caption"] = m.group(1) if m else None
        # printed equation number "(3)" in the right margin, same rows
        lab = next((l["text"].strip("() ") for l in lines if l["page"] == r["page"]
                    and re.fullmatch(r"\(\d{1,3}[a-z]?\)", l["text"].strip())
                    and l["x0"] > r["bbox"][2] and r["bbox"][1] - 2 <= l["base"] <= r["bbox"][3] + 2), None)
        base["label"] = lab
        if r.get("source") == "image":
            eqs = [{**base, "kind": "equation", "linear": None, "latex": None, "lhs": None,
                    "symbols": [g["symbol"] for g in glossary], "outcome": None, "parse_status": "image_only",
                    "raw_text": None}]
        else:
            x_range = (r["bbox"][0], r["bbox"][2]) if r.get("inline") else None
            items = [it for l in rlines for it in line_items(l, x_range)]
            if not items:
                continue
            raw = " ".join(l["raw_text"] for l in rlines) if not r.get("inline") else \
                "".join(it["raw"] for it in sorted(items, key=lambda i: i["x0"]))
            eqs = []
            groups = split_row_equations(items) if not r.get("inline") else [items]
            for g in groups:
                gx0, gx1 = min(i["x0"] for i in g), max(i["x1"] for i in g)
                rules = [ru for ru in r.get("rules", []) if ru[0] >= gx0 - 6 and ru[2] <= gx1 + 6]
                e = build_equation(r, g, rules, context)
                bbox = [gx0, min(i["y0"] for i in g), gx1, max(i["y1"] for i in g)] if len(groups) > 1 else r["bbox"]
                eqs.append({**base, **e, "raw_text": raw if len(groups) == 1 else
                            " ".join(i["raw"] for i in sorted(g, key=lambda i: (i["base"], i["x0"]))),
                            "bbox": bbox})
        # a bare numeric fragment ("1/3600" set apart from its integral) is
        # not an equation of its own
        kept = [e for e in eqs if not (e["kind"] == "expression" and not e["symbols"])]
        dropped += len(eqs) - len(kept)
        eqs = kept
        for k, e in enumerate(eqs):
            nid = a["node_id"] if k == 0 else f"{a['node_id']}b{k}"
            e["id"] = nid
            safe = re.sub(r"[^\w.\-]", "_", nid)
            e["image_path"] = f"equations/{safe}.png" if crop(doc, e["page"], e["bbox"], crop_dir / f"{safe}.png") else None
            equations.append(e)

    # Variables: one node per symbol key in the document; meanings stay on
    # the equation (DESCRIBED_AS data), since 's' or 'i' mean different
    # things in different equations.
    # glossary symbols are typeset separately from the equation; reconcile
    # spelling variants ('UBEmeasured,nc' vs 'UBE_measured,nc') by a
    # compact key before they become variables
    def compact(k):
        return re.sub(r"[_\s{}]", "", k or "").lower()

    for e in equations:
        known = {compact(s): s for s in e["symbols"] + ([e["lhs"]] if e["lhs"] else [])}
        for g in e["glossary"]:
            if g["symbol"] not in known.values() and compact(g["symbol"]) in known:
                g["symbol"] = known[compact(g["symbol"])]

    variables = {}
    for e in equations:
        for s in e["symbols"] + [g["symbol"] for g in e["glossary"]] + ([e["lhs"]] if e["lhs"] else []):
            if not s or len(s) > 60:
                continue
            v = variables.setdefault(s, {"id": f"{ctx.doc_id}.VAR:{s}", "symbol": s, "display": s.replace("_", ""),
                                         "latex": re.sub(r"_(.+)$", r"_{\1}", s), "equations": 0, "descriptions": []})
            v["equations"] += 1
        for g in e["glossary"]:
            v = variables.get(g["symbol"])
            if v and g["description"] and g["description"] not in v["descriptions"]:
                v["descriptions"].append(g["description"])
    definers = collections.defaultdict(list)
    for e in equations:
        if e["lhs"] and e["kind"] == "equation":
            definers[e["lhs"]].append(e["id"])
    for e in equations:
        uses = [s for s in e["symbols"] if s != e["lhs"]]
        e["depends_on"] = sorted({d for s in uses for d in definers.get(s, []) if d != e["id"]})

    write_jsonl(ctx.path("equations.jsonl"), equations)
    write_jsonl(ctx.path("variables.jsonl"), list(variables.values()))
    status = collections.Counter(e["parse_status"] for e in equations)
    kinds = collections.Counter(e["kind"] for e in equations)
    ctx.record("phase3b_equations", equations=len(equations), variables=len(variables),
               parse_status=dict(status), kinds=dict(kinds),
               with_glossary=sum(1 for e in equations if e["glossary"]),
               with_lhs=sum(1 for e in equations if e["lhs"]),
               depends_on_edges=sum(len(e["depends_on"]) for e in equations),
               crops=sum(1 for e in equations if e["image_path"]),
               numeric_fragments_dropped=dropped)
    print(f"[{ctx.doc_id}] phase3b: {len(equations)} equations ({', '.join(f'{k} {v}' for k, v in kinds.items())}; "
          f"{', '.join(f'{k} {v}' for k, v in status.items())}), {len(variables)} variables",
          file=sys.stderr)
    return equations
