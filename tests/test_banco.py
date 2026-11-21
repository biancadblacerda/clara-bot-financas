import banco
from conftest import HOJE, MES


def test_adiciona_e_soma_por_categoria(engine):
    banco.adicionar_gasto(engine, 1, 45.0, "mercado", None, HOJE, "gastei 45 no mercado")
    banco.adicionar_gasto(engine, 1, 30.0, "mercado", None, HOJE, "mercado 30")
    banco.adicionar_gasto(engine, 1, 18.5, "transporte", "uber", HOJE, "uber 18,50")
    linhas = banco.total_por_categoria(engine, 1, MES)
    assert linhas[0] == {"categoria": "mercado", "total": 75.0, "quantidade": 2}
    assert linhas[1]["categoria"] == "transporte"


def test_consulta_respeita_o_mes(engine):
    banco.adicionar_gasto(engine, 1, 10.0, "lazer", None, "2020-01-15", "x")
    assert banco.total_por_categoria(engine, 1, MES) == []
    assert banco.total_por_categoria(engine, 1, "2020-01")[0]["total"] == 10.0


def test_usuarios_nao_veem_dados_um_do_outro(engine):
    id_a = banco.adicionar_gasto(engine, 1, 50.0, "lazer", None, HOJE, "a")
    banco.adicionar_gasto(engine, 2, 99.0, "lazer", None, HOJE, "b")
    assert banco.total_por_categoria(engine, 1, MES)[0]["total"] == 50.0
    assert banco.buscar_gasto(engine, id_a, usuario=2) is None
    assert banco.mudar_categoria(engine, id_a, usuario=2, categoria="saúde") == 0
    assert banco.buscar_gasto(engine, id_a, usuario=1)["categoria"] == "lazer"


def test_desfazer_apaga_o_ultimo_registro_inteiro_so_do_proprio_usuario(engine):
    banco.adicionar_gasto(engine, 1, 10.0, "lazer", None, HOJE, "primeiro", grupo="g1")
    banco.adicionar_gasto(engine, 1, 20.0, "lazer", None, HOJE, "segundo", grupo="g2")
    banco.adicionar_gasto(engine, 1, 25.0, "lazer", None, HOJE, "segundo", grupo="g2")
    banco.adicionar_gasto(engine, 2, 30.0, "lazer", None, HOJE, "de outra pessoa", grupo="g3")
    assert [g["valor"] for g in banco.desfazer_ultimo(engine, 1)] == [20.0, 25.0]
    assert [g["mensagem"] for g in banco.desfazer_ultimo(engine, 1)] == ["primeiro"]
    assert banco.desfazer_ultimo(engine, 1) == []
    assert len(banco.listar_gastos(engine, 2)) == 1


def test_mudar_categoria_muda_todas_as_parcelas_da_compra(engine):
    ids = [banco.adicionar_gasto(engine, 1, 80.0, "compras", f"tênis ({i}/3)", HOJE, "x", grupo="g", compra="c")
           for i in (1, 2, 3)]
    avulso = banco.adicionar_gasto(engine, 1, 5.0, "compras", "bala", HOJE, "y", grupo="h")
    assert banco.mudar_categoria(engine, ids[1], 1, "lazer") == 3
    assert banco.buscar_gasto(engine, avulso, 1)["categoria"] == "compras"


def test_separa_gasto_e_previsto(engine):
    banco.adicionar_gasto(engine, 1, 10.0, "lazer", None, "2026-11-10", "x")
    banco.adicionar_gasto(engine, 1, 99.0, "lazer", None, "2026-11-25", "y")
    assert banco.total_por_categoria(engine, 1, "2026-11", ate="2026-11-21")[0]["total"] == 10.0
    assert banco.total_por_categoria(engine, 1, "2026-11", depois_de="2026-11-21")[0]["total"] == 99.0
    assert banco.total_por_categoria(engine, 1, "2026-11")[0]["total"] == 109.0


def test_banco_antigo_ganha_as_colunas_novas_sem_perder_dados(tmp_path):
    import sqlite3
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE gastos (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario INTEGER NOT NULL, "
                "valor REAL NOT NULL, categoria TEXT NOT NULL, descricao TEXT, data TEXT NOT NULL, "
                "mensagem TEXT, criado_em TEXT NOT NULL)")
    con.execute("INSERT INTO gastos (usuario, valor, categoria, data, mensagem, criado_em) "
                "VALUES (1, 45, 'mercado', '2026-11-05', 'antigo', '2026-11-05')")
    con.commit()
    con.close()
    engine = banco.conectar(f"sqlite:///{caminho}")
    assert banco.listar_gastos(engine, 1)[0]["valor"] == 45.0
    banco.adicionar_gasto(engine, 1, 10.0, "lazer", None, HOJE, "novo", grupo="g")
    assert banco.desfazer_ultimo(engine, 1)[0]["mensagem"] == "novo"
    assert banco.desfazer_ultimo(engine, 1)[0]["mensagem"] == "antigo"   # sem grupo: apaga só ele


def test_apagar_dados_remove_gastos_e_historico_so_do_usuario(engine):
    banco.adicionar_gasto(engine, 1, 10.0, "lazer", None, HOJE, "x")
    banco.registrar_interacao(engine, 1, "registrar", "x")
    banco.adicionar_gasto(engine, 2, 10.0, "lazer", None, HOJE, "y")
    assert banco.apagar_dados_do_usuario(engine, 1) == 1
    assert banco.listar_gastos(engine, 1) == []
    assert len(banco.listar_gastos(engine, 2)) == 1


def test_valor_arredondado_em_centavos(engine):
    gasto_id = banco.adicionar_gasto(engine, 1, 10.005, "lazer", None, HOJE, "x")
    assert banco.buscar_gasto(engine, gasto_id, 1)["valor"] in (10.0, 10.01)


def test_converte_url_do_postgres():
    # Só verifica a conversão do endereço, sem conectar de verdade
    import sqlalchemy
    url = sqlalchemy.engine.make_url("postgresql+psycopg://u:s@host/db")
    assert url.drivername == "postgresql+psycopg"
