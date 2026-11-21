"""Respostas da Clara para conversa (saudação, ajuda, agradecimento...).

O LLM só diz QUE TIPO de mensagem chegou; o texto é escrito aqui. Para não soar
robótica, a Clara varia as frases, usa o primeiro nome da pessoa e responde de
acordo com o período do dia (ou repete o "boa noite" que a pessoa mandou).
"""
import random
import unicodedata
from datetime import datetime

AJUDA = (
    "Eu sou a Clara e anoto seus gastos do jeito que você fala. 📒\n\n"
    "Para registrar, é só escrever:\n"
    "• \"gastei 45 no mercado\"\n"
    "• \"uber 18,50 ontem\"\n"
    "• \"30 no almoço e 15 no café\"\n"
    "• \"comprei um tênis de 400 em 5 vezes\" (eu divido nos próximos meses)\n"
    "• \"vou pagar 60 no cabelo amanhã\" (fica como previsto)\n\n"
    "Para consultar:\n"
    "• \"me manda o resumo do mês\"\n"
    "• \"quanto gastei com comida em outubro?\"\n"
    "• \"quanto vou pagar de parcelas em dezembro?\"\n\n"
    "Também entendo pedidos como \"desfaz o último\", \"quero exportar meus gastos\" "
    "e \"apaga meus dados\". Se preferir, os comandos são:\n"
    "/resumo, /desfazer, /exportar, /apagar_meus_dados e /ajuda"
)

CONVITES = [
    "Quer anotar algum gasto?",
    "Me conta: gastou com alguma coisa hoje?",
    "Se quiser saber como está o mês, é só mandar /resumo.",
]

AGRADECIMENTOS = [
    "Imagina{nome}! Tô aqui pra isso. 😊",
    "De nada{nome}! Qualquer gasto, é só me mandar.",
    "Por nada{nome}! Conta comigo pra manter as contas em dia.",
]

DESPEDIDAS = [
    "Até mais{nome}! Quando gastar, me conta. 👋",
    "Tchau{nome}! Tô por aqui quando precisar.",
    "Até logo{nome}! Boa semana com as contas em dia. 😉",
]

FORA_DO_TEMA = [
    "Essa eu não sei responder 😅. Eu só entendo de gastos! Tente \"gastei 30 no almoço\" ou \"quanto gastei este mês?\".",
    "Hmm, isso foge do meu assunto. Eu cuido só dos seus gastos: me manda um, tipo \"uber 18,50\".",
]

OUTROS = {
    "receita": "Que bom que entrou dinheiro! 🎉 Mas por enquanto eu só registro gastos, não entradas.",
    "estorno": "Não registro estornos ainda. Se o gasto original foi anotado errado, use /desfazer.",
    "sem_valor": "Entendi que é um gasto, mas faltou o valor. Me manda algo como \"gastei 30 no almoço\".",
}


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def periodo_do_dia(texto: str, quando: datetime) -> str:
    """Repete o cumprimento da pessoa; se ela não usou um, escolhe pelo horário."""
    t = _sem_acento(texto)
    for cumprimento in ("bom dia", "boa tarde", "boa noite"):
        if cumprimento in t:
            return cumprimento.capitalize()
    if 5 <= quando.hour < 12:
        return "Bom dia"
    if 12 <= quando.hour < 18:
        return "Boa tarde"
    return "Boa noite"


def _vocativo(nome: str | None) -> str:
    return f", {nome}" if nome else ""


def saudacao(texto: str, nome: str | None, quando: datetime) -> str:
    t = _sem_acento(texto)
    perguntou_como_esta = any(p in t for p in ("tudo bem", "tudo bom", "como vai", "como voce esta", "td bem"))
    inicio = f"{periodo_do_dia(texto, quando)}{_vocativo(nome)}!"
    if perguntou_como_esta:
        meio = random.choice(["Tudo ótimo por aqui, e com você?", "Tudo certo por aqui! E aí, como você está?"])
    else:
        meio = random.choice(["Que bom te ver por aqui.", "Tudo certo por aí?"])
    return f"{inicio} {meio} {random.choice(CONVITES)}"


def responder_conversa(motivo: str, texto: str, nome: str | None, quando: datetime) -> str:
    """Escolhe a resposta para mensagens que não são gasto nem consulta."""
    if motivo == "saudacao":
        return saudacao(texto, nome, quando)
    if motivo == "ajuda":
        return AJUDA
    if motivo == "agradecimento":
        return random.choice(AGRADECIMENTOS).format(nome=_vocativo(nome))
    if motivo == "despedida":
        return random.choice(DESPEDIDAS).format(nome=_vocativo(nome))
    if motivo in OUTROS:
        return OUTROS[motivo]
    return random.choice(FORA_DO_TEMA)
