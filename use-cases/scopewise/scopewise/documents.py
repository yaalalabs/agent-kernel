import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader

MAX_BYTES = 8 * 1024 * 1024
MAX_PAGES = 60
MAX_TEXT = 100_000


def extract_pages(data: bytes, filename: str) -> list[str]:
    if not data or len(data) > MAX_BYTES:
        raise ValueError("File is empty or exceeds the 8 MB limit.")
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("This file is not a valid PDF.")
        try:
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported. Upload an unlocked copy you are permitted to use.")
            if len(reader.pages) > MAX_PAGES:
                raise ValueError("Upload at most 60 pages at a time.")
            pages, size = [], 0
            for page in reader.pages:
                text = page.extract_text() or ""
                size += len(text)
                if size > MAX_TEXT:
                    raise ValueError("Document text exceeds 100,000 characters. Split it into smaller files.")
                pages.append(text.strip())
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("The PDF could not be read. Export a fresh text PDF and try again.") from exc
    elif suffix == ".pptx":
        if not data.startswith(b"PK"):
            raise ValueError("This file is not a valid PowerPoint presentation.")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as deck:
                members = deck.infolist()
                if sum(item.file_size for item in members) > 50 * 1024 * 1024:
                    raise ValueError("The presentation expands beyond the safe processing limit.")
                slides = [item for item in members if item.filename.startswith("ppt/slides/slide") and item.filename.endswith(".xml")]
                slides.sort(key=lambda item: int(Path(item.filename).stem.removeprefix("slide")))
                if len(slides) > MAX_PAGES:
                    raise ValueError("Upload at most 60 slides at a time.")
                pages = []
                for slide in slides:
                    xml = deck.read(slide)
                    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                        raise ValueError("The presentation contains unsupported XML declarations.")
                    root = ElementTree.fromstring(xml)
                    text = "\n".join((node.text or "").strip() for node in root.iter() if node.tag.endswith("}t") and (node.text or "").strip())
                    pages.append(text)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("The PowerPoint file could not be read. Export a fresh PPTX or text PDF and try again.") from exc
    elif suffix in {".txt", ".md"}:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Text files must use UTF-8 encoding.") from exc
        pages = [p.strip() for p in text.split("\f")]
    else:
        raise ValueError("Upload a PDF, PPTX, TXT or Markdown file.")
    if len(pages) > MAX_PAGES or sum(map(len, pages)) > MAX_TEXT:
        raise ValueError("Document exceeds the page or text limit.")
    if not any(len(p.strip()) >= 12 for p in pages):
        raise ValueError("The document is empty or has no readable text. Scanned pages need OCR before upload.")
    return pages


async def extract_isolated(data: bytes, filename: str):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "scopewise.documents",
        filename,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(data), timeout=25)
    except (TimeoutError, asyncio.CancelledError):
        process.kill()
        await process.wait()
        raise ValueError("Document processing timed out. Try a smaller text PDF.") from None
    if process.returncode:
        raise ValueError("Document processing failed safely. Try a smaller text PDF.")
    result = json.loads(stdout)
    if "error" in result:
        raise ValueError(result["error"])
    return result["pages"]


if __name__ == "__main__":
    if sys.platform.startswith("linux"):
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    try:
        print(json.dumps({"pages": extract_pages(sys.stdin.buffer.read(MAX_BYTES + 1), sys.argv[1])}))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
