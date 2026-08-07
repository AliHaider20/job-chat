from pathlib import Path

SEPARATOR = "\n\n" + "-" * 60 + "\n\n"


class ProfileLoader:
    """Loads the candidate's markdown profile documents into a single context string."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)

    def load_and_format_markdown(self):
        # Sorted so document order — and therefore model output — is reproducible.
        md_files = sorted(self.data_dir.glob("*.md"))
        if not md_files:
            raise FileNotFoundError(f"No .md documents found in {self.data_dir}")

        sections = []
        for md_file in md_files:
            content = md_file.read_text(encoding="utf-8").strip()
            sections.append(f"# Source: {md_file.stem}\n\n{content}")

        return SEPARATOR.join(sections)
