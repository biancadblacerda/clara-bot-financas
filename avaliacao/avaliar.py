"""Mede a taxa de acerto do interpretador num conjunto fixo de mensagens.

Uso:
    python avaliacao/avaliar.py                                      # modelo do .env
    python avaliacao/avaliar.py gemini-3.5-flash-lite gemini-3.1-flash-lite   # compara modelos
    python avaliacao/avaliar.py gemini-3.5-flash-lite --casos 13,26          # só alguns casos

Quando o modelo está fora do ar (sobrecarga ou cota), a mensagem conta como
"indisponível", e não como erro de interpretação: são problemas diferentes.

As datas esperadas consideram que "hoje" é 21/11/2026 (sábado), para o resultado não
mudar conforme o dia em que a avaliação roda.
"""
import asyncio
import json
import math
import os
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

from interpretador import Interpretador, ServicoIndisponivel  # noqa: E402

load_dotenv()
HOJE = date(2026, 11, 21)
PASTA = Path(__file__).resolve().parent
PAUSA_ENTRE_CHAMADAS = 4.5   # segundos; respeita o limite por minuto da camada gratuita
PAUSA_ANTES_DE_REPETIR = 15  # segundos; espera antes de tentar de novo um modelo sobrecarregado
MAX_INDISPONIVEIS_SEGUIDOS = 5  # depois disso, desiste do modelo para não gastar a cota à toa


def comparar(esperado: dict, obtido) -> list[str]:
    """Devolve a lista de diferenças entre o esperado e o que o LLM entendeu (vazia = acertou)."""
    if obtido.acao != esperado["acao"]:
        return [f"ação: esperava {esperado['acao']}, veio {obtido.acao}"]
    erros = []
    if esperado["acao"] == "registrar":
        if len(obtido.gastos) != len(esperado["gastos"]):
            return [f"quantidade de gastos: esperava {len(esperado['gastos'])}, veio {len(obtido.gastos)}"]
        for i, (e, o) in enumerate(zip(esperado["gastos"], obtido.gastos), start=1):
            if abs(o.valor - e["valor"]) > 0.01:
                erros.append(f"gasto {i} valor: esperava {e['valor']}, veio {o.valor}")
            if o.categoria not in e["categorias"]:
                erros.append(f"gasto {i} categoria: esperava {'/'.join(e['categorias'])}, veio {o.categoria}")
            if o.data != e["data"]:
                erros.append(f"gasto {i} data: esperava {e['data']}, veio {o.data}")
            if o.parcelas != e.get("parcelas"):
                erros.append(f"gasto {i} parcelas: esperava {e.get('parcelas')}, veio {o.parcelas}")
    elif esperado["acao"] == "consultar":
        if obtido.categoria != esperado["categoria"]:
            erros.append(f"categoria: esperava {esperado['categoria']}, veio {obtido.categoria}")
        if obtido.mes != esperado["mes"]:
            erros.append(f"mês: esperava {esperado['mes']}, veio {obtido.mes}")
    elif esperado["acao"] == "comando":
        if obtido.comando != esperado["comando"]:
            erros.append(f"comando: esperava {esperado['comando']}, veio {obtido.comando}")
    elif esperado["motivos"] and obtido.motivo not in esperado["motivos"]:
        erros.append(f"motivo: esperava {'/'.join(esperado['motivos'])}, veio {obtido.motivo}")
    return erros


async def avaliar_modelo(modelo: str, casos: list[dict]) -> dict:
    interpretador = Interpretador(modelos=[modelo])
    resultados = []
    seguidos = 0
    for i, caso in enumerate(casos, start=1):
        if seguidos >= MAX_INDISPONIVEIS_SEGUIDOS:
            resultados.append({"mensagem": caso["mensagem"], "acao": caso["esperado"]["acao"],
                               "status": "nao_avaliado", "erros": [], "latencia_ms": None})
            continue
        resultado, motivo = None, None
        for tentativa in range(2):
            try:
                resultado = await interpretador.interpretar(caso["mensagem"], hoje=HOJE)
                break
            except ServicoIndisponivel as e:
                motivo = str(e)
                if tentativa == 0:
                    await asyncio.sleep(PAUSA_ANTES_DE_REPETIR)
        if resultado is None:
            seguidos += 1
            registro = {"status": "indisponivel", "erros": [motivo], "latencia_ms": None}
            print(f"  [{caso['numero']:2}] INDISPONÍVEL {caso['mensagem']}")
            if seguidos == MAX_INDISPONIVEIS_SEGUIDOS:
                print(f"  {modelo} indisponível {seguidos} vezes seguidas: interrompendo para não gastar a cota.")
        else:
            seguidos = 0
            erros = comparar(caso["esperado"], resultado.interpretacao)
            registro = {"status": "ok" if not erros else "erro", "erros": erros,
                        "latencia_ms": resultado.latencia_ms}
            print(f"  [{caso['numero']:2}] {'ok  ' if not erros else 'ERRO'} {caso['mensagem']}")
        resultados.append({"mensagem": caso["mensagem"], "acao": caso["esperado"]["acao"], **registro})
        await asyncio.sleep(PAUSA_ENTRE_CHAMADAS)

    avaliados = [r for r in resultados if r["status"] in ("ok", "erro")]
    latencias = sorted(r["latencia_ms"] for r in avaliados)
    por_acao = {}
    for acao in ("registrar", "consultar", "comando", "outro"):
        grupo = [r for r in avaliados if r["acao"] == acao]
        por_acao[acao] = f"{sum(r['status'] == 'ok' for r in grupo)}/{len(grupo)}"
    return {
        "modelo": modelo,
        "acertos": sum(r["status"] == "ok" for r in avaliados),
        "avaliados": len(avaliados),
        "indisponiveis": sum(r["status"] == "indisponivel" for r in resultados),
        "nao_avaliados": sum(r["status"] == "nao_avaliado" for r in resultados),
        "por_acao": por_acao,
        "latencia_media_ms": round(statistics.mean(latencias)) if latencias else None,
        "latencia_p95_ms": latencias[math.ceil(0.95 * len(latencias)) - 1] if latencias else None,
        "casos": resultados,
    }


async def main():
    casos = [json.loads(l) for l in (PASTA / "casos.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    for numero, caso in enumerate(casos, start=1):
        caso["numero"] = numero
    argumentos = sys.argv[1:]
    if "--casos" in argumentos:
        posicao = argumentos.index("--casos")
        escolhidos = {int(n) for n in argumentos[posicao + 1].split(",")}
        casos = [c for c in casos if c["numero"] in escolhidos]
        argumentos = argumentos[:posicao] + argumentos[posicao + 2:]
    modelos = argumentos or [os.environ["MODELO"]]

    resumo = []
    for modelo in modelos:
        print(f"\nAvaliando {modelo} em {len(casos)} mensagens...")
        r = await avaliar_modelo(modelo, casos)
        (PASTA / f"resultado_{modelo}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        resumo.append(r)

    print("\n================ RESULTADO ================")
    for r in resumo:
        print(f"\n{r['modelo']}:")
        if not r["avaliados"]:
            print(f"   não respondeu a nenhuma mensagem ({r['indisponiveis']} indisponíveis, "
                  f"{r['nao_avaliados']} não avaliadas)")
            continue
        print(f"   acerto: {r['acertos']}/{r['avaliados']} ({r['acertos'] / r['avaliados']:.0%}) | "
              f"registrar {r['por_acao']['registrar']}, consultar {r['por_acao']['consultar']}, "
              f"comando {r['por_acao']['comando']}, outro {r['por_acao']['outro']}")
        print(f"   disponibilidade: {r['avaliados']} respondidas, {r['indisponiveis']} indisponíveis, "
              f"{r['nao_avaliados']} não avaliadas")
        print(f"   latência média {r['latencia_media_ms']} ms, p95 {r['latencia_p95_ms']} ms")
        for c in r["casos"]:
            if c["status"] == "erro":
                print(f"   ✗ \"{c['mensagem']}\": {'; '.join(c['erros'])}")


if __name__ == "__main__":
    asyncio.run(main())
