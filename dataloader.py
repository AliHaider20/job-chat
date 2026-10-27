import logging
from functools import lru_cache
from pathlib import Path

SEPARATOR = "\n\n" + "-" * 60 + "\n\n"
SUPPORTED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".md", ".txt"}

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_ocr_engine():
    from rapidocr import RapidOCR

    return RapidOCR()


def _convert_pdf_with_ocr(path):
    """Render a PDF page-by-page and extract text with RapidOCR."""
    import pypdfium2

    ocr = _get_ocr_engine()
    pdf = pypdfium2.PdfDocument(str(path))
    pages = []
    try:
        for page_number in range(len(pdf)):
            page = pdf[page_number]
            try:
                image = page.render(scale=2).to_numpy()
                result = ocr(image)
                if result is not None and result.txts:
                    pages.append("\n".join(text for text in result.txts if text.strip()))
            finally:
                page.close()
    finally:
        pdf.close()
    return "\n\n".join(pages)


def _convert_pdf(path):
    """Prefer MarkItDown and use OCR when extraction fails or returns no text."""
    try:
        from markitdown import MarkItDown

        content = MarkItDown().convert(str(path)).markdown
    except Exception as exc:
        markitdown_error = exc
        logger.warning(
            "MarkItDown failed for PDF %s; trying RapidOCR: %s",
            path.name,
            exc,
        )
    else:
        if content and content.strip():
            return content
        logger.info("MarkItDown returned no text for PDF %s; trying RapidOCR.", path.name)
        markitdown_error = None

    try:
        return _convert_pdf_with_ocr(path)
    except Exception as ocr_exc:
        markitdown_detail = (
            f"MarkItDown failed: {markitdown_error}"
            if markitdown_error
            else "MarkItDown returned no readable text"
        )
        raise RuntimeError(
            f"{markitdown_detail}; RapidOCR could not read PDF "
            f"'{path.name}': {ocr_exc}"
        ) from ocr_exc


def format_documents(documents):
    """Combine named Markdown strings into the profile context."""
    sections = [
        f"# Source: {Path(name).stem}\n\n{content.strip()}"
        for name, content in documents
        if content and content.strip()
    ]
    if not sections:
        raise ValueError("The uploaded documents contain no readable text.")
    return SEPARATOR.join(sections)


def convert_uploaded_documents(files):
    """Convert supported uploaded files to one Markdown profile in memory."""
    documents = []
    converter = None

    for file_path in files or []:
        path = Path(file_path)
        extension = path.suffix.lower()
        if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_UPLOAD_EXTENSIONS))
            raise ValueError(
                f"Unsupported file type '{extension or '(none)'}' for {path.name}. "
                f"Upload files with these extensions: {supported}."
            )

        if extension in {".md", ".txt"}:
            content = path.read_text(encoding="utf-8-sig")
        elif extension == ".pdf":
            content = _convert_pdf(path)
        else:
            if converter is None:
                from markitdown import MarkItDown

                converter = MarkItDown()
            content = converter.convert(str(path)).markdown
        documents.append((path.name, content))

    return format_documents(documents)
