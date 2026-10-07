"""Controle do que ja foi encontrado, baixado e processado (SQLite).

Por que SQLite e nao o control.duckdb do lake: o DuckDB aceita um unico
processo escritor por arquivo, e as cargas de 6x/dia seguram esse arquivo. A
RPA roda em outro horario/processo e nao pode brigar pela trava. SQLite vem com
o Python, aguenta um leitor olhando enquanto grava e abre em qualquer
visualizador (DB Browser for SQLite).

Identidade de um arquivo do portal = (ano, mes, regional, DN, nome). Como o
portal pode renomear arquivos, o SHA-256 do PDF baixado tambem e guardado: um
arquivo "novo" com o mesmo conteudo de outro ja processado e reconhecido e nao
entra de novo na planilha.

Status de um arquivo:
    encontrado  -> listado no portal, ainda nao baixado
    baixado     -> PDF salvo e validado, ainda nao lancado na planilha
    processado  -> dados lancados na planilha (fim)
    duplicado   -> mesmo conteudo de outro arquivo ja processado (fim)
    erro        -> falhou; tentado de novo na proxima execucao
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .valores import normalizar_texto

FINAIS = ("processado", "duplicado")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS arquivos (
    id               TEXT PRIMARY KEY,
    ano              INTEGER,
    mes              INTEGER,
    regional         TEXT,
    dn               TEXT,
    nome             TEXT,
    status           TEXT NOT NULL DEFAULT 'encontrado',
    tentativas       INTEGER NOT NULL DEFAULT 0,
    sha256           TEXT,
    caminho_pdf      TEXT,
    layout           TEXT,
    duplicado_de     TEXT,
    erro             TEXT,
    encontrado_em    TEXT NOT NULL,
    visto_em         TEXT NOT NULL,
    baixado_em       TEXT,
    processado_em    TEXT
);
CREATE INDEX IF NOT EXISTS ix_arquivos_sha ON arquivos(sha256);
CREATE TABLE IF NOT EXISTS registros (
    arquivo_id   TEXT NOT NULL,
    chave        TEXT NOT NULL,          -- a SG
    dados        TEXT NOT NULL,          -- JSON com todos os campos extraidos
    acao         TEXT NOT NULL,          -- inserida | atualizada | sem_mudanca | divergente
    detalhe      TEXT,
    registrado_em TEXT NOT NULL,
    PRIMARY KEY (arquivo_id, chave)
);
CREATE TABLE IF NOT EXISTS execucoes (
    run_id       TEXT PRIMARY KEY,
    inicio       TEXT NOT NULL,
    fim          TEXT,
    status       TEXT,
    resumo       TEXT
);
"""


def agora() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def id_arquivo(ano: Any, mes: Any, regional: Any, dn: Any, nome: Any) -> str:
    """Identificador estavel de um item da lista (independe da ordem na tela)."""
    partes = [normalizar_texto(str(x if x is not None else "")) for x in (ano, mes, regional, dn, nome)]
    return hashlib.sha1("|".join(partes).encode("utf-8")).hexdigest()[:16]


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with Path(caminho).open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


@dataclass
class ItemLista:
    """Uma linha da 'Lista de arquivos' do portal."""

    ano: int
    mes: int
    regional: str
    dn: str
    nome: str
    indice: int = 0  # posicao na tabela (so para achar o link de novo)
    id_fixo: str | None = None  # importacao manual: identidade pelo conteudo do PDF

    @property
    def id(self) -> str:
        return self.id_fixo or id_arquivo(self.ano, self.mes, self.regional, self.dn, self.nome)

    @property
    def rotulo(self) -> str:
        return f"{self.ano}-{self.mes:02d} DN {self.dn} {self.nome}"


class Controle:
    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as con:
            con.executescript(_SCHEMA)

    @contextmanager
    def _con(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.caminho, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------- execucao
    def iniciar_execucao(self, run_id: str) -> None:
        with self._con() as con:
            con.execute("INSERT INTO execucoes(run_id, inicio) VALUES (?, ?)", (run_id, agora()))

    def finalizar_execucao(self, run_id: str, status: str, resumo: dict[str, Any]) -> None:
        with self._con() as con:
            con.execute(
                "UPDATE execucoes SET fim=?, status=?, resumo=? WHERE run_id=?",
                (agora(), status, json.dumps(resumo, ensure_ascii=False), run_id),
            )

    # --------------------------------------------------------------- arquivos
    def registrar_listagem(self, itens: list[ItemLista]) -> None:
        momento = agora()
        with self._con() as con:
            for it in itens:
                con.execute(
                    """
                    INSERT INTO arquivos(id, ano, mes, regional, dn, nome, encontrado_em, visto_em)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET visto_em = excluded.visto_em
                    """,
                    (it.id, it.ano, it.mes, it.regional, it.dn, it.nome, momento, momento),
                )

    def status(self, arquivo_id: str) -> sqlite3.Row | None:
        with self._con() as con:
            return con.execute("SELECT * FROM arquivos WHERE id=?", (arquivo_id,)).fetchone()

    def pendentes(self, itens: list[ItemLista]) -> list[ItemLista]:
        """Itens ainda nao finalizados, do mais antigo para o mais novo."""
        faltam = []
        for it in itens:
            linha = self.status(it.id)
            if linha is None or linha["status"] not in FINAIS:
                faltam.append(it)
        return sorted(faltam, key=lambda i: (i.ano, i.mes, normalizar_texto(i.nome)))

    def processado_com_hash(self, sha: str, exceto: str) -> str | None:
        with self._con() as con:
            linha = con.execute(
                "SELECT id FROM arquivos WHERE sha256=? AND status='processado' AND id<>? LIMIT 1",
                (sha, exceto),
            ).fetchone()
        return linha["id"] if linha else None

    def marcar_baixado(self, arquivo_id: str, sha: str, caminho: Path) -> None:
        with self._con() as con:
            con.execute(
                "UPDATE arquivos SET status='baixado', sha256=?, caminho_pdf=?, baixado_em=?, erro=NULL "
                "WHERE id=?",
                (sha, str(caminho), agora(), arquivo_id),
            )

    def marcar_duplicado(self, arquivo_id: str, original: str) -> None:
        with self._con() as con:
            con.execute(
                "UPDATE arquivos SET status='duplicado', duplicado_de=?, processado_em=? WHERE id=?",
                (original, agora(), arquivo_id),
            )

    def marcar_processado(self, arquivo_id: str, layout: str, registros: list[dict[str, Any]]) -> None:
        """registros: [{'chave','dados','acao','detalhe'}] -- o que foi feito na planilha."""
        momento = agora()
        with self._con() as con:
            for r in registros:
                con.execute(
                    """
                    INSERT INTO registros(arquivo_id, chave, dados, acao, detalhe, registrado_em)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(arquivo_id, chave) DO UPDATE SET
                        dados=excluded.dados, acao=excluded.acao,
                        detalhe=excluded.detalhe, registrado_em=excluded.registrado_em
                    """,
                    (arquivo_id, r["chave"], json.dumps(r["dados"], ensure_ascii=False, default=str),
                     r["acao"], r.get("detalhe"), momento),
                )
            con.execute(
                "UPDATE arquivos SET status='processado', layout=?, processado_em=?, erro=NULL WHERE id=?",
                (layout, momento, arquivo_id),
            )

    def marcar_erro(self, arquivo_id: str, motivo: str) -> None:
        with self._con() as con:
            con.execute(
                "UPDATE arquivos SET status='erro', erro=?, tentativas=tentativas+1 WHERE id=?",
                (motivo, arquivo_id),
            )

    def contagem(self) -> dict[str, int]:
        with self._con() as con:
            linhas = con.execute("SELECT status, COUNT(*) n FROM arquivos GROUP BY status").fetchall()
        return {l["status"]: l["n"] for l in linhas}

    def processados_por_mes(self, dn: str) -> dict[tuple[int, int], int]:
        with self._con() as con:
            linhas = con.execute(
                "SELECT ano, mes, COUNT(*) n FROM arquivos WHERE dn=? AND status IN ('processado','duplicado') "
                "GROUP BY ano, mes", (dn,),
            ).fetchall()
        return {(l["ano"], l["mes"]): l["n"] for l in linhas}
