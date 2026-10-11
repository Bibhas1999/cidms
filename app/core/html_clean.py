"""Report text comes from a rich-text editor as HTML. Before it's saved it is cleaned down to a small set of
harmless tags (paragraphs, headings, bold/italic/underline, lists, simple tables) with no attributes beyond
a table cell's span, so a report can never carry a script, a link elsewhere, an image or a style that hides text."""

import html as html_lib
import re

import nh3

TAGS = {"p", "br", "strong", "b", "em", "i", "u", "s", "h2", "h3", "h4", "ul", "ol", "li", "blockquote",
        "table", "thead", "tbody", "tr", "th", "td", "hr", "sub", "sup"}
ATTRIBUTES = {"td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"}}
MAX_HTML = 200_000

_EMPTY = re.compile(r"^(\s|<p>\s*(<br\s*/?>)?\s*</p>|<br\s*/?>)*$", re.I)


def clean_html(html: str | None) -> str:
    if not html:
        return ""
    out = nh3.clean(html[:MAX_HTML], tags=TAGS, attributes=ATTRIBUTES, url_schemes=set(), link_rel=None,
                    strip_comments=True, clean_content_tags={"script", "style"}).strip()
    return "" if _EMPTY.match(out) else out


def plain_text(html: str) -> str:
    """The words alone (for search and short previews)."""
    return re.sub(r"\s+", " ", html_lib.unescape(nh3.clean(html or "", tags=set()))).strip()
