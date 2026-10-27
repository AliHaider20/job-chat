from pathlib import Path

SEPARATOR = "\n\n" + "-" * 60 + "\n\n"
SUPPORTED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".md", ".txt"}


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
        else:
            if converter is None:
                from markitdown import MarkItDown

                converter = MarkItDown()
            content = converter.convert(str(path)).markdown
        documents.append((path.name, content))

    return format_documents(documents)
