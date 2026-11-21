from datetime import datetime

import respostas

MANHA = datetime(2026, 11, 21, 9, 0)
NOITE = datetime(2026, 11, 21, 22, 0)


def test_periodo_pelo_horario():
    assert respostas.periodo_do_dia("oi", MANHA) == "Bom dia"
    assert respostas.periodo_do_dia("oi", datetime(2026, 11, 21, 15, 0)) == "Boa tarde"
    assert respostas.periodo_do_dia("oi", NOITE) == "Boa noite"
    assert respostas.periodo_do_dia("oi", datetime(2026, 11, 21, 3, 0)) == "Boa noite"


def test_repete_o_cumprimento_da_pessoa_mesmo_fora_do_horario():
    assert respostas.periodo_do_dia("BOM DIA!!", NOITE) == "Bom dia"
    assert respostas.periodo_do_dia("boa tarde clara", MANHA) == "Boa tarde"


def test_saudacao_sem_nome_nao_deixa_virgula_solta():
    texto = respostas.saudacao("oi", None, MANHA)
    assert texto.startswith("Bom dia!")


def test_pedido_de_ajuda_lista_os_comandos():
    texto = respostas.responder_conversa("ajuda", "o que você faz?", "Bia", MANHA)
    for comando in ("/resumo", "/desfazer", "/exportar", "/apagar_meus_dados"):
        assert comando in texto


def test_respostas_variam_mas_sempre_usam_o_nome():
    vistas = {respostas.responder_conversa("agradecimento", "valeu", "Bia", MANHA) for _ in range(60)}
    assert len(vistas) > 1 and all("Bia" in v for v in vistas)


def test_motivo_desconhecido_cai_em_fora_do_tema():
    assert respostas.responder_conversa("qualquer", "x", None, MANHA) in respostas.FORA_DO_TEMA


def test_fuso_de_brasilia():
    import fuso
    assert fuso.agora().utcoffset().total_seconds() == -3 * 3600
