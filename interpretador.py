"""Usa um LLM (Gemini) para transformar uma mensagem em português numa ação estruturada."""
import logging
import os
from datetime import date
from typing import Literal, Optional

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

CATEGORIAS = [
    "alimentação", "mercado", "transporte", "moradia", "contas",
    "saúde", "educação", "lazer", "compras", "outros",
]


class Interpretacao(BaseModel):
    """Formato que o LLM é obrigado a devolver."""
    acao: Literal["registrar", "consultar", "outro"]
    valor: Optional[float] = None       # em reais, só para "registrar"
    categoria: Optional[str] = None     # uma das CATEGORIAS
    descricao: Optional[str] = None     # ex.: "mercado do bairro"
    data: Optional[str] = None          # AAAA-MM-DD, só para "registrar"
    mes: Optional[str] = None           # AAAA-MM, só para "consultar"


def montar_instrucoes(hoje: date) -> str:
    return f"""Você é o interpretador de um bot de controle de gastos pessoais.
Hoje é {hoje.isoformat()}.

Classifique a mensagem do usuário em uma ação:
- "registrar": a pessoa informa um gasto. Extraia o valor em reais (número positivo), a categoria, uma descrição curta e a data (AAAA-MM-DD). Se a data não for mencionada, use hoje; entenda "ontem", "sexta passada" etc. a partir de hoje.
- "consultar": a pessoa pergunta quanto gastou. Extraia a categoria, se houver, e o mês (AAAA-MM). Se o mês não for mencionado, use o mês atual.
- "outro": qualquer outra coisa (saudação, dúvida, mensagem sem valor).

A categoria deve ser exatamente uma destas: {", ".join(CATEGORIAS)}.
Restaurante, lanche, delivery e café são "alimentação"; compras de supermercado são "mercado"; Uber, ônibus e gasolina são "transporte"; luz, água, internet e celular são "contas".
Se nenhuma categoria servir, use "outros". Nunca invente um valor que a pessoa não disse."""


class ServicoIndisponivel(Exception):
    """Nenhum modelo respondeu (sobrecarga ou limite de uso)."""


class Interpretador:
    def __init__(self, api_key: Optional[str] = None, modelos: Optional[list[str]] = None):
        self.cliente = genai.Client(
            api_key=api_key or os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(
                timeout=20_000,  # milissegundos: não deixa o usuário esperando mais de 20 s por modelo
                retry_options=types.HttpRetryOptions(attempts=2, initial_delay=1.0),
            ),
        )
        # Modelo principal e modelos de reserva, tentados nesta ordem
        self.modelos = modelos or [
            m.strip() for m in (os.environ.get("MODELO", ""), os.environ.get("MODELO_RESERVA", ""))
            if m.strip()
        ]

    async def interpretar(self, mensagem: str, hoje: Optional[date] = None) -> Interpretacao:
        config = types.GenerateContentConfig(
            system_instruction=montar_instrucoes(hoje or date.today()),
            response_mime_type="application/json",
            response_schema=Interpretacao,
            temperature=0,
        )
        falhas = []
        for modelo in self.modelos:
            try:
                resposta = await self.cliente.aio.models.generate_content(
                    model=modelo, contents=mensagem, config=config
                )
                return validar(Interpretacao.model_validate_json(resposta.text))
            except errors.APIError as e:
                # 429 = limite de uso, 500/503/504 = instabilidade do servidor: tenta o próximo modelo
                if e.code in (429, 500, 503, 504):
                    logging.warning("Modelo %s indisponível (%s): %s", modelo, e.code, e.message)
                    falhas.append(f"{modelo}: {e.code}")
                    continue
                raise
        raise ServicoIndisponivel("Nenhum modelo disponível: " + ", ".join(falhas))


def validar(r: Interpretacao) -> Interpretacao:
    """Corrige o que o LLM pode errar mesmo seguindo o formato."""
    if r.categoria is not None and r.categoria not in CATEGORIAS:
        r.categoria = "outros"
    if r.acao == "registrar" and (r.valor is None or r.valor <= 0):
        r.acao = "outro"   # sem valor válido não dá para registrar
    return r
