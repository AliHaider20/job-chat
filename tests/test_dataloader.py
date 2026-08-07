import pytest

from dataloader import ProfileLoader


@pytest.fixture
def docs(tmp_path):
    (tmp_path / "resume.md").write_text("Resume body", encoding="utf-8")
    (tmp_path / "projects.md").write_text("Projects body", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("not markdown", encoding="utf-8")
    return tmp_path


def test_loads_every_markdown_file(docs):
    content = ProfileLoader(docs).load_and_format_markdown()
    assert "Resume body" in content
    assert "Projects body" in content


def test_ignores_non_markdown_files(docs):
    assert "not markdown" not in ProfileLoader(docs).load_and_format_markdown()


def test_documents_are_labelled_with_their_source(docs):
    content = ProfileLoader(docs).load_and_format_markdown()
    assert "# Source: resume" in content
    assert "# Source: projects" in content


def test_order_is_sorted_and_therefore_reproducible(docs):
    """Unsorted glob order made identical questions produce different answers."""
    content = ProfileLoader(docs).load_and_format_markdown()
    assert content.index("# Source: projects") < content.index("# Source: resume")
    assert content == ProfileLoader(docs).load_and_format_markdown()


def test_empty_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="No .md documents"):
        ProfileLoader(tmp_path).load_and_format_markdown()


def test_missing_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ProfileLoader(tmp_path / "absent").load_and_format_markdown()


def test_unicode_survives_the_round_trip(tmp_path):
    (tmp_path / "doc.md").write_text("Café — naïve — 日本語", encoding="utf-8")
    assert "Café — naïve — 日本語" in ProfileLoader(tmp_path).load_and_format_markdown()
