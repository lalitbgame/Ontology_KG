"""Phase 1 - layout-aware text extraction (task.md Phase 1).

PDF -> pages.jsonl, one record per text line, in reading order.

Tracked-changes tagging is intentionally NOT implemented: the Phase 0 spike
(vector-drawing scan + span-color scan across the full 668 pages) found no
reliable insertion/deletion markup in this PDF's body - the only colored
text is the cover page's informal-document notice, and vector paths
correlate with table borders, not strike/underline decoration. Every span
is therefore treated as current text (schema.yaml Clause.status defaults to
"active"). See task.md Phase 0 for the write-up.
"""
import re
import sys
import json
import pymupdf

PDF_PATH = "Document/154-04 without 1C 1.pdf"
OUT_PATH = "output/pages.jsonl"

# A chemical-formula span: starts/ends on a letter or digit, made only of
# uppercase letters, digits and single spaces (e.g. "CH 4", "C2 H 6").
_FORMULA_RE = re.compile(r"\b[A-Z][A-Z0-9 ]{0,15}[A-Z0-9]\b")
# One element+subscript piece within such a span, e.g. "CH", "2", "H6".
_PIECE_RE = re.compile(r"[A-Z]{0,2}\d{0,3}")


def normalize_chem(text: str) -> str:
    """Collapse spacing artifacts in chemical formulas: 'CH 4' -> 'CH4',
    'C2 H 6' -> 'C2H6'. Piece letters are capped at 2 chars so real
    abbreviations (WLTC, REESS, ...) are never touched."""
    def collapse(m):
        span = m.group(0)
        pieces = span.split(" ")
        if len(pieces) > 1 and all(p and _PIECE_RE.fullmatch(p) for p in pieces):
            return "".join(pieces)
        return span
    return _FORMULA_RE.sub(collapse, text)


def extract_lines(doc):
    """One record per visual line, across all pages, in reading order."""
    lines = []
    for page in doc:
        height = page.rect.height
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(s["text"] for s in line["spans"]).strip()
                if not text:
                    continue
                x0, y0, x1, y1 = line["bbox"]
                size = line["spans"][0]["size"]
                lines.append({
                    "page": page.number,
                    "x0": round(x0, 1), "y0": round(y0, 1),
                    "text": normalize_chem(text),
                    "size": round(size, 1),
                    "page_height": height,
                })
    return lines


def header_footer_signatures(lines, n_pages, threshold=0.9):
    """Line signatures (rounded y + digit-normalized text) repeating on
    >90% of pages are headers/footers (e.g. running title, bare page no.)."""
    seen_per_page = {}
    for l in lines:
        sig = (round(l["y0"] / 5) * 5, re.sub(r"\d+", "#", l["text"]))
        seen_per_page.setdefault(l["page"], set()).add(sig)
    counts = {}
    for sigs in seen_per_page.values():
        for sig in sigs:
            counts[sig] = counts.get(sig, 0) + 1
    return {sig for sig, c in counts.items() if c / n_pages > threshold}


def tag_footnotes(lines):
    """Footnote = markedly smaller font, in the bottom slice of the page."""
    page_sizes = {}
    for l in lines:
        page_sizes.setdefault(l["page"], []).append(l["size"])
    median_size = {p: sorted(s)[len(s) // 2] for p, s in page_sizes.items()}
    for l in lines:
        is_small = l["size"] < 0.85 * median_size[l["page"]]
        is_bottom = l["y0"] > 0.85 * l["page_height"]
        l["is_footnote"] = bool(is_small and is_bottom)


def run(pdf_path=PDF_PATH, out_path=OUT_PATH):
    doc = pymupdf.open(pdf_path)
    lines = extract_lines(doc)
    hf = header_footer_signatures(lines, doc.page_count)
    lines = [l for l in lines
             if (round(l["y0"] / 5) * 5, re.sub(r"\d+", "#", l["text"])) not in hf]
    tag_footnotes(lines)
    for l in lines:
        del l["page_height"]

    with open(out_path, "w") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")
    print(f"{len(lines)} lines -> {out_path} "
          f"({len(hf)} header/footer patterns stripped, "
          f"{sum(l['is_footnote'] for l in lines)} footnote lines tagged)",
          file=sys.stderr)


if __name__ == "__main__":
    run(*sys.argv[1:])
