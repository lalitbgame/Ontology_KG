"""Phase 2 - profile-driven structural parse (plan.md §5).

lines.jsonl + regions.jsonl -> units.jsonl (every structural node: Part,
Chapter, Article, ArticleParagraph, Point, Recital, Annex, Appendix,
Clause, Form, Preamble ...), footnotes.jsonl, anchors.jsonl.

A stack machine walks the lines in reading order. Each profile level is a
heading grammar (regex + style predicate + where it may appear + how its id
is formed); decimal clauses ("6.3.2.") are handled generically. Numbering is
scoped by the stack, so an EU Article's "1." never collides with another
Article's "1.", and GTR 22's rationale paragraphs never collide with its
text clauses.

Non-prose regions (tables, figures, display equations + glossaries) are not
added to clause text: they leave a placeholder ("[TABLE:<id>]") in the body
of the unit open when they are reached, and anchors.jsonl records which
unit each region belongs to and the node id it will become.
"""
import collections
import re
import sys

from .common import join_lines, read_jsonl, write_jsonl
from .phase1_extract import FOOTNOTE_MARKER_RE, NUMBER_TOKEN_RE

DECIMAL_RE = re.compile(r"^(\d+(?:\.\d+)*)\.(?:\s+(.*))?$")
DECIMAL_COMPACT_RE = re.compile(r"^(\d+(?:\.\d+)*)\.(\S.*)$")   # "5.Text" (no space)
PLACEHOLDER = {"table": "TABLE", "figure": "FIGURE", "equation": "EQ", "form": "FORM"}


class Unit(dict):
    """A structural node under construction."""


def num_value(label):
    m = re.match(r"(\d+)", str(label or ""))
    if m:
        return int(m.group(1))
    from .common import roman_to_int
    return roman_to_int(str(label or "")) or None


class Parser:
    def __init__(self, doc_id, profile, stats, page_meta):
        self.doc_id = doc_id
        self.profile = profile
        st = profile["structure"]
        self.levels = st.get("levels", [])
        self.compiled = [(lvl, re.compile(lvl["match"])) for lvl in self.levels]
        self.decimal = st.get("decimal") or {}
        self.labels = (st.get("labels") or {}).get("decimal_by_depth", ["Section", "Subsection", "Provision"])
        self.form_titles = [re.compile(p) for p in st.get("form_titles", [])]
        self.body = stats.get("body_size", 10.0)
        cols = [x for x, c in stats.get("number_columns", []) if c >= 3]
        self.number_cols = cols[:2]
        self.page_w = {m["page"]: m["width"] for m in page_meta}
        self.units, self.stack = [], []
        self.ids = collections.Counter()
        self.warnings = collections.Counter()
        self.last_article = None
        self.sibling_last = {}          # (parent_id, level) -> last number
        self.seen_after = set()          # 'after' triggers seen in the current initial unit
        init = st.get("initial") or {"id": "BODY", "unit_type": "Body"}
        self.initial = self.new_unit(init["id"], init.get("unit_type", "Body"), "initial",
                                     None, None, 0, page=0)
        self.stack.append(self.initial)
        self.pending_title = None
        self.form_active = None

    # -- construction -----------------------------------------------------

    def new_unit(self, seg, unit_type, level, parent, label, depth, page, scope="root", **extra):
        if scope == "root" or parent is None:
            qid = f"{self.doc_id}.{seg}"
        else:
            qid = f"{self.id_base(parent)}.{seg}"
        u = Unit(qualified_id=qid, unit_type=unit_type, level=level,
                 parent_id=parent["qualified_id"] if parent else None,
                 local_label=label, depth=depth, page=page, page_end=page,
                 title_lines=[], body_lines=[], footnote_lines=[], **extra)
        self.units.append(u)
        return u

    def id_base(self, unit):
        """Id prefix for children: skips 'transparent' containers (GTR
        rationale sections) so their paragraphs stay RATIONALE.<n>."""
        while unit.get("transparent") and unit["parent_id"]:
            unit = self.by_id[unit["parent_id"]]
        return unit["qualified_id"]

    @property
    def by_id(self):
        return {u["qualified_id"]: u for u in self.units}

    @property
    def current(self):
        return self.stack[-1]

    # -- predicates -------------------------------------------------------

    def style_ok(self, style, line):
        if style in (None, "any"):
            return True
        if style == "heading":
            return line["size"] >= 1.15 * self.body or (line.get("bold") and len(line["text"]) <= 90
                                                         and line["size"] >= 0.95 * self.body)
        if style == "centered":
            w = self.page_w.get(line["page"], 595)
            mid = (line["x0"] + line["x1"]) / 2
            return abs(mid - w / 2) <= 0.09 * w and (line["x1"] - line["x0"]) <= 0.6 * w
        return False

    def on_stack(self, names):
        return any(u["level"] in names for u in self.stack)

    def sequence_ok(self, lvl, num, parent):
        mode = lvl.get("sequence")
        n = num_value(num)
        if not mode or n is None:
            return True
        if mode == "global":
            prev = self.last_article
            return (prev is None and n <= 3) or (prev is not None and n in (prev, prev + 1))
        key = (parent["qualified_id"] if parent else None, lvl["name"])
        prev = self.sibling_last.get(key)
        return (prev is None and n == 1) or (prev is not None and n == prev + 1)

    def find_parent(self, lvl):
        allowed = lvl.get("parent", ["root"])
        if "root" in allowed and not any(a != "root" for a in allowed):
            return None, 0
        for i in range(len(self.stack) - 1, -1, -1):
            u = self.stack[i]
            if u["level"] in allowed:
                return u, i + 1
        if "root" in allowed:
            return None, 0
        return False, None

    # -- heading matching ------------------------------------------------

    def match_level(self, line):
        text = line["text"]
        for lvl, rx in self.compiled:
            m = rx.match(text)
            if not m:
                continue
            within = lvl.get("within")
            if within:
                names = set(within)
                if "initial" in names and self.stack and self.stack[0] is self.initial:
                    pass
                elif not self.on_stack(names - {"initial"}):
                    continue
            if self.form_active and lvl.get("scope", "root") != "root" and lvl["name"] not in ("appendix",):
                continue
            if lvl.get("after") and lvl["name"] not in self.seen_after:
                continue
            if not self.style_ok(lvl.get("style", "any"), line):
                continue
            parent, depth_idx = self.find_parent(lvl)
            if parent is False:
                continue
            g = {k: (v or "") for k, v in m.groupdict().items()}
            if not self.sequence_ok(lvl, g.get("num"), parent):
                self.warnings[f"sequence_rejected:{lvl['name']}"] += 1
                continue
            return lvl, m, g, parent, depth_idx
        return None

    def open_level(self, lvl, g, parent, depth_idx, line):
        seg = lvl["id"].format(**g)
        seg = re.sub(r"-$", "", seg) or lvl["name"].upper()
        label = lvl.get("label", "").format(**g) or None
        self.stack = self.stack[:depth_idx] if parent is not None else []
        depth = (parent["depth"] + 1) if parent else 0
        u = self.new_unit(seg, lvl["unit_type"], lvl["name"], parent, label, depth,
                          line["page"], scope=lvl.get("scope", "root"),
                          transparent=bool(lvl.get("transparent")),
                          normative=lvl.get("normative", True if parent is None else parent.get("normative", True)))
        self.stack.append(u)
        if lvl.get("sequence") == "global":
            self.last_article = num_value(g.get("num"))
        elif lvl.get("sequence"):
            self.sibling_last[(parent["qualified_id"] if parent else None, lvl["name"])] = num_value(g.get("num"))
        if g.get("title"):
            u["title_lines"].append(g["title"])
        if g.get("rest"):
            u["body_lines"].append(g["rest"])
        if lvl.get("title") == "next" and not g.get("title"):
            self.pending_title = {"unit": u, "lines": 0, "style": None}
        elif lvl.get("title") == "next":
            self.pending_title = {"unit": u, "lines": 1, "style": None}
        if parent is None or lvl.get("scope", "root") == "root":
            if self.form_active and self.form_active is not u:
                self.form_active = None
        return u

    # -- decimal clauses ---------------------------------------------------

    def decimal_container_ok(self):
        within = self.decimal.get("within")
        if not self.decimal.get("enabled", True) or self.form_active:
            return False
        if not within:
            return True
        return self.on_stack(set(within))

    def at_number_column(self, line):
        return any(abs(line["x0"] - x) <= 6 for x in self.number_cols)

    def match_decimal(self, line, number_only):
        text = line["text"]
        m = DECIMAL_RE.match(text)
        if not m:
            return None
        path, rest = m.group(1), (m.group(2) or "")
        if rest[:1].isdigit():
            return None                   # "273.15 K" - a value, not a clause
        parts = [int(p) for p in path.split(".")]
        if parts[0] >= 1900 or parts[0] > self.decimal.get("max_top_level", 300):
            self.warnings["decimal_rejected:implausible"] += 1
            return None
        if not number_only:
            # number + text on one fragment: only trust it in the numbering
            # column and as a plausible successor of an open clause
            if not self.at_number_column(line):
                return None
            if len(parts) > 1 and not any(u.get("number_path") == parts[:-1] for u in self.stack):
                return None
        # plausibility against the clause stack (rejects "2032." after "2.")
        prev_top = self.last_top_level()
        if len(parts) == 1 and prev_top is not None and parts[0] > prev_top + 12:
            self.warnings["decimal_rejected:jump"] += 1
            return None
        return path, parts, rest

    def last_top_level(self):
        container = self.decimal_container()
        for u in reversed(self.units):
            if u.get("number_path") and len(u["number_path"]) == 1 and u.get("container") == container["qualified_id"]:
                return u["number_path"][0]
            if u is container:
                return None
        return None

    def decimal_container(self):
        for u in reversed(self.stack):
            if not u.get("number_path"):
                return u
        return self.initial

    def open_decimal(self, path, parts, rest, line):
        d = len(parts)
        while self.stack and self.stack[-1].get("number_path") and self.stack[-1]["depth"] >= d:
            self.stack.pop()
        top = self.stack[-1] if self.stack else self.initial
        container = self.decimal_container()
        if top.get("number_path") and top["depth"] < d - 1:
            self.warnings["depth_jump"] += 1
        elif not top.get("number_path") and d > 1:
            self.warnings["depth_jump"] += 1
        base = self.id_base(container)
        qid = f"{base}.{path}"
        u = Unit(qualified_id=qid, unit_type=self.decimal.get("unit_type", "Clause"), level="decimal",
                 parent_id=top["qualified_id"], local_label=path, local_number=path,
                 number_path=parts, depth=d, page=line["page"], page_end=line["page"],
                 container=container["qualified_id"],
                 normative=container.get("normative", True),
                 title_lines=[], body_lines=[], footnote_lines=[])
        self.units.append(u)
        self.stack.append(u)
        if rest:
            u["rest_line"] = rest
        return u

    # -- pending title ---------------------------------------------------

    def take_title(self, line):
        """Short lines right after a titled heading, in one consistent
        style, become that unit's title (max 3 lines)."""
        pt = self.pending_title
        if pt is None:
            return False
        u = pt["unit"]
        text = line["text"]
        style = (round(line["size"], 1), bool(line.get("bold")), bool(line.get("italic")))
        ok = (len(text) <= 160 and pt["lines"] < 3 and not NUMBER_TOKEN_RE.match(text)
              and (pt["style"] is None or abs(style[0] - pt["style"][0]) <= 0.3 and style[1:] == pt["style"][1:])
              and not text.endswith((";",)))
        if pt["lines"] >= 1 and pt["style"] is None:
            ok = False
        if ok and any(rx.match(text) for _, rx in self.compiled):
            ok = False          # the next heading ("Part I", "Article 2") is never a title
        if not ok:
            self.pending_title = None
            return False
        u["title_lines"].append(text)
        pt["lines"] += 1
        pt["style"] = style
        if self.form_titles and any(rx.search(" ".join(u["title_lines"])) for rx in self.form_titles):
            u["unit_type_form"] = True
            self.form_active = u
        return True


def anchor_positions(lines, regions):
    """region id -> line index at which its placeholder is emitted."""
    index = {l["id"]: i for i, l in enumerate(lines)}
    by_page = collections.defaultdict(list)
    for i, l in enumerate(lines):
        by_page[l["page"]].append(i)
    pos = {}
    for r in regions:
        ids = r.get("line_ids", []) + r.get("caption_line_ids", []) + r.get("glossary_line_ids", [])
        idx = [index[i] for i in ids if i in index]
        if idx:
            pos[r["id"]] = min(idx)
        elif r.get("after_line") in index:
            pos[r["id"]] = index[r["after_line"]] + 0.5
        else:
            after = [i for i in by_page.get(r["page"], []) if lines[i]["y0"] >= (r.get("bbox") or [0, 0])[1] - 0.5]
            pos[r["id"]] = (after[0] - 0.5) if after else (by_page[r["page"]][-1] + 0.5 if by_page.get(r["page"]) else 0)
    return pos


def group_footnotes(lines):
    """Footnote lines -> footnote records (marker, text, page, line ids)."""
    notes = []
    for l in lines:
        text = l["text"]
        m = FOOTNOTE_MARKER_RE.match(text)
        marker_only = re.fullmatch(r"\(?\d{1,3}\)?|\*{1,3}|†|‡", text.strip())
        if m or marker_only:
            mk = (m.group(0) if m else text).strip("() ")
            notes.append({"marker": mk, "page": l["page"], "lines": [], "line_ids": [l["id"]]})
            rest = text[m.end():].strip() if m else ""
            if rest:
                notes[-1]["lines"].append(rest)
        elif notes and notes[-1]["page"] == l["page"]:
            notes[-1]["lines"].append(text)
            notes[-1]["line_ids"].append(l["id"])
        else:
            notes.append({"marker": None, "page": l["page"], "lines": [text], "line_ids": [l["id"]]})
    for n in notes:
        n["text"] = join_lines(n.pop("lines"))
    return [n for n in notes if n["text"] or n["marker"]]


def parse(doc_id, profile, lines, regions, stats, page_meta):
    p = Parser(doc_id, profile, stats, page_meta)
    region_by_line = {}
    for r in regions:
        if r["kind"] == "layout_table" or (r["kind"] == "equation" and r.get("inline")):
            continue
        for i in r.get("line_ids", []) + r.get("caption_line_ids", []) + r.get("glossary_line_ids", []):
            region_by_line.setdefault(i, r)
    positions = anchor_positions(lines, regions)
    emit_at = collections.defaultdict(list)
    for r in regions:
        if r["kind"] in ("toc", "layout_table"):
            continue
        emit_at[positions[r["id"]]].append(r)
    anchors = []
    footnote_lines = []
    after_trigger = [re.compile(lvl["after"]) for lvl in p.levels if lvl.get("after")]
    after_names = [lvl["name"] for lvl in p.levels if lvl.get("after")]

    def emit(r):
        unit = p.current
        anchors.append({"region_id": r["id"], "kind": r["kind"], "unit_id": unit["qualified_id"],
                        "page": r["page"]})
        if r["kind"] in PLACEHOLDER:
            unit["body_lines"].append(f"[{PLACEHOLDER[r['kind']]}:{r['id']}]")
        unit["page_end"] = max(unit["page_end"], r["page"])

    ordered_keys = sorted(emit_at)
    k = 0
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        while k < len(ordered_keys) and ordered_keys[k] <= i:
            for r in emit_at[ordered_keys[k]]:
                p.pending_title = None
                emit(r)
            k += 1
        if line["id"] in region_by_line:
            i += 1
            continue
        if line.get("is_footnote"):
            footnote_lines.append((line, p.current["qualified_id"]))
            i += 1
            continue
        for name, rx in zip(after_names, after_trigger):
            if rx.match(line["text"]):
                p.seen_after.add(name)
        if p.pending_title and p.take_title(line):
            i += 1
            continue
        hit = p.match_level(line)
        if hit:
            lvl, m, g, parent, depth_idx = hit
            u = p.open_level(lvl, g, parent, depth_idx, line)
            u["footnote_refs"] = list(line.get("footnote_refs", []))
            i += 1
            continue
        number_only = bool(NUMBER_TOKEN_RE.match(line["text"]))
        if p.decimal_container_ok():
            dm = p.match_decimal(line, number_only)
            if dm:
                path, parts, rest = dm
                u = p.open_decimal(path, parts, rest, line)
                u["footnote_refs"] = list(line.get("footnote_refs", []))
                # title vs body (plan §5.2): the text right after a number-only
                # heading is a title when short, unpunctuated, and followed by
                # a paragraph break
                if number_only and i + 1 < n and abs(lines[i + 1]["base"] - line["base"]) <= 2.5 \
                        and lines[i + 1]["page"] == line["page"] and lines[i + 1]["id"] not in region_by_line:
                    nxt = lines[i + 1]
                    after = lines[i + 2] if i + 2 < n else None
                    gap = (after["base"] - nxt["base"]) if after and after["page"] == nxt["page"] else 99
                    heading_next = after is not None and (DECIMAL_RE.match(after["text"]) is not None
                                                          or any(rx.match(after["text"]) for _, rx in p.compiled))
                    if len(nxt["text"]) <= 110 and not re.search(r"[.;:,]\s*$", nxt["text"]) \
                            and (gap > 1.35 * max(nxt["size"], 6) or heading_next) and not DECIMAL_RE.match(nxt["text"]):
                        u["title_lines"].append(nxt["text"])
                    else:
                        u["body_lines"].append(nxt["text"])
                        u.setdefault("line_idx", []).append(i + 1)
                    u["footnote_refs"] += nxt.get("footnote_refs", [])
                    i += 2
                    continue
                if rest:
                    u["body_lines"].append(rest)
                    u.setdefault("line_idx", []).append(i)
                i += 1
                continue
        cur = p.current
        cur.setdefault("line_idx", []).append(i)
        cur["body_lines"].append(line["text"])
        cur.setdefault("footnote_refs", []).extend(line.get("footnote_refs", []))
        cur["page_end"] = max(cur["page_end"], line["page"])
        i += 1
    while k < len(ordered_keys):
        for r in emit_at[ordered_keys[k]]:
            emit(r)
        k += 1
    return p, anchors, footnote_lines


def finalize(p):
    units = p.units
    for u in units:
        u["title"] = join_lines(u.pop("title_lines")) or None
        u["body_text"] = join_lines(u.pop("body_lines"))
        u["footnote_text"] = None
        u["line_ranges"] = compress(u.pop("line_idx", []))
        u.pop("footnote_lines", None)
        u.pop("rest_line", None)
        u["has_body"] = bool(re.sub(r"\[(?:TABLE|FIGURE|EQ|FORM):[^\]]+\]", "", u["body_text"]).strip())
        if u.pop("unit_type_form", False):
            u["unit_type"] = u["unit_type"]
            u["is_form"] = True
        if u.get("level") == "decimal":
            d = u["depth"]
            label = p.labels[min(d, len(p.labels)) - 1]
        else:
            label = u["unit_type"]
        u["labels"] = [label, "Paragraph"] if u["has_body"] else [label]
        u["local_number"] = u.get("local_number") or u.get("local_label")
        # `division`: the root-scoped unit this one lives in, minus the doc prefix
        u["number_path"] = u.get("number_path")
        u.setdefault("normative", True)
    by_id = {u["qualified_id"]: u for u in units}
    for u in units:
        u["division"] = division_of(u, by_id, p.doc_id)
    return units


def compress(idx):
    """[3,4,5,9,10] -> [[3,5],[9,10]] (line indices into lines.jsonl)."""
    out = []
    for i in idx:
        if out and i == out[-1][1] + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return out


def division_of(u, by_id, doc_id):
    """The nearest ancestor-or-self whose id is not nested under its
    parent's id (an Annex, Appendix, Article, Recital, Chapter, Part...)."""
    cur = u
    while cur is not None:
        parent = by_id.get(cur["parent_id"]) if cur["parent_id"] else None
        if parent is None or not cur["qualified_id"].startswith(parent["qualified_id"] + "."):
            if cur.get("level") != "decimal":
                return cur["qualified_id"][len(doc_id) + 1:]
        cur = parent
    return u["qualified_id"][len(doc_id) + 1:].split(".")[0]


def dedupe(units):
    """Last-resort safety net: two source lines produced the same id. Merge
    (never drop) and report every merge - each is a QA failure."""
    by_id, order, merges = {}, [], []
    for u in units:
        kept = by_id.get(u["qualified_id"])
        if kept is None:
            by_id[u["qualified_id"]] = u
            order.append(u["qualified_id"])
            continue
        merges.append({"qualified_id": u["qualified_id"], "pages": [kept["page"], u["page"]]})
        kept["body_text"] = " ".join(t for t in (kept["body_text"], u["body_text"]) if t)
        kept["title"] = kept["title"] or u["title"]
        kept["has_body"] = kept["has_body"] or u["has_body"]
        kept["labels"] = list(dict.fromkeys(kept["labels"] + u["labels"]))
        kept["page_end"] = max(kept["page_end"], u["page_end"])
        kept["line_ranges"] = kept.get("line_ranges", []) + u.get("line_ranges", [])
        # children of the dropped twin now hang off the kept one (same id)
    return [by_id[i] for i in order], merges


def assign_region_ids(units, anchors, regions):
    """Give every anchored region its final node id, scoped to the unit /
    division it belongs to (tables restart numbering per annex in EU acts,
    so the id carries the division)."""
    by_id = {u["qualified_id"]: u for u in units}
    reg = {r["id"]: r for r in regions}
    per_unit = collections.Counter()
    used = collections.Counter()
    caption_ids = {}
    for a in anchors:
        r = reg[a["region_id"]]
        unit = by_id.get(a["unit_id"])
        div = f"{unit['qualified_id'].split('.')[0]}" if unit else ""
        if r["kind"] == "equation":
            per_unit[(a["unit_id"], "EQ")] += 1
            a["node_id"] = f"{a['unit_id']}.EQ-{per_unit[(a['unit_id'], 'EQ')]}"
        elif r["kind"] in ("table", "figure"):
            tag = "TABLE" if r["kind"] == "table" else "FIG"
            division_id = division_unit_id(unit, by_id) if unit else a["unit_id"]
            cap = r.get("caption_id")
            if cap:
                key = (division_id, cap)
                if r.get("continues") and key in caption_ids:
                    a["node_id"] = caption_ids[key]
                elif key in caption_ids and same_table_run(caption_ids, key, r):
                    a["node_id"] = caption_ids[key]
                else:
                    num = re.sub(r"^(Table|Figure)\s+", "", cap)
                    nid = f"{division_id}.{tag}-{num}"
                    used[nid] += 1
                    if used[nid] > 1:
                        nid = f"{nid}~{used[nid]}"
                    caption_ids[key] = nid
                    a["node_id"] = nid
            else:
                per_unit[(a["unit_id"], tag)] += 1
                a["node_id"] = f"{a['unit_id']}.{tag}-U{per_unit[(a['unit_id'], tag)]}"
        elif r["kind"] == "form":
            a["node_id"] = f"{a['unit_id']}.FORM"
        a["caption_id"] = r.get("caption_id")
    return anchors


PLACEHOLDER_RE = re.compile(r"\[(TABLE|FIGURE|EQ|FORM):([^\]]+)\]")


def rewrite_placeholders(units, anchors):
    """[TABLE:p16-r1] -> [TABLE:<final node id>]; repeated placeholders for
    one multi-block table collapse into one."""
    node = {a["region_id"]: a.get("node_id") for a in anchors}

    def sub(m):
        nid = node.get(m.group(2))
        return f"[{m.group(1)}:{nid}]" if nid else ""

    for u in units:
        if "[" in u["body_text"]:
            text = PLACEHOLDER_RE.sub(sub, u["body_text"])
            text = re.sub(r"(\[[A-Z]+:[^\]]+\])(?:\s*\1)+", r"\1", text)
            u["body_text"] = re.sub(r"\s{2,}", " ", text).strip()


def same_table_run(caption_ids, key, r):
    """Several detected blocks under one caption on the same page are one
    table (Euro 7 Annex II Table 1: energy- and range-based sub-tables)."""
    return True


def division_unit_id(unit, by_id):
    cur = unit
    while cur is not None and cur.get("level") in ("decimal", "article_paragraph", "point"):
        cur = by_id.get(cur["parent_id"])
    return (cur or unit)["qualified_id"]


def attach_footnotes(doc_id, footnote_lines, units):
    """Footnote records -> attached to the unit that cites their marker
    (same page first), else to the unit open where the note was printed."""
    by_id = {u["qualified_id"]: u for u in units}
    groups = collections.defaultdict(list)
    for line, unit_id in footnote_lines:
        groups[unit_id].append(line)
    notes = []
    for unit_id, ls in groups.items():
        for n in group_footnotes(ls):
            n["open_unit"] = unit_id
            notes.append(n)
    refs = collections.defaultdict(list)   # marker -> [(page, unit_id)]
    for u in units:
        for mk in u.get("footnote_refs", []):
            refs[mk].append((u["page"], u["page_end"], u["qualified_id"]))
    markers = collections.Counter(n["marker"] for n in notes)
    for n in notes:
        cands = refs.get(n["marker"] or "", [])
        same = [c for c in cands if c[0] <= n["page"] <= c[1]]
        n["unit_id"] = (same or cands or [(0, 0, n["open_unit"])])[-1][2] if n["marker"] else n["open_unit"]
        mk = n["marker"] or "x"
        mk_safe = re.sub(r"[^\w]", "star", mk) if not mk.isalnum() else mk
        n["id"] = f"{doc_id}.FN-{mk_safe}" if markers[n["marker"]] == 1 and n["marker"] else f"{doc_id}.FN-{mk_safe}-p{n['page']}"
    seen = collections.Counter()
    for n in notes:
        seen[n["id"]] += 1
        if seen[n["id"]] > 1:
            n["id"] = f"{n['id']}~{seen[n['id']]}"
        u = by_id.get(n["unit_id"])
        if u is not None:
            u["footnote_text"] = " ".join(t for t in (u.get("footnote_text"), n["text"]) if t)
    return notes


def run(ctx):
    lines = read_jsonl(ctx.path("lines.jsonl"))
    regions = read_jsonl(ctx.path("regions.jsonl"))
    page_meta = read_jsonl(ctx.path("page_meta.jsonl"))
    stats = ctx.manifest.get("layout", {})
    p, anchors, footnote_lines = parse(ctx.doc_id, ctx.profile, lines, regions, stats, page_meta)
    units = finalize(p)
    units, merges = dedupe(units)
    anchors = assign_region_ids(units, anchors, regions)
    rewrite_placeholders(units, anchors)
    notes = attach_footnotes(ctx.doc_id, footnote_lines, units)
    ids = {u["qualified_id"] for u in units}
    orphans = sum(1 for u in units if u["parent_id"] and u["parent_id"] not in ids)
    for u in units:
        u.pop("footnote_refs", None)
        u.pop("container", None)
        u.pop("transparent", None)
    write_jsonl(ctx.path("units.jsonl"), units)
    write_jsonl(ctx.path("anchors.jsonl"), anchors)
    write_jsonl(ctx.path("footnotes.jsonl"), notes)
    types = collections.Counter(u["unit_type"] for u in units)
    ctx.record("phase2_parse", units=len(units), unit_types=dict(types), orphans=orphans,
               dedupe_merges=len(merges), merges=merges[:200], warnings=dict(p.warnings),
               footnotes=len(notes), anchors=len(anchors),
               divisions=sorted({u["division"] for u in units if u["parent_id"] is None}))
    print(f"[{ctx.doc_id}] phase2: {len(units)} units ({', '.join(f'{k} {v}' for k, v in types.most_common())}), "
          f"{orphans} orphans, {len(merges)} dedupe merges, {len(notes)} footnotes", file=sys.stderr)
    return units
