"""Render the first chapter of an EPUB as one self-contained, script-free HTML document."""
from __future__ import annotations

import base64
import posixpath
import re
import zipfile
from html import escape
from xml.etree import ElementTree as ET

MAX_XML = 8 * 1024 * 1024
MAX_IMAGE = 2 * 1024 * 1024
MAX_IMAGES_TOTAL = 6 * 1024 * 1024
MAX_ELEMENTS = 400  # top-level blocks kept from the chapter
MIN_TEXT = 200

CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
SAFE_URL = re.compile(r"^(https?:|mailto:|#)", re.I)
IMG_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
             "webp": "image/webp", "svg": "image/svg+xml"}


def _read(z: zipfile.ZipFile, name: str, limit: int = MAX_XML) -> bytes | None:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > limit:
        return None
    with z.open(info) as f:
        data = f.read(limit + 1)
    return data if len(data) <= limit else None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        el.tag = _local(el.tag)
        for k in list(el.attrib):
            lk = _local(k) if k.startswith("{") else k
            if lk != k:
                el.attrib[lk] = el.attrib.pop(k)


def _spine(z: zipfile.ZipFile) -> list[str]:
    container = _read(z, "META-INF/container.xml")
    if container is None:
        return []
    root = ET.fromstring(container)
    opf_path = next((e.get("full-path") for e in root.iter() if _local(e.tag) == "rootfile"), None)
    opf = _read(z, opf_path) if opf_path else None
    if opf is None:
        return []
    pkg = ET.fromstring(opf)
    _strip_ns(pkg)
    base = posixpath.dirname(opf_path)
    manifest = {i.get("id"): i for i in pkg.iter("item")}
    out = []
    for ref in pkg.iter("itemref"):
        item = manifest.get(ref.get("idref"))
        if item is None or "nav" in (item.get("properties") or "").split():
            continue
        if item.get("media-type") == "application/xhtml+xml":
            out.append(posixpath.normpath(posixpath.join(base, item.get("href", ""))))
    return out


def render_preview(epub_path) -> str | None:
    """Return a sandbox-safe HTML document for the first substantial chapter, or None."""
    with zipfile.ZipFile(epub_path) as z:
        chapters = _spine(z)
        chosen = None
        for name in chapters:
            data = _read(z, name)
            if data is None:
                continue
            try:
                root = ET.fromstring(data)
            except ET.ParseError:
                continue
            _strip_ns(root)
            text = "".join(root.itertext())
            if chosen is None:
                chosen = (name, root)
            if len(text.strip()) >= MIN_TEXT:
                chosen = (name, root)
                break
        if chosen is None:
            return None
        name, root = chosen
        base = posixpath.dirname(name)
        body = root.find("body")
        if body is None:
            return None
        head = root.find("head")
        css = []
        if head is not None:
            for link in head.iter("link"):
                href = link.get("href")
                if href and "stylesheet" in (link.get("rel") or ""):
                    data = _read(z, posixpath.normpath(posixpath.join(base, href)), 512 * 1024)
                    if data:
                        css.append(data.decode("utf-8", "replace").replace("</", "<\\/"))
        budget = [MAX_IMAGES_TOTAL]
        for el in list(body.iter()):
            for attr in list(el.attrib):
                if attr.lower().startswith("on") or attr in ("style", "srcset"):
                    del el.attrib[attr]
            if el.tag == "a":
                href = el.get("href", "")
                if SAFE_URL.match(href):
                    if not href.startswith("#"):
                        el.set("target", "_blank")
                        el.set("rel", "noopener noreferrer")
                else:
                    el.attrib.pop("href", None)
        for parent in list(body.iter()):
            for child in list(parent):
                if child.tag in ("script", "iframe", "object", "embed", "form", "link", "style", "audio", "video"):
                    parent.remove(child)
                elif child.tag in ("img", "image"):
                    _inline_image(z, child, base, budget)
        kids = list(body)
        for extra in kids[MAX_ELEMENTS:]:
            body.remove(extra)
        parts = []
        for k in body:
            parts.append(ET.tostring(k, encoding="unicode", method="html"))
        title = escape("".join(root.find("head/title").itertext()) if root.find("head/title") is not None else "")
    style = "\n".join(css)
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<meta http-equiv=\"Content-Security-Policy\" content=\"{CSP}\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{title}</title><style>{style}</style>"
        "<style>:root{color-scheme:light}html{background:#fff}body{color:#111;background:#fff;font:1.05em/1.6 Georgia,serif;margin:1em auto;max-width:42em;padding:0 1em}"
        "img{max-width:100%;height:auto}</style></head><body>" + "".join(parts) + "</body></html>"
    )


def _inline_image(z: zipfile.ZipFile, el: ET.Element, base: str, budget: list[int]) -> None:
    src = el.get("src") or el.get("href")
    if not src or src.startswith("data:"):
        return
    path = posixpath.normpath(posixpath.join(base, src.split("#")[0]))
    ext = path.rsplit(".", 1)[-1].lower()
    data = _read(z, path, MAX_IMAGE) if ext in IMG_TYPES and ext != "svg" else None
    el.attrib.pop("href", None)
    if data is None or len(data) > budget[0]:
        el.set("src", "data:,")
        return
    budget[0] -= len(data)
    el.tag = "img"
    el.set("src", f"data:{IMG_TYPES[ext]};base64,{base64.b64encode(data).decode()}")
