"""Phase 0 - document registry, document-family profiles, identity (plan §2).

documents.yaml (repo root) maps each PDF to a doc_id and, optionally, a
profile. Profiles (pipeline/profiles/<family>.yaml) hold every piece of
document-family grammar - heading words, numbering style, definition
phrasing, reference grammar - so the phase scripts stay generic.

If a PDF has no registry entry, the profile is auto-detected from the first
pages' text + PDF metadata, and a doc_id is derived from that profile's
metadata regexes; the guess is written to the manifest for a human to
confirm (never silently trusted - see `Registry.entry_for`).
"""
import datetime
import hashlib
import re
import subprocess
from pathlib import Path

import yaml

from .common import DOCUMENT_DIR, OUTPUT_DIR, PROJECT_DIR, read_json, slug, write_json

PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
REGISTRY_PATH = PROJECT_DIR / "documents.yaml"

# Top-level keys every profile must define, and the keys allowed under each
# - a typo in a profile should fail loudly, not silently disable a feature.
PROFILE_SCHEMA = {
    "family": None,
    "description": None,
    "detect": {"any", "all", "min_score"},
    "metadata": {"title", "number", "series", "date", "issuer", "region", "doc_id", "self_id", "kind"},
    "layout": {"chem_normalize", "header_min_share", "footnote_marker", "numbering_tolerance"},
    "structure": {"initial", "levels", "decimal", "labels", "form_titles"},
    "terms": {"definition_sections", "abbreviation_sections", "definition_patterns",
              "inline_abbreviation_patterns", "scope_patterns"},
    "references": {"self_words", "default_scope"},
    "equations": {"math_fonts", "glossary_trigger", "units"},
    "viz": {"groups", "root_label"},
}


class ProfileError(ValueError):
    pass


def validate_profile(p, name):
    for key in p:
        if key not in PROFILE_SCHEMA:
            raise ProfileError(f"profile {name}: unknown top-level key {key!r}")
    for key in ("family", "detect", "structure"):
        if key not in p:
            raise ProfileError(f"profile {name}: missing required key {key!r}")
    for key, allowed in PROFILE_SCHEMA.items():
        if allowed and isinstance(p.get(key), dict):
            for sub in p[key]:
                if sub not in allowed:
                    raise ProfileError(f"profile {name}: unknown key {key}.{sub}")
    for lvl in p["structure"].get("levels", []):
        for req in ("name", "unit_type", "match", "id"):
            if req not in lvl:
                raise ProfileError(f"profile {name}: level {lvl.get('name')!r} missing {req!r}")
        try:
            re.compile(lvl["match"])
        except re.error as e:
            raise ProfileError(f"profile {name}: level {lvl['name']} bad regex: {e}")
    return p


def load_profile(family):
    path = PROFILE_DIR / f"{family}.yaml"
    if not path.exists():
        raise ProfileError(f"no profile file {path}")
    with open(path, encoding="utf-8") as f:
        return validate_profile(yaml.safe_load(f), family)


def all_profiles():
    return {p.stem: load_profile(p.stem) for p in sorted(PROFILE_DIR.glob("*.yaml"))}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def first_pages_text(doc, n=2):
    text = " ".join(doc[i].get_text() for i in range(min(n, doc.page_count)))
    meta = doc.metadata or {}
    return re.sub(r"\s+", " ", f"{meta.get('title') or ''} {meta.get('subject') or ''} {text}")


def score_profile(profile, text):
    det = profile["detect"]
    if any(not re.search(p, text) for p in det.get("all", [])):
        return 0
    return sum(1 for p in det.get("any", []) if re.search(p, text))


def detect_profile(doc, profiles=None):
    """Return (family, score). Falls back to 'generic' if nothing scores."""
    profiles = profiles or all_profiles()
    text = first_pages_text(doc)
    scored = sorted(((score_profile(p, text), fam) for fam, p in profiles.items()
                     if fam != "generic"), reverse=True)
    if scored and scored[0][0] >= profiles[scored[0][1]]["detect"].get("min_score", 1):
        return scored[0][1], scored[0][0]
    return "generic", 0


def extract_metadata(doc, profile):
    """Apply the profile's metadata regexes to the first pages. Each regex's
    first group (or whole match) becomes the value; misses stay None."""
    text = first_pages_text(doc, n=3)
    out = {}
    for key, pattern in (profile.get("metadata") or {}).items():
        if key in ("doc_id", "self_id", "kind"):
            continue
        m = re.search(pattern, text)
        out[key] = (m.group(1) if m and m.groups() else m.group(0) if m else None)
        if out[key]:
            out[key] = re.sub(r"\s+", " ", out[key]).strip()
    return out


def format_template(template, values):
    """Fill a metadata template; '/' in values becomes '-' so '2024/1257'
    yields id-safe 'EU2024-1257'. Returns None if a field is missing."""
    fields = re.findall(r"\{(\w+)\}", template)
    if any(not values.get(f) for f in fields):
        return None
    return template.format(**{f: values[f].replace("/", "-") for f in fields})


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class Registry:
    def __init__(self, path=REGISTRY_PATH):
        self.path = Path(path)
        data = {}
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        self.entries = data.get("documents", [])

    def by_file(self, pdf_path):
        name = Path(pdf_path).name
        return next((e for e in self.entries if e["file"] == name), None)

    def by_doc_id(self, doc_id):
        return next((e for e in self.entries if e["doc_id"] == doc_id), None)

    def entry_for(self, pdf_path, doc=None):
        """Registry entry for this PDF, or an auto-derived one marked
        `confirmed: False` (written to the manifest for human review)."""
        entry = self.by_file(pdf_path)
        if entry:
            return {**entry, "confirmed": True}
        import pymupdf
        doc = doc or pymupdf.open(pdf_path)
        family, score = detect_profile(doc)
        profile = load_profile(family)
        meta = extract_metadata(doc, profile)
        tmpl = (profile.get("metadata") or {}).get("doc_id")
        doc_id = format_template(tmpl, meta) if tmpl else None
        if not doc_id or doc_id.strip(".-") == "":
            doc_id = slug(Path(pdf_path).stem).upper()
        self_tmpl = (profile.get("metadata") or {}).get("self_id")
        return {"file": Path(pdf_path).name, "doc_id": doc_id, "profile": family,
                "self_ids": [format_template(self_tmpl, meta)] if self_tmpl else [],
                "detect_score": score, "confirmed": False}


def resolve_documents(spec=None, registry=None):
    """`spec`: None/'all' -> every PDF in Document/; a doc_id; or a path."""
    registry = registry or Registry()
    pdfs = sorted(DOCUMENT_DIR.glob("*.pdf"))
    if spec in (None, "all", "--all"):
        return [(p, registry.entry_for(p)) for p in pdfs]
    entry = registry.by_doc_id(spec)
    if entry:
        return [(DOCUMENT_DIR / entry["file"], {**entry, "confirmed": True})]
    path = Path(spec)
    if not path.exists():
        path = DOCUMENT_DIR / spec
    if not path.exists():
        raise FileNotFoundError(f"no document matching {spec!r} (doc_id, file name or path)")
    return [(path, registry.entry_for(path))]


def doc_output_dir(doc_id):
    return OUTPUT_DIR / doc_id


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_DIR,
                              capture_output=True, text=True, timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


class Context:
    """Everything a phase needs about the document being processed: paths,
    doc_id, profile, and the manifest (shared, phase-appended run record)."""

    def __init__(self, pdf_path, entry, out_dir=None):
        self.pdf_path = Path(pdf_path)
        self.entry = entry
        self.doc_id = entry["doc_id"]
        self.family = entry.get("profile")
        if not self.family:
            import pymupdf
            self.family, _ = detect_profile(pymupdf.open(self.pdf_path))
        self.profile = load_profile(self.family)
        self.out = Path(out_dir) if out_dir else doc_output_dir(self.doc_id)
        self.out.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.out / "manifest.json"
        self.manifest = read_json(self.manifest_path, {}) or {}

    def path(self, name):
        return self.out / name

    def self_ids(self):
        return set(self.entry.get("self_ids") or [])

    def record(self, phase, **info):
        self.manifest.setdefault("phases", {})[phase] = info
        self.save()

    def save(self):
        write_json(self.manifest_path, self.manifest)

    def init_manifest(self, doc):
        meta = extract_metadata(doc, self.profile)
        self.manifest = {
            "doc_id": self.doc_id,
            "source_file": self.pdf_path.name,
            "sha256": sha256(self.pdf_path),
            "profile": self.family,
            "registry_confirmed": self.entry.get("confirmed", False),
            "registry_entry": {k: v for k, v in self.entry.items() if k != "confirmed"},
            "page_count": doc.page_count,
            "metadata": {**meta, **(self.entry.get("metadata") or {})},
            "outline": [[lvl, title.replace("\xa0", " ").strip(), page]
                        for lvl, title, page in doc.get_toc()],
            "pipeline_commit": git_commit(),
            "run_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "phases": {},
        }
        self.save()
