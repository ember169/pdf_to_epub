"""Intermediate representation shared by the extraction, layout and EPUB stages."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 in page space (top-left origin)


# ---------------------------------------------------------------------------
# Page-level geometry (output of extract.py / ocr.py)
# ---------------------------------------------------------------------------
@dataclass
class Span:
    text: str
    size: float
    bold: bool = False
    italic: bool = False
    sup: bool = False
    sub: bool = False
    mono: bool = False
    bbox: Rect = (0, 0, 0, 0)
    link: tuple | None = None  # ("url", href) | ("page", page_no, y)
    math: bool = False  # set in a math font (CMMI, CMSY, CMEX, STIX Math, Cambria Math, ...)


@dataclass
class Line:
    spans: list[Span]
    bbox: Rect
    page: int = 0
    kind: str = ""  # "dmath": a one-row display formula kept as text (its own block, joined to the sentence)

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def size(self) -> float:
        """Dominant font size (character-weighted)."""
        acc: dict[float, int] = {}
        for s in self.spans:
            if s.text.strip():
                k = round(s.size, 1)
                acc[k] = acc.get(k, 0) + len(s.text)
        return max(acc, key=acc.get) if acc else 0.0

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def x1(self) -> float:
        return self.bbox[2]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def bold_ratio(self) -> float:
        tot = sum(len(s.text.strip()) for s in self.spans)
        if not tot:
            return 0.0
        return sum(len(s.text.strip()) for s in self.spans if s.bold) / tot

    @property
    def mono_ratio(self) -> float:
        tot = sum(len(s.text.strip()) for s in self.spans)
        if not tot:
            return 0.0
        return sum(len(s.text.strip()) for s in self.spans if s.mono) / tot

    @property
    def is_mono(self) -> bool:
        """Code-like line: (almost) entirely set in a monospaced font."""
        return self.mono_ratio >= 0.8

    @property
    def italic_ratio(self) -> float:
        tot = sum(len(s.text.strip()) for s in self.spans)
        if not tot:
            return 0.0
        return sum(len(s.text.strip()) for s in self.spans if s.italic) / tot


@dataclass
class ImageItem:
    bbox: Rect
    image_id: str  # key into PageData/Document.images
    page: int = 0
    kind: str = "image"  # "image" | "figure" (rasterised vector region) | "scan" | "formula" (display math region)
    xref: int = 0
    alt: str = ""  # formula: linearised text
    label: str = ""  # formula: equation number, kept as text ("(12)")
    lead: str = ""  # formula: a connecting word printed beside it ("or", "and"), emitted before it
    width_em: float = 0.0  # formula: printed width in body-text ems (the image scales with the reader's font size)


@dataclass
class TableItem:
    bbox: Rect
    rows: list[list[str]]
    page: int = 0
    header: bool = False


@dataclass
class PageData:
    number: int  # 1-based
    width: float
    height: float
    lines: list[Line] = field(default_factory=list)
    images: list[ImageItem] = field(default_factory=list)
    tables: list[TableItem] = field(default_factory=list)
    source: str = "native"  # "native" | "ocr"
    ocr_layer: bool = False  # native text that is an invisible OCR layer (Tesseract GlyphLessFont): sizes are noisy
    scanned: bool = False  # the page is a full-page scan image (its text, if any, came from an OCR program)
    ocr_failed: bool = False
    has_graphics: bool = False
    bad_chars: int = 0  # unmapped glyphs (e.g. '(cid:12)') removed by the backend


@dataclass
class ImageAsset:
    data: bytes
    media_type: str  # image/jpeg | image/png
    width: int
    height: int


# ---------------------------------------------------------------------------
# Document-level IR (output of layout.py / structure.py, input of epub.py)
# ---------------------------------------------------------------------------
@dataclass
class Run:
    """Inline text run. `link` is ("url", href) | ("page", page_no, y) | ("anchor", id)."""

    text: str
    bold: bool = False
    italic: bool = False
    sup: bool = False
    sub: bool = False
    mono: bool = False
    link: tuple | None = None
    noteref: str | None = None  # footnote id this run points to
    display: int = 0  # > 0: part of display formula number n (consecutive runs form one centred block)
    image: tuple | None = None  # (image_id, width_em): a formula picture; `text` is its alt text
    eqno: bool = False  # equation number of a display formula
    pagebreak: int = 0  # > 0: an empty marker where PDF page n begins (printed page number in the page list)


@dataclass
class Paragraph:
    runs: list[Run]
    kind: str = "p"  # "p" | "blockquote" | "pre"
    # layout bookkeeping (not emitted)
    page: int = 0
    y0: float = 0.0
    break_before: str | None = None  # None | "column" | "page"
    indented: bool = False
    size: float = 0.0
    id: str | None = None
    y1: float = 0.0  # bottom of the last line (layout bookkeeping)
    last_page: int = 0  # page of the last part when joined across pages (layout bookkeeping)


@dataclass
class Heading:
    level: int
    runs: list[Run]
    page: int = 0
    y0: float = 0.0
    size: float = 0.0
    break_before: str | None = None
    id: str | None = None
    weak: bool = False  # OCR-derived without strong evidence: a section heading, never a chapter split


@dataclass
class ListBlock:
    ordered: bool
    items: list[list[Run]]
    page: int = 0
    y0: float = 0.0
    break_before: str | None = None
    id: str | None = None
    start: int | None = None


@dataclass
class Table:
    rows: list[list[list[Run]]]
    header: bool = False
    page: int = 0
    y0: float = 0.0
    break_before: str | None = None
    id: str | None = None


@dataclass
class Figure:
    image_id: str
    alt: str = ""
    caption: list[Run] | None = None
    page: int = 0
    y0: float = 0.0
    break_before: str | None = None
    id: str | None = None


@dataclass
class Footnote:
    id: str
    runs: list[Run]
    marker: str = ""
    page: int = 0
    orphan: bool = False  # detected note block without a detectable reference in the text


@dataclass
class Endnotes:
    """A chapter's numbered endnotes (rendered as one <section epub:type="endnotes"> with an <ol>)."""
    notes: list[Footnote]
    page: int = 0
    y0: float = 0.0
    break_before: str | None = None
    id: str | None = None


Block = Union[Paragraph, Heading, ListBlock, Table, Figure, Endnotes]


@dataclass
class Chapter:
    title: str
    blocks: list[Block] = field(default_factory=list)
    footnotes: list[Footnote] = field(default_factory=list)
    filename: str = ""
    first_page: int = 0
    # nav children: (title, block id or None)
    sections: list[tuple[int, str, str | None]] = field(default_factory=list)  # (level, title, anchor)
    title_is_heading: bool = False
    nav_level: int = 1  # 2: a chapter inside a part (nested under it in the navigation)


@dataclass
class Document:
    title: str
    author: str
    language: str
    chapters: list[Chapter]
    images: dict[str, ImageAsset] = field(default_factory=dict)
    cover: ImageAsset | None = None
    warnings: list[str] = field(default_factory=list)
    creators: list[tuple[str, str]] = field(default_factory=list)  # (name, MARC relator: "aut", "edt"); else `author`
    publisher: str = ""
    date: str = ""
    isbn: str = ""
    page_labels: dict[int, str] = field(default_factory=dict)  # PDF page -> printed page number (page-list nav)
