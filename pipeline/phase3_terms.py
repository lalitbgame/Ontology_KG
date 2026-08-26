"""Phase 3 - term extraction (task.md Phase 3).

pages.jsonl + clauses.jsonl -> abbreviations.jsonl (schema.yaml Abbreviation)
                              + definitions.jsonl   (schema.yaml Definition)

No merge/reconciliation and no DEFINES/SAME_AS edges - term-model-deferral
(schema.yaml) keeps these two node types separate and unconnected in v1.
"""
import re
import sys
import json

from .phase2_parse import strip_toc  # run this file via `python -m pipeline.phase3_terms`

PAGES_PATH = "output/pages.jsonl"
CLAUSES_PATH = "output/clauses.jsonl"
ABBR_OUT = "output/abbreviations.jsonl"
DEF_OUT = "output/definitions.jsonl"

TERM_COLUMN_X0_LIMIT = 200  # left column (surface_form) vs right column (expansion)
DEFINITION_RE = re.compile(r'^"([^"]+)"\s*(?:\(([A-Za-z0-9\-]+)\))?\s*means\s+(.*)$')


def find_line(lines, text):
    for i, l in enumerate(lines):
        if l["text"] == text:
            return i
    return None


def extract_column_pairs(lines):
    """Two-column (surface_form | expansion) table, per §2.1/§2.2's layout:
    a line starting left of TERM_COLUMN_X0_LIMIT begins a new entry; every
    following line further right belongs to that entry's (possibly
    multi-line, oddly word-split) expansion, until the next term line.
    Raw extraction order occasionally batches several term-column lines
    before their expansions (e.g. "NOVC"/"NOVC-HEV" both land before
    either's expansion text) even though same-row entries share a y0 - so
    sort by (page, y0, x0) first to force term-then-expansion within each
    row without disturbing the overall page order."""
    entries = []
    current = None
    for l in sorted(lines, key=lambda l: (l["page"], round(l["y0"], 1), l["x0"])):
        if l["x0"] < TERM_COLUMN_X0_LIMIT:
            current = {"surface_form": l["text"], "parts": []}
            entries.append(current)
        elif current is not None:
            current["parts"].append(l["text"])
    for e in entries:
        e["expansion"] = " ".join(e.pop("parts")).strip()
    return entries


def extract_abbreviations(pages_lines):
    lines = strip_toc(pages_lines)
    i21, i22, i3 = (find_line(lines, t) for t in ("2.1.", "2.2.", "3."))
    if None in (i21, i22, i3):
        print("WARN could not locate §2.1/§2.2/§3 boundaries - "
              "no abbreviations extracted", file=sys.stderr)
        return []
    sections = [
        ("General abbreviations", "REG154.04.BODY.2.1", lines[i21 + 2:i22]),
        ("Chemical symbols", "REG154.04.BODY.2.2", lines[i22 + 2:i3]),
    ]
    out = []
    for category, source_clause, section_lines in sections:
        for e in extract_column_pairs(section_lines):
            e["category"] = category
            e["source_clause"] = source_clause
            out.append(e)
    return out


def extract_definitions(clauses):
    out = []
    for c in clauses:
        if c["division"] != "BODY" or not c["local_number"]:
            continue
        if c["local_number"].split(".")[0] != "3":
            continue
        m = DEFINITION_RE.match(c["body_text"])
        if not m:
            continue
        out.append({
            "quoted_term": m.group(1),
            "abbreviation": m.group(2),
            "gloss": m.group(3).strip(),
            "source_clause": c["qualified_id"],
        })
    return out


def run(pages_path=PAGES_PATH, clauses_path=CLAUSES_PATH,
        abbr_out=ABBR_OUT, def_out=DEF_OUT):
    with open(pages_path) as f:
        pages = [json.loads(l) for l in f]
    with open(clauses_path) as f:
        clauses = [json.loads(l) for l in f]

    abbreviations = extract_abbreviations(pages)
    with open(abbr_out, "w") as f:
        for e in abbreviations:
            f.write(json.dumps(e) + "\n")

    definitions = extract_definitions(clauses)
    with open(def_out, "w") as f:
        for e in definitions:
            f.write(json.dumps(e) + "\n")

    print(f"{len(abbreviations)} abbreviations -> {abbr_out} | "
          f"{len(definitions)} definitions -> {def_out}", file=sys.stderr)


if __name__ == "__main__":
    run(*sys.argv[1:])
