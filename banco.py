"""Acesso ao banco de dados.

Usa SQLAlchemy para que o mesmo código funcione com SQLite (no computador, para
desenvolver) e com PostgreSQL (na nuvem, com o bot no ar). Qual banco usar é
definido pela variável de ambiente DATABASE_URL.
"""
import json
import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

import fuso

URL_PADRAO = "sqlite:///gastos.db"

ESQUEMA = [
    """
    CREATE TABLE IF NOT EXISTS gastos (
        id          {id_auto},
        usuario     BIGINT  NOT NULL,
        valor       NUMERIC(12, 2) NOT NULL,
        categoria   TEXT    NOT NULL,
        descricao   TEXT,
        data        TEXT    NOT NULL,   -- AAAA-MM-DD
        mensagem    TEXT,               -- frase original, para auditar erros do LLM
        criado_em   TEXT    NOT NULL,
        grupo       TEXT,               -- mesma mensagem = mesmo grupo (o /desfazer apaga o grupo)
        compra      TEXT                -- parcelas da mesma compra têm a mesma compra
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_gastos_usuario_data ON gastos (usuario, data)",
    """
    CREATE TABLE IF NOT EXISTS interacoes (
        id            {id_auto},
        quando        TEXT    NOT NULL,
        usuario       BIGINT  NOT NULL,
        tipo          TEXT    NOT NULL, -- registrar, consultar, outro, desfazer, corrigir, erro...
        mensagem      TEXT,
        interpretacao TEXT,             -- JSON com o que o LLM entendeu
        modelo        TEXT,             -- qual modelo respondeu
        latencia_ms   INTEGER,          -- quanto tempo o LLM levou
        erro          TEXT
    )
    """,
]


def conectar(url: str | None = None) -> Engine:
    """Cria a conexão e as tabelas, se ainda não existirem."""
    url = url or os.environ.get("DATABASE_URL") or URL_PADRAO
    # Alguns provedores entregam "postgres://"; o SQLAlchemy espera "postgresql+psycopg://"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]

    engine = create_engine(url, pool_pre_ping=True)
    id_auto = ("INTEGER PRIMARY KEY AUTOINCREMENT" if engine.dialect.name == "sqlite"
               else "BIGSERIAL PRIMARY KEY")
    with engine.begin() as con:
        for comando in ESQUEMA:
            con.execute(text(comando.format(id_auto=id_auto)))
    _atualizar_esquema(engine)
    return engine


def _atualizar_esquema(engine: Engine):
    """Bancos criados por versões antigas não têm as colunas novas: acrescenta sem perder dados."""
    existentes = {c["name"] for c in inspect(engine).get_columns("gastos")}
    with engine.begin() as con:
        for coluna in ("grupo", "compra"):
            if coluna not in existentes:
                con.execute(text(f"ALTER TABLE gastos ADD COLUMN {coluna} TEXT"))


def _agora() -> str:
    return fuso.agora().replace(tzinfo=None).isoformat(timespec="seconds")


# ---------- gastos ----------

def adicionar_gasto(engine: Engine, usuario: int, valor: float, categoria: str,
                    descricao: str | None, data: str, mensagem: str,
                    grupo: str | None = None, compra: str | None = None) -> int:
    with engine.begin() as con:
        resultado = con.execute(
            text("INSERT INTO gastos (usuario, valor, categoria, descricao, data, mensagem, criado_em, grupo, compra) "
                 "VALUES (:usuario, :valor, :categoria, :descricao, :data, :mensagem, :criado_em, :grupo, :compra) "
                 "RETURNING id"),
            dict(usuario=usuario, valor=round(valor, 2), categoria=categoria, descricao=descricao,
                 data=data, mensagem=mensagem, criado_em=_agora(), grupo=grupo, compra=compra),
        )
        return resultado.scalar_one()


def buscar_gasto(engine: Engine, gasto_id: int, usuario: int) -> dict | None:
    """Busca um gasto só se ele pertencer ao usuário (ninguém mexe no gasto de outra pessoa)."""
    with engine.connect() as con:
        linha = con.execute(
            text("SELECT * FROM gastos WHERE id = :id AND usuario = :usuario"),
            dict(id=gasto_id, usuario=usuario),
        ).mappings().first()
    return _como_dict(linha)


def mudar_categoria(engine: Engine, gasto_id: int, usuario: int, categoria: str) -> int:
    """Muda a categoria de um gasto; numa compra parcelada, muda todas as parcelas. Devolve quantas mudaram."""
    with engine.begin() as con:
        gasto = con.execute(text("SELECT compra FROM gastos WHERE id = :id AND usuario = :u"),
                            dict(id=gasto_id, u=usuario)).mappings().first()
        if gasto is None:
            return 0
        if gasto["compra"]:
            filtro, parametros = "compra = :compra", dict(compra=gasto["compra"])
        else:
            filtro, parametros = "id = :id", dict(id=gasto_id)
        return con.execute(text(f"UPDATE gastos SET categoria = :categoria WHERE usuario = :u AND {filtro}"),
                           dict(categoria=categoria, u=usuario, **parametros)).rowcount


def desfazer_ultimo(engine: Engine, usuario: int) -> list[dict]:
    """Apaga o último registro do usuário: todos os gastos da última mensagem, parcelas incluídas."""
    with engine.begin() as con:
        ultimo = con.execute(
            text("SELECT * FROM gastos WHERE usuario = :usuario ORDER BY id DESC LIMIT 1"),
            dict(usuario=usuario),
        ).mappings().first()
        if ultimo is None:
            return []
        if ultimo["grupo"]:
            filtro, parametros = "grupo = :grupo", dict(grupo=ultimo["grupo"])
        else:  # gastos salvos por versões antigas não têm grupo
            filtro, parametros = "id = :id", dict(id=ultimo["id"])
        apagados = con.execute(
            text(f"SELECT * FROM gastos WHERE usuario = :usuario AND {filtro} ORDER BY id"),
            dict(usuario=usuario, **parametros),
        ).mappings().all()
        con.execute(text(f"DELETE FROM gastos WHERE usuario = :usuario AND {filtro}"),
                    dict(usuario=usuario, **parametros))
    return [_como_dict(g) for g in apagados]


def total_por_categoria(engine: Engine, usuario: int, mes: str,
                        ate: str | None = None, depois_de: str | None = None) -> list[dict]:
    """Total e quantidade por categoria num mês (AAAA-MM), do maior para o menor.

    ate / depois_de (AAAA-MM-DD) separam o que já foi gasto do que está previsto.
    """
    filtros, parametros = [], dict(usuario=usuario, mes=mes)
    if ate:
        filtros.append("AND data <= :ate")
        parametros["ate"] = ate
    if depois_de:
        filtros.append("AND data > :depois_de")
        parametros["depois_de"] = depois_de
    with engine.connect() as con:
        linhas = con.execute(
            text("SELECT categoria, SUM(valor) AS total, COUNT(*) AS quantidade FROM gastos "
                 f"WHERE usuario = :usuario AND substr(data, 1, 7) = :mes {' '.join(filtros)} "
                 "GROUP BY categoria ORDER BY total DESC"),
            parametros,
        ).mappings().all()
    return [_como_dict(l) for l in linhas]


def listar_gastos(engine: Engine, usuario: int) -> list[dict]:
    with engine.connect() as con:
        linhas = con.execute(
            text("SELECT data, valor, categoria, descricao FROM gastos "
                 "WHERE usuario = :usuario ORDER BY data, id"),
            dict(usuario=usuario),
        ).mappings().all()
    return [_como_dict(l) for l in linhas]


def apagar_dados_do_usuario(engine: Engine, usuario: int) -> int:
    """Apaga todos os gastos e o histórico de interações de um usuário (LGPD)."""
    with engine.begin() as con:
        apagados = con.execute(text("DELETE FROM gastos WHERE usuario = :u"), dict(u=usuario)).rowcount
        con.execute(text("DELETE FROM interacoes WHERE usuario = :u"), dict(u=usuario))
    return apagados


# ---------- interações (métricas) ----------

def registrar_interacao(engine: Engine, usuario: int, tipo: str, mensagem: str | None = None,
                        interpretacao: dict | None = None, modelo: str | None = None,
                        latencia_ms: int | None = None, erro: str | None = None):
    with engine.begin() as con:
        con.execute(
            text("INSERT INTO interacoes (quando, usuario, tipo, mensagem, interpretacao, modelo, latencia_ms, erro) "
                 "VALUES (:quando, :usuario, :tipo, :mensagem, :interpretacao, :modelo, :latencia_ms, :erro)"),
            dict(quando=_agora(), usuario=usuario, tipo=tipo, mensagem=mensagem,
                 interpretacao=json.dumps(interpretacao, ensure_ascii=False) if interpretacao else None,
                 modelo=modelo, latencia_ms=latencia_ms, erro=erro),
        )


def _como_dict(linha) -> dict | None:
    if linha is None:
        return None
    d = dict(linha)
    for campo in ("valor", "total"):
        if d.get(campo) is not None:
            d[campo] = float(d[campo])  # PostgreSQL devolve Decimal; padronizo como float
    return d
