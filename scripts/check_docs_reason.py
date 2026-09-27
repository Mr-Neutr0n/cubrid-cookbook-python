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
from html import unescape
from html.parser import HTMLParser

_PREFIX = "Docs: not needed -"
_LITERAL_RUN = re.compile(r"`+|\\+")


class _HTMLContext(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.blocked: list[str] = []
        self.lines: dict[int, str] = {}
        self.marker_lines: set[int] = set()
        self.literal_positions: set[tuple[int, int]] = set()
        self.source = source
        self.inline_end = -1
        self.inline_spans: list[tuple[int, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"blockquote", "pre", "code"}:
            self.blocked.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # These non-void containers still need an explicit closing tag in HTML.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self.blocked and self.blocked[-1] == tag:
            self.blocked.pop()

    def handle_data(self, data: str) -> None:
        if not self.blocked:
            line, column = self.getpos()
            for offset, text in enumerate(data.split("\n")):
                number = line + offset
                self.lines[number] = self.lines.get(number, "") + text
                indentation = len(text) - len(text.lstrip(" "))
                origin = column if offset == 0 else 0
                if origin + indentation <= 3 and text.lstrip(" ").startswith(_PREFIX):
                    self.marker_lines.add(number)
                for index, character in enumerate(text):
                    if character in "`\\":
                        self.literal_positions.add((number, origin + index))

    def handle_entityref(self, name: str) -> None:
        self.handle_data(unescape(f"&{name};").replace("\r", " ").replace("\n", " "))

    def handle_charref(self, name: str) -> None:
        self.handle_data(unescape(f"&#{name};").replace("\r", " ").replace("\n", " "))

    def outside_prefix(self, number: int, prefix: str) -> bool:
        self.feed(prefix)
        return not self.blocked and self.lines.get(number) == prefix

    def feed_literals(self, text: str, number: int, column: int, offset: int) -> None:
        cursor = 0
        while cursor < len(text):
            if offset + cursor < self.inline_end:
                end = min(len(text), self.inline_end - offset)
                self.feed(text[cursor:end].replace("<", " ").replace("&", " "))
                cursor = end
                continue
            run = _LITERAL_RUN.search(text, cursor)
            if run is None:
                self.feed(text[cursor:])
                break
            self.feed(text[cursor : run.end()])
            outside = not self.blocked and (number, column + run.start()) in self.literal_positions
            cursor = run.end()
            if not outside:
                continue
            if run[0][0] == "\\":
                if len(run[0]) % 2 and cursor < len(text) and text[cursor] in "<`":
                    self.feed(" " if text[cursor] == "<" else "`")
                    cursor += 1
                continue
            start = offset + cursor
            paragraph = re.search(r"\n[ \t]*\n", self.source[start:])
            limit = start + paragraph.start() if paragraph else len(self.source)
            quote_boundary = re.search(r"\n {0,3}>", self.source[start:limit])
            if quote_boundary:
                limit = start + quote_boundary.start() + 1
            for boundary in re.finditer(r"\n {0,3}(`{3,}|~{3,})([^\n]*)", self.source[start:limit]):
                if boundary[1][0] == "~" or "`" not in boundary[2]:
                    limit = start + boundary.start() + 1
                    break
            closing = next(
                (
                    match
                    for match in re.finditer(r"`+", self.source[start:limit])
                    if len(match[0]) == len(run[0])
                ),
                None,
            )
            if closing is not None:
                self.inline_end = start + closing.end()
                self.inline_spans.append((offset + run.start(), self.inline_end))


def has_docs_not_needed_reason(body: str | None) -> bool:
    prefix = _PREFIX
    raw_lines = (body or "").splitlines()
    html = _HTMLContext("\n".join(raw_lines))
    candidates = []
    fence = None
    quoted = False
    offset = 0
    for number, raw in enumerate(raw_lines, 1):
        origin = offset
        offset += len(raw) + 1
        line = raw.rstrip()
        stripped = line.lstrip()
        marker = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if origin < html.inline_end:
            html.feed_literals(line + "\n", number, 0, origin)
            continue
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1]:
                if not line[marker.end() :].strip():
                    fence = None
            html.feed("\n")
            continue
        if not stripped:
            quoted = False
        if quoted:
            html.feed("\n")
            continue
        indentation = re.match(r"(?: {4,}| {0,3}\t)", line)
        quote = re.match(r" {0,3}>", line)
        if indentation:
            if html.outside_prefix(number, line[: indentation.end()]):
                html.feed("\n")
                continue
            html.feed_literals(
                line[indentation.end() :] + "\n",
                number,
                indentation.end(),
                origin + indentation.end(),
            )
        elif quote:
            if html.outside_prefix(number, line[: quote.end()]):
                quoted = True
                html.feed("\n")
                continue
            html.feed_literals(
                line[quote.end() :] + "\n", number, quote.end(), origin + quote.end()
            )
        elif marker and (marker[1][0] == "~" or "`" not in line[marker.end() :]):
            if html.outside_prefix(number, line[: marker.end()]):
                fence = (marker[1][0], len(marker[1]))
                html.feed("\n")
                continue
            html.feed_literals(
                line[marker.end() :] + "\n", number, marker.end(), origin + marker.end()
            )
        else:
            html.feed_literals(line + "\n", number, 0, origin)
        if re.match(r" {0,3}" + re.escape(prefix), line):
            position = origin + len(line) - len(line.lstrip(" "))
            if not line.lstrip(" ")[len(prefix) :].lstrip().startswith("<reason>"):
                candidates.append((number, position))
    for number, position in candidates:
        line = html.lines.get(number, "").lstrip(" ")
        inside = any(start <= position < end for start, end in html.inline_spans)
        if not inside and number in html.marker_lines and line.startswith(prefix):
            reason = line[len(prefix) :].strip()
            if reason and not reason.startswith("<reason>"):
                return True
    return False
