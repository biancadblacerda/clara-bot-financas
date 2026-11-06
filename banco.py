"""Armazenamento dos gastos em SQLite (um arquivo local, sem servidor)."""
import sqlite3
from datetime import datetime

ARQUIVO_BANCO = "gastos.db"


def conectar(caminho: str = ARQUIVO_BANCO) -> sqlite3.Connection:
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE IF NOT EXISTS gastos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario     INTEGER NOT NULL,
            valor       REAL    NOT NULL,
            categoria   TEXT    NOT NULL,
            descricao   TEXT,
            data        TEXT    NOT NULL,   -- AAAA-MM-DD
            mensagem    TEXT,               -- frase original, útil para auditar erros do LLM
            criado_em   TEXT    NOT NULL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_usuario_data ON gastos (usuario, data)")
    return con


def adicionar_gasto(con, usuario: int, valor: float, categoria: str,
                    descricao: str | None, data: str, mensagem: str) -> int:
    cur = con.execute(
        "INSERT INTO gastos (usuario, valor, categoria, descricao, data, mensagem, criado_em) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (usuario, valor, categoria, descricao, data, mensagem, datetime.now().isoformat(timespec="seconds")),
    )
    con.commit()
    return cur.lastrowid


def desfazer_ultimo(con, usuario: int) -> sqlite3.Row | None:
    """Apaga o gasto registrado por último pelo usuário e devolve o que foi apagado."""
    ultimo = con.execute(
        "SELECT * FROM gastos WHERE usuario = ? ORDER BY id DESC LIMIT 1", (usuario,)
    ).fetchone()
    if ultimo:
        con.execute("DELETE FROM gastos WHERE id = ?", (ultimo["id"],))
        con.commit()
    return ultimo


def total_por_categoria(con, usuario: int, mes: str) -> list[sqlite3.Row]:
    """Total e quantidade de gastos por categoria num mês (AAAA-MM), do maior para o menor."""
    return con.execute(
        "SELECT categoria, SUM(valor) AS total, COUNT(*) AS quantidade FROM gastos "
        "WHERE usuario = ? AND substr(data, 1, 7) = ? "
        "GROUP BY categoria ORDER BY total DESC",
        (usuario, mes),
    ).fetchall()
