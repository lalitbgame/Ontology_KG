"""Single entry point for the whole pipeline (plan.md §1).

    python -m pipeline.run --all                 # every PDF in Document/
    python -m pipeline.run --doc GTR22           # one document, by doc_id ...
    python -m pipeline.run --doc "ECE_TRANS_180a22e.pdf"   # ... or file name
    python -m pipeline.run --all --from phase3_terms        # resume mid-way
    python -m pipeline.run --all --only phase6_qa

Every document gets its own output/<doc_id>/ folder and manifest.json; no
graph is combined with another document's.
"""
import argparse
import importlib
import sys
import time

from .profile import Context, resolve_documents

PHASES = [
    "phase1_extract",
    "phase1b_regions",
    "phase2_parse",
    "phase3_terms",
    "phase3b_equations",
    "phase3c_tables",
    "phase4a_external",
    "phase4_references",
    "phase5_assemble",
    "phase6_qa",
    "build_viz_data",
]


def run_document(pdf, entry, phases, out_dir=None):
    ctx = Context(pdf, entry, out_dir=out_dir)
    timings = {}
    for name in phases:
        mod = importlib.import_module(f"pipeline.{name}")
        t = time.time()
        mod.run(ctx)
        timings[name] = round(time.time() - t, 2)
    ctx.manifest["timings"] = {**ctx.manifest.get("timings", {}), **timings}
    ctx.save()
    return ctx


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="process every PDF in Document/")
    g.add_argument("--doc", help="doc_id, file name in Document/, or path")
    ap.add_argument("--from", dest="start", choices=PHASES, help="start at this phase")
    ap.add_argument("--only", choices=PHASES, help="run just this phase")
    ap.add_argument("--out", help="output root override (default output/<doc_id>)")
    args = ap.parse_args(argv)

    phases = PHASES
    if args.only:
        phases = [args.only]
    elif args.start:
        phases = PHASES[PHASES.index(args.start):]

    docs = resolve_documents(None if args.all else args.doc)
    for pdf, entry in docs:
        out_dir = f"{args.out}/{entry['doc_id']}" if args.out else None
        if not entry.get("confirmed", True):
            print(f"[{entry['doc_id']}] NOTE: {pdf.name} is not in documents.yaml - "
                  f"auto-detected profile {entry['profile']!r}; confirm the entry in the manifest",
                  file=sys.stderr)
        run_document(pdf, entry, phases, out_dir)
    if len(docs) > 1 or args.all:
        from . import build_viz_data
        build_viz_data.write_index(args.out)


if __name__ == "__main__":
    main()
