"""Script CLI para migração segura de lançamentos legados de receita e despesa_fixa.

Uso:
  python scripts/migrate_legacy_fixed.py [--dry-run]
  python scripts/migrate_legacy_fixed.py --apply --decisions decisions.json
"""
import os
import sys
import json
import argparse
from datetime import date
from decimal import Decimal
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

def get_engine():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERRO: DATABASE_URL não definida.", file=sys.stderr)
        sys.exit(1)
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(db_url)

def main():
    parser = argparse.ArgumentParser(description="Migração de receitas e despesas fixas legadas para Recurrence.")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Executa sem gravar alterações e gera decisões de exemplo.")
    parser.add_argument("--apply", action="store_true", default=False, help="Aplica as decisões contidas no arquivo JSON.")
    parser.add_argument("--decisions", type=str, default="decisions.json", help="Caminho do arquivo de decisões JSON.")
    args = parser.parse_args()

    engine = get_engine()
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        # Busca todas as transações legadas de receita e despesa_fixa que ainda não possuem recurrence_id
        rows = db.execute(text("""
            SELECT id, tipo, valor, data, descricao, category_id, author
            FROM transactions
            WHERE tipo IN ('receita', 'despesa_fixa')
              AND recurrence_id IS NULL
            ORDER BY tipo, data, id
        """)).fetchall()

        if not rows:
            print("Nenhuma transação legada de receita/despesa_fixa pendente de migração.")
            return

        print(f"\nForam encontradas {len(rows)} transações legadas sem regra de recorrência:\n")
        print(f"{'ID':<6} | {'Tipo':<14} | {'Data':<12} | {'Valor (R$)':<12} | {'Descrição'}")
        print("-" * 75)

        propostas = {}
        for r in rows:
            tid, tipo, val, dt, desc, cat_id, author = r[0], r[1], float(r[2]), str(r[3]), r[4], r[5], r[6]
            print(f"{tid:<6} | {tipo:<14} | {dt:<12} | {val:<12.2f} | {desc or '-'}")
            # Proposta inteligente padrão:
            # - despesa_fixa -> 'recorrente'
            # - receita com nome de pessoa ou salário -> 'recorrente'
            proposta = "recorrente"
            propostas[str(tid)] = proposta

        # Modo 1: Dry-Run (ou sem --apply)
        if not args.apply:
            print("\n[MODO DRY-RUN] Nenhuma alteração foi realizada no banco de dados.")
            print(f"Gerando arquivo de exemplo '{args.decisions}' com propostas...")
            with open(args.decisions, "w", encoding="utf-8") as f:
                json.dump(propostas, f, indent=2, ensure_ascii=False)
            print(f"Arquivo '{args.decisions}' gerado. Revise as decisões e rode:")
            print(f"  python scripts/migrate_legacy_fixed.py --apply --decisions {args.decisions}\n")
            return

        # Modo 2: Apply
        if not os.path.exists(args.decisions):
            print(f"ERRO: Arquivo de decisões '{args.decisions}' não encontrado.", file=sys.stderr)
            sys.exit(1)

        with open(args.decisions, "r", encoding="utf-8") as f:
            decisions = json.load(f)

        # Validação estrita: todo ID legado existente precisa de decisão ("recorrente" ou "avulsa")
        missing_ids = []
        invalid_decisions = []
        for r in rows:
            tid_str = str(r[0])
            if tid_str not in decisions:
                missing_ids.append(tid_str)
            elif decisions[tid_str] not in ["recorrente", "avulsa"]:
                invalid_decisions.append((tid_str, decisions[tid_str]))

        if missing_ids or invalid_decisions:
            if missing_ids:
                print(f"ERRO DE VALIDAÇÃO: IDs legados sem decisão informada: {missing_ids}", file=sys.stderr)
            if invalid_decisions:
                print(f"ERRO DE VALIDAÇÃO: Decisões inválidas (deve ser 'recorrente' ou 'avulsa'): {invalid_decisions}", file=sys.stderr)
            print("Operação abortada sem nenhuma alteração no banco de dados.", file=sys.stderr)
            sys.exit(1)

        # Execução das decisões
        migrados_recorrente = 0
        mantidos_avulsa = 0

        for r in rows:
            tid, tipo, val, dt, desc, cat_id, author = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
            tid_str = str(tid)
            decisao = decisions[tid_str]

            if isinstance(dt, str):
                dt_obj = date.fromisoformat(dt)
            else:
                dt_obj = dt

            if decisao == "recorrente":
                primeiro_dia_mes = dt_obj.replace(day=1)
                dia_do_mes = dt_obj.day

                # Cria a regra Recurrence
                rec_res = db.execute(text("""
                    INSERT INTO recurrences (tipo, descricao, valor, category_id, author, dia_do_mes, inicio, fim, ativo)
                    VALUES (:tipo, :desc, :val, :cat_id, :author, :dia, :inicio, NULL, TRUE)
                    RETURNING id
                """), {
                    "tipo": tipo,
                    "desc": desc or f"{tipo.title()} Recorrente",
                    "val": val,
                    "cat_id": cat_id,
                    "author": author,
                    "dia": dia_do_mes,
                    "inicio": primeiro_dia_mes
                }).fetchone()
                
                new_rec_id = rec_res[0]

                # Vincula a transação existente como a instância daquela competência
                db.execute(text("""
                    UPDATE transactions
                    SET recurrence_id = :rec_id, competencia = :comp, editado_manual = FALSE
                    WHERE id = :tid
                """), {
                    "rec_id": new_rec_id,
                    "comp": primeiro_dia_mes,
                    "tid": tid
                })
                migrados_recorrente += 1
            else:
                # 'avulsa': mantém a linha intacta; ela agora vale exclusivamente no seu próprio mês
                mantidos_avulsa += 1

        db.commit()
        print(f"\n[SUCESSO] Migração concluída com sucesso!")
        print(f"  • {migrados_recorrente} registros transformados em regras Recurrence + instâncias.")
        print(f"  • {mantidos_avulsa} registros mantidos como lançamentos avulsos.\n")

    except Exception as e:
        db.rollback()
        print(f"ERRO durante a migração: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
