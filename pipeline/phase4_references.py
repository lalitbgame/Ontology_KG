"""Phase 4 - cross-reference linking (task.md Phase 4, cross-ref half only).

Term-usage linking (whole-word Term scan -> MENTIONED_IN) is NOT
implemented here: schema.yaml's term-model-deferral keeps MENTIONED_IN
deferred (Abbreviation/Definition aren't merged into one queryable Term
node yet) - see deferred_relationship_types and output/PHASE1_2_NOTES.md.

clauses.jsonl -> references.jsonl (schema.yaml REFERENCES edges): resolved
where the target clause/division exists, otherwise an honest
{status: "unresolved", raw_text: ...} record - never guessed. Table/Figure
references are always unresolved for now: no phase populates Table/Figure
nodes yet, so there is nothing to resolve them against.
"""
import re
import sys
import json

CLAUSES_PATH = "output/clauses.jsonl"
OUT_PATH = "output/references.jsonl"

PARAGRAPH_RE = re.compile(r"paragraph\s+([\dA-Za-z.]+)\.")
ANNEX_RE = re.compile(r"Annex\s+([A-Z]?\d+[a-z]?)")
APPENDIX_RE = re.compile(r"Appendix\s+(\d+)(?:\s+to\s+Annex\s+([A-Z]?\d+[a-z]?))?")
# task.md specifies Table/Figure\s+\S+; tightened to an identifier-shaped
# token (starts uppercase/digit) so trailing punctuation like "Table 1B)"
# and unrelated prose like "Table of Contents" aren't swept in.
TABLE_RE = re.compile(r"Table\s+([A-Z0-9][\w/.\-]*)")
FIGURE_RE = re.compile(r"Figure\s+([A-Z0-9][\w/.\-]*)")

SCOPE_WINDOW = 60  # chars scanned after a "paragraph N." match for scope cues
REGULATION_RE = re.compile(r"^\s*of\s+this\s+Regulation")
OF_APPENDIX_RE = re.compile(r"^\s*of\s+Appendix\s+(\d+)(?:\s+to\s+Annex\s+([A-Z]?\d+[a-z]?))?")
OF_ANNEX_RE = re.compile(r"^\s*of\s+Annex\s+([A-Z]?\d+[a-z]?)")


def annex_base(division):
    """'ANNEX-B6.APP1' -> 'B6'; 'ANNEX-B6' -> 'B6'; 'BODY' -> None."""
    if not division.startswith("ANNEX-"):
        return None
    return division[len("ANNEX-"):].split(".")[0]


def resolve_appendix(division, num, annex_code=None):
    """A bare 'Appendix N' (no 'to Annex X') means the current annex's own
    appendix when the referencing clause is inside one (plan §6.4's
    same-Division default); otherwise an Appendix to the Regulation body."""
    if annex_code:
        return f"ANNEX-{annex_code}.APP{num}"
    base = annex_base(division)
    return f"ANNEX-{base}.APP{num}" if base else f"APPENDIX-{num}"


def resolve_paragraph_scope(division, tail):
    """`tail` is the text right after a 'paragraph N.' match. Look for an
    explicit scope override per plan §6.4; default to the referencing
    clause's own division otherwise."""
    if REGULATION_RE.match(tail):
        return "BODY"
    if m := OF_APPENDIX_RE.match(tail):
        return resolve_appendix(division, m.group(1), m.group(2))
    if m := OF_ANNEX_RE.match(tail):
        return f"ANNEX-{m.group(1)}"
    return division


def extract_references(clauses):
    ids = {c["qualified_id"] for c in clauses}

    def make(from_id, target_division, raw_text):
        to_id = f"REG154.04.{target_division}"
        resolved = to_id in ids
        return {"from": from_id, "to": to_id if resolved else None,
                "status": "resolved" if resolved else "unresolved", "raw_text": raw_text}

    def unresolved(from_id, raw_text):
        return {"from": from_id, "to": None, "status": "unresolved", "raw_text": raw_text}

    refs = []
    for c in clauses:
        text, div, from_id = c["body_text"], c["division"], c["qualified_id"]
        if not text:
            continue

        for m in PARAGRAPH_RE.finditer(text):
            scope = resolve_paragraph_scope(div, text[m.end():m.end() + SCOPE_WINDOW])
            refs.append(make(from_id, f"{scope}.{m.group(1)}", m.group(0)))

        for m in ANNEX_RE.finditer(text):
            refs.append(make(from_id, f"ANNEX-{m.group(1)}", m.group(0)))

        for m in APPENDIX_RE.finditer(text):
            refs.append(make(from_id, resolve_appendix(div, m.group(1), m.group(2)), m.group(0)))

        for m in TABLE_RE.finditer(text):
            refs.append(unresolved(from_id, m.group(0)))

        for m in FIGURE_RE.finditer(text):
            refs.append(unresolved(from_id, m.group(0)))

    return refs


def run(clauses_path=CLAUSES_PATH, out_path=OUT_PATH):
    with open(clauses_path) as f:
        clauses = [json.loads(l) for l in f]
    refs = extract_references(clauses)

    with open(out_path, "w") as f:
        for r in refs:
            f.write(json.dumps(r) + "\n")

    resolved = sum(r["status"] == "resolved" for r in refs)
    rate = f"{resolved / len(refs):.0%}" if refs else "n/a"
    print(f"{len(refs)} references -> {out_path} | {resolved} resolved ({rate})",
          file=sys.stderr)


if __name__ == "__main__":
    run(*sys.argv[1:])
