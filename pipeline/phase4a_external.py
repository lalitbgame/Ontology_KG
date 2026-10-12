"""Phase 4a - external documents and the provisions cited in them
(plan.md §9a).

units.jsonl + footnotes.jsonl -> external_docs.jsonl (ExternalDocument
nodes), external_provisions.jsonl (ExternalProvision nodes), citations.jsonl
(CITES / AMENDS / REPEALS / IMPLEMENTS / LEGAL_BASIS edges),
external_mask.jsonl (text spans Phase 4 must not resolve internally) and
external_citations.csv (review / acquisition list).

Every kind of external document is recorded (regulations, directives,
decisions, GTRs, standards, UNECE working documents, agreements, treaties).
A document that is also in Document/ still gets its own ExternalDocument
node here (`in_corpus` is informational only): graphs are never connected.
Citations of the document itself (its `self_ids`) are not external.
"""
import collections
import csv
import re
import sys

from .common import read_jsonl, write_jsonl
from .profile import Registry

PH = re.compile(r"\[(?:TABLE|FIGURE|EQ|FORM):[^\]]+\]")
FN_MARK = r"(?:\s*\(\d{1,3}\))?"

# --- grammar ---------------------------------------------------------------
# Order matters: earlier patterns mask their span so later ones can't
# re-match inside it (GTR before UN Regulation: "Global Technical
# Regulation No. 22" must not also yield "Regulation No. 22").
GRAMMAR = [
    ("un_gtr", re.compile(
        r"\b(?:UN\s+|United\s+Nations\s+)?(?:Global\s+Technical\s+Regulation|GTR)\s*No\.?\s*(?P<num>\d{1,3})\b"
        r"|\bUN\s+GTR\s*(?P<num2>\d{1,3})\b|\bGTR(?P<num3>\d{1,3})\b")),
    ("eu_act", re.compile(
        r"\b(?P<prefix>(?:Commission\s+|Council\s+)?(?:Implementing\s+|Delegated\s+)?)"
        r"(?P<type>Regulation|Directive|Decision)s?\s+\((?P<org>EU|EC|EEC|Euratom)\)\s*(?:No\.?\s*)?"
        r"(?P<a>\d{1,4})/(?P<b>\d{1,4})(?:/(?P<suffix>EC|EEC|EU))?" + FN_MARK)),
    ("eu_act_old", re.compile(
        r"\b(?P<prefix>(?:Commission\s+|Council\s+)?)(?P<type>Directive|Decision)s?\s+"
        r"(?P<a>\d{2,4})/(?P<b>\d{1,4})/(?P<suffix>EC|EEC|EU)\b" + FN_MARK)),
    ("un_regulation", re.compile(
        r"\b(?:UN\s+)?Regulations?\s+No\.?\s*(?P<num>\d{1,3})\b(?!\s*/)"
        r"(?:\s+of\s+the\s+Economic\s+Commission\s+for\s+Europe(?:\s+of\s+the\s+United\s+Nations)?(?:\s*\(UN/ECE\))?)?"
        r"(?:\s*\(?(?P<series>\d{2})\s+series\s+of\s+amendments\)?)?" + FN_MARK)),
    ("treaty", re.compile(r"\bTreaty\s+on\s+the\s+Functioning\s+of\s+the\s+European\s+Union\b|\bTFEU\b")),
    ("unece_agreement", re.compile(r"\b(?P<year>1958|1998)\s+Agreement\b")),
    ("unece_document", re.compile(r"\b(?:ECE/TRANS|ECE/TRADE|TRANS/WP\.?29)/[\w.\-/]*[\w]")),
    ("standard", re.compile(
        r"\b(?P<org>EN[\s-]ISO|ISO/IEC|ISO/TS|ISO|IEC|SAE|ASTM|DIN|JIS|CEN|CISPR)\s?"
        r"(?P<num>[A-Z]{0,2}\d{2,6}(?:-\d+)*)(?::(?P<year>\d{4}))?\b")),
]
LIST_CONT = {
    "eu_act": re.compile(r"^(?P<sep>\s*(?:,|and|or|,\s*and)\s+)\((?P<org>EU|EC|EEC)\)\s*(?:No\.?\s*)?(?P<a>\d{1,4})/(?P<b>\d{1,4})" + FN_MARK),
    "un_regulation": re.compile(r"^(?P<sep>\s*(?:,|and|or|,\s*and)\s+)(?:No\.?\s*)(?P<num>\d{1,3})\b(?!\s*/)" + FN_MARK),
}

LOC_WORD = (r"(?:Articles?|[Pp]aragraphs?|[Pp]oints?|[Ss]ubparagraphs?|Annex(?:es)?|ANNEX|Appendix|Appendices|"
            r"Tables?|Figures?|Sections?|Chapters?|Parts?|[Ss]teps?(?:\s+no\.?)?|Item)")
LOC_ID = r"(?:\(?[A-Za-z0-9]+(?:[./\-][A-Za-z0-9]+)*\.?\)?(?:\(\w{1,4}\))*)"
CONNECTOR = r"(?:of|to|in|and|or|the|this|that|thereof|thereto|under|from|with|as|by|for)\b"
LOC_ITEM = rf"{LOC_WORD}\s+(?!{CONNECTOR}){LOC_ID}(?:(?:\s*,\s*|\s+and\s+|\s+or\s+|\s+to\s+)(?!{LOC_WORD}|{CONNECTOR}){LOC_ID})*"
ORDINAL = r"(?:,\s*(?:first|second|third|fourth|fifth|last)\s+sub-?paragraph)?"
LEFT_CHAIN_RE = re.compile(
    rf"(?P<chain>(?:{LOC_ITEM}{ORDINAL}(?:,?\s*(?:and\s+)?{LOC_ITEM}{ORDINAL})*\s*,?\s*(?:of|to|in|under|from)\s+(?:the\s+)?)+)$")
RIGHT_CHAIN_RE = re.compile(rf"^(?P<chain>(?:\s*,?\s*{LOC_ITEM}){{1,4}})")
BACKREF_RE = re.compile(r"\b(thereof|thereto|of that (?:Regulation|Directive|Decision)|of the said (?:Regulation|Directive))\b")
BACKREF_CHAIN_RE = None  # built after ART_CHAIN (needs the article grammar)
SELF_WORDS_RE = re.compile(r"\b(?:of\s+)?this\s+(?:Regulation|Directive|Decision|GTR|Global Technical Regulation)\b")
ITEM_RE = re.compile(rf"(?P<word>{LOC_WORD})\s+(?!{CONNECTOR})(?P<ids>{LOC_ID}(?:(?:\s*,\s*|\s+and\s+|\s+or\s+|\s+to\s+)(?!{LOC_WORD}|{CONNECTOR}){LOC_ID})*)")
# "Articles 14(3), point (i), and 14(4), points (a), (q) and (v)" / "Article 3, point 49"
ART_ITEM = (r"(?P<art>\d+[a-z]?)(?P<para>(?:\(\d+\))*)(?:,?\s*points?\s+(?P<pts>\(?\w{1,4}\)?(?:(?:\s*,\s*|\s+and\s+|,\s*and\s+)\(\w{1,4}\))*))?"
            r"(?:,\s*(?P<ord>first|second|third|fourth|fifth|last)\s+sub-?paragraph)?")
_ART_ITEM_NC = re.sub(r"\(\?P<\w+>", "(?:", ART_ITEM)
ART_CHAIN_RE = re.compile(rf"Articles?\s+{_ART_ITEM_NC}(?:(?:\s*,\s*|\s+and\s+|,\s*and\s+){_ART_ITEM_NC})*")
ART_ONE_RE = re.compile(ART_ITEM)
_ART_CHAIN_NC = rf"Articles?\s+{_ART_ITEM_NC}(?:(?:\s*,\s*|\s+and\s+|,\s*and\s+){_ART_ITEM_NC})*"
BACKREF_CHAIN_RE = re.compile(
    rf"(?P<chain>(?:{_ART_CHAIN_NC}|{LOC_ITEM}{ORDINAL})(?:\s*,?\s*(?:and\s+)?(?:{_ART_CHAIN_NC}|{LOC_ITEM}{ORDINAL}))*"
    rf"(?:\s*,?\s*(?:of|to|in)\s+{LOC_ITEM})*)\s*,?\s*$")
SENTENCE_END_RE = re.compile(r"(?<![0-9A-Z][.)])(?<!No)(?<!\bp)[.;]\s+(?=[A-Z(‘“\"])")

ROLE_CUES = [
    ("amends", re.compile(r"\bamending\b|\bis amended\b|\bare amended\b", re.I)),
    ("repeals", re.compile(r"\brepealing\b|\bis repealed\b|\bare repealed\b", re.I)),
    ("implements", re.compile(r"\bfor the application of\b|\bimplementing\b|\bsupplementing\b", re.I)),
    ("legal_basis", re.compile(r"\bHaving regard to\b", re.I)),
    ("definition_source", re.compile(r"\bas defined (?:in|by)\b|\bdefinitions?\b[^.]{0,80}\bapply\b|\bwithin the meaning of\b", re.I)),
    ("requirement_source", re.compile(
        r"\bshall (?:apply|comply|be (?:carried out|determined|measured|tested|performed))\b|\bin accordance with\b"
        r"|\baccording to\b|\bdetermined (?:according|in accordance)\b|\bas specified in\b|\bas set out in\b"
        r"|\bas laid down in\b|\bshall reflect\b|\bshall meet\b|\bthe requirements? (?:of|in|set out in)\b", re.I)),
    ("replaces", re.compile(r"\breplaces?\b|\bin place of\b", re.I)),
]
DOC_LEVEL_ROLES = {"amends", "repeals", "implements", "legal_basis"}
ROLE_EDGE = {"amends": "AMENDS", "repeals": "REPEALS", "implements": "IMPLEMENTS", "legal_basis": "LEGAL_BASIS"}
KIND_ISSUER = {"un_regulation": "UNECE WP.29 (1958 Agreement)", "un_gtr": "UNECE WP.29 (1998 Agreement)",
               "treaty": "European Union", "unece_agreement": "United Nations / UNECE",
               "unece_document": "UNECE"}


def year_of(a, b):
    a, b = int(a), int(b)
    if 1950 <= a <= 2100:
        return a, b
    if 1950 <= b <= 2100:
        return b, a
    if a < 100 and len(str(a)) == 2:
        return (1900 + a if a > 50 else 2000 + a), b
    return None, None


def canonical(kind, m):
    """-> (ext_id, doc_kind, number, year, subtype, version) or None.
    `m` is a regex match, or a dict of its groups plus '_text'."""
    g = m if isinstance(m, dict) else {**m.groupdict(), "_text": m.group(0)}
    if kind == "un_gtr":
        num = g.get("num") or g.get("num2") or g.get("num3")
        return f"EXT:UNGTR-{int(num)}", "un_gtr", num, None, None, None
    if kind == "un_regulation":
        return f"EXT:UNR-{int(g['num'])}", "un_regulation", g["num"], None, None, g.get("series")
    if kind in ("eu_act", "eu_act_old"):
        org = {"EEC": "EC", "Euratom": "EURATOM"}.get(g.get("org") or "", g.get("org") or "")
        suffix = g.get("suffix")
        if not org:
            org = "EC" if suffix in ("EC", "EEC") else "EU"
        typ = {"Regulation": "REG", "Directive": "DIR", "Decision": "DEC"}[g["type"]]
        prefix = (g.get("prefix") or "").lower()
        subtype = "implementing" if "implementing" in prefix else "delegated" if "delegated" in prefix else None
        a, b = g["a"], g["b"]
        if kind == "eu_act_old" and len(a) == 2:
            a = str(1900 + int(a) if int(a) > 50 else 2000 + int(a))
        year, _ = year_of(a, b)
        doc_kind = {"REG": "eu_regulation", "DIR": "eu_directive", "DEC": "eu_decision"}[typ]
        if org == "EC" and typ == "REG":
            doc_kind = "ec_regulation"
        return f"EXT:{org}.{typ}.{a}-{b}", doc_kind, f"{a}/{b}", year, subtype, None
    if kind == "treaty":
        return "EXT:TFEU", "treaty", None, None, None, None
    if kind == "unece_agreement":
        return f"EXT:UNECE.AGREEMENT-{g['year']}", "unece_agreement", g["year"], int(g["year"]), None, None
    if kind == "unece_document":
        sym = g["_text"].rstrip(".")
        return "EXT:" + re.sub(r"[/]+", ".", sym.upper()).replace("WP.29", "WP29"), "unece_document", sym, None, None, None
    if kind == "standard":
        org = re.sub(r"[\s]+", "-", g["org"].upper())
        return f"EXT:{org}.{g['num']}", "standard", f"{g['org']} {g['num']}", None, None, g.get("year")
    return None


# --- pinpoints --------------------------------------------------------------

def split_ids(ids):
    return [x.strip() for x in re.split(r"\s*,\s*|\s+and\s+|\s+or\s+", ids) if x.strip()]


def expand_range(ids_text):
    """'32. to 37.' -> ['32', ..., '37'] when both ends are plain integers."""
    m = re.fullmatch(r"(\d+)\.?\s+to\s+(\d+)\.?", ids_text.strip())
    if m and 0 < int(m.group(2)) - int(m.group(1)) < 50:
        return [str(i) for i in range(int(m.group(1)), int(m.group(2)) + 1)]
    return None


def clean_id(x):
    return x.strip().rstrip(".").strip()


def parse_chain(chain):
    """Locator chain text -> list of locator paths (outermost first), e.g.
    'paragraph 3.1.2. of Annex 5 of' -> [[('annex','5'), ('paragraph','3.1.2')]]
    'Articles 7(1) and 10(1) of'    -> [[('article','7'),('paragraph','1')], [...10, 1]]."""
    current = []
    art_paths = []
    am = ART_CHAIN_RE.search(chain)
    if am:
        body = am.group(0)
        body = re.sub(r"^Articles?\s+", "", body)
        for it in ART_ONE_RE.finditer(body):
            if not it.group("art"):
                continue
            base = [("article", it.group("art"))] + [("paragraph", p) for p in re.findall(r"\((\d+)\)", it.group("para") or "")]
            if it.group("ord"):
                base.append(("subparagraph", it.group("ord")))
            pts = re.findall(r"\(?(\w{1,4})\)?", it.group("pts") or "")
            pts = [p for p in pts if p not in ("and",)]
            art_paths += [base + [("point", p)] for p in pts] if pts else [base]
        chain = chain[:am.start()] + " " + chain[am.end():]
    for m in ITEM_RE.finditer(chain):
        word = m.group("word").lower()
        kind = ("article" if word.startswith("article") else "paragraph" if word.startswith("paragraph")
                else "subparagraph" if word.startswith("subparagraph") else "point" if word.startswith("point")
                else "annex" if word.startswith("annex") else "appendix" if word.startswith("append")
                else "table" if word.startswith("table") else "figure" if word.startswith("figure")
                else "section" if word.startswith("section") else "chapter" if word.startswith("chapter")
                else "part" if word.startswith("part") else "step" if word.startswith("step") else "item")
        ids = expand_range(m.group("ids")) or [clean_id(x) for x in split_ids(m.group("ids"))]
        if kind == "step":
            ids = [i for i in ids if i.isdigit()]
            if not ids:
                continue
        current.append((kind, [i for i in ids if i]))
    if not current:
        return art_paths
    # A 'point' list attaches to the item just before it; containers
    # (annex/appendix/article) attach as parents of what precedes them.
    paths = []
    pending = []
    for kind, ids in current:
        if kind in ("point", "step", "subparagraph") and pending:
            pending = [p + [(kind, i)] for p in pending for i in ids] if len(pending) == 1 else \
                pending[:-1] + [pending[-1] + [(kind, i)] for i in ids]
            continue
        if kind in ("annex", "appendix", "chapter", "part", "section") and pending and \
                all(p[-1][0] not in ("annex",) for p in pending):
            pending = [[(kind, ids[0])] + p for p in pending]
            continue
        if kind == "table" and pending and pending[-1][0][0] == "annex":
            pending = [p + [(kind, i)] for p in pending for i in ids]
            continue
        paths.extend(pending)
        pending = []
        for i in ids:
            if kind == "article":
                am = re.fullmatch(r"(\d+[a-z]?)((?:\(\w{1,4}\))*)", i)
                if am:
                    path = [("article", am.group(1))]
                    for sub in re.findall(r"\((\w{1,4})\)", am.group(2)):
                        path.append(("paragraph" if sub.isdigit() else "point", sub))
                    pending.append(path)
                    continue
            pending.append([(kind, i.strip("()"))])
    paths.extend(pending)
    # containers that follow an article chain ("Article 4 of Annex II" is rare;
    # "Articles 7(1) and 10(1) of" has none) - article paths first
    return art_paths + paths


def provision_key(path):
    seg = {"article": "ART-{}", "annex": "ANNEX-{}", "appendix": "APP-{}", "table": "TABLE-{}",
           "figure": "FIGURE-{}", "point": "PT-{}", "step": "STEP-{}", "chapter": "CH-{}", "part": "PART-{}",
           "section": "SEC-{}", "subparagraph": "SUBPARA-{}", "item": "ITEM-{}", "paragraph": "{}"}
    return ".".join(seg[k].format(v) for k, v in path)


def label_of(path):
    names = {"article": "Article", "paragraph": "paragraph", "point": "point", "annex": "Annex",
             "appendix": "Appendix", "table": "Table", "figure": "Figure", "step": "Step", "chapter": "Chapter",
             "part": "Part", "section": "Section", "subparagraph": "subparagraph", "item": "Item"}
    return ", ".join(f"{names[k]} {v}" for k, v in path)


# --- footnotes ----------------------------------------------------------------

def footnote_meta(text):
    meta = {}
    oj = re.search(r"\(?(OJ\s+[LC]\s*[^()]*?p\.\s*\d+)", text) or \
        re.search(r"\(?(OJ\s+[LC]\s*[^()]*?\d{1,2}\.\d{1,2}\.\d{4})", text)
    if oj:
        meta["oj_ref"] = re.sub(r"\s+", " ", oj.group(1)).strip(" ,")
    eli = re.search(r"ELI:\s*(http[^\s)]*(?:\s+[\w./]+)*?/oj)", text)
    if eli:
        meta["eli"] = re.sub(r"\s+", "", eli.group(1))
    d = re.search(r"\bof\s+(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})", text)
    if d:
        meta["adoption_date"] = d.group(1)
    title = re.split(r"\s*\(OJ\b|\s*\[\d{4}/\d+\]", text)[0].strip(" .")
    un = re.search(r"[–—-]\s*(Uniform provisions[^\[(]+)", text)
    if un:
        meta["title"] = un.group(1).strip(" .")
    elif len(title) > 25:
        meta["title"] = title
    return meta


# --- driver -------------------------------------------------------------------

def sentence_bounds(text, pos):
    start = 0
    for m in SENTENCE_END_RE.finditer(text, 0, pos):
        start = m.end()
    m = SENTENCE_END_RE.search(text, pos)
    return start, (m.start() + 1 if m else len(text))


def blank_citations(text, a, b, found, own_start):
    """Window text with every OTHER citation blanked, so 'Commission
    Implementing Regulation ...' next door doesn't read as an
    'implementing' cue for this one."""
    w = list(text[a:b])
    for f in found:
        if f[0] == own_start:
            continue
        for i in range(max(f[0], a), min(f[1], b)):
            w[i - a] = " "
    return "".join(w)


def classify_role(window):
    for role, rx in ROLE_CUES:
        if rx.search(window):
            return role
    return "cites"


class Collector:
    def __init__(self, doc_id, self_ids, corpus_ids):
        self.doc_id = doc_id
        self.self_ids = self_ids
        self.corpus_ids = corpus_ids
        self.docs = {}
        self.provisions = {}
        self.citations = []
        self.masks = collections.defaultdict(list)
        self.self_hits = 0

    def add_doc(self, ext_id, doc_kind, number, year, subtype, surface, unit_id):
        d = self.docs.get(ext_id)
        if d is None:
            d = self.docs[ext_id] = {
                "id": ext_id, "doc_kind": doc_kind, "number": number, "year": year, "subtype": subtype,
                "issuer": KIND_ISSUER.get(doc_kind) or ("European Union" if doc_kind.startswith(("eu_", "ec_")) else
                                                         surface.split()[0] if doc_kind == "standard" else None),
                "title": None, "adoption_date": None, "oj_ref": None, "eli": None,
                "aliases": [], "mention_count": 0, "first_cited_in": unit_id,
                "in_corpus": ext_id in self.corpus_ids, "corpus_doc_id": self.corpus_ids.get(ext_id),
            }
        surface = re.sub(r"\s*\(\d{1,3}\)$", "", re.sub(r"\s+", " ", surface)).strip()
        surface = re.sub(r"^(?:,\s*)?(?:and|or)\s+", "", surface).strip(" ,")
        if surface not in d["aliases"]:
            d["aliases"].append(surface)
        d["mention_count"] += 1
        if subtype and not d["subtype"]:
            d["subtype"] = subtype
        return d

    def add_provision(self, ext_id, path, raw):
        key = provision_key(path)
        pid = f"{ext_id}#{key}"
        p = self.provisions.get(pid)
        if p is None:
            p = self.provisions[pid] = {"id": pid, "external_doc": ext_id, "locator": [list(x) for x in path],
                                        "label": label_of(path), "raw_text": raw, "mention_count": 0}
        p["mention_count"] += 1
        return pid

    def cite(self, from_id, ext_id, paths, raw, sentence, role, version, via, chain_raw):
        targets = [self.add_provision(ext_id, p, chain_raw) for p in paths] or [ext_id]
        for t in targets:
            self.citations.append({"from": from_id, "to": t, "external_doc": ext_id, "type": "CITES",
                                   "role": role, "raw_text": raw, "sentence": sentence[:400],
                                   "version": version, "via": via})


def scan_text(col, unit_id, text, self_words_re, via="direct"):
    record_mask = via == "direct"   # offsets are only meaningful for body_text
    """Find every external citation in `text` (one unit's body/title)."""
    taken = []           # spans already claimed by a citation
    found = []           # (start, end, ext_id)
    for kind, rx in GRAMMAR:
        for m in rx.finditer(text):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue
            canon = canonical(kind, m)
            if not canon:
                continue
            ext_id, doc_kind, number, year, subtype, version = canon
            items = [(m.start(), m.end(), ext_id, doc_kind, number, year, subtype, version, m.group(0))]
            # shared-head list: "Regulations (EC) No 715/2007 and (EC) No 595/2009"
            end = m.end()
            cont = LIST_CONT.get(kind)
            while cont is not None:
                cm = cont.match(text[end:])
                if not cm:
                    break
                g2 = {**m.groupdict(), **{k: v for k, v in cm.groupdict().items() if k != "sep"},
                      "suffix": None, "series": None, "_text": cm.group(0)}
                sub = canonical(kind, g2)
                if not sub:
                    break
                s0 = end + cm.start() + len(cm.group("sep"))
                items.append((s0, end + cm.end(), sub[0], sub[1], sub[2], sub[3], sub[4], sub[5], cm.group(0).strip(" ,")))
                end = end + cm.end()
            for it in items:
                taken.append((it[0], it[1]))
                found.append(it)
    found.sort()
    last_ext = None
    for (s, e, ext_id, doc_kind, number, year, subtype, version, surface) in found:
        if ext_id in col.self_ids:
            col.self_hits += 1
            if record_mask:
                col.masks[unit_id].append([s, e, "self"])
            continue
        d = col.add_doc(ext_id, doc_kind, number, year, subtype, surface, unit_id)
        ss, se = sentence_bounds(text, s)
        sentence = text[ss:se].strip()
        left = text[max(ss, s - 220):s]
        lm = LEFT_CHAIN_RE.search(left)
        if not lm and doc_kind == "treaty":
            # "Article 290 TFEU" - the Treaty is cited without "of"
            lm = re.search(rf"(?P<chain>(?:{_ART_CHAIN_NC}))\s*$", left)
        chain_raw, paths, cs = "", [], s
        if lm:
            chain_raw = lm.group("chain").strip()
            paths = parse_chain(chain_raw)
            cs = s - len(left) + lm.start()
        rm = RIGHT_CHAIN_RE.match(text[e:e + 120])
        ce = e
        if rm and not paths and doc_kind in ("un_gtr", "un_regulation", "standard", "eu_regulation", "ec_regulation"):
            chain_raw = rm.group("chain").strip(" ,")
            # right-hand chains read outer -> inner ("Annex 8, Table A8/11 Step no. 1")
            outer = parse_chain(chain_raw)
            if outer:
                flat = [x for p in outer for x in p]
                paths = [flat]
                ce = e + rm.end()
        role = classify_role(blank_citations(text, max(ss, s - 160), min(se, ce + 40), found, s))
        col.cite(unit_id, ext_id, paths, text[cs:ce].strip(), sentence, role, version, via, chain_raw)
        if record_mask:
            col.masks[unit_id].append([cs, ce, ext_id])
        last_ext = (ext_id, s)
    # back-references: "<locator> thereof / thereto / of that Regulation"
    for m in BACKREF_RE.finditer(text):
        before = text[max(0, m.start() - 200):m.start()]
        lm = BACKREF_CHAIN_RE.search(before)
        if not lm:
            continue
        ss, se = sentence_bounds(text, m.start())
        prior = [f for f in found if f[1] <= m.start() and f[2] not in col.self_ids and
                 (f[0] >= ss or (m.group(1).startswith("of that") and f[0] >= sentence_bounds(text, max(0, ss - 2))[0]))]
        if not prior:
            continue
        # "Having regard to Regulation X ..., amending Y and repealing Z,
        # and in particular Article 14 thereof": the governing act is the
        # first one cited after the last "Having regard to", not the last one
        hr = [h for h in re.finditer(r"Having regard to", text[ss:m.start()])]
        if hr:
            after = [f for f in prior if f[0] >= ss + hr[-1].start()]
            ext_id = (after or prior)[0][2]
        else:
            ext_id = prior[-1][2]
        chain_raw = lm.group("chain").strip(" ,")
        paths = parse_chain(chain_raw + " of")
        cs = m.start() - len(before) + lm.start()
        role = classify_role(text[ss:se])
        col.cite(unit_id, ext_id, paths, text[cs:m.end()], text[ss:se].strip(), role, None, "back_reference", chain_raw)
        col.docs[ext_id]["mention_count"] += 1
        if record_mask:
            col.masks[unit_id].append([cs, m.end(), ext_id])
    # "of this Regulation" etc. are self references: mask them for Phase 4's
    # scope logic only (it reads them itself), nothing to record here
    return found


def doc_level_roles(col, doc_id, units, family):
    """Title / preamble cues -> Document -> ExternalDocument edges."""
    root = next((u for u in units if u["parent_id"] is None), None)
    if root is None:
        return
    text = PH.sub(" ", root.get("body_text") or "")
    head = re.split(r"\(Text with EEA relevance\)|Having regard to|Whereas:|\bHAS ADOPTED\b|\bHAVE ADOPTED\b", text)[0]
    cue_at = []
    for role, rx in ROLE_CUES[:3]:
        for m in rx.finditer(head):
            cue_at.append((m.start(), role))
    cue_at.sort()
    seen = set()
    for c in col.citations:
        if c["from"] != root["qualified_id"]:
            continue
        pos = head.find(c["raw_text"][:30]) if c["raw_text"] else -1
        role = None
        if pos >= 0:
            prior = [r for p, r in cue_at if p < pos]
            role = prior[-1] if prior else None
        if not role and c["role"] == "legal_basis":
            role = "legal_basis"
        if role in DOC_LEVEL_ROLES and role != "legal_basis":
            c["role"] = role
        if role in DOC_LEVEL_ROLES and (c["external_doc"], role) not in seen:
            seen.add((c["external_doc"], role))
            col.citations.append({"from": doc_id, "to": c["external_doc"], "external_doc": c["external_doc"],
                                  "type": ROLE_EDGE[role], "role": role, "raw_text": c["raw_text"],
                                  "sentence": c["sentence"], "version": c.get("version"), "via": "title"})
    # legal basis sentences anywhere in the preamble ("Having regard to ...")
    for c in list(col.citations):
        if c["type"] == "CITES" and c["role"] == "legal_basis" and (c["external_doc"], "legal_basis") not in seen:
            seen.add((c["external_doc"], "legal_basis"))
            col.citations.append({"from": doc_id, "to": c["external_doc"], "external_doc": c["external_doc"],
                                  "type": "LEGAL_BASIS", "role": "legal_basis", "raw_text": c["raw_text"],
                                  "sentence": c["sentence"], "version": None, "via": "preamble"})


def run(ctx):
    units = read_jsonl(ctx.path("units.jsonl"))
    footnotes = read_jsonl(ctx.path("footnotes.jsonl"))
    registry = Registry()
    corpus_ids = {sid: e["doc_id"] for e in registry.entries for sid in (e.get("self_ids") or [])}
    col = Collector(ctx.doc_id, ctx.self_ids(), corpus_ids)
    self_words = re.compile("|".join(re.escape(w) for w in (ctx.profile.get("references") or {}).get("self_words", ["this Regulation"])) or "$^")

    for u in units:
        text = u.get("body_text") or ""
        scan_text(col, u["qualified_id"], text, self_words)
        if u.get("title"):
            scan_text(col, u["qualified_id"], u["title"], self_words, via="title")
    # table cells cite external procedures too (GTR 22 Annex 3: "GTR15
    # Annex 8, Table A8/11 Step no. 1"); attributed to the table's unit
    for t in read_jsonl(ctx.path("tables.jsonl")):
        if t.get("flow_text") or t.get("cell_text"):
            scan_text(col, t["defining_unit"], t.get("flow_text") or t["cell_text"].replace("\n", " ; "),
                      self_words, via="table")
    # footnotes: citations inside them, plus metadata for the cited act
    fn_by_marker = collections.defaultdict(list)
    for n in footnotes:
        fn_by_marker[n.get("marker")].append(n)
        found = scan_text(col, n["unit_id"], n["text"], self_words, via="footnote")
        if found and found[0][0] < 8 and found[0][2] in col.docs:
            meta = footnote_meta(n["text"])
            d = col.docs[found[0][2]]
            for k, v in meta.items():
                if v and not d.get(k):
                    d[k] = v
                    d.setdefault("metadata_source", {})[k] = n["id"]
    doc_level_roles(col, ctx.doc_id, units, ctx.family)

    # masks only refer to body_text offsets (title scans are short and not
    # resolved internally by Phase 4)
    masks = [{"unit_id": k, "spans": sorted(v)} for k, v in col.masks.items()]
    docs = sorted(col.docs.values(), key=lambda d: (d["doc_kind"], d["id"]))
    provisions = sorted(col.provisions.values(), key=lambda p: p["id"])
    write_jsonl(ctx.path("external_docs.jsonl"), docs)
    write_jsonl(ctx.path("external_provisions.jsonl"), provisions)
    write_jsonl(ctx.path("citations.jsonl"), col.citations)
    write_jsonl(ctx.path("external_mask.jsonl"), masks)

    rows = collections.defaultdict(lambda: {"roles": collections.Counter(), "units": set(), "n": 0})
    for c in col.citations:
        if c["type"] != "CITES":
            continue
        key = (c["external_doc"], c["to"] if c["to"] != c["external_doc"] else "")
        rows[key]["n"] += 1
        rows[key]["roles"][c["role"]] += 1
        rows[key]["units"].add(c["from"])
    with open(ctx.path("external_citations.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["external_doc", "doc_kind", "title", "provision", "mentions", "roles", "citing_units", "in_corpus"])
        for (ext, prov), r in sorted(rows.items()):
            d = col.docs[ext]
            w.writerow([ext, d["doc_kind"], d.get("title") or "", col.provisions[prov]["label"] if prov else "",
                        r["n"], "; ".join(f"{k}:{v}" for k, v in r["roles"].most_common()),
                        " ".join(sorted(r["units"]))[:2000], d["in_corpus"]])

    kinds = collections.Counter(d["doc_kind"] for d in docs)
    roles = collections.Counter(c["role"] for c in col.citations if c["type"] == "CITES")
    doc_edges = collections.Counter(c["type"] for c in col.citations if c["type"] != "CITES")
    ctx.record("phase4a_external", external_docs=len(docs), by_kind=dict(kinds), provisions=len(provisions),
               citations=sum(1 for c in col.citations if c["type"] == "CITES"), roles=dict(roles),
               document_edges=dict(doc_edges), self_citations_filtered=col.self_hits,
               back_references=sum(1 for c in col.citations if c["via"] == "back_reference"))
    print(f"[{ctx.doc_id}] phase4a: {len(docs)} external docs ({', '.join(f'{k} {v}' for k, v in kinds.most_common())}), "
          f"{len(provisions)} provisions, {sum(1 for c in col.citations if c['type'] == 'CITES')} citations, "
          f"{col.self_hits} self-citations filtered, doc edges {dict(doc_edges)}", file=sys.stderr)
    return docs
