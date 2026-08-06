from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from dataloader import ProfileLoader
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

profile_loader = ProfileLoader(data_dir="data")
# Load and format the Markdown content from the .md files
profile_data = profile_loader.load_and_format_markdown("data")

# 1. Define the system and user instructions
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an assistant that answers questions accurately based ONLY on the provided context."),
    ("user", "Context:\n<context>\n{context_text}\n</context>\n\nQuestion: {user_query}")
])

# 2. Format the prompt with your full Markdown string
llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0, max_tokens=2048)
chain = prompt | llm

response = chain.invoke({
    "context_text": profile_data,
    "user_query": "What are the strongest and weakest skills of the candidate based on the provided context?"
})

print(response)