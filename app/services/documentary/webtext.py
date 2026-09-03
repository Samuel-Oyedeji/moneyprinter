"""Minimal HTML-to-text extraction using only the standard library.

The research step fetches news articles and Wikipedia pages. A full-blown
readability dependency isn't warranted yet: stripping non-content elements and
collapsing block text gets us clean-enough input for LLM fact extraction.
"""

from html import unescape
from html.parser import HTMLParser

_SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "svg",
    "iframe",
    "button",
}
_BLOCK_TAGS = {
    "p",
    "div",
    "section",
    "article",
    "li",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "tr",
    "blockquote",
}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        # Drop empty lines and menu-like fragments; keep sentence-bearing text.
        kept = [line for line in lines if len(line) > 2]
        return "\n".join(kept)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(unescape(html) if "&lt;" in html[:200] else html)
        parser.close()
    except Exception:
        # A malformed page shouldn't kill the whole research run; return what
        # was collected before the parser choked.
        pass
    return parser.text()
