from docling.document_converter import DocumentConverter
import os 
from tqdm import tqdm

file_paths = os.listdir("data")

for file_path in tqdm(file_paths):
    if file_path.endswith(".pdf"):
        doc_dir = "data"
        converter = DocumentConverter()
        doc = converter.convert(os.path.join(doc_dir, file_path)).document

        with open(os.path.join(doc_dir, file_path.replace(".pdf", ".md")), "w", encoding="utf-8") as f:
            f.write(doc.export_to_markdown())