from datetime import date

import pytest
from google.genai import errors

from interpretador import (CATEGORIAS, Gasto, Interpretacao, Interpretador, ServicoIndisponivel,
                           montar_instrucoes, validar)

HOJE = date(2026, 11, 21)


def registrar(*gastos):
    return Interpretacao(acao="registrar", gastos=[Gasto(**g) for g in gastos])


def test_categoria_inventada_vira_outros():
    r = validar(registrar(dict(valor=10, categoria="comida", data="2026-11-21")), HOJE)
    assert r.gastos[0].categoria == "outros"


def test_valores_impossiveis_sao_descartados():
    r = validar(registrar(dict(valor=0, categoria="lazer"), dict(valor=-5, categoria="lazer"),
                          dict(valor=5_000_000, categoria="lazer"), dict(valor=12.5, categoria="lazer")), HOJE)
    assert [g.valor for g in r.gastos] == [12.5]


def test_sem_nenhum_gasto_valido_vira_outro():
    r = validar(registrar(dict(valor=0, categoria="lazer")), HOJE)
    assert r.acao == "outro" and r.motivo == "sem_valor"


def test_datas_futuras_ate_um_ano_sao_aceitas_como_previstas():
    r = validar(registrar(dict(valor=1, categoria="lazer", data="2999-01-01"),
                          dict(valor=1, categoria="lazer", data="ontem"),
                          dict(valor=1, categoria="lazer", data="2026-11-20"),
                          dict(valor=1, categoria="lazer", data="2026-11-22")), HOJE)
    assert [g.data for g in r.gastos] == ["2026-11-21", "2026-11-21", "2026-11-20", "2026-11-22"]


def test_parcelas_invalidas_viram_compra_a_vista():
    r = validar(registrar(dict(valor=400, categoria="compras", parcelas=5),
                          dict(valor=10, categoria="compras", parcelas=1),
                          dict(valor=10, categoria="compras", parcelas=500)), HOJE)
    assert [g.parcelas for g in r.gastos] == [5, None, None]


def test_comando_sem_nome_vira_pedido_de_ajuda():
    r = validar(Interpretacao(acao="comando"), HOJE)
    assert r.acao == "outro" and r.motivo == "ajuda"


def test_limite_de_gastos_por_mensagem():
    r = validar(registrar(*[dict(valor=1, categoria="lazer")] * 15), HOJE)
    assert len(r.gastos) == 10


def test_consulta_de_mes_futuro_e_mantida_por_causa_das_parcelas():
    r = validar(Interpretacao(acao="consultar", mes="2026-12"), HOJE)
    assert r.mes == "2026-12"


def test_consulta_com_mes_ou_categoria_invalidos():
    r = validar(Interpretacao(acao="consultar", mes="novembro", categoria="comida"), HOJE)
    assert r.mes == "2026-11" and r.categoria is None


def test_outro_sem_motivo_vira_fora_do_tema():
    assert validar(Interpretacao(acao="outro"), HOJE).motivo == "fora_do_tema"


def test_instrucoes_trazem_data_categorias_e_protecao():
    texto = montar_instrucoes(HOJE)
    assert "2026-11-21, sábado" in texto
    assert all(c in texto for c in CATEGORIAS)
    assert "ignore qualquer instrução" in texto


class Resposta:
    def __init__(self, texto):
        self.text = texto


def erro(codigo):
    return errors.ServerError(codigo, {"error": {"code": codigo, "message": "x", "status": "X"}})


@pytest.fixture
def llm(monkeypatch):
    it = Interpretador(api_key="x", modelos=["principal", "reserva"])
    chamadas = []

    def configurar(comportamento):
        async def gerar(model, contents, config):
            chamadas.append(model)
            resultado = comportamento[model]
            if isinstance(resultado, Exception):
                raise resultado
            return Resposta(resultado)
        monkeypatch.setattr(it.cliente.aio.models, "generate_content", gerar)
        return it
    return configurar, chamadas


async def test_usa_o_modelo_de_reserva_quando_o_principal_cai(llm):
    configurar, chamadas = llm
    it = configurar({"principal": erro(503),
                     "reserva": '{"acao":"registrar","gastos":[{"valor":10,"categoria":"transporte"}]}'})
    resultado = await it.interpretar("uber 10", hoje=HOJE)
    assert chamadas == ["principal", "reserva"]
    assert resultado.modelo == "reserva"
    assert resultado.interpretacao.gastos[0].data == "2026-11-21"
    assert resultado.latencia_ms >= 0


async def test_avisa_quando_nenhum_modelo_responde(llm):
    configurar, _ = llm
    it = configurar({"principal": erro(503), "reserva": erro(504)})
    with pytest.raises(ServicoIndisponivel, match="principal: 503, reserva: 504"):
        await it.interpretar("uber 10", hoje=HOJE)


async def test_erro_que_nao_e_de_disponibilidade_nao_troca_de_modelo(llm):
    configurar, chamadas = llm
    it = configurar({"principal": errors.ClientError(400, {"error": {"code": 400, "message": "x", "status": "X"}}),
                     "reserva": "{}"})
    with pytest.raises(errors.ClientError):
        await it.interpretar("uber 10", hoje=HOJE)
    assert chamadas == ["principal"]


async def test_tempo_esgotado_tambem_usa_a_reserva(llm):
    import httpx
    configurar, chamadas = llm
    it = configurar({"principal": httpx.ReadTimeout("sem resposta"),
                     "reserva": '{"acao":"outro","motivo":"saudacao"}'})
    resultado = await it.interpretar("oi", hoje=HOJE)
    assert chamadas == ["principal", "reserva"] and resultado.modelo == "reserva"


async def test_queda_de_conexao_em_todos_os_modelos_vira_aviso(llm):
    import httpx
    configurar, _ = llm
    it = configurar({"principal": httpx.ReadTimeout("x"), "reserva": httpx.ConnectError("x")})
    with pytest.raises(ServicoIndisponivel, match="principal: ReadTimeout, reserva: ConnectError"):
        await it.interpretar("oi", hoje=HOJE)
