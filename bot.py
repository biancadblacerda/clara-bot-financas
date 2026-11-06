"""Bot de controle de gastos no Telegram (Clara). Etapa 2: salvar e consultar gastos."""
import json
import logging
import os
import re
from datetime import date, datetime

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import banco
from interpretador import Interpretador, ServicoIndisponivel

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

ARQUIVO_REGISTRO = "registros.jsonl"
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

interpretador = Interpretador()
con = banco.conectar()


# ---------- funções auxiliares ----------

def registrar_interacao(usuario: int, mensagem: str, tipo: str, interpretacao: dict | None = None,
                        gasto_id: int | None = None, erro: str | None = None):
    """Guarda cada interação. É daqui que saem as métricas de uso e de erro do bot."""
    linha = {
        "quando": datetime.now().isoformat(timespec="seconds"),
        "usuario": usuario,
        "tipo": tipo,                    # registrar, consultar, outro, desfazer, resumo, erro
        "mensagem": mensagem,
        "interpretacao": interpretacao,
        "gasto_id": gasto_id,
        "erro": erro,
    }
    with open(ARQUIVO_REGISTRO, "a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def reais(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def nome_do_mes(mes: str) -> str:
    ano, m = mes.split("-")
    return f"{MESES[int(m) - 1]} de {ano}"


def data_valida(texto: str | None) -> str:
    """Usa a data do LLM se ela estiver no formato certo e não for no futuro; senão, hoje."""
    try:
        d = date.fromisoformat(texto)
        return d.isoformat() if d <= date.today() else date.today().isoformat()
    except (TypeError, ValueError):
        return date.today().isoformat()


def mes_valido(texto: str | None) -> str:
    if texto and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", texto):
        return texto
    return date.today().strftime("%Y-%m")


def texto_resumo(usuario: int, mes: str, categoria: str | None = None) -> str:
    linhas = banco.total_por_categoria(con, usuario, mes)
    if categoria:
        linha = next((l for l in linhas if l["categoria"] == categoria), None)
        if not linha:
            return f"Você não registrou gastos com {categoria} em {nome_do_mes(mes)}."
        vezes = "gasto" if linha["quantidade"] == 1 else "gastos"
        return (f"Em {nome_do_mes(mes)}, você gastou {reais(linha['total'])} com {categoria} "
                f"({linha['quantidade']} {vezes}).")
    if not linhas:
        return f"Você ainda não registrou gastos em {nome_do_mes(mes)}."
    total = sum(l["total"] for l in linhas)
    detalhes = "\n".join(f"• {l['categoria']}: {reais(l['total'])}" for l in linhas)
    return f"Seus gastos em {nome_do_mes(mes)}:\n\n{detalhes}\n\nTotal: {reais(total)}"


# ---------- comandos ----------

async def comando_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Oi! Eu sou a Clara e anoto seus gastos.\n\n"
        "Para registrar, escreva do seu jeito: \"gastei 45 no mercado\" ou \"uber 18,50 ontem\".\n"
        "Para consultar: \"quanto gastei com comida este mês?\"\n\n"
        "/resumo mostra seus gastos do mês por categoria\n"
        "/desfazer apaga o último gasto, se eu tiver entendido errado"
    )


async def comando_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = update.effective_user.id
    registrar_interacao(usuario, "/resumo", "resumo")
    await update.message.reply_text(texto_resumo(usuario, date.today().strftime("%Y-%m")))


async def comando_desfazer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario = update.effective_user.id
    apagado = banco.desfazer_ultimo(con, usuario)
    if not apagado:
        await update.message.reply_text("Não há nenhum gasto para desfazer.")
        return
    # Cada /desfazer é tratado como um erro de interpretação: vira métrica de qualidade
    registrar_interacao(usuario, "/desfazer", "desfazer", gasto_id=apagado["id"],
                        interpretacao={"mensagem_original": apagado["mensagem"]})
    data = date.fromisoformat(apagado["data"]).strftime("%d/%m")
    await update.message.reply_text(
        f"Apaguei: {reais(apagado['valor'])} em {apagado['categoria']} ({data}).\n"
        "Pode mandar de novo do jeito certo."
    )


# ---------- mensagens livres ----------

async def receber_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    usuario = update.effective_user.id
    try:
        r = await interpretador.interpretar(texto)
    except ServicoIndisponivel as e:
        registrar_interacao(usuario, texto, "erro", erro=str(e))
        await update.message.reply_text("O serviço de IA está sobrecarregado agora. Tenta de novo em um minuto?")
        return
    except Exception as e:
        logging.exception("Falha ao interpretar")
        registrar_interacao(usuario, texto, "erro", erro=str(e))
        await update.message.reply_text("Tive um problema para entender agora. Pode tentar de novo?")
        return

    if r.acao == "registrar":
        data = data_valida(r.data)
        gasto_id = banco.adicionar_gasto(con, usuario, r.valor, r.categoria or "outros",
                                         r.descricao, data, texto)
        registrar_interacao(usuario, texto, "registrar", r.model_dump(), gasto_id=gasto_id)
        quando = date.fromisoformat(data).strftime("%d/%m")
        mostrar = r.descricao and r.descricao.lower() != (r.categoria or "").lower()
        descricao = f" ({r.descricao})" if mostrar else ""
        resposta = (f"Anotei! {reais(r.valor)} em {r.categoria or 'outros'}{descricao}, dia {quando}.\n"
                    "Errei? Use /desfazer")
    elif r.acao == "consultar":
        registrar_interacao(usuario, texto, "consultar", r.model_dump())
        resposta = texto_resumo(usuario, mes_valido(r.mes), r.categoria)
    else:
        registrar_interacao(usuario, texto, "outro", r.model_dump())
        resposta = ("Não identifiquei um gasto nem uma consulta. Tente algo como "
                    "\"gastei 30 no almoço\" ou \"quanto gastei este mês?\"")
    await update.message.reply_text(resposta)


def main():
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    app.add_handler(CommandHandler("start", comando_start))
    app.add_handler(CommandHandler("resumo", comando_resumo))
    app.add_handler(CommandHandler("desfazer", comando_desfazer))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber_mensagem))
    logging.info("Bot rodando. Aperte Ctrl+C para parar.")
    app.run_polling()


if __name__ == "__main__":
    main()
