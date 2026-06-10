from dotenv import load_dotenv
load_dotenv()

from langchain_openai import ChatOpenAI
from pydantic import BaseModel
import os

print(f"API Key gesetzt: {'ja' if os.getenv('OPENAI_API_KEY') else 'nein'}")
print(f"API Base: {os.getenv('OPENAI_API_BASE', 'nicht gesetzt')}\n")

llm = ChatOpenAI(model="qwen/qwen3.5-397b-a17b", temperature=0)

print("Test 1: Normaler Call...")
try:
    result = llm.invoke("Sage Hallo")
    print(f"✅ {result.content[:100]}\n")
except Exception as e:
    print(f"❌ {e}\n")

print("Test 2: Structured Output...")
class SimpleTask(BaseModel):
    title: str
    description: str

try:
    chain = llm.with_structured_output(SimpleTask)
    result = chain.invoke("Erstelle einen Task: Login migrieren")
    print(f"✅ {result.title}\n")
except Exception as e:
    print(f"❌ {e}\n")

print("Test 3: JSON Mode...")
try:
    llm_json = llm.bind(response_format={"type": "json_object"})
    result = llm_json.invoke('Gib JSON: {"title": "test", "description": "test"}')
    print(f"✅ {result.content[:200]}\n")
except Exception as e:
    print(f"❌ {e}\n")
