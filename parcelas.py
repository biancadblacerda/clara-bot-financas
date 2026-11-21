"""Transforma uma compra parcelada em uma parcela por mês."""
import calendar
from datetime import date


def somar_meses(d: date, meses: int) -> date:
    """Mesmo dia, N meses depois. Dia 31 em mês de 30 dias vira dia 30 (ou 28/29 em fevereiro)."""
    total = d.month - 1 + meses
    ano, mes = d.year + total // 12, total % 12 + 1
    return date(ano, mes, min(d.day, calendar.monthrange(ano, mes)[1]))


def dividir(valor_total: float, parcelas: int) -> list[float]:
    """Divide em centavos exatos; a primeira parcela fica com o que sobrar da divisão."""
    centavos = round(valor_total * 100)
    base, resto = divmod(centavos, parcelas)
    return [(base + (resto if i == 0 else 0)) / 100 for i in range(parcelas)]


def expandir(gasto: dict) -> list[dict]:
    """Um gasto à vista vira uma linha; um parcelado vira uma linha por parcela."""
    n = gasto.get("parcelas")
    if not n:
        return [dict(gasto)]
    inicio = date.fromisoformat(gasto["data"])
    descricao = gasto.get("descricao") or gasto["categoria"]
    return [
        {**gasto, "valor": valor, "data": somar_meses(inicio, i).isoformat(),
         "descricao": f"{descricao} ({i + 1}/{n})"}
        for i, valor in enumerate(dividir(gasto["valor"], n))
    ]
