import os
from google import genai
from google.genai import types

def generate_application_email(
    resume_text: str, 
    projects_text: str, 
    volunteer_text: str, 
    target_company: str, 
    job_title: str, 
    recruiter_name: str = "Hiring Manager"
):
    # 1. Initialize the AI client (ensure GEMINI_API_KEY is in your environment variables)
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    # 2. Load the skill instructions
    # In production, you would read this from your skill.md file
    with open("skill.md", "r") as file:
        skill_instructions = file.read()

    # 3. Construct the user prompt with all inputs
    user_prompt = f"""
    Please write my job application email based on the following information:
    
    TARGET JOB:
    - Company: {target_company}
    - Role: {job_title}
    - Recruiter/Contact: {recruiter_name}
    
    MY BACKGROUND:
    [Resume]
    {resume_text}
    
    [Projects]
    {projects_text}
    
    [Volunteer Experience]
    {volunteer_text}
    """

    # 4. Call the LLM with the skill.md as the system instruction
    print(f"Generating email for {job_title} at {target_company}...\n")
    
    response = client.models.generate_content(
        model='gemini-2.5-pro',
        contents=user_prompt,
        config=types.GenerateContentConfig(
            # The system instruction forces the AI to obey skill.md
            system_instruction=skill_instructions,
            # Lower temperature keeps the AI factual and prevents creative fluff
            temperature=0.3,
        )
    )

    return response.text

# ==========================================
# Example Usage
# ==========================================
if __name__ == "__main__":
    # Mock inputs based on your profile
    my_resume = "AI/ML Engineer with experience in deep learning frameworks. Tech stack: Python, PyTorch, Docker, Kubernetes."
    my_projects = "Co-founder of Cysora: Built autonomous sales AI agents. Optimized PyTorch FSDP memory management for vision models."
    my_volunteer = "Organized local tree-planting initiatives, coordinating 50+ volunteers."
    
    company = "Anthropic"
    role = "Senior Machine Learning Engineer"
    contact = "Sarah (Technical Recruiter)"

    # Run the function
    email_draft = generate_application_email(
        resume_text=my_resume,
        projects_text=my_projects,
        volunteer_text=my_volunteer,
        target_company=company,
        job_title=role,
        recruiter_name=contact
    )
    
    print(email_draft)