"""Offline PDF reference indexing and retrieval for the assistant (not live data)."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from functools import lru_cache
import json
import logging
import math
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from uuid import UUID

log = logging.getLogger(__name__)
INDEX_NAME = "reference-index.json"
MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_PAGES = 2400
MAX_PDF_BYTES = 40 * 1024 * 1024
MAX_PASSAGE_CHARS = 850
STOP_WORDS = frozenset(
    "about any are can could does explain for from give has have how into its may more not please "
    "related report should show some than that the their them then there these they this those use "
    "used using was were what when where which who why will with would you your".split()
)


@dataclass(frozen=True)
class Passage:
    file: str
    page: int
    text: str

    @property
    def citation(self) -> str:
        return f"{self.file} · PDF p. {self.page}"


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[^\W\d_]{2,}", text.casefold())) - STOP_WORDS


def _chunks(text: str):
    text = " ".join(text.split())[:16_000]
    while len(text) > MAX_PASSAGE_CHARS:
        cut = text.rfind(" ", 0, MAX_PASSAGE_CHARS + 1)
        if cut < MAX_PASSAGE_CHARS // 2:
            cut = MAX_PASSAGE_CHARS
        yield text[:cut]
        # Retain a little context on the other side of the split.
        overlap = text.find(" ", cut - 120, cut)
        text = text[overlap + 1 if overlap != -1 else cut:].lstrip()
    if text:
        yield text


def _workspace_dir(root: Path, workspace_id: str) -> Path:
    return root / str(UUID(workspace_id))


def build_index(source: Path, destination: Path) -> None:
    """Operator-only batch operation; the API never parses PDFs on request."""
    from pypdf import PdfReader

    if not source.is_dir():
        raise ValueError(f"Not a PDF directory: {source}")
    files = sorted(path for path in source.iterdir() if path.is_file() and path.suffix.lower() == ".pdf")
    if not files:
        raise ValueError("No PDFs found. To clear a library, remove the published index file.")
    pages_read = 0
    passages: list[Passage] = []
    for pdf in files:
        if pdf.stat().st_size > MAX_PDF_BYTES:
            raise ValueError(f"{pdf.name}: exceeds the {MAX_PDF_BYTES // (1024 * 1024)} MiB PDF limit")
        with pdf.open("rb") as handle:
            reader = PdfReader(handle)
            if reader.is_encrypted:
                raise ValueError(f"{pdf.name}: encrypted PDFs are not supported")
            pages_read += len(reader.pages)
            if pages_read > MAX_PAGES:
                raise ValueError(f"Reference library exceeds {MAX_PAGES} PDF pages")
            scanned = sum(1 for page, obj in enumerate(reader.pages, start=1)
                          if not _index_page(passages, pdf.name, page, obj.extract_text() or ""))
            print(f"{pdf.name}: {len(reader.pages) - scanned} text page(s), {scanned} blank/image page(s) skipped")
    if not passages:
        raise ValueError("No searchable text found. OCR image-only PDFs before indexing.")
    raw = json.dumps({"version": 1, "passages": [asdict(p) for p in passages]}, ensure_ascii=False).encode()
    if len(raw) > MAX_INDEX_BYTES:
        raise ValueError("Reference index exceeds 8 MiB; use a smaller set of documents")
    destination.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination, delete=False) as temporary:
        tmp_path = Path(temporary.name)
        try:
            temporary.write(raw)
            temporary.close()
            # Only this derived artifact is mounted into the API container.
            tmp_path.chmod(0o644)
            tmp_path.replace(destination / INDEX_NAME)
        finally:
            tmp_path.unlink(missing_ok=True)
    print(f"Published {len(passages)} passages from {pages_read} page(s) to {destination / INDEX_NAME}")


def _index_page(passages: list[Passage], file: str, page: int, text: str) -> bool:
    chunks = [chunk for chunk in _chunks(text) if _tokens(chunk)]
    passages.extend(Passage(file, page, chunk) for chunk in chunks)
    return bool(chunks)


@lru_cache(maxsize=2)
def _load(path: Path, stamp: tuple[int, int, int]) -> tuple[tuple[tuple[Passage, frozenset[str]], ...], Counter[str]]:
    # stamp is part of the cache key; atomic replacements invalidate it.
    with path.open("rb") as handle:
        raw = handle.read(MAX_INDEX_BYTES + 1)
    if len(raw) > MAX_INDEX_BYTES:
        raise ValueError("Reference index too large")
    data = json.loads(raw)
    if data["version"] != 1:
        raise ValueError("Unsupported reference index version")
    rows = tuple((p, frozenset(_tokens(p.text))) for p in (Passage(**row) for row in data["passages"]))
    return rows, Counter(word for _, words in rows for word in words)


def retrieve(root: str, workspace_id: str, question: str) -> list[Passage]:
    query = _tokens(question)
    if not root or not query:
        return []
    try:
        directory = _workspace_dir(Path(root), workspace_id)
        path = directory / INDEX_NAME
        if directory.is_symlink() or path.is_symlink():
            return []
        info = path.stat()
        rows, frequencies = _load(path, (info.st_ino, info.st_mtime_ns, info.st_size))
    except FileNotFoundError:
        return []
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        log.warning("Could not read assistant reference index for workspace %s", workspace_id)
        return []

    ranked = []
    for i, (passage, words) in enumerate(rows):
        matches = words & query
        if len(matches) < min(len(query), 2):
            continue
        score = sum(math.log1p(len(rows) / frequencies[word]) for word in matches)
        ranked.append((score, i, passage))
    matches = []
    seen_pages = set()
    for _, _, passage in sorted(ranked, key=lambda item: (-item[0], item[1])):
        page = (passage.file, passage.page)
        if page not in seen_pages:
            seen_pages.add(page)
            matches.append(passage)
            if len(matches) == 2:
                break
    return matches


def prompt_context(passages: list[Passage]) -> str:
    if not passages:
        return ""
    return "\nSUPPLEMENTAL PDF REFERENCE (not live records or application policy):\n" + "\n".join(
        f"[{p.citation}] {p.text}" for p in passages
    )


def verified_context(answer) -> str:
    """Keep exact answer facts ahead of ancillary context for small models."""
    if answer.confidence == "low" and not (answer.facts or answer.tables):
        return ""
    lines = [f"VERIFIED ANSWER BASELINE: {answer.answer[:1200]}"]
    lines.extend(f"- {fact.label}: {fact.value}" for fact in answer.facts[:8])
    if answer.steps:
        lines.append("STEPS: " + " | ".join(answer.steps[:4])[:700])
    return "\n".join(lines) + "\n"


def main() -> None:
    from pypdf.errors import PdfReadError

    parser = argparse.ArgumentParser(description="Build a workspace PDF reference index for WellCostIQ")
    parser.add_argument("--workspace-id", required=True, help="Organization UUID (not a slug)")
    parser.add_argument("--pdf-dir", required=True, type=Path, help="Directory of approved text PDFs")
    parser.add_argument("--output-root", required=True, type=Path, help="API reference library directory")
    args = parser.parse_args()
    try:
        build_index(args.pdf_dir, _workspace_dir(args.output_root, args.workspace_id))
    except (OSError, ValueError, PdfReadError) as exc:
        parser.exit(1, f"Index not published: {exc}\n")


if __name__ == "__main__":
    main()
