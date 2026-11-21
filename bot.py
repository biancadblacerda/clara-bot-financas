"""Clara: bot de controle de gastos no Telegram."""
import csv
import io
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import date

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import banco
import fuso
import parcelas
import respostas
from interpretador import CATEGORIAS, Interpretador, ServicoIndisponivel

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]
LIMITE_CONFIRMACAO = float(os.environ.get("LIMITE_CONFIRMACAO", "500"))  # pede confirmação acima disso
MAX_CARACTERES = 300                # mensagens maiores não vão para o LLM
MAX_MENSAGENS_POR_MINUTO = 10       # protege a cota da API quando há muitos usuários

# Preenchidos em main(); os testes substituem por versões simuladas
engine = None
interpretador = None
_historico_mensagens: dict[int, deque] = defaultdict(deque)


# ---------- formatação ----------

def reais(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def nome_do_mes(mes: str) -> str:
    ano, m = mes.split("-")
    return f"{MESES[int(m) - 1]} de {ano}"


def dia(data_iso: str, com_ano: bool = False) -> str:
    return date.fromisoformat(data_iso).strftime("%d/%m/%Y" if com_ano else "%d/%m")


def descrever(g: dict) -> str:
    """Uma linha legível para um gasto: à vista, previsto ou parcelado."""
    descricao = g.get("descricao")
    mostrar = descricao and descricao.lower() != g["categoria"].lower()
    base = f"{reais(g['valor'])} em {g['categoria']}{f' ({descricao})' if mostrar else ''}"
    n = g.get("parcelas")
    if n:
        valor_parcela = parcelas.dividir(g["valor"], n)[-1]
        fim = parcelas.somar_meses(date.fromisoformat(g["data"]), n - 1).isoformat()
        return f"{base}, em {n}x de {reais(valor_parcela)}, de {dia(g['data'], True)} a {dia(fim, True)}"
    if g["data"] > fuso.hoje().isoformat():
        return f"{base}, previsto para {dia(g['data'])}"
    return f"{base}, dia {dia(g['data'])}"


def dentro_do_limite(usuario: int, agora: float | None = None) -> bool:
    """Limita quantas mensagens cada pessoa pode mandar por minuto."""
    agora = agora or time.monotonic()
    fila = _historico_mensagens[usuario]
    while fila and agora - fila[0] > 60:
        fila.popleft()
    if len(fila) >= MAX_MENSAGENS_POR_MINUTO:
        return False
    fila.append(agora)
    return True


# ---------- resumo ----------

def _bloco(linhas: list[dict], titulo: str, rotulo_total: str) -> str:
    detalhes = "\n".join(f"• {l['categoria']}: {reais(l['total'])}" for l in linhas)
    return f"{titulo}\n\n{detalhes}\n\n{rotulo_total}: {reais(sum(l['total'] for l in linhas))}"


def texto_resumo(usuario: int, mes: str, categoria: str | None = None) -> str:
    """Separa o que já foi gasto do que está previsto (parcelas futuras e gastos agendados)."""
    hoje = fuso.hoje().isoformat()
    gastos = banco.total_por_categoria(engine, usuario, mes, ate=hoje)
    previstos = banco.total_por_categoria(engine, usuario, mes, depois_de=hoje)
    nome = nome_do_mes(mes)

    if categoria:
        gasto = next((l for l in gastos if l["categoria"] == categoria), None)
        previsto = next((l for l in previstos if l["categoria"] == categoria), None)
        if not gasto and not previsto:
            return f"Você não tem gastos com {categoria} em {nome}."
        partes = []
        if gasto:
            vezes = "gasto" if gasto["quantidade"] == 1 else "gastos"
            partes.append(f"Em {nome}, você gastou {reais(gasto['total'])} com {categoria} "
                          f"({gasto['quantidade']} {vezes}).")
        if previsto:
            partes.append(f"Ainda estão previstos {reais(previsto['total'])} com {categoria} em {nome}.")
        return " ".join(partes)

    if not gastos and not previstos:
        return f"Você ainda não tem gastos em {nome}."
    partes = []
    if gastos:
        partes.append(_bloco(gastos, f"Seus gastos em {nome}:", "Total gasto"))
    if previstos:
        titulo = "Previstos até o fim do mês" if gastos else f"Previstos para {nome}"
        partes.append(_bloco(previstos, f"{titulo} (parcelas e gastos agendados):", "Total previsto"))
    return "\n\n".join(partes)


# ---------- registro ----------

def salvar_gastos(usuario: int, gastos: list[dict], mensagem: str) -> list[dict]:
    """Salva os gastos de uma mensagem. Cada compra parcelada vira uma linha por mês."""
    grupo = secrets.token_hex(6)          # a mensagem inteira: é o que o /desfazer apaga
    salvos = []
    for g in gastos:
        compra = secrets.token_hex(6) if g.get("parcelas") else None
        ids = [banco.adicionar_gasto(engine, usuario, linha["valor"], linha["categoria"], linha.get("descricao"),
                                     linha["data"], mensagem, grupo=grupo, compra=compra)
               for linha in parcelas.expandir(g)]
        salvos.append({**g, "id": ids[0]})
    return salvos


def texto_anotado(salvos: list[dict]) -> str:
    if len(salvos) == 1:
        return f"Anotei! {descrever(salvos[0])}."
    return f"Anotei {len(salvos)} gastos:\n" + "\n".join(f"• {descrever(g)}" for g in salvos)


def botoes_corrigir(salvos: list[dict]) -> InlineKeyboardMarkup:
    """Um botão por gasto para trocar a categoria, caso a Clara tenha errado."""
    if len(salvos) == 1:
        rotulos = ["✏️ Mudar categoria"]
    else:
        rotulos = [f"✏️ Categoria de {reais(g['valor'])}" for g in salvos]
    return InlineKeyboardMarkup([[InlineKeyboardButton(r, callback_data=f"cat:{g['id']}")]
                                 for r, g in zip(rotulos, salvos)])


async def pedir_confirmacao(update: Update, context: ContextTypes.DEFAULT_TYPE, gastos: list[dict], texto: str):
    """Valores altos só são salvos depois que a pessoa confirma."""
    token = secrets.token_hex(4)
    context.user_data.setdefault("pendentes", {})[token] = {"gastos": gastos, "mensagem": texto}
    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Registrar", callback_data=f"conf:{token}"),
        InlineKeyboardButton("❌ Cancelar", callback_data=f"canc:{token}"),
    ]])
    linhas = "\n".join(f"• {descrever(g)}" for g in gastos)
    await update.message.reply_text(f"Esse valor é alto. Confirma?\n{linhas}", reply_markup=teclado)


# ---------- ações (usadas pelos comandos com "/" e pelos pedidos em texto livre) ----------

async def enviar_resumo(update: Update, origem: str):
    usuario = update.effective_user.id
    banco.registrar_interacao(engine, usuario, "resumo", origem)
    await update.message.reply_text(texto_resumo(usuario, fuso.hoje().strftime("%Y-%m")))


async def desfazer(update: Update, origem: str):
    usuario = update.effective_user.id
    apagados = banco.desfazer_ultimo(engine, usuario)
    if not apagados:
        await update.message.reply_text("Não há nenhum gasto para desfazer.")
        return
    # Cada desfazer conta como um possível erro de interpretação nas métricas
    banco.registrar_interacao(engine, usuario, "desfazer", origem, interpretacao={
        "gastos_apagados": [g["id"] for g in apagados], "mensagem_original": apagados[0]["mensagem"]})
    if len(apagados) == 1:
        g = apagados[0]
        texto = f"Apaguei: {reais(g['valor'])} em {g['categoria']} ({dia(g['data'])})."
    else:
        linhas = "\n".join(f"• {reais(g['valor'])} em {g['categoria']} ({dia(g['data'])})" for g in apagados[:6])
        resto = f"\n• e mais {len(apagados) - 6}" if len(apagados) > 6 else ""
        texto = (f"Apaguei o último registro ({len(apagados)} lançamentos, "
                 f"{reais(sum(g['valor'] for g in apagados))}):\n{linhas}{resto}")
    await update.message.reply_text(texto + "\nPode mandar de novo do jeito certo.")


async def exportar(update: Update, origem: str):
    usuario = update.effective_user.id
    gastos = banco.listar_gastos(engine, usuario)
    if not gastos:
        await update.message.reply_text("Você ainda não tem gastos registrados.")
        return
    arquivo = io.StringIO()
    escritor = csv.writer(arquivo, delimiter=";")  # ";" abre direto no Excel em português
    escritor.writerow(["data", "valor", "categoria", "descricao"])
    for g in gastos:
        escritor.writerow([g["data"], f"{g['valor']:.2f}".replace(".", ","), g["categoria"], g["descricao"] or ""])
    conteudo = io.BytesIO(arquivo.getvalue().encode("utf-8-sig"))  # utf-8-sig mantém os acentos no Excel
    banco.registrar_interacao(engine, usuario, "exportar", origem)
    quantidade = f"{len(gastos)} {'gasto registrado' if len(gastos) == 1 else 'gastos registrados'}."
    await update.message.reply_document(document=conteudo, filename="meus_gastos.csv", caption=quantidade)


async def pedir_para_apagar_dados(update: Update):
    """Apagar tudo é irreversível: sempre pede confirmação por botão, mesmo quando o pedido veio em texto."""
    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("Sim, apagar tudo", callback_data="apagar:sim"),
        InlineKeyboardButton("Cancelar", callback_data="apagar:nao"),
    ]])
    await update.message.reply_text(
        "Isso apaga todos os seus gastos e o histórico das nossas conversas. Não dá para desfazer. Confirma?",
        reply_markup=teclado,
    )


# ---------- comandos com "/" ----------

async def comando_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = update.effective_user.first_name
    await update.message.reply_text(f"Oi{f', {nome}' if nome else ''}! " + respostas.AJUDA)


async def comando_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await enviar_resumo(update, "/resumo")


async def comando_desfazer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await desfazer(update, "/desfazer")


async def comando_exportar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await exportar(update, "/exportar")


async def comando_apagar_dados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await pedir_para_apagar_dados(update)


# ---------- mensagens livres ----------

async def receber_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    usuario = update.effective_user.id

    if len(texto) > MAX_CARACTERES:
        await update.message.reply_text("Mensagem muito longa. Me manda os gastos de forma mais curta?")
        return
    if not dentro_do_limite(usuario):
        await update.message.reply_text("Calma! 😅 Muitas mensagens em pouco tempo. Espera um minutinho.")
        return

    try:
        resultado = await interpretador.interpretar(texto)
    except ServicoIndisponivel as e:
        banco.registrar_interacao(engine, usuario, "erro", texto, erro=str(e))
        await update.message.reply_text("O serviço de IA está sobrecarregado agora. Tenta de novo em um minuto?")
        return
    except Exception as e:
        logging.exception("Falha ao interpretar")
        banco.registrar_interacao(engine, usuario, "erro", texto, erro=f"{type(e).__name__}: {e}")
        await update.message.reply_text("Tive um problema para entender agora. Pode tentar de novo?")
        return

    r = resultado.interpretacao
    banco.registrar_interacao(engine, usuario, r.acao, texto, interpretacao=r.model_dump(),
                              modelo=resultado.modelo, latencia_ms=resultado.latencia_ms)

    if r.acao == "registrar":
        gastos = [g.model_dump() for g in r.gastos]
        if any(g["valor"] >= LIMITE_CONFIRMACAO for g in gastos):
            await pedir_confirmacao(update, context, gastos, texto)
            return
        salvos = salvar_gastos(usuario, gastos, texto)
        await update.message.reply_text(texto_anotado(salvos) + "\nErrei? É só dizer \"desfaz\".",
                                        reply_markup=botoes_corrigir(salvos))
    elif r.acao == "consultar":
        await update.message.reply_text(texto_resumo(usuario, r.mes, r.categoria))
    elif r.acao == "comando":
        if r.comando == "exportar":
            await exportar(update, texto)
        elif r.comando == "desfazer":
            await desfazer(update, texto)
        else:
            await pedir_para_apagar_dados(update)
    else:
        await update.message.reply_text(respostas.responder_conversa(
            r.motivo, texto, update.effective_user.first_name, fuso.agora()))


# ---------- botões ----------

async def receber_botao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    usuario = query.from_user.id
    acao, _, argumento = query.data.partition(":")
    await query.answer()

    if acao in ("conf", "canc"):
        pendente = context.user_data.get("pendentes", {}).pop(argumento, None)
        if pendente is None:
            await query.edit_message_text("Essa confirmação expirou. Me manda o gasto de novo.")
            return
        if acao == "canc":
            banco.registrar_interacao(engine, usuario, "cancelar", pendente["mensagem"])
            await query.edit_message_text("Ok, não registrei.")
            return
        salvos = salvar_gastos(usuario, pendente["gastos"], pendente["mensagem"])
        await query.edit_message_text(texto_anotado(salvos) + "\nErrei? É só dizer \"desfaz\".",
                                      reply_markup=botoes_corrigir(salvos))

    elif acao == "cat":
        gasto = banco.buscar_gasto(engine, int(argumento), usuario)
        if gasto is None:
            await query.edit_message_text("Não encontrei esse gasto. Ele pode ter sido apagado.")
            return
        teclado = [[InlineKeyboardButton(c, callback_data=f"setcat:{gasto['id']}:{i}")
                    for i, c in enumerate(CATEGORIAS[j:j + 2], start=j)]
                   for j in range(0, len(CATEGORIAS), 2)]
        await query.edit_message_text(
            f"Qual a categoria certa para {gasto['descricao'] or gasto['categoria']}?",
            reply_markup=InlineKeyboardMarkup(teclado),
        )

    elif acao == "setcat":
        gasto_id, _, indice = argumento.partition(":")
        gasto = banco.buscar_gasto(engine, int(gasto_id), usuario)
        nova = CATEGORIAS[int(indice)]
        alterados = banco.mudar_categoria(engine, int(gasto_id), usuario, nova) if gasto else 0
        if not alterados:
            await query.edit_message_text("Não encontrei esse gasto. Ele pode ter sido apagado.")
            return
        # Correção de categoria = erro do LLM; entra nas métricas de qualidade
        banco.registrar_interacao(engine, usuario, "corrigir_categoria", gasto["mensagem"],
                                  interpretacao={"gasto_id": gasto["id"], "de": gasto["categoria"], "para": nova})
        nas_parcelas = f" nas {alterados} parcelas" if alterados > 1 else ""
        await query.edit_message_text(f"Pronto! Mudei a categoria para {nova}{nas_parcelas}.")

    elif acao == "apagar":
        if argumento == "sim":
            quantidade = banco.apagar_dados_do_usuario(engine, usuario)
            await query.edit_message_text(f"Apaguei seus {quantidade} gastos e todo o seu histórico.")
        else:
            await query.edit_message_text("Ok, nada foi apagado.")


async def tratar_erro(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Última rede de segurança: qualquer erro não previsto vira log, nunca um bot travado."""
    logging.error("Erro não tratado", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Algo deu errado do meu lado. Pode tentar de novo?")


def main():
    global engine, interpretador
    engine = banco.conectar()
    interpretador = Interpretador()

    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    privado = filters.ChatType.PRIVATE  # só conversa individual: gastos são pessoais
    app.add_handler(CommandHandler(["start", "ajuda"], comando_start, filters=privado))
    app.add_handler(CommandHandler("resumo", comando_resumo, filters=privado))
    app.add_handler(CommandHandler("desfazer", comando_desfazer, filters=privado))
    app.add_handler(CommandHandler("exportar", comando_exportar, filters=privado))
    app.add_handler(CommandHandler("apagar_meus_dados", comando_apagar_dados, filters=privado))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & privado, receber_mensagem))
    app.add_handler(CallbackQueryHandler(receber_botao))
    app.add_error_handler(tratar_erro)

    # Na nuvem (Render), o Telegram avisa o bot de cada mensagem por HTTP (webhook).
    # No computador, o próprio bot pergunta ao Telegram se há mensagens novas (polling).
    url_publica = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("WEBHOOK_URL")
    if url_publica:
        segredo = os.environ["WEBHOOK_SECRET"]  # garante que as chamadas vêm mesmo do Telegram
        logging.info("Clara no ar via webhook em %s, banco %s", url_publica, engine.dialect.name)
        app.run_webhook(listen="0.0.0.0", port=int(os.environ.get("PORT", "8080")),
                        url_path="telegram", webhook_url=f"{url_publica}/telegram",
                        secret_token=segredo, drop_pending_updates=False)
    else:
        logging.info("Clara rodando localmente com %s. Aperte Ctrl+C para parar.", engine.dialect.name)
        app.run_polling()


if __name__ == "__main__":
    main()
