import os
from dotenv import load_dotenv
load_dotenv()
print(f"Token: {os.getenv('TELEGRAM_TOKEN')[:10]}...")
print(f"Groq Key: {os.getenv('GROQ_API_KEY')[:10]}...")
