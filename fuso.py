"""Data e hora no horário de Brasília.

Na nuvem, o servidor costuma estar em UTC (3 horas à frente). Sem isso, um gasto
feito às 22h de segunda seria salvo como terça, e "bom dia" sairia à noite.
"""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

FUSO = ZoneInfo(os.environ.get("FUSO_HORARIO", "America/Sao_Paulo"))


def agora() -> datetime:
    return datetime.now(FUSO)


def hoje() -> date:
    return agora().date()
