import os
import sys
from google import genai

# 1. Obter API Key a partir de variável de ambiente
API_KEY = os.environ.get("GEMINI_API_KEY", "")

if not API_KEY or API_KEY == "SUA_API_KEY_AQUI":
    print("❌ Erro: Defina a variável de ambiente GEMINI_API_KEY ou configure-a no arquivo builder.py!")
    sys.exit(1)

client = genai.Client(api_key=API_KEY)

# Lista dos arquivos do projeto que a IA precisa ler e atualizar
FILES_TO_PROCESS = [
    "backend/schemas.py",
    "backend/routes.py",
    "backend/webhook.py",
    "backend/parser.py",
    "index.html"
]

def get_project_context():
    context = "Estrutura e arquivos atuais do projeto:\n\n"
    for filepath in FILES_TO_PROCESS:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                context += f"--- INÍCIO DE {filepath} ---\n{f.read()}\n--- FIM DE {filepath} ---\n\n"
        else:
            context += f"--- {filepath} (arquivo ainda não existe) ---\n\n"
    return context

prompt_master = f"""
Você é o Agente Builder Fullstack Python/FastAPI.
Receba o contexto dos arquivos do projeto `Finanças` abaixo e atualize/gere o código de cada um deles seguindo os requisitos.

Requisitos:
1. Atualize `backend/schemas.py` e `backend/routes.py` para incluir suporte a CRUD de transações (tipo: receita/despesa, valor, categoria, data, descrição) e endpoint de resumo mensal (entradas, saídas, saldo).
2. Refatore `backend/webhook.py` e `backend/parser.py` para receber payloads JSON e cadastrar a transação no SQLite (`fintrack.db`).
3. Atualize `index.html` com cartões de Resumo (Entradas, Saídas, Saldo), formulário de cadastro via fetch API, e tabela de lançamentos com opção de exclusão (usando JS puro e CSS embutido).

IMPORTANTE NA RESPOSTA:
Para cada arquivo alterado, formate a resposta EXATAMENTE com a marcação abaixo para que o script salve automaticamente:

<<<FILE: caminho/do/arquivo.ext>>>
conteúdo do arquivo aqui
<<<END_FILE>>>

{get_project_context()}
"""

print("🚀 Executando o Agente Builder via Gemini API...")

response = client.models.generate_content(
    model="gemini-3.8-flash",
    contents=prompt_master,
)

content = response.text

# Processa e salva os arquivos automaticamente na máquina
import re
pattern = r"<<<FILE:\s*(.*?)>>>\n(.*?)<<<END_FILE>>>"
matches = re.findall(pattern, content, re.DOTALL)

if not matches:
    print("⚠️ Resposta gerada, mas o formato de arquivos não foi identificado automaticamente. Exibindo resposta:\n")
    print(content)
else:
    for filepath, file_code in matches:
        filepath = filepath.strip()
        os.makedirs(os.path.dirname(filepath), exist_ok=True) if os.path.dirname(filepath) else None
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(file_code.strip())
        print(f"✅ Arquivo atualizado com sucesso: {filepath}")

print("\n🎉 Todas as alterações foram aplicadas ao projeto!")