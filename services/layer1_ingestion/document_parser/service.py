"""
Document parser — Layer 1

Reads:  raw HTML/PDF path from staging.documents
Writes: cleaned plain text (returned to caller; not stored separately in v1)

Does NOT chunk or call LLM.
"""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from shared.repositories import get_document


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def parse_document(doc_id: str) -> str:
    doc = get_document(doc_id)
    if not doc:
        raise ValueError(f"Document not found: {doc_id}")

    raw_path = Path(doc["raw_path"])
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw file missing: {raw_path}")

    content = raw_path.read_text(encoding="utf-8", errors="replace")
    if doc["raw_format"] == "html" or raw_path.suffix.lower() in {".htm", ".html"}:
        return html_to_text(content)
    return content
