"""
Extract all embedded JSON objects from a Dzen article HTML dump.

Finds ``window.XXX = {...}``, ``var _params = (...)``, and
``window.__scriptInfoGetters.push(function() {return {...}})``
assignments, saves each parsed JSON to ``data/extracted_json_N.json``,
and recursively searches for article-related keys.

Usage::

    python tools/extract_json_from_article.py
    python tools/extract_json_from_article.py data/debug_article.html
"""

import json
import re
import sys
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup

HTML_PATH = "data/debug_article.html"
OUTPUT_DIR = "data"
SEARCH_KEYS = [
    "text", "content", "body", "blocks", "article",
    "title", "headline",
    "publishedAt", "date", "timestamp",
    "images", "media",
    "draft", "draftJsState", "contentState",
    "publisherId", "addTime", "publishTime", "modificationTime",
]


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

def find_json_assignments(script_text: str) -> list[dict]:
    """Find all ``window.NAME = VALUE`` and ``var _params = VALUE`` assignments.

    Returns a list of dicts with keys: ``var``, ``json_str``, ``start``.
    """
    results = []

    # Pattern 1: window.XXXX = {...} or window.XXXX = [...]
    for m in re.finditer(
        r'(window\.\w+(?:\.\w+)*)\s*=\s*([\[\{])',
        script_text,
    ):
        var_name = m.group(1)
        bracket = m.group(2)
        json_str = _extract_json_value(script_text, m.end() - 1)
        if json_str:
            results.append({"var": var_name, "json_str": json_str, "start": m.start()})

    # Pattern 2: var _params = ({...})
    for m in re.finditer(r'var\s+(_params)\s*=\s*\(?(\{)', script_text):
        var_name = m.group(1)
        json_str = _extract_json_value(script_text, m.end() - 1)
        if json_str:
            results.append({"var": var_name, "json_str": json_str, "start": m.start()})

    # Pattern 3: push(function() {return {...}})
    for m in re.finditer(
        r'(window\.__\w+)\.push\(function\(\)\s*\{return\s*(\{)',
        script_text,
    ):
        var_name = m.group(1)
        js_obj = _extract_json_value(script_text, m.end() - 1)
        if js_obj:
            json_str = _js_object_to_json(js_obj)
            results.append({"var": var_name, "json_str": json_str, "start": m.start()})

    return results


def _js_object_to_json(js_text: str) -> str:
    """Convert a JavaScript object literal to valid JSON by quoting keys.

    This handles simple cases like ``{startStack: ..., endStack: ...}``
    where keys are unquoted identifiers.
    """
    # Regex to find unquoted JS object keys: word chars before a colon
    # Must be careful not to match colons inside strings
    result = []
    in_string = False
    escape = False
    in_key = True  # We're at a position where a key is expected
    depth = 0
    bracket_stack = []  # track { and [
    i = 0

    while i < len(js_text):
        ch = js_text[i]

        if escape:
            result.append(ch)
            escape = False
            i += 1
            continue

        if ch == "\\":
            result.append(ch)
            escape = True
            i += 1
            continue

        if ch == '"' or ch == "'":
            result.append('"')  # normalize to double quotes
            quote_char = ch
            i += 1
            # Read until matching quote
            while i < len(js_text):
                c = js_text[i]
                if c == "\\":
                    result.append(c)
                    if i + 1 < len(js_text):
                        result.append(js_text[i + 1])
                        i += 2
                    else:
                        i += 1
                    continue
                if c == quote_char:
                    result.append('"')
                    i += 1
                    break
                result.append(c)
                i += 1
            continue

        if ch in ("{", "["):
            result.append(ch)
            depth += 1
            bracket_stack.append(ch)
            in_key = True
        elif ch in ("}", "]"):
            result.append(ch)
            depth -= 1
            if bracket_stack:
                bracket_stack.pop()
            in_key = False
        elif ch == ":":
            result.append(ch)
            in_key = False
        elif ch == ",":
            result.append(ch)
            in_key = True
        elif ch in (" ", "\n", "\r", "\t"):
            result.append(ch)
        elif in_key and ch.isidentifier() or ch in ("$", "_"):
            # Start of an unquoted key
            key_start = i
            while i < len(js_text) and (js_text[i].isidentifier() or js_text[i] in ("$", "_")):
                i += 1
            key = js_text[key_start:i]
            # Skip whitespace to find colon
            j = i
            while j < len(js_text) and js_text[j] in (" ", "\n", "\r", "\t"):
                j += 1
            if j < len(js_text) and js_text[j] == ":":
                result.append('"')
                result.append(key)
                result.append('"')
                # Continue from i (position after key)
            else:
                result.append(key)
            continue
        else:
            result.append(ch)
            in_key = False

        i += 1

    return "".join(result)


def _extract_json_value(text: str, start_pos: int) -> str | None:
    """Extract a JSON object or array starting at *start_pos* using bracket counting.

    *start_pos* must point to the opening ``{`` or ``[``.
    """
    if start_pos >= len(text):
        return None

    open_char = text[start_pos]
    close_char = "}" if open_char == "{" else "]"
    depth = 0
    in_string = False
    escape = False

    for i in range(start_pos, len(text)):
        ch = text[i]

        if escape:
            escape = False
            continue

        if ch == "\\":
            escape = True
            continue

        if ch == '"' and not escape:
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start_pos : i + 1]

    # If we hit the end without closing, try to find a reasonable end
    return None


# ---------------------------------------------------------------------------
# Recursive key search
# ---------------------------------------------------------------------------

def find_keys_recursive(obj, path: str = "") -> list[tuple]:
    """Recursively search *obj* for interesting keys.

    Returns a list of ``(path, value_preview)`` tuples.
    """
    results = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            current_path = f"{path}.{key}" if path else key
            key_lower = key.lower()

            # Check if this key is interesting
            for search_key in SEARCH_KEYS:
                if search_key.lower() in key_lower:
                    preview = _make_preview(value)
                    results.append((current_path, preview))
                    break

            # Recurse into nested structures
            if isinstance(value, (dict, list)):
                results.extend(find_keys_recursive(value, current_path))
            elif isinstance(value, str) and len(value) > 100:
                # Try to parse as JSON string
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, (dict, list)):
                        results.extend(find_keys_recursive(parsed, current_path))
                except (json.JSONDecodeError, TypeError):
                    pass

    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, (dict, list)):
                results.extend(find_keys_recursive(item, f"{path}[{i}]"))

    return results


def _make_preview(value) -> str:
    """Create a human-readable preview of a value."""
    if isinstance(value, str):
        if len(value) > 200:
            words = value.split()
            word_count = len(words)
            preview = value[:200].replace("\n", "\\n")
            preview = _sanitize_for_console(preview)
            return f"str ({word_count} words) \"{preview}...\""
        return f"str \"{_sanitize_for_console(value)}\""
    elif isinstance(value, (int, float)):
        return f"{type(value).__name__} {value}"
    elif isinstance(value, list):
        return f"list [{len(value)} items]"
    elif isinstance(value, dict):
        return f"dict {{{len(value)} keys}}"
    elif isinstance(value, bool):
        return f"bool {value}"
    elif value is None:
        return "null"
    return str(type(value).__name__)


def _sanitize_for_console(text: str) -> str:
    """Replace non-ASCII characters with ASCII equivalents for Windows console."""
    # Replace common problematic Unicode chars
    replacements = {
        "₽": "RUB",  # ruble sign
        "✓": "[v]",  # check mark
        "✗": "[x]",  # cross mark
        "–": "--",  # en dash
        "—": "---",  # em dash
        " ": " ",  # non-breaking space
        "’": "'",  # right single quote
        "‘": "'",  # left single quote
        "“": '"',  # left double quote
        "”": '"',  # right double quote
        "«": "<<",  # left guillemet
        "»": ">>",  # right guillemet
        "…": "...",  # ellipsis
        "№": "N",  # numero sign
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Fallback: encode to ASCII, replacing any remaining non-ASCII
    return text.encode("ascii", errors="replace").decode("ascii")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    html_path = sys.argv[1] if len(sys.argv) > 1 else HTML_PATH
    print(f"=== JSON Extractor for Dzen Article ===\n")
    print(f"HTML:  {html_path}")
    print(f"Output: {OUTPUT_DIR}/\n")

    if not Path(html_path).exists():
        print(f"ERROR: {html_path} not found")
        sys.exit(1)

    # Load HTML
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    print(f"HTML size: {len(html):,} bytes\n")

    # Parse with BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script")

    # Filter scripts with window.__ or _params
    target_scripts = []
    for script in scripts:
        text = script.string or ""
        if "window.__" in text or "window.Ya" in text or "_params" in text:
            target_scripts.append(text)

    print(f"Total <script> tags: {len(scripts)}")
    print(f"Scripts with window.__ / _params: {len(target_scripts)}\n")

    # Extract all JSON assignments
    all_assignments = []
    for i, script_text in enumerate(target_scripts):
        assignments = find_json_assignments(script_text)
        for a in assignments:
            a["script_index"] = i
        all_assignments.extend(assignments)

    print(f"Total window/var assignments found: {len(all_assignments)}\n")

    # Deduplicate by json_str (many scripts have identical push calls)
    seen_hashes = set()
    unique_assignments = []
    for a in all_assignments:
        h = hash(a["json_str"])
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique_assignments.append(a)

    print(f"Unique assignments (after dedup): {len(unique_assignments)}\n")

    # Parse each JSON
    Path(OUTPUT_DIR).mkdir(exist_ok=True)

    extracted = []
    for i, a in enumerate(unique_assignments):
        try:
            obj = json.loads(a["json_str"])
        except json.JSONDecodeError:
            # Try JS → JSON conversion as fallback
            try:
                fixed = _js_object_to_json(a["json_str"])
                obj = json.loads(fixed)
            except (json.JSONDecodeError, Exception) as e2:
                print(f"  [{i}] FAILED to parse: {a['var']} (pos {a['start']}): {e2}")
                # Save raw string for debugging
                raw_path = f"{OUTPUT_DIR}/extracted_json_{i}_raw.txt"
                with open(raw_path, "w", encoding="utf-8") as f:
                    f.write(a["json_str"])
                continue

        # Save JSON
        json_path = f"{OUTPUT_DIR}/extracted_json_{i}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

        size_kb = len(a["json_str"]) / 1024

        # Find interesting keys
        interesting = find_keys_recursive(obj)

        extracted.append({
            "file": f"extracted_json_{i}.json",
            "size_kb": size_kb,
            "var": a["var"],
            "obj": obj,
            "interesting": interesting,
        })

        print(f"  [{i}] {a['var']} -> extracted_json_{i}.json ({size_kb:.1f} KB)")

        if interesting:
            # Prioritize: show article-content paths first, then others
            article_paths = []
            meta_paths = []
            for p, preview in interesting:
                pl = p.lower()
                if any(kw in pl for kw in ("contentstate", "draftjsstate", "blocks", "articlecontent")):
                    article_paths.append((p, preview))
                elif any(kw in pl for kw in ("title", "headline", "publishtime", "addtime", "publisherid")):
                    article_paths.append((p, preview))
                else:
                    meta_paths.append((p, preview))

            # Show article paths first, up to 10 total
            shown = 0
            for p, preview in (article_paths + meta_paths):
                if shown >= 10:
                    remaining = len(article_paths) + len(meta_paths) - 10
                    print(f"      ... and {remaining} more keys (see report for full list)")
                    break
                print(f"      .{_sanitize_for_console(p)}: {_sanitize_for_console(preview)}")
                shown += 1
        else:
            print(f"      (no article-related keys found)")

    # Summary table
    print(f"\n{'=' * 80}")
    print(f"{'File':<30} | {'Size':>8} | {'Found keys with article data'}")
    print(f"{'-' * 30} | {'-' * 8} | {'-' * 40}")

    article_found = None
    article_found_score = 0

    for e in extracted:
        if e["interesting"]:
            # Filter for text/content keys with actual words
            text_keys = []
            max_words = 0
            has_article_structure = False

            for path, preview in e["interesting"]:
                if any(kw in path.lower() for kw in ("text", "content", "body", "draft")):
                    # Extract word count from preview
                    wc_match = re.search(r"\((\d+)\s*words\)", preview)
                    words = int(wc_match.group(1)) if wc_match else 0
                    if words > max_words:
                        max_words = words

                    if wc_match and int(wc_match.group(1)) > 10:
                        text_keys.append(f".{path} ({wc_match.group(1)} words)")
                    elif wc_match:
                        text_keys.append(f".{path} ({wc_match.group(1)} words)")
                    else:
                        text_keys.append(f".{path}")

                # Check for article structure indicators
                if any(kw in path.lower() for kw in ("contentstate", "draftjsstate", "articlecontent", "article_content")):
                    has_article_structure = True

            if text_keys:
                # Score: prioritize article structure, then word count
                score = max_words
                if has_article_structure:
                    score += 100000  # heavy bonus for actual article content

                if score > article_found_score:
                    article_found_score = score
                    article_found = {
                        "file": e["file"],
                        "var": e["var"],
                        "paths": text_keys,
                    }
                for tk in text_keys[:3]:
                    print(f"{e['file']:<30} | {e['size_kb']:>7.1f}K | {tk}")
            else:
                other_keys = [f".{p}" for p, _ in e["interesting"][:3]]
                print(f"{e['file']:<30} | {e['size_kb']:>7.1f}K | {', '.join(other_keys)}")
        else:
            print(f"{e['file']:<30} | {e['size_kb']:>7.1f}K | --")

    print(f"{'=' * 80}")

    # Recommendation
    if article_found:
        print(f"\nRECOMMENDATION: article data found in `{article_found['var']}`")
        for p in article_found["paths"]:
            print(f"  -> {p}")
        print(f"\nFiles saved: {article_found['file']}")
    else:
        print("\nRECOMMENDATION: No article text found in embedded JSON.")
        print("  The article content is likely loaded via XHR/fetch at runtime,")
        print("  which means Playwright (full browser) is needed for extraction.")

    # Also save all extracted JSON paths for easy reference
    report_path = f"{OUTPUT_DIR}/extracted_json_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"JSON Extraction Report for {html_path}\n")
        f.write(f"{'=' * 60}\n\n")
        for e in extracted:
            f.write(f"[{e['var']}] -> {e['file']} ({e['size_kb']:.1f} KB)\n")
            for path, preview in e["interesting"]:
                f.write(f"  .{path}: {preview}\n")
            f.write("\n")
        if article_found:
            f.write(f"\nRECOMMENDATION: article data in `{article_found['var']}`\n")
            for p in article_found["paths"]:
                f.write(f"  -> {p}\n")
    print(f"\nFull report saved to: {report_path}")


if __name__ == "__main__":
    main()