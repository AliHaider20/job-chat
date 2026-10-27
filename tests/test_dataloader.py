import pytest

from dataloader import convert_uploaded_documents


def test_uploaded_markdown_and_text_are_formatted_without_disk_output(tmp_path):
    markdown = tmp_path / "resume.md"
    text = tmp_path / "projects.txt"
    markdown.write_text("# Resume", encoding="utf-8")
    text.write_text("Project work", encoding="utf-8")

    profile = convert_uploaded_documents([str(markdown), str(text)])

    assert "# Source: resume" in profile
    assert "# Resume" in profile
    assert "# Source: projects" in profile
    assert "Project work" in profile


def test_uploaded_pdf_is_converted_to_markdown(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"fake pdf")

    class FakeConverter:
        def convert(self, path):
            assert path == str(pdf)
            return SimpleNamespace(markdown="# Converted resume")

    monkeypatch.setitem(
        sys.modules, "markitdown", SimpleNamespace(MarkItDown=FakeConverter)
    )

    assert "# Converted resume" in convert_uploaded_documents([str(pdf)])


def test_uploaded_unsupported_file_type_is_rejected(tmp_path):
    unsupported = tmp_path / "profile.exe"
    unsupported.write_text("not a document", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported file type"):
        convert_uploaded_documents([str(unsupported)])
