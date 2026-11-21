"""Métricas de uso e de qualidade da Clara, calculadas a partir do banco de dados.

Uso: python metricas.py   (usa o DATABASE_URL do .env, ou o gastos.db local)
"""
import json
import math
import statistics

from dotenv import load_dotenv
from sqlalchemy import text

import banco

load_dotenv()


def main():
    engine = banco.conectar()
    with engine.connect() as con:
        interacoes = [dict(l) for l in con.execute(text("SELECT * FROM interacoes")).mappings()]
        gastos = con.execute(text("SELECT COUNT(*) FROM gastos")).scalar_one()

    if not interacoes:
        print("Ainda não há interações registradas.")
        return

    contar = lambda tipo: sum(1 for i in interacoes if i["tipo"] == tipo)  # noqa: E731
    interpretadas = [i for i in interacoes if i["tipo"] in ("registrar", "consultar", "outro", "erro")]
    registros = contar("registrar")
    correcoes = contar("desfazer") + contar("corrigir_categoria")
    latencias = sorted(i["latencia_ms"] for i in interacoes if i["latencia_ms"] is not None)
    modelos = {}
    for i in interacoes:
        if i["modelo"]:
            modelos[i["modelo"]] = modelos.get(i["modelo"], 0) + 1
    gastos_por_mensagem = [len(json.loads(i["interpretacao"])["gastos"]) for i in interacoes
                           if i["tipo"] == "registrar" and i["interpretacao"]]

    print("=========== MÉTRICAS DA CLARA ===========")
    print(f"Usuários diferentes:              {len({i['usuario'] for i in interacoes})}")
    print(f"Mensagens enviadas ao LLM:        {len(interpretadas)}")
    print(f"  falhas do serviço de IA:        {contar('erro')} ({contar('erro') / len(interpretadas):.0%})")
    print(f"Mensagens com gasto:              {registros} ({sum(gastos_por_mensagem)} gastos)")
    print(f"Consultas:                        {contar('consultar')}")
    print(f"Gastos guardados no banco:        {gastos}")
    if registros:
        print(f"Correções pelo usuário:           {correcoes} "
              f"({contar('desfazer')} desfazer, {contar('corrigir_categoria')} troca de categoria)")
        print(f"Taxa de correção:                 {correcoes / registros:.1%} das mensagens com gasto")
    if latencias:
        p95 = latencias[math.ceil(0.95 * len(latencias)) - 1]
        print(f"Tempo de resposta do LLM:         média {statistics.mean(latencias):.0f} ms, p95 {p95} ms")
    if modelos:
        total = sum(modelos.values())
        print("Uso dos modelos:                  " +
              ", ".join(f"{m} {n / total:.0%}" for m, n in sorted(modelos.items(), key=lambda x: -x[1])))


if __name__ == "__main__":
    main()
