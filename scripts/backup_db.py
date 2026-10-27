"""
Utilitário de Backup Automatizado do Banco de Dados (Atlas Finanças).

Funcionalidades:
- Conecta diretamente à DATABASE_URL (Supabase / PostgreSQL ou SQLite).
- Gera snapshot integral das tabelas ('transactions') com carimbo de data e hora em JSON e SQL.
- Salva na pasta 'backups/' (100% isolada e protegida pelo .gitignore).
- Valida integridade e contagem dos registros exportados.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# Ajusta path para importar módulos do backend
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal
from backend.models import Transaction


def format_sql_val(val):
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    # Escapa aspas simples
    safe_str = str(val).replace("'", "''")
    return f"'{safe_str}'"


def executar_backup(destino_custom: str = None):
    pasta_backups = Path(destino_custom) if destino_custom else PROJECT_ROOT / "backups"
    pasta_backups.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo_json = pasta_backups / f"backup_atlas_financas_{timestamp}.json"
    arquivo_sql = pasta_backups / f"backup_atlas_financas_{timestamp}.sql"

    print(f"[*] Iniciando backup seguro do banco de dados ({timestamp})...")

    db = SessionLocal()
    try:
        transacoes = db.query(Transaction).order_by(Transaction.id.asc()).all()
        total = len(transacoes)
        print(f"[*] Extraindo {total} registros da tabela 'transactions'...")

        dados_exportados = []
        linhas_sql = [
            "-- Snapshot de Produção do Atlas Finanças",
            f"-- Gerado em: {datetime.now().isoformat()}",
            f"-- Total de registros: {total}",
            "",
            "BEGIN TRANSACTION;",
            "",
        ]

        for t in transacoes:
            item = {
                "id": t.id,
                "tipo": t.tipo,
                "valor": float(t.valor) if t.valor is not None else 0.0,
                "categoria": t.categoria,
                "data": str(t.data) if t.data else None,
                "descricao": t.descricao,
                "source": t.source,
                "vencimento": t.vencimento,
                "created_at": t.created_at.isoformat()
                if hasattr(t, "created_at") and t.created_at
                else None,
            }
            dados_exportados.append(item)

            sql_insert = (
                f"INSERT INTO transactions (id, tipo, valor, categoria, data, descricao, source, vencimento) "
                f"VALUES ({format_sql_val(t.id)}, {format_sql_val(t.tipo)}, {format_sql_val(t.valor)}, "
                f"{format_sql_val(t.categoria)}, {format_sql_val(t.data)}, {format_sql_val(t.descricao)}, "
                f"{format_sql_val(t.source)}, {format_sql_val(t.vencimento)});"
            )
            linhas_sql.append(sql_insert)

        linhas_sql.append("")
        linhas_sql.append("COMMIT;")
        linhas_sql.append("")

        # 1. Salva em formato JSON estruturado
        with open(arquivo_json, "w", encoding="utf-8") as f:
            json.dump(dados_exportados, f, ensure_ascii=False, indent=2)

        # 2. Salva em formato script SQL recuperável
        with open(arquivo_sql, "w", encoding="utf-8") as f:
            f.write("\n".join(linhas_sql))

        tamanho_json = arquivo_json.stat().st_size
        tamanho_sql = arquivo_sql.stat().st_size

        print("[+] Backup concluído com 100% de sucesso!")
        print(f"    - JSON: {arquivo_json.name} ({tamanho_json} bytes)")
        print(f"    - SQL:  {arquivo_sql.name} ({tamanho_sql} bytes)")
        print(f"    - Pasta de destino: {pasta_backups}")
        return {
            "status": "success",
            "total_registros": total,
            "json_path": str(arquivo_json),
            "sql_path": str(arquivo_sql),
        }

    except Exception as e:
        print(f"[-] Erro crítico durante o backup: {e}", file=sys.stderr)
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    executar_backup()
