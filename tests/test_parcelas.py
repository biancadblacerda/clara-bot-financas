from datetime import date

from parcelas import dividir, expandir, somar_meses


def test_divisao_exata_em_centavos():
    assert dividir(400, 5) == [80.0] * 5
    assert dividir(100, 3) == [33.34, 33.33, 33.33]
    assert round(sum(dividir(99.99, 7)), 2) == 99.99


def test_fim_de_mes_e_virada_de_ano():
    assert somar_meses(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert somar_meses(date(2028, 1, 31), 1) == date(2028, 2, 29)     # ano bissexto
    assert somar_meses(date(2026, 11, 21), 3) == date(2027, 2, 21)


def test_expandir_parcelado_e_a_vista():
    linhas = expandir({"valor": 300, "categoria": "compras", "descricao": "fone", "data": "2026-11-21", "parcelas": 3})
    assert [(l["valor"], l["data"], l["descricao"]) for l in linhas] == [
        (100.0, "2026-11-21", "fone (1/3)"), (100.0, "2026-12-21", "fone (2/3)"), (100.0, "2027-01-21", "fone (3/3)")]
    assert len(expandir({"valor": 30, "categoria": "lazer", "data": "2026-11-21", "parcelas": None})) == 1
