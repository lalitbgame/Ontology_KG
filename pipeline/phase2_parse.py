"""Phase 2 - hierarchical structural parsing (task.md Phase 2).

pages.jsonl -> clauses.jsonl, one record per Clause node (schema.yaml),
via a stack-based numbering parser. Division boundaries (Annex/Appendix
headings) reset the numbering stack and the qualified-id prefix.

Lettered/roman sub-items ("a.", "(i)", ...) are NOT detected specially:
since they never match CLAUSE_RE (which requires leading digits), they
fall through to the plain-text branch and are appended into the current
clause's body_text as-is - satisfying schema.yaml's rule that they stay
inline, structured text rather than becoming separate nodes, for free.
"""
import re
import sys
import json
import collections

IN_PATH = "output/pages.jsonl"
OUT_PATH = "output/clauses.jsonl"

CLAUSE_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s*(.*)$")
ANNEX_APP_RE = re.compile(r"^Annex\s+([A-Z]\d+[a-z]?)\s*-\s*Appendix\s+(\d+)$")
ANNEX_RE = re.compile(r"^Annex\s+([A-Z]\d+[a-z]?)$")
APPENDIX_RE = re.compile(r"^Appendix\s+(\d+)$")
DOT_LEADER_RE = re.compile(r"\.{4,}")


def strip_toc(lines, page_limit=10, min_leaders=3):
    """Drop the document's own Table of Contents: dot-leadered
    "Title .......... 5" lines. Dot-leader density alone isn't a safe
    signal - e.g. Annex A1's fill-in-the-blank form ("Test voltage:
    .......... V") is just as dense - so a page only counts as TOC if it's
    also near the front of the document, before any real content."""
    counts = collections.Counter(
        l["page"] for l in lines if DOT_LEADER_RE.search(l["text"]))
    toc_pages = {p for p, c in counts.items() if p <= page_limit and c >= min_leaders}
    return [l for l in lines if l["page"] not in toc_pages]


DIVISION_HEADING_MIN_SIZE = 12  # real headings render at 14.3pt; body text is <=9.8pt


def division_code(text, size=DIVISION_HEADING_MIN_SIZE):
    """Return a new division code if `text` is a Division heading, else None.

    A bare "Annex B6" or "Appendix 2" can also occur as the tail of a
    wrapped in-prose reference ("...in accordance with paragraph 3.4. of
    \\nAppendix 2") landing alone on its own line - indistinguishable from a
    real heading by text alone. Real headings render at a distinctly larger
    font size (14.3pt vs ~9.8pt body text), so `size` is required to reject
    those; the default only exists so text-only callers/tests keep working."""
    if size < DIVISION_HEADING_MIN_SIZE:
        return None
    if m := ANNEX_APP_RE.match(text):
        return f"ANNEX-{m.group(1)}.APP{m.group(2)}"
    if m := ANNEX_RE.match(text):
        return f"ANNEX-{m.group(1)}"
    if m := APPENDIX_RE.match(text):
        return f"APPENDIX-{m.group(1)}"
    return None


def labels_for(depth, has_body):
    label = ("DivisionRoot" if depth == 0 else
              "Section" if depth == 1 else
              "Subsection" if depth == 2 else "Provision")
    return [label, "Paragraph"] if has_body else [label]


def division_root(division, page):
    """Synthetic depth-0 clause per Division, so prose that precedes (or is
    the entirety of) a division's content - e.g. unnumbered declaration
    forms in some Annex appendices - still lands in some clause's body_text
    instead of being silently dropped."""
    node = {
        "qualified_id": f"REG154.04.{division}",
        "division": division,
        "depth": 0,
        "parent_id": None,
        "local_number": None,
        "page": page,
        "body_lines": [],
        "footnote_lines": [],
    }
    return node


def parse(lines):
    all_clauses = []
    division, stack = "BODY", []
    root = division_root(division, lines[0]["page"] if lines else 0)
    all_clauses.append(root)
    stack.append(root)

    for line in lines:
        text = line["text"]

        if (code := division_code(text, line["size"])) is not None:
            division = code
            root = division_root(division, line["page"])
            all_clauses.append(root)
            stack = [root]
            continue

        # A numeric line like "273.15K (0 C)." (a value, not a clause number)
        # also matches CLAUSE_RE; real clause bodies never start with a bare
        # digit right after the number, so use that to reject false hits.
        if (m := CLAUSE_RE.match(text)) and not m.group(2)[:1].isdigit():
            number_path, rest = m.group(1), m.group(2)
            depth = number_path.count(".") + 1
            while stack and stack[-1]["depth"] >= depth:
                stack.pop()
            if stack and depth > stack[-1]["depth"] + 1:
                print(f"WARN depth jump {stack[-1]['depth']}->{depth} at "
                      f"page {line['page']} ({number_path})", file=sys.stderr)
            node = {
                "qualified_id": f"REG154.04.{division}.{number_path}",
                "division": division,
                "depth": depth,
                "parent_id": stack[-1]["qualified_id"] if stack else None,
                "local_number": number_path,
                "page": line["page"],
                "body_lines": [rest] if rest else [],
                "footnote_lines": [],
            }
            all_clauses.append(node)
            stack.append(node)
            continue

        target = stack[-1]["footnote_lines"] if line["is_footnote"] else stack[-1]["body_lines"]
        target.append(text)

    return all_clauses


def finalize(nodes):
    ids = {n["qualified_id"] for n in nodes}
    orphans = 0
    for n in nodes:
        n["body_text"] = " ".join(n.pop("body_lines")).strip()
        n["footnote_text"] = " ".join(n.pop("footnote_lines")).strip() or None
        n["has_body"] = bool(n["body_text"])
        n["labels"] = labels_for(n["depth"], n["has_body"])
        if n["parent_id"] is not None and n["parent_id"] not in ids:
            orphans += 1
    return orphans


def dedupe(nodes):
    """Two different source lines can (rarely) produce the same
    qualified_id - e.g. a cross-reference like '...paragraph 5.9.' wrapping
    so '5.9.' starts the next line, indistinguishable from a real heading
    by position alone. Rather than silently keep one and drop the other,
    merge their body_text so nothing is lost, and log every merge."""
    by_id, order = {}, []
    for n in nodes:
        kept = by_id.get(n["qualified_id"])
        if kept is None:
            by_id[n["qualified_id"]] = n
            order.append(n["qualified_id"])
            continue
        print(f"WARN merged duplicate qualified_id {n['qualified_id']} "
              f"(pages {kept['page']}, {n['page']})", file=sys.stderr)
        kept["body_text"] = " ".join(t for t in (kept["body_text"], n["body_text"]) if t)
        kept["footnote_text"] = " ".join(
            t for t in (kept["footnote_text"], n["footnote_text"]) if t) or None
        kept["has_body"] = bool(kept["body_text"])
        kept["labels"] = labels_for(kept["depth"], kept["has_body"])
    return [by_id[i] for i in order]


def run(in_path=IN_PATH, out_path=OUT_PATH):
    lines = strip_toc([json.loads(l) for l in open(in_path)])
    clauses = parse(lines)
    orphans = finalize(clauses)
    clauses = dedupe(clauses)

    with open(out_path, "w") as f:
        for c in clauses:
            f.write(json.dumps(c) + "\n")

    divisions = sorted({c["division"] for c in clauses})
    print(f"{len(clauses)} clauses -> {out_path} | "
          f"{len(divisions)} divisions | {orphans} orphans", file=sys.stderr)
    print("divisions:", divisions, file=sys.stderr)


if __name__ == "__main__":
    run(*sys.argv[1:])
