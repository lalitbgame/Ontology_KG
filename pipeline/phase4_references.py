"""Phase 4 - internal cross-references (plan.md §9).

units + tables + figures + equations + external_mask -> references.jsonl.

Targets are found by LOOKUP in indexes built from the parsed document
(annex label -> unit, (annex, appendix number) -> unit, container +
paragraph number -> clause, article number -> Article ...), never by
assembling a Reg-154-shaped id string - so the same code serves UNECE
regulations, GTRs and EU acts.

Scope resolution order (plan §9 step 5): explicit qualifier ("of Annex IV",
"of Appendix 2 to Annex B8", "of Article 5") -> external (masked by Phase
4a, never resolved here) -> self ("of this Regulation" / "of this GTR" ->
the main text) -> the referencing unit's own container.

Never guess: a reference whose target doesn't exist is written as
{status: unresolved, raw_text} for review.
"""
import collections
import re
import sys

from .common import read_jsonl, roman_to_int, write_jsonl

ANNEX_ID = r"(?:[A-Z]?\d+[a-z]?|[IVXLC]+)\b"
PARA_ID = r"\d+(?:\.\d+)*\.?"
SEP = r"(?:\s*,\s*|\s+and\s+|\s+or\s+|,\s*and\s+|,\s*or\s+)"

PARAGRAPH_RE = re.compile(rf"\b[Pp]aragraphs?\s+(?P<ids>{PARA_ID}(?:(?:{SEP}|\s+to\s+){PARA_ID})*)")
ARTICLE_RE = re.compile(
    rf"\bArticles?\s+(?P<ids>\d+[a-z]?(?:\(\d+\))*(?:,?\s*points?\s+\(?\w{{1,4}}\)?)?"
    rf"(?:{SEP}\d+[a-z]?(?:\(\d+\))*(?:,?\s*points?\s+\(?\w{{1,4}}\)?)?)*)")
ANNEX_RE = re.compile(rf"\bAnnex(?:es)?\s+(?P<ids>{ANNEX_ID}(?:{SEP}{ANNEX_ID})*)")
APPENDIX_RE = re.compile(rf"\bAppendix\s+(?P<num>\d+)(?:\s+(?:to|of)\s+(?:this\s+)?Annex\s+(?P<annex>{ANNEX_ID}))?")
TABLE_RE = re.compile(r"\bTables?\s+(?P<ids>[A-Z]?\d+[A-Za-z]?(?:[/.\-]\d+[A-Za-z]?)*(?:(?:\s*,\s*|\s+and\s+)[A-Z]?\d+[A-Za-z]?(?:[/.\-]\d+[A-Za-z]?)*)*)")
FIGURE_RE = re.compile(r"\bFigures?\s+(?P<ids>[A-Z]?[IVX\d]+[A-Za-z]?(?:[/.\-][A-Za-z]?\d+[a-z]?)*)")
RECITAL_RE = re.compile(r"\b[Rr]ecitals?\s+\(?(?P<num>\d+)\)?")
CHAPTER_RE = re.compile(r"\bChapter\s+(?P<num>[IVXLC]+)\b")
EQUATION_IN_RE = re.compile(r"\b(?:equations?|formulae?|formulas?)\s+(?:set out |laid down |given )?in\s+[Pp]aragraph\s+(?P<num>\d+(?:\.\d+)*)\.?")
EQUATION_HERE_RE = re.compile(r"\b(?:the\s+)?(?:following\s+(?:equation|formula)s?|(?:equation|formula)s?\s+(?:below|above))\b")
EQUATION_LABEL_RE = re.compile(r"\b(?:[Ee]quation|[Ff]ormula)\s+\((?P<num>\d{1,3}[a-z]?)\)")

QUALIFIER_RE = re.compile(
    rf"^\s*,?\s*(?:(?:of|to|in)\s+(?:the\s+)?)(?:(?P<this>this\s+(?:Regulation|GTR|Global Technical Regulation|Directive|Decision|Annex|Appendix|Article))"
    rf"|Appendix\s+(?P<app>\d+)(?:\s+(?:to|of)\s+(?:this\s+)?Annex\s+(?P<app_annex>{ANNEX_ID}))?"
    rf"|Annex\s+(?P<annex>{ANNEX_ID})|Article\s+(?P<article>\d+[a-z]?))")
PH_RE = re.compile(r"\[(?:TABLE|FIGURE|EQ|FORM):[^\]]+\]")


def split(ids):
    return [i.strip().rstrip(".") for i in re.split(r"\s*,\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+", ids) if i.strip()]


def expand_paragraph_ids(ids):
    """'32. to 37.' -> 32..37; '9.1 and 9.4' -> [9.1, 9.4]."""
    out = []
    parts = re.split(r"\s+to\s+", ids)
    if len(parts) == 2:
        a, b = (split(p)[-1] if i == 0 else split(p)[0] for i, p in enumerate(parts))
        pa, pb = a.split("."), b.split(".")
        if len(pa) == len(pb) and pa[:-1] == pb[:-1] and pa[-1].isdigit() and pb[-1].isdigit() \
                and 0 < int(pb[-1]) - int(pa[-1]) < 40:
            out = split(parts[0])[:-1] + [".".join(pa[:-1] + [str(i)]) for i in range(int(pa[-1]), int(pb[-1]) + 1)] \
                + split(parts[1])[1:]
            return out, True
    return split(ids), False


class Index:
    def __init__(self, doc_id, units, tables, figures, equations, profile):
        self.doc_id = doc_id
        self.units = {u["qualified_id"]: u for u in units}
        self.annex = {}
        self.appendix = {}
        self.articles = {}
        self.recitals = {}
        self.chapters = {}
        for u in units:
            t, lab = u["unit_type"], (u.get("local_label") or "")
            if t == "Annex" and lab:
                self.annex[self.norm_annex(lab)] = u["qualified_id"]
            elif t == "Appendix" and lab:
                self.appendix[(self.annex_of(u), lab)] = u["qualified_id"]
            elif t == "Article":
                self.articles[lab] = u["qualified_id"]
            elif t == "Recital":
                self.recitals[lab] = u["qualified_id"]
            elif t == "Chapter":
                self.chapters[lab] = u["qualified_id"]
        # the "main text" a self reference ("of this Regulation") points into
        self.main = next((f"{doc_id}.{c}" for c in ("BODY",) if f"{doc_id}.{c}" in self.units), None)
        self.tables = collections.defaultdict(list)     # caption number -> [table]
        for t in tables:
            if t.get("caption_id"):
                self.tables[re.sub(r"^Table\s+", "", t["caption_id"])].append(t)
        self.figures = collections.defaultdict(list)
        for f in figures:
            if f.get("caption_id"):
                self.figures[re.sub(r"^Figure\s+", "", f["caption_id"])].append(f)
        self.eq_by_unit = collections.defaultdict(list)
        self.eq_by_label = collections.defaultdict(list)
        for e in equations:
            self.eq_by_unit[e["unit_id"]].append(e["id"])
            if e.get("label"):
                self.eq_by_label[e["label"]].append(e)

    @staticmethod
    def norm_annex(lab):
        return lab.strip().rstrip(".")

    def annex_of(self, u):
        """Annex label an appendix belongs to: its Annex parent, or (Reg 154
        'ANNEX-B6.APP1' root ids) the annex named in its id."""
        p = self.units.get(u.get("parent_id") or "")
        if p and p["unit_type"] == "Annex":
            return self.norm_annex(p.get("local_label") or "")
        m = re.search(r"\.ANNEX-([^.]+)\.APP", "." + u["qualified_id"][len(self.doc_id) + 1:])
        return m.group(1) if m else None

    def container(self, u):
        """Nearest non-clause unit whose id prefixes this one's clause path:
        a decimal clause's id is <container>.<number>."""
        if u.get("level") == "decimal" and u.get("local_number"):
            return u["qualified_id"][: -len(u["local_number"]) - 1]
        if u["unit_type"] in ("ArticleParagraph", "Point"):
            cur = u
            while cur and cur["unit_type"] != "Article":
                cur = self.units.get(cur.get("parent_id") or "")
            return cur["qualified_id"] if cur else u["qualified_id"]
        return u["qualified_id"]

    def enclosing(self, u, unit_type):
        cur = u
        while cur is not None:
            if cur["unit_type"] == unit_type:
                return cur
            cur = self.units.get(cur.get("parent_id") or "")
        return None

    def current_annex_label(self, u):
        a = self.enclosing(u, "Annex")
        if a:
            return self.norm_annex(a.get("local_label") or "")
        app = self.enclosing(u, "Appendix")
        return self.annex_of(app) if app else None

    def appendix_target(self, u, num, annex=None):
        if annex:
            return self.appendix.get((self.norm_annex(annex), num))
        cur = self.current_annex_label(u)
        if cur and (cur, num) in self.appendix:
            return self.appendix[(cur, num)]
        return self.appendix.get((None, num))


def resolve_scope(idx, u, tail):
    """-> (container id or None, qualifier text, kind)"""
    m = QUALIFIER_RE.match(tail)
    if not m:
        return idx.container(u), None, "default"
    if m.group("this"):
        w = m.group("this").split()[-1].lower()
        if w == "annex":
            a = idx.enclosing(u, "Annex")
            return (a["qualified_id"] if a else idx.container(u)), m.group(0), "this_annex"
        if w == "appendix":
            a = idx.enclosing(u, "Appendix")
            return (a["qualified_id"] if a else idx.container(u)), m.group(0), "this_appendix"
        if w == "article":
            a = idx.enclosing(u, "Article")
            return (a["qualified_id"] if a else idx.container(u)), m.group(0), "this_article"
        return idx.main or idx.container(u), m.group(0), "self"
    if m.group("app"):
        return idx.appendix_target(u, m.group("app"), m.group("app_annex")), m.group(0), "appendix"
    if m.group("annex"):
        return idx.annex.get(idx.norm_annex(m.group("annex"))), m.group(0), "annex"
    if m.group("article"):
        return idx.articles.get(m.group("article")), m.group(0), "article"
    return idx.container(u), None, "default"


def masked(spans, s, e):
    return any(a < e and s < b and kind != "self" for a, b, kind in spans)


def self_masked(spans, s, e):
    return any(a <= s < b or a < e <= b for a, b, kind in spans if kind == "self")


def extract(idx, units, masks):
    refs = []

    def add(u, kind, to, raw, qual=None, qkind=None, level=None):
        refs.append({"from": u["qualified_id"], "to": to, "kind": kind,
                     "status": "resolved" if to else "unresolved", "raw_text": raw,
                     "qualifier": qual, "scope": qkind, **({"resolved_level": level} if level else {})})

    for u in units:
        raw_text = u.get("body_text") or ""
        if not raw_text:
            continue
        text = PH_RE.sub(lambda m: " " * len(m.group(0)), raw_text)
        spans = masks.get(u["qualified_id"], [])
        taken = []

        def free(s, e):
            if masked(spans, s, e) or any(a < e and s < b for a, b in taken):
                return False
            taken.append((s, e))
            return True

        def tail_after(e):
            t = text[e:e + 90]
            # a self citation ("of UN Regulation No. 154") reads as "of this Regulation"
            for a, b, kind in spans:
                if kind == "self" and e <= a <= e + 12:
                    t = text[e:a] + "this Regulation" + text[b:b + 40]
            return t

        # equations referenced by the paragraph that holds them
        for m in EQUATION_IN_RE.finditer(text):
            if not free(m.start(), m.end()):
                continue
            container, qual, qkind = resolve_scope(idx, u, tail_after(m.end()))
            target = f"{container}.{m.group('num')}" if container else None
            eqs = idx.eq_by_unit.get(target, []) if target in idx.units else []
            for eid in eqs or [None]:
                add(u, "equation", eid, m.group(0), qual, qkind)
        for m in EQUATION_LABEL_RE.finditer(text):
            if free(m.start(), m.end()):
                cands = idx.eq_by_label.get(m.group("num"), [])
                same = [e for e in cands if e["unit_id"].startswith(idx.container(u))]
                add(u, "equation", (same or cands or [{}])[0].get("id") if len(same or cands) == 1 else None, m.group(0))
        for m in EQUATION_HERE_RE.finditer(text):
            if free(m.start(), m.end()):
                eqs = idx.eq_by_unit.get(u["qualified_id"], [])
                if eqs:
                    add(u, "equation", eqs[0] if "below" in m.group(0) or "following" in m.group(0) else eqs[-1], m.group(0))

        for m in PARAGRAPH_RE.finditer(text):
            if not free(m.start(), m.end()):
                continue
            container, qual, qkind = resolve_scope(idx, u, tail_after(m.end()))
            ids, is_range = expand_paragraph_ids(m.group("ids"))
            for pid in ids:
                pid = pid.rstrip(".")
                target = f"{container}.{pid}" if container else None
                ok = target if target in idx.units else None
                if is_range and not ok:
                    continue
                add(u, "paragraph", ok, f"paragraph {pid}" if len(ids) > 1 else m.group(0), qual, qkind)

        for m in ARTICLE_RE.finditer(text):
            if not free(m.start(), m.end()):
                continue
            for item in re.split(rf"{SEP}(?=\d)", m.group("ids")):
                am = re.match(r"(\d+[a-z]?)((?:\(\d+\))*)(?:,?\s*points?\s+\(?(\w{1,4})\)?)?", item.strip())
                if not am:
                    continue
                art = idx.articles.get(am.group(1))
                target, level = art, "article"
                if art:
                    for p in re.findall(r"\((\d+)\)", am.group(2) or ""):
                        if f"{target}.{p}" in idx.units:
                            target, level = f"{target}.{p}", "paragraph"
                    if am.group(3):
                        pt = f"{target}.PT-{am.group(3)}"
                        if pt in idx.units:
                            target, level = pt, "point"
                        else:
                            level += "+inline_point"
                add(u, "article", target, f"Article {item.strip()}", None, None, level if art else None)

        for m in APPENDIX_RE.finditer(text):
            if free(m.start(), m.end()):
                add(u, "appendix", idx.appendix_target(u, m.group("num"), m.group("annex")), m.group(0))

        for m in ANNEX_RE.finditer(text):
            if not free(m.start(), m.end()):
                continue
            for a in split(m.group("ids")):
                add(u, "annex", idx.annex.get(idx.norm_annex(a)), f"Annex {a}")

        for m in TABLE_RE.finditer(text):
            if not free(m.start(), m.end()):
                continue
            qual = QUALIFIER_RE.match(text[m.end():m.end() + 60])
            annex_unit = idx.annex.get(idx.norm_annex(qual.group("annex"))) if qual and qual.group("annex") else None
            for tid in split(m.group("ids")):
                cands = idx.tables.get(tid, [])
                div = annex_unit or idx.container(u)
                here = [t for t in cands if t["id"].startswith(div + ".") or t["defining_unit"].startswith(div)]
                if not here and not annex_unit:
                    a = idx.enclosing(u, "Annex")
                    here = [t for t in cands if a and t["id"].startswith(a["qualified_id"] + ".")]
                pick = here if here else (cands if len(cands) == 1 and not annex_unit else [])
                add(u, "table", pick[0]["id"] if len(pick) >= 1 else None, f"Table {tid}",
                    qual.group(0) if qual else None)

        for m in FIGURE_RE.finditer(text):
            if not free(m.start(), m.end()):
                continue
            cands = idx.figures.get(m.group("ids"), [])
            a = idx.enclosing(u, "Annex")
            here = [f for f in cands if a and f["id"].startswith(a["qualified_id"] + ".")]
            pick = here or (cands if len(cands) == 1 else [])
            add(u, "figure", pick[0]["id"] if pick else None, m.group(0))

        for m in RECITAL_RE.finditer(text):
            if free(m.start(), m.end()):
                add(u, "recital", idx.recitals.get(m.group("num")), m.group(0))
        for m in CHAPTER_RE.finditer(text):
            if free(m.start(), m.end()):
                add(u, "chapter", idx.chapters.get(m.group("num")), m.group(0))
    return refs


def run(ctx):
    units = read_jsonl(ctx.path("units.jsonl"))
    tables = read_jsonl(ctx.path("tables.jsonl"))
    figures = read_jsonl(ctx.path("figures.jsonl"))
    equations = read_jsonl(ctx.path("equations.jsonl"))
    masks = {m["unit_id"]: [(a, b, k) for a, b, k in m["spans"]] for m in read_jsonl(ctx.path("external_mask.jsonl"))}
    idx = Index(ctx.doc_id, units, tables, figures, equations, ctx.profile)
    refs = extract(idx, units, masks)
    write_jsonl(ctx.path("references.jsonl"), refs)
    by_kind = collections.defaultdict(lambda: [0, 0])
    for r in refs:
        by_kind[r["kind"]][1] += 1
        by_kind[r["kind"]][0] += r["status"] == "resolved"
    resolved = sum(r["status"] == "resolved" for r in refs)
    ctx.record("phase4_references", references=len(refs), resolved=resolved,
               rate=round(resolved / len(refs), 3) if refs else None,
               by_kind={k: {"resolved": a, "total": b, "rate": round(a / b, 3)} for k, (a, b) in by_kind.items()},
               masked_external_spans=sum(len(v) for v in masks.values()))
    print(f"[{ctx.doc_id}] phase4: {len(refs)} references, {resolved} resolved "
          f"({resolved / len(refs):.0%})" if refs else f"[{ctx.doc_id}] phase4: no references", file=sys.stderr)
    for k, (a, b) in sorted(by_kind.items()):
        print(f"    {k:10} {a}/{b} ({a / b:.0%})", file=sys.stderr)
    return refs
