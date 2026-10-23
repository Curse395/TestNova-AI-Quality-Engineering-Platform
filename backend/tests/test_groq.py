import os
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("GROQ_API_KEY")
print("Groq API key loaded:", bool(key))