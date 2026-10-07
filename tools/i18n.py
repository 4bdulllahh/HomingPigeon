"""Find the app's English text and keep the translations complete.

    python tools/i18n.py missing ar          numbered list of what Arabic lacks
    python tools/i18n.py merge ar FILE       add translations from FILE to ar.json
    python tools/i18n.py check               every language complete and consistent?

The text the app shows is found by reading the source, not by running it:
  * the first argument of every t("...") call (templates with {fields});
  * plain English strings in the UI and the user-facing core modules, such as a
    button label passed to a widget, which translates it when it is shown.

A merge FILE has one translation per line, "NUMBER<TAB>text", numbered as
``missing`` printed them. Line breaks inside a translation are written as \\n.

tests/test_i18n.py runs the same check, so new text without translations
fails the build. Add the translations with ``missing`` and ``merge``.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "app" / "i18n" / "locales"

# Where plain English strings are collected. Other modules are only searched
# for t("...") calls.
TEXT_FILES = sorted(
    [p for p in (ROOT / "app" / "ui").rglob("*.py") if p.name != "theme.py"]
    + list((ROOT / "app" / "models").glob("*.py"))
    + [ROOT / "app" / "core" / name for name in (
        "sender.py", "imap_sync.py", "importer.py", "dns_tools.py", "warmup.py",
        "credentials.py", "exporter.py", "prefs.py", "shortcut.py", "scorer.py", "db.py")]
    + list((ROOT / "app" / "services").glob("*.py"))
    + list((ROOT / "app" / "workers").glob("*.py"))
)

# Module-level lists that are data, not wording shown to the user
SKIP_NAMES = {
    "TRIGGER_WORDS", "SUBJECT_TRIGGERS", "PROMOTION_WORDS", "OPT_OUT_WORDS",
    "SHORTENER_DOMAINS", "UNSUBSCRIBE_PHRASES", "BOUNCE_SENDERS", "BOUNCE_SUBJECTS",
    "BOUNCE_BODY_HINTS", "HARD_CODES", "SOFT_CODES", "ROLE_PREFIXES", "TYPO_DOMAINS",
    "EMAIL_HINTS", "COMPANY_HINTS", "PERSON_HINTS", "SEVERITY_WEIGHT", "SQL", "CSS",
    "DATE_FORMATS", "STATUS_ICONS", "ICONS", "BLACKLISTS", "DNSBLS", "COMMON_SELECTORS",
    "hard_markers", "soft_markers", "SKIP_IN_PYTHON", "__all__",
}

# Strings that pass every test below but are still not wording: folder names,
# a header name, programmer errors and DNS record types
IGNORE = {
    "a mx", "Doc", "Scripts", "Lib", "Message-ID", "Desktop", "sign off",
    "db.init() must be called before db.connect()", "CryptProtectData failed",
    "CryptUnprotectData failed", "Start HomingPigeon - Mac.command",
    "Start HomingPigeon - Linux.sh",
}

# Calls whose string arguments are identifiers, SQL, styles or file names
SKIP_CALLS = {
    "setProperty", "setObjectName", "get_setting", "set_setting", "set_setting_soft",
    "execute", "execute_soft", "execute_many", "query", "query_one", "setStyleSheet",
    "set_tone", "set_role", "color", "qcolor", "icon", "compile", "search", "match", "sub",
    "findall", "split", "startswith", "endswith", "replace", "strftime", "strptime",
    "getattr", "hasattr", "setattr", "get", "pop", "setdefault", "log_event", "suppress",
    "encode", "decode", "Path", "open", "print", "write", "write_text", "read_text",
    "joinpath", "with_suffix", "ensure_page", "show_page", "go", "page", "set", "add",
    "isinstance", "QKeySequence", "fromisoformat", "status_color", "resource_path",
    "ignore_patterns", "Popen", "run", "check_output", "QFont", "QColor", "px",
}
# tabs.add("Import", ...) and the like use the English name as a key; their
# labels are still collected, from the first argument only
KEEP_FIRST_ARG = {"add", "set"}

SQL = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|WHERE|CREATE|PRAGMA|COLLATE|ORDER BY|ASC|"
                 r"DESC|COALESCE|LIKE|JOIN|IS NOT NULL)\b|\w+ = ['?\w]")
CSS = re.compile(r"[a-z-]+\s*:\s*[^;{}]*;|px;|font-family")
HTML = re.compile(r"<[a-zA-Z/!][^>]*>")
FILE = re.compile(r"^[\w.\- ]*\.(py|json|xlsx|xls|csv|db|ico|png|svg|txt|bat|exe|hpbackup|log)$")


def _wording(text: str) -> bool:
    """Is this string something a person reads?"""
    stripped = text.strip()
    if len(stripped) < 2 or not re.search(r"[a-z]", stripped) or stripped in IGNORE:
        return False
    if re.match(r"^_?[A-Z][a-z0-9]+([A-Z][a-z0-9]*)+$", stripped):   # class names
        return False
    if "\\" in stripped or "(?" in stripped or re.search(r"%[A-Za-z]", stripped) \
            or " | " in stripped:                                      # regexes, formats, types
        return False
    if SQL.search(stripped) or CSS.search(stripped) or FILE.match(stripped):
        return False
    if HTML.search(stripped) and not re.search(r"[a-z]{3,} [a-z]{3,}", stripped):
        return False
    if re.match(r"^[a-z0-9_.\-/:@%]+$", stripped):     # keys, hosts, tokens, formats
        return False
    if re.search(r"\w=\S*;|\$[A-Za-z]|^https?://|^mailto:", stripped):
        return False
    # A sentence or phrase, or a capitalised label such as "Sent" or "Dark"
    return " " in stripped or bool(re.match(r"^[A-Z(\[]", stripped))


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _strings_in(path: Path, collect_plain: bool) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))

    skipped: set[int] = set()

    def skip_subtree(node: ast.AST) -> None:
        for child in ast.walk(node):
            skipped.add(id(child))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name == "t" and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                found.append(node.args[0].value)
                skipped.add(id(node.args[0]))
            elif name in SKIP_CALLS:
                args = node.args[1:] if name in KEEP_FIRST_ARG else node.args
                for arg in args:
                    skip_subtree(arg)
                for keyword in node.keywords:
                    skip_subtree(keyword.value)
                if name not in KEEP_FIRST_ARG:
                    skip_subtree(node.func)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id in SKIP_NAMES
                   for target in targets):
                skip_subtree(node)
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant):
                    skipped.add(id(key))
        elif isinstance(node, ast.Compare):
            # "app password" in lowered: a pattern matched against text, not wording
            if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
                skip_subtree(node.left)
        elif isinstance(node, (ast.arg, ast.FunctionDef, ast.AsyncFunctionDef)):
            annotation = node.annotation if isinstance(node, ast.arg) else node.returns
            if annotation is not None:
                skip_subtree(annotation)
        elif isinstance(node, ast.JoinedStr):
            skip_subtree(node)

    if collect_plain:
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in docstrings and id(node) not in skipped \
                    and _wording(node.value):
                found.append(node.value)
    return found


def keys() -> list[str]:
    """Every English string that needs a translation, in a stable order."""
    seen: dict[str, None] = {}
    text_files = set(TEXT_FILES)
    for path in sorted((ROOT / "app").rglob("*.py")):
        if "i18n" in path.parts or path.name in ("theme.py", "examples.py"):
            continue
        for text in _strings_in(path, collect_plain=path in text_files):
            seen.setdefault(text, None)
    return list(seen)


def load(code: str) -> dict[str, str]:
    path = LOCALES / f"{code}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save(code: str, catalog: dict[str, str]) -> None:
    LOCALES.mkdir(parents=True, exist_ok=True)
    wanted = keys()
    order = {text: index for index, text in enumerate(wanted)}
    ordered = dict(sorted(catalog.items(), key=lambda item: order.get(item[0], len(order))))
    (LOCALES / f"{code}.json").write_text(
        json.dumps(ordered, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def missing(code: str) -> list[str]:
    catalog = load(code)
    return [text for text in keys() if text not in catalog]


def problems(code: str) -> list[str]:
    """Missing keys, and translations whose {fields} differ from the English."""
    from app.i18n import fields

    catalog = load(code)
    found = [f"missing: {text!r}" for text in keys() if text not in catalog]
    for english, translated in catalog.items():
        if fields(english) != fields(translated):
            found.append(f"fields differ: {english!r} -> {translated!r}")
    return found


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")


def _unescape(text: str) -> str:
    out, index = [], 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            out.append({"n": "\n", "t": "\t", "\\": "\\"}.get(nxt, "\\" + nxt))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(ROOT))
    if not argv or argv[0] not in ("missing", "merge", "check", "keys"):
        print(__doc__)
        return 1
    command = argv[0]
    if command == "keys":
        for number, text in enumerate(keys(), start=1):
            print(f"{number}\t{_escape(text)}")
        return 0
    if command == "missing":
        for number, text in enumerate(missing(argv[1]), start=1):
            print(f"{number}\t{_escape(text)}")
        return 0
    if command == "merge":
        code, source = argv[1], Path(argv[2])
        wanted = missing(code)
        catalog = load(code)
        added = 0
        for line in source.read_text(encoding="utf-8").splitlines():
            if not line.strip() or "\t" not in line:
                continue
            number, translated = line.split("\t", 1)
            index = int(number) - 1
            if 0 <= index < len(wanted):
                catalog[wanted[index]] = _unescape(translated)
                added += 1
        save(code, catalog)
        print(f"{code}: {added} added, {len(missing(code))} still missing")
        return 0
    from app.i18n import CODES, DEFAULT

    bad = 0
    for code in CODES:
        if code == DEFAULT:
            continue
        found = problems(code)
        bad += len(found)
        print(f"{code}: {'complete' if not found else f'{len(found)} problem(s)'}")
        for item in found[:20]:
            print("   ", item)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
