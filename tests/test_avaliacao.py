"""Garante que o avaliador compara certo (senão a taxa de acerto seria mentira)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "avaliacao"))
from avaliar import comparar  # noqa: E402
from interpretador import Gasto, Interpretacao  # noqa: E402

CASOS = [json.loads(l) for l in (Path(__file__).resolve().parent.parent / "avaliacao" / "casos.jsonl")
         .read_text(encoding="utf-8").splitlines()]


def test_casos_bem_formados():
    assert len(CASOS) >= 40
    for c in CASOS:
        assert c["esperado"]["acao"] in ("registrar", "consultar", "comando", "outro")


def test_acerto_e_erros_detectados():
    esperado = {"acao": "registrar", "gastos": [{"valor": 18.5, "categorias": ["transporte"], "data": "2026-11-20"}]}
    certo = Interpretacao(acao="registrar", gastos=[Gasto(valor=18.5, categoria="transporte", data="2026-11-20")])
    assert comparar(esperado, certo) == []
    errado = Interpretacao(acao="registrar", gastos=[Gasto(valor=18.0, categoria="lazer", data="2026-11-21")])
    assert len(comparar(esperado, errado)) == 3
    assert comparar(esperado, Interpretacao(acao="outro", motivo="sem_valor"))[0].startswith("ação")


def test_categoria_ambigua_aceita_alternativas():
    esperado = {"acao": "registrar", "gastos": [{"valor": 55.9, "categorias": ["contas", "lazer"], "data": "2026-11-21"}]}
    for cat in ("contas", "lazer"):
        assert comparar(esperado, Interpretacao(acao="registrar", gastos=[
            Gasto(valor=55.9, categoria=cat, data="2026-11-21")])) == []


def test_parcelas_e_comandos_sao_comparados():
    esperado = {"acao": "registrar", "gastos": [{"valor": 400, "categorias": ["compras"], "data": "2026-11-21", "parcelas": 5}]}
    sem_parcelas = Interpretacao(acao="registrar", gastos=[Gasto(valor=400, categoria="compras", data="2026-11-21")])
    assert comparar(esperado, sem_parcelas) == ["gasto 1 parcelas: esperava 5, veio None"]
    assert comparar({"acao": "comando", "comando": "exportar"}, Interpretacao(acao="comando", comando="desfazer"))
    assert comparar({"acao": "comando", "comando": "exportar"}, Interpretacao(acao="comando", comando="exportar")) == []
