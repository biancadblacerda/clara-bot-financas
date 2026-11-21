import banco
import bot
from conftest import HOJE, MES, Contexto, Update, UpdateBotao, botoes
from interpretador import ServicoIndisponivel


def test_formatacao_de_reais_e_mes():
    assert bot.reais(1234.5) == "R$ 1.234,50"
    assert bot.reais(4) == "R$ 4,00"
    assert bot.nome_do_mes("2026-03") == "março de 2026"


async def test_registra_um_gasto(clara):
    clara.ensinar("gastei 45 no mercado", acao="registrar",
                  gastos=[dict(valor=45, categoria="mercado", descricao="mercado", data=HOJE)])
    u = Update("gastei 45 no mercado")
    await bot.receber_mensagem(u, Contexto())
    texto, teclado = u.message.respostas[0]
    assert texto.startswith("Anotei! R$ 45,00 em mercado, dia")
    assert len(botoes(teclado)) == 1
    assert banco.total_por_categoria(bot.engine, 1, MES)[0]["total"] == 45.0


async def test_registra_varios_gastos_de_uma_vez(clara):
    clara.ensinar("30 no almoço e 15 no café", acao="registrar", gastos=[
        dict(valor=30, categoria="alimentação", descricao="almoço", data=HOJE),
        dict(valor=15, categoria="alimentação", descricao="café", data=HOJE)])
    u = Update("30 no almoço e 15 no café")
    await bot.receber_mensagem(u, Contexto())
    assert "Anotei 2 gastos" in u.message.respostas[0][0]
    assert banco.total_por_categoria(bot.engine, 1, MES)[0]["total"] == 45.0


async def test_valor_alto_so_salva_depois_de_confirmar(clara):
    clara.ensinar("notebook 3500", acao="registrar",
                  gastos=[dict(valor=3500, categoria="compras", descricao="notebook", data=HOJE)])
    contexto, u = Contexto(), Update("notebook 3500")
    await bot.receber_mensagem(u, contexto)
    assert "Confirma" in u.message.respostas[0][0]
    assert banco.listar_gastos(bot.engine, 1) == []

    confirmar = botoes(u.message.respostas[0][1])[0]
    clique = UpdateBotao(confirmar)
    await bot.receber_botao(clique, contexto)
    assert "Anotei" in clique.callback_query.edicoes[0][0]
    assert len(banco.listar_gastos(bot.engine, 1)) == 1

    # O mesmo botão clicado de novo não registra duas vezes
    clique2 = UpdateBotao(confirmar)
    await bot.receber_botao(clique2, contexto)
    assert "expirou" in clique2.callback_query.edicoes[0][0]
    assert len(banco.listar_gastos(bot.engine, 1)) == 1


async def test_cancelar_valor_alto_nao_salva(clara):
    clara.ensinar("notebook 3500", acao="registrar",
                  gastos=[dict(valor=3500, categoria="compras", data=HOJE)])
    contexto, u = Contexto(), Update("notebook 3500")
    await bot.receber_mensagem(u, contexto)
    cancelar = botoes(u.message.respostas[0][1])[1]
    clique = UpdateBotao(cancelar)
    await bot.receber_botao(clique, contexto)
    assert clique.callback_query.edicoes[0][0] == "Ok, não registrei."
    assert banco.listar_gastos(bot.engine, 1) == []


async def test_corrigir_categoria_pelo_botao(clara):
    clara.ensinar("netflix 55,90", acao="registrar",
                  gastos=[dict(valor=55.9, categoria="lazer", descricao="netflix", data=HOJE)])
    u = Update("netflix 55,90")
    await bot.receber_mensagem(u, Contexto())
    abrir = UpdateBotao(botoes(u.message.respostas[0][1])[0])
    await bot.receber_botao(abrir, Contexto())
    opcoes = botoes(abrir.callback_query.edicoes[0][1])
    assert len(opcoes) == len(bot.CATEGORIAS)

    escolher = UpdateBotao(next(o for o in opcoes if o.endswith(f":{bot.CATEGORIAS.index('contas')}")))
    await bot.receber_botao(escolher, Contexto())
    assert escolher.callback_query.edicoes[0][0] == "Pronto! Mudei a categoria para contas."
    assert banco.listar_gastos(bot.engine, 1)[0]["categoria"] == "contas"


async def test_ninguem_muda_o_gasto_de_outra_pessoa(clara):
    gasto_id = banco.adicionar_gasto(bot.engine, 1, 20.0, "lazer", None, HOJE, "x")
    intrusa = UpdateBotao(f"setcat:{gasto_id}:0", usuario=999)
    await bot.receber_botao(intrusa, Contexto())
    assert "Não encontrei" in intrusa.callback_query.edicoes[0][0]
    assert banco.buscar_gasto(bot.engine, gasto_id, 1)["categoria"] == "lazer"


async def test_consulta_por_categoria(clara):
    banco.adicionar_gasto(bot.engine, 1, 32.5, "alimentação", "almoço", HOJE, "x")
    clara.ensinar("quanto gastei com comida?", acao="consultar", categoria="alimentação", mes=MES)
    u = Update("quanto gastei com comida?")
    await bot.receber_mensagem(u, Contexto())
    assert "R$ 32,50 com alimentação (1 gasto)" in u.message.respostas[0][0]


async def test_respostas_para_o_que_nao_e_gasto(clara):
    for motivo, trecho in [("receita", "só registro gastos"), ("estorno", "/desfazer"),
                           ("sem_valor", "faltou o valor"),
                           ("ajuda", "/resumo"), ("agradecimento", "Bianca"), ("despedida", "Bianca")]:
        clara.ensinar(motivo, acao="outro", motivo=motivo)
        u = Update(motivo)
        await bot.receber_mensagem(u, Contexto())
        assert trecho in u.message.respostas[0][0], motivo
    assert banco.listar_gastos(bot.engine, 1) == []


async def test_saudacao_usa_nome_e_repete_o_cumprimento(clara):
    clara.ensinar("boa noite, tudo bem?", acao="outro", motivo="saudacao")
    u = Update("boa noite, tudo bem?")
    await bot.receber_mensagem(u, Contexto())
    resposta = u.message.respostas[0][0]
    assert resposta.startswith("Boa noite, Bianca!")
    assert "e com você" in resposta.lower() or "como você está" in resposta


async def test_mensagem_longa_nao_vai_para_o_llm(clara):
    u = Update("a" * 500)
    await bot.receber_mensagem(u, Contexto())   # sem resposta ensinada: chamaria o LLM e quebraria
    assert "muito longa" in u.message.respostas[0][0]


async def test_limite_de_mensagens_por_minuto(clara):
    clara.ensinar("oi", acao="outro", motivo="fora_do_tema")
    for _ in range(bot.MAX_MENSAGENS_POR_MINUTO):
        await bot.receber_mensagem(Update("oi"), Contexto())
    u = Update("oi")
    await bot.receber_mensagem(u, Contexto())
    assert "Espera um minutinho" in u.message.respostas[0][0]
    outra_pessoa = Update("oi", usuario=2)
    await bot.receber_mensagem(outra_pessoa, Contexto())
    assert "Espera um minutinho" not in outra_pessoa.message.respostas[0][0]


async def test_llm_fora_do_ar_gera_aviso_e_fica_registrado(clara):
    clara.erro = ServicoIndisponivel("principal: 503")
    u = Update("uber 10")
    await bot.receber_mensagem(u, Contexto())
    assert "sobrecarregado" in u.message.respostas[0][0]
    with bot.engine.connect() as con:
        from sqlalchemy import text
        assert con.execute(text("SELECT erro FROM interacoes")).scalar_one() == "principal: 503"


async def test_desfazer(clara):
    banco.adicionar_gasto(bot.engine, 1, 20.0, "lazer", None, HOJE, "x")
    u = Update("/desfazer")
    await bot.comando_desfazer(u, Contexto())
    assert u.message.respostas[0][0].startswith("Apaguei: R$ 20,00 em lazer")
    u2 = Update("/desfazer")
    await bot.comando_desfazer(u2, Contexto())
    assert u2.message.respostas[0][0] == "Não há nenhum gasto para desfazer."


async def test_resumo_do_mes(clara):
    banco.adicionar_gasto(bot.engine, 1, 45.0, "mercado", None, HOJE, "x")
    banco.adicionar_gasto(bot.engine, 1, 18.5, "transporte", None, HOJE, "y")
    u = Update("/resumo")
    await bot.comando_resumo(u, Contexto())
    texto = u.message.respostas[0][0]
    assert "• mercado: R$ 45,00" in texto and "Total gasto: R$ 63,50" in texto
    assert "Previstos" not in texto


async def test_exportar_csv(clara):
    banco.adicionar_gasto(bot.engine, 1, 1234.5, "compras", "notebook; usado", HOJE, "x")
    u = Update("/exportar")
    await bot.comando_exportar(u, Contexto())
    nome, conteudo, legenda = u.message.documentos[0]
    assert nome == "meus_gastos.csv"
    assert conteudo.splitlines()[0] == "data;valor;categoria;descricao"
    assert f'{HOJE};1234,50;compras;"notebook; usado"' in conteudo
    assert legenda == "1 gasto registrado."


async def test_apagar_meus_dados(clara):
    banco.adicionar_gasto(bot.engine, 1, 20.0, "lazer", None, HOJE, "x")
    banco.adicionar_gasto(bot.engine, 2, 20.0, "lazer", None, HOJE, "y")
    nao = UpdateBotao("apagar:nao")
    await bot.receber_botao(nao, Contexto())
    assert len(banco.listar_gastos(bot.engine, 1)) == 1
    sim = UpdateBotao("apagar:sim")
    await bot.receber_botao(sim, Contexto())
    assert banco.listar_gastos(bot.engine, 1) == []
    assert len(banco.listar_gastos(bot.engine, 2)) == 1


async def test_compra_parcelada_vira_uma_parcela_por_mes(clara):
    clara.ensinar("tênis de 400 em 5 vezes", acao="registrar",
                  gastos=[dict(valor=400, categoria="compras", descricao="tênis", data=HOJE, parcelas=5)])
    u = Update("tênis de 400 em 5 vezes")
    await bot.receber_mensagem(u, Contexto())
    assert "R$ 400,00 em compras (tênis), em 5x de R$ 80,00" in u.message.respostas[0][0]
    gastos = banco.listar_gastos(bot.engine, 1)
    assert [g["valor"] for g in gastos] == [80.0] * 5
    assert [g["descricao"] for g in gastos][-1] == "tênis (5/5)"
    assert len({g["data"][:7] for g in gastos}) == 5          # um mês diferente para cada parcela

    # o resumo do mês separa a parcela de hoje das futuras, e o mês seguinte mostra a próxima como prevista
    from parcelas import somar_meses
    from datetime import date
    proximo = somar_meses(date.fromisoformat(HOJE), 1).strftime("%Y-%m")
    assert "Total gasto: R$ 80,00" in bot.texto_resumo(1, MES)
    assert "Previstos para" in bot.texto_resumo(1, proximo)

    # desfazer apaga a compra inteira
    d = Update("desfaz")
    await bot.desfazer(d, "desfaz")
    assert "5 lançamentos, R$ 400,00" in d.message.respostas[0][0]
    assert banco.listar_gastos(bot.engine, 1) == []


async def test_trocar_categoria_de_parcelado_muda_todas(clara):
    clara.ensinar("celular 1200 em 3x", acao="registrar",
                  gastos=[dict(valor=1200, categoria="outros", descricao="celular", data=HOJE, parcelas=3)])
    contexto, u = Contexto(), Update("celular 1200 em 3x")
    await bot.receber_mensagem(u, contexto)                 # valor alto: pede confirmação primeiro
    clique = UpdateBotao(botoes(u.message.respostas[0][1])[0])
    await bot.receber_botao(clique, contexto)
    abrir = UpdateBotao(botoes(clique.callback_query.edicoes[0][1])[0])
    await bot.receber_botao(abrir, Contexto())
    escolher = UpdateBotao(next(o for o in botoes(abrir.callback_query.edicoes[0][1])
                                if o.endswith(f":{bot.CATEGORIAS.index('compras')}")))
    await bot.receber_botao(escolher, Contexto())
    assert escolher.callback_query.edicoes[0][0] == "Pronto! Mudei a categoria para compras nas 3 parcelas."
    assert {g["categoria"] for g in banco.listar_gastos(bot.engine, 1)} == {"compras"}


async def test_gasto_futuro_fica_como_previsto(clara):
    from datetime import date, timedelta
    amanha = (date.fromisoformat(HOJE) + timedelta(days=1)).isoformat()
    clara.ensinar("vou pagar 100 no cabelo amanhã", acao="registrar",
                  gastos=[dict(valor=100, categoria="outros", descricao="cabelo", data=amanha)])
    u = Update("vou pagar 100 no cabelo amanhã")
    await bot.receber_mensagem(u, Contexto())
    assert f"previsto para {bot.dia(amanha)}" in u.message.respostas[0][0]
    resumo = bot.texto_resumo(1, amanha[:7])
    assert "R$ 100,00" in resumo and "revisto" in resumo


async def test_comandos_pedidos_em_texto_livre(clara):
    banco.adicionar_gasto(bot.engine, 1, 20.0, "lazer", None, HOJE, "x", grupo="g")
    clara.ensinar("quero exportar meus gastos", acao="comando", comando="exportar")
    u = Update("quero exportar meus gastos")
    await bot.receber_mensagem(u, Contexto())
    assert u.message.documentos[0][0] == "meus_gastos.csv"

    clara.ensinar("desfazer última ação", acao="comando", comando="desfazer")
    u = Update("desfazer última ação")
    await bot.receber_mensagem(u, Contexto())
    assert u.message.respostas[0][0].startswith("Apaguei: R$ 20,00")

    clara.ensinar("me manda o resumo do mês", acao="consultar", mes=MES)
    u = Update("me manda o resumo do mês")
    await bot.receber_mensagem(u, Contexto())
    assert "Você ainda não tem gastos" in u.message.respostas[0][0]


async def test_apagar_dados_por_texto_sempre_pede_confirmacao(clara):
    banco.adicionar_gasto(bot.engine, 1, 20.0, "lazer", None, HOJE, "x")
    clara.ensinar("apaga tudo que você sabe de mim", acao="comando", comando="apagar_dados")
    u = Update("apaga tudo que você sabe de mim")
    await bot.receber_mensagem(u, Contexto())
    assert "Confirma?" in u.message.respostas[0][0]
    assert botoes(u.message.respostas[0][1]) == ["apagar:sim", "apagar:nao"]
    assert len(banco.listar_gastos(bot.engine, 1)) == 1      # nada apagado sem o clique
