from markitdown import MarkItDown
import os 
from tqdm import tqdm
    
md_converter = MarkItDown()

home_dir = "C:\\Users\\Jasmi\\OneDrive\\Desktop\\job"
file_names = ["Haider_Ali_AI_engineer_resume.pdf", "Projects.pdf", "Volunteer Experiences.pdf"]

for file_name in file_names:
    file_path = os.path.join(home_dir, file_name)
    result = md_converter.convert(file_path)

    with open(os.path.join(home_dir, "job-chat", "data", file_name.replace(".pdf", ".md")), "w", encoding="utf-8") as f:
        f.write(result.markdown)