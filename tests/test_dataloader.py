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


@pytest.mark.parametrize("markitdown_result", ["", "raise"])
def test_uploaded_pdf_falls_back_to_rapidocr(tmp_path, monkeypatch, markitdown_result):
    import sys
    from types import SimpleNamespace
    import dataloader

    pdf = tmp_path / "scanned.pdf"
    pdf.write_bytes(b"fake pdf")

    class FakeConverter:
        def convert(self, _path):
            if markitdown_result == "raise":
                raise ValueError("No text layer")
            return SimpleNamespace(markdown="  ")

    class FakeBitmap:
        def to_numpy(self):
            return object()

    class FakePage:
        def render(self, scale):
            assert scale == 2
            return FakeBitmap()

        def close(self):
            pass

    class FakePdfDocument:
        def __init__(self, path):
            assert path == str(pdf)

        def __len__(self):
            return 2

        def __getitem__(self, _index):
            return FakePage()

        def close(self):
            pass

    class FakeOCR:
        def __call__(self, _image):
            return SimpleNamespace(txts=("recognized text",))

    monkeypatch.setitem(
        sys.modules, "markitdown", SimpleNamespace(MarkItDown=FakeConverter)
    )
    monkeypatch.setitem(
        sys.modules,
        "pypdfium2",
        SimpleNamespace(PdfDocument=FakePdfDocument),
    )
    dataloader._get_ocr_engine.cache_clear()
    monkeypatch.setattr(dataloader, "_get_ocr_engine", FakeOCR)

    profile = convert_uploaded_documents([str(pdf)])

    assert profile.count("recognized text") == 2


def test_uploaded_unsupported_file_type_is_rejected(tmp_path):
    unsupported = tmp_path / "profile.exe"
    unsupported.write_text("not a document", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported file type"):
        convert_uploaded_documents([str(unsupported)])
