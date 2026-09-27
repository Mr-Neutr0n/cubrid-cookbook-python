r"""Recognize a real standalone docs exception, outside Markdown examples.

>>> has_docs_not_needed_reason(None)
False
>>> has_docs_not_needed_reason('Docs: not needed - tests only')
True
>>> has_docs_not_needed_reason('Docs: not needed - <reason>')
False
>>> has_docs_not_needed_reason('> Docs: not needed - tests only')
False
>>> has_docs_not_needed_reason('````text\n```\nDocs: not needed - tests only\n````')
False
>>> has_docs_not_needed_reason('<!--\nDocs: not needed - tests only\n-->')
False
"""

from __future__ import annotations

import re


def has_docs_not_needed_reason(body: str | None) -> bool:
    prefix = "Docs: not needed -"
    fence = None
    comment = quoted = False
    for raw in (body or "").splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        marker = re.match(r"(`{3,}|~{3,})", stripped)
        if fence:
            if marker and marker[0][0] == fence[0] and len(marker[0]) >= fence[1]:
                if not stripped[len(marker[0]) :].strip():
                    fence = None
            continue
        if comment:
            comment = "-->" not in line
            continue
        if marker:
            fence = (marker[0][0], len(marker[0]))
            continue
        if not stripped:
            quoted = False
            continue
        if stripped.startswith(">"):
            quoted = True
            continue
        if "<!--" in line:
            comment = "-->" not in line.rsplit("<!--", 1)[1]
        if not quoted and line.startswith(prefix):
            reason = re.sub(r"<!--.*?(?:-->|$)", "", line[len(prefix) :]).strip()
            if reason and reason != "<reason>":
                return True
    return False
