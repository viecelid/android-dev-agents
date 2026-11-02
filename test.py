# test.py

from langchain_openai import ChatOpenAI
from config.settings import settings

llm = ChatOpenAI(model=settings.default_model, temperature=0)

prompt="Schreibe mir einen kurzen Text zum gestrigen wetter"
print(f"🧪 Teste Model: {settings.default_model}")
print(f"   Base URL: {llm.openai_api_base or 'default'}")
print()

response = llm.invoke(prompt)
print(f"✅ Antwort: {response.content}")
