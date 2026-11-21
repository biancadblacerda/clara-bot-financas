"""Peças simuladas para testar o bot sem Telegram e sem chamar o LLM de verdade."""
import os
import sys
from datetime import date

import pytest
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GEMINI_API_KEY", "chave-falsa")
os.environ.setdefault("MODELO", "modelo-falso")

import banco  # noqa: E402
import bot  # noqa: E402
from interpretador import Gasto, Interpretacao, Resultado  # noqa: E402

HOJE = date.today().isoformat()
MES = date.today().strftime("%Y-%m")


class InterpretadorFalso:
    """Devolve uma interpretação pronta para cada mensagem, como se fosse o LLM."""
    def __init__(self):
        self.respostas = {}
        self.erro = None

    def ensinar(self, mensagem, **campos):
        if "gastos" in campos:
            campos["gastos"] = [Gasto(**g) for g in campos["gastos"]]
        self.respostas[mensagem] = Interpretacao(**campos)

    async def interpretar(self, mensagem, hoje=None):
        if self.erro:
            raise self.erro
        return Resultado(self.respostas[mensagem], "modelo-falso", 123)


class Mensagem:
    def __init__(self, texto=""):
        self.text = texto
        self.respostas = []      # (texto, teclado)
        self.documentos = []

    async def reply_text(self, texto, reply_markup=None):
        self.respostas.append((texto, reply_markup))

    async def reply_document(self, document, filename, caption=None):
        self.documentos.append((filename, document.getvalue().decode("utf-8-sig"), caption))


class Usuario:
    def __init__(self, id, first_name="Bianca"):
        self.id = id
        self.first_name = first_name


class Update:
    def __init__(self, texto, usuario=1):
        self.message = Mensagem(texto)
        self.effective_user = Usuario(usuario)
        self.callback_query = None


class Query:
    def __init__(self, data, usuario=1):
        self.data = data
        self.from_user = Usuario(usuario)
        self.edicoes = []    # (texto, teclado)

    async def answer(self):
        pass

    async def edit_message_text(self, texto, reply_markup=None):
        self.edicoes.append((texto, reply_markup))


class UpdateBotao:
    def __init__(self, data, usuario=1):
        self.callback_query = Query(data, usuario)


class Contexto:
    def __init__(self):
        self.user_data = {}


@pytest.fixture
def engine(tmp_path):
    """SQLite temporário por padrão; defina TEST_DATABASE_URL para rodar contra um PostgreSQL."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        return banco.conectar(f"sqlite:///{tmp_path / 'teste.db'}")
    e = banco.conectar(url)
    with e.begin() as con:
        con.execute(text("DELETE FROM gastos"))
        con.execute(text("DELETE FROM interacoes"))
    return e


@pytest.fixture
def clara(engine, monkeypatch):
    """O módulo bot ligado a um banco temporário e a um LLM simulado."""
    falso = InterpretadorFalso()
    monkeypatch.setattr(bot, "engine", engine)
    monkeypatch.setattr(bot, "interpretador", falso)
    bot._historico_mensagens.clear()
    return falso


def botoes(teclado):
    """Lista os callback_data de um teclado de botões."""
    return [b.callback_data for linha in teclado.inline_keyboard for b in linha] if teclado else []
