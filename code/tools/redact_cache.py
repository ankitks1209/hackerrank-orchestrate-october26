"""Redact the stored media-extraction replies of the response cache at rest (DECISIONS D25).

A media entry holds what the vision model transcribed from a dataset image or PDF: emails,
phones and names. This tool rewrites each such entry so that

* every email is replaced by `sha256:` + sha256(lower-cased email);
* every phone is replaced by `sha256:` + sha256(digits of the phone);
* names are removed (names are never matching keys);
* the top-level field `redacted_at_rest` says so, and the original model text is not kept.

`evidence.media` matches the digests against the identity's hash keys, so the redaction does
not change a single output row. Other entries (the intent verdicts) are left alone; the tool
only reports how many of them contain an email address. The tool is idempotent.

    python3 -m tools.redact_cache                 redact the entries in place and print the counts
    python3 -m tools.redact_cache --check         change nothing; exit 1 if an entry is not redacted

Exit codes: 0 done or clean; 1 a check found an unredacted entry; 2 unusable input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ghostaudit.config import REPO_ROOT
from ghostaudit.llm.cache import REDACTED_FIELD
from ghostaudit.llm.media_extract import REDACTION_NOTE, redact_reply

EXIT_OK = 0
EXIT_UNREDACTED = 1
EXIT_INPUT = 2
CACHE_DIR = REPO_ROOT / "code" / "ghostaudit" / "cache"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IDENTIFIER_FIELDS = ("emails", "phones", "names")


def is_media_entry(entry: Dict[str, Any]) -> bool:
    """True when the entry's text is a JSON object with a `records` list (a media extraction)."""
    try:
        payload = json.loads(entry["text"])
    except (KeyError, TypeError, ValueError):
        return False
    return isinstance(payload, dict) and isinstance(payload.get("records"), list)


def count_identifiers(text: str) -> Counter:
    """Emails, phones and names listed by the records of a media reply."""
    counts: Counter = Counter()
    for record in json.loads(text)["records"]:
        for name in IDENTIFIER_FIELDS:
            counts[name] += len(record.get(name) or [])
    return counts


def redact_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The redacted copy of a media entry, or None when it is already redacted."""
    if entry.get(REDACTED_FIELD):
        return None
    redacted = dict(entry, text=redact_reply(entry["text"]))
    redacted[REDACTED_FIELD] = REDACTION_NOTE
    return redacted


def write_entry(path: Path, entry: Dict[str, Any]) -> None:
    """Same layout as `DiskCache.put`: sorted keys, two-space indent, trailing newline."""
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(entry, stream, sort_keys=True, indent=2, ensure_ascii=False)
        stream.write("\n")


def run(cache_dir: Path, check: bool) -> int:
    paths = sorted(cache_dir.glob("*.json"))
    if not paths:
        sys.stderr.write("no cache entries in %s\n" % cache_dir)
        return EXIT_INPUT
    totals: Counter = Counter()
    unredacted: List[str] = []
    other_with_email = 0
    for path in paths:
        entry = json.loads(path.read_text(encoding="utf-8"))
        if not is_media_entry(entry):
            other_with_email += bool(EMAIL.search(json.dumps(entry)))
            continue
        totals["media entries"] += 1
        redacted = redact_entry(entry)
        if redacted is None:
            totals["already redacted"] += 1
        else:
            unredacted.append(path.name)
            if not check:
                totals["entries redacted"] += 1
                totals.update(count_identifiers(entry["text"]))
                write_entry(path, redacted)
                entry = redacted
        totals["media entries with an email-looking string"] += bool(EMAIL.search(json.dumps(entry)))
    labels = ("media entries", "already redacted", "entries redacted", "emails", "phones", "names",
              "media entries with an email-looking string")
    for label in labels:
        sys.stdout.write("%s: %d\n" % (label, totals[label]))
    sys.stdout.write("other entries with an email-looking string (left unchanged): %d\n" % other_with_email)
    if check and unredacted:
        sys.stderr.write("not redacted: %s\n" % ", ".join(unredacted))
        return EXIT_UNREDACTED
    return EXIT_UNREDACTED if totals[labels[-1]] else EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR, help="response cache (default: code/ghostaudit/cache)")
    parser.add_argument("--check", action="store_true", help="change nothing; exit 1 if an entry is not redacted")
    args = parser.parse_args(argv)
    return run(args.cache_dir, args.check)


if __name__ == "__main__":
    sys.exit(main())
