"""Phase 3 - definitions and abbreviations, generalized (plan.md §6).

units.jsonl (+ lines/regions/anchors for table geometry) ->
definitions.jsonl, abbreviations.jsonl.

  * Definition / abbreviation sections are found by their heading TITLE
    (profile `terms.definition_sections` / `abbreviation_sections`), never
    by a hard-coded clause number.
  * Definition patterns are quote-agnostic ("…", “…”, ‘…’) and accept
    means / refers to / is / shall mean, with an optional "(ABBR)" or
    "or ‘ABBR’" right after the term.
  * Abbreviation tables are split into term | expansion columns by x-gap
    clustering of their own lines, not a fixed x0 threshold.
  * Inline abbreviations come from definitions ("(UBE)", "or ‘CoP’") and
    from body text "Expansion Words (ACRONYM)" where the acronym's letters
    are the expansion's word initials.

Still no merge of an Abbreviation with its matching Definition and no
MENTIONED_IN / SAME_AS edges: term-model-deferral (schema.yaml) holds.
"""
import collections
import re
import sys

from .common import Q_CLOSE, Q_OPEN, join_lines, read_jsonl, write_jsonl

VERBS = r"(?:means|shall mean|refers to|is|are|denotes)"
DEFINITION_RE = re.compile(
    rf"^{Q_OPEN}(?P<term>[^\"“”‘’]{{1,160}}?){Q_CLOSE}\s*"
    rf"(?:\((?P<abbr>[^()]{{1,40}})\)\s*|,?\s*or\s+{Q_OPEN}(?P<abbr2>[^\"“”‘’]{{1,40}}){Q_CLOSE}\s*)?"
    rf",?\s*(?P<verb>{VERBS})\b[\s,]*(?P<gloss>.*)$", re.S)
TERM_ABBR_RE = re.compile(r"^(?P<term>.+?)\s*\((?P<abbr>[A-Z][\w\-./]{0,15})\)$")
IMPORTED_RE = re.compile(r"\bas defined (?:in|by)\b|\bwithin the meaning of\b", re.I)
SECTION_IMPORT_RE = re.compile(r"(?:relevant )?definitions?\b[^.]{0,80}?\bin\b[^.]{0,120}?\b(?:shall )?apply", re.I)
PLACEHOLDER_RE = re.compile(r"\[(?:TABLE|FIGURE|EQ|FORM):[^\]]+\]")
INLINE_ABBR_RE = re.compile(
    r"(?P<exp>(?:[A-Za-z][\w\-’']*\s+){0,8}[A-Za-z][\w\-’']*)\s+\((?P<abbr>[A-Z][A-Za-z0-9]*(?:[\-/.][A-Za-z0-9]+)*)\)")
STOP = {"of", "the", "and", "for", "to", "in", "on", "a", "an", "with", "by", "or"}


def unit_text(u):
    return PLACEHOLDER_RE.sub(" ", u.get("body_text") or "").strip()


def descendants(units, root_ids):
    children = collections.defaultdict(list)
    for u in units:
        if u["parent_id"]:
            children[u["parent_id"]].append(u["qualified_id"])
    out, stack = set(), list(root_ids)
    while stack:
        i = stack.pop()
        if i in out:
            continue
        out.add(i)
        stack.extend(children.get(i, []))
    return out


def sections_matching(units, patterns):
    rx = [re.compile(p, re.I) for p in patterns]
    return [u for u in units if u.get("title") and any(r.search(u["title"]) for r in rx)]


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------

def parse_definition(text):
    m = DEFINITION_RE.match(text.strip())
    if not m:
        return None
    term = re.sub(r"\s+", " ", m.group("term")).strip(" ,")
    abbr = (m.group("abbr") or m.group("abbr2") or "").strip() or None
    tm = TERM_ABBR_RE.match(term)
    if tm and not abbr:
        term, abbr = tm.group("term").strip(), tm.group("abbr")
    gloss = m.group("gloss").strip()
    if not gloss or len(term) < 1:
        return None
    if abbr and not re.search(r"[A-Za-z]", abbr):
        abbr = None
    return {"quoted_term": term, "abbreviation": abbr, "verb": m.group("verb"), "gloss": gloss}


def scope_unit(u, by_id, scope_res):
    """Nearest ancestor (or self) stating 'For the purposes of this <X>'."""
    cur = u
    while cur is not None:
        if any(r.search(cur.get("body_text") or "") for r in scope_res) and cur.get("level") != "decimal":
            return cur["qualified_id"]
        cur = by_id.get(cur["parent_id"]) if cur["parent_id"] else None
    return None


def extract_definitions(units, terms_cfg, doc_id):
    by_id = {u["qualified_id"]: u for u in units}
    secs = sections_matching(units, terms_cfg.get("definition_sections", [r"^Definitions?\b"]))
    in_scope = descendants(units, [s["qualified_id"] for s in secs])
    scope_res = [re.compile(p, re.I) for p in terms_cfg.get("scope_patterns", [])]
    out = []
    for u in units:
        if u["qualified_id"] not in in_scope:
            continue
        text = unit_text(u)
        if u.get("title") and u["title"][0] in "\"“‘'":
            text = f"{u['title']} {text}".strip()
        d = parse_definition(text)
        if not d:
            continue
        d["source_clause"] = u["qualified_id"]
        d["id"] = f"{doc_id}.DEF:{u['qualified_id'][len(doc_id) + 1:]}"
        d["defined_by_reference"] = bool(IMPORTED_RE.search(d["gloss"]))
        d["scope_unit"] = scope_unit(u, by_id, scope_res)
        d["normative"] = u.get("normative", True)
        out.append(d)
    imports = []
    for s in secs:
        for uid in sorted(descendants(units, [s["qualified_id"]])):
            m = SECTION_IMPORT_RE.search(unit_text(by_id[uid]))
            if m:
                imports.append({"unit_id": uid, "text": m.group(0)})
    return out, imports


# ---------------------------------------------------------------------------
# Abbreviations
# ---------------------------------------------------------------------------

def column_split(lines):
    """x boundary between the term column and the expansion column: the
    widest gap between the two most populated x0 clusters."""
    xs = collections.Counter(round(l["x0"] / 4) * 4 for l in lines)
    if len(xs) < 2:
        return None
    top = sorted(x for x, _ in xs.most_common(4))
    left = top[0]
    right = next((x for x in top[1:] if x - left >= 25), None)
    return None if right is None else (left + right) / 2


def extract_column_pairs(lines, split=None):
    """Two-column (surface_form | expansion) table: a line left of `split`
    starts a new entry; lines to its right extend that entry's expansion.
    Sorted by (page, y0, x0) first so a row's term always precedes its
    expansion even when raw extraction order batches term-column lines."""
    split = split if split is not None else column_split(lines)
    if split is None:
        return []
    entries, current = [], None
    for l in sorted(lines, key=lambda l: (l["page"], round(l["y0"], 1), l["x0"])):
        if l["x0"] < split:
            current = {"surface_form": l["text"].strip(), "parts": []}
            entries.append(current)
        elif current is not None:
            current["parts"].append(l["text"])
    for e in entries:
        e["expansion"] = join_lines(e.pop("parts")).strip()
    return [e for e in entries if e["expansion"] and len(e["surface_form"]) <= 40]


def unit_lines(u, lines, anchors_by_unit, region_lines):
    out = [lines[i] for a, b in u.get("line_ranges", []) for i in range(a, b + 1)]
    for rid in anchors_by_unit.get(u["qualified_id"], []):
        out += region_lines.get(rid, [])
    return out


def acronym_expansion(words, abbr):
    """Trailing words of `words` whose initials spell `abbr`'s letters."""
    letters = [c.lower() for c in abbr if c.isalpha()]
    if len(letters) < 2:
        return None
    for start in range(max(0, len(words) - len(letters) - 4), len(words)):
        cand = words[start:]
        initials = [w[0].lower() for w in cand if w.lower() not in STOP and w[:1].isalpha()]
        joined = "".join(w.lower() for w in cand)
        if not cand or cand[0].lower() in STOP:
            continue
        if initials[: len(letters)] == letters[: len(initials)] and len(initials) >= len(letters) - 1 \
                and initials[0] == letters[0]:
            return " ".join(cand)
        # hyphenated / compound acronyms: letters as subsequence of the text
        it = iter(joined)
        if all(c in it for c in letters) and cand[0][0].lower() == letters[0] and len(cand) <= len(letters) + 2:
            return " ".join(cand)
    return None


def inline_abbreviations(units, doc_id):
    out = []
    for u in units:
        text = unit_text(u)
        for m in INLINE_ABBR_RE.finditer(text):
            abbr = m.group("abbr")
            if len(abbr) < 2 or abbr.isdigit() or re.fullmatch(r"[IVXL]+|[a-z]+", abbr):
                continue
            exp = acronym_expansion(m.group("exp").split(), abbr)
            if exp:
                out.append({"surface_form": abbr, "expansion": exp, "category": "Inline",
                            "source": "inline", "source_clause": u["qualified_id"]})
    return out


def extract_abbreviations(units, lines, anchors, regions, terms_cfg, definitions):
    anchors_by_unit = collections.defaultdict(list)
    for a in anchors:
        if a["kind"] == "table":
            anchors_by_unit[a["unit_id"]].append(a["region_id"])
    line_by_id = {l["id"]: l for l in lines}
    region_lines = {r["id"]: [line_by_id[i] for i in r.get("line_ids", []) if i in line_by_id] for r in regions}
    secs = sections_matching(units, terms_cfg.get("abbreviation_sections", [r"^Abbreviations"]))
    sec_ids = {s["qualified_id"] for s in secs}
    out = []
    for s in secs:
        # a section with sub-sections (2. Abbreviations -> 2.1/2.2) is
        # handled through its children, which are sections themselves
        if any(u["parent_id"] == s["qualified_id"] and u["qualified_id"] in sec_ids for u in units):
            continue
        ls = unit_lines(s, lines, anchors_by_unit, region_lines)
        for e in extract_column_pairs(ls):
            out.append({**e, "category": s["title"], "source": "table", "source_clause": s["qualified_id"]})
    for d in definitions:
        if d.get("abbreviation"):
            out.append({"surface_form": d["abbreviation"], "expansion": d["quoted_term"],
                        "category": "Defined term", "source": "definition", "source_clause": d["source_clause"]})
    return out


def dedupe_abbreviations(rows, doc_id):
    """One node per surface form; the first source (table > definition >
    inline) wins, the others are counted."""
    rank = {"table": 0, "definition": 1, "inline": 2}
    rows = sorted(rows, key=lambda r: rank.get(r["source"], 3))
    by_sf = {}
    for r in rows:
        key = r["surface_form"]
        if key in by_sf:
            by_sf[key]["occurrences"] += 1
            continue
        by_sf[key] = {**r, "id": f"{doc_id}.ABBR:{key}", "occurrences": 1}
    return list(by_sf.values())


def run(ctx):
    units = read_jsonl(ctx.path("units.jsonl"))
    lines = read_jsonl(ctx.path("lines.jsonl"))
    regions = read_jsonl(ctx.path("regions.jsonl"))
    anchors = read_jsonl(ctx.path("anchors.jsonl"))
    cfg = ctx.profile.get("terms") or {}
    definitions, imports = extract_definitions(units, cfg, ctx.doc_id)
    abbr = extract_abbreviations(units, lines, anchors, regions, cfg, definitions)
    abbr += inline_abbreviations(units, ctx.doc_id)
    abbr = dedupe_abbreviations(abbr, ctx.doc_id)
    write_jsonl(ctx.path("definitions.jsonl"), definitions)
    write_jsonl(ctx.path("abbreviations.jsonl"), abbr)
    by_src = collections.Counter(a["source"] for a in abbr)
    ctx.record("phase3_terms", definitions=len(definitions), abbreviations=len(abbr),
               abbreviations_by_source=dict(by_src), definition_imports=imports,
               defined_by_reference=sum(d["defined_by_reference"] for d in definitions))
    print(f"[{ctx.doc_id}] phase3: {len(definitions)} definitions, {len(abbr)} abbreviations "
          f"({', '.join(f'{k} {v}' for k, v in by_src.items())})", file=sys.stderr)
    return definitions, abbr
