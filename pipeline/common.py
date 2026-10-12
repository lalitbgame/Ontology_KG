"""Small shared helpers used by every phase: JSONL I/O, text normalisation,
roman numerals, and quote-agnostic regex fragments."""
import json
import re
import unicodedata
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_DIR / "output"
DOCUMENT_DIR = PROJECT_DIR / "Document"


# ---------------------------------------------------------------------------
# JSONL
# ---------------------------------------------------------------------------

def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Text normalisation (plan §3 step 6)
# ---------------------------------------------------------------------------

QUOTES_OPEN = "\"“‘'’”"
QUOTES_CLOSE = "\"”’'‘“"
Q_OPEN = "[\"“‘'’”]"
Q_CLOSE = "[\"”’'‘“]"

_SOFT_HYPHEN = "­"
_SPACES = dict.fromkeys(map(ord, "      "), " ")
# Private-use bullets emitted by Wingdings/Symbol fonts (e.g. U+F0A7).
_PRIVATE_USE_RE = re.compile("[-]")


def normalize_text(text):
    """Searchable form of a raw PDF string: NFKC folds mathematical
    alphanumerics (𝑆𝑂𝐶𝐸 -> SOCE) and ligatures; soft hyphens are dropped,
    exotic spaces become plain spaces, private-use bullet glyphs become '•'."""
    if not text:
        return text
    text = text.replace(_SOFT_HYPHEN, "").translate(_SPACES)
    text = _PRIVATE_USE_RE.sub("•", text)
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"[ \t]+", " ", text)


def join_lines(lines):
    """Join wrapped lines into prose, gluing a trailing hyphen to the next
    word only when it is a soft line-break hyphen (lowercase on both sides)."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if out.endswith("-") and len(out) > 1 and out[-2].islower() and line[:1].islower():
            out = out[:-1] + line
        else:
            out = f"{out} {line}" if out else line
    return out


# ---------------------------------------------------------------------------
# Roman numerals
# ---------------------------------------------------------------------------

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
ROMAN_RE = r"(?:M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))"


def roman_to_int(s):
    s = s.upper()
    if not s or not re.fullmatch(ROMAN_RE, s):
        return None
    total = 0
    for i, ch in enumerate(s):
        v = _ROMAN[ch]
        if i + 1 < len(s) and _ROMAN[s[i + 1]] > v:
            total -= v
        else:
            total += v
    return total


def numeric_key(label):
    """Total-order sort key for a printed label: '6.3.20' sorts as 6,3,20;
    'IV' as 4; 'B6a' as B,6,a. Every element is an (int, str) pair so keys
    of different shapes always compare; unparseable labels sort last."""
    if label is None:
        return ((9, ""),)
    label = str(label).strip("().")
    if re.fullmatch(r"\d+(\.\d+)*", label):
        return tuple((0, f"{int(p):06d}") for p in label.split("."))
    r = roman_to_int(label)
    if r:
        return ((0, f"{r:06d}"),)
    m = re.fullmatch(r"([A-Z]?)(\d+)([a-z]?)", label)
    if m:
        return ((1, m.group(1)), (0, f"{int(m.group(2)):06d}"), (1, m.group(3)))
    return ((8, label),)


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
