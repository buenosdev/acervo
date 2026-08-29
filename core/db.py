"""Banco SQLite do Acervo: schema, migracoes e conexao."""
from __future__ import annotations

import sqlite3
from pathlib import Path

VERSAO_SCHEMA = 2

SCHEMA = """
-- Um registro por arquivo .torrent lido do indice.
CREATE TABLE IF NOT EXISTS torrents (
    infohash        TEXT NOT NULL,
    caminho         TEXT PRIMARY KEY,          -- caminho do .torrent, relativo ao indice
    nome            TEXT NOT NULL,             -- campo `name` de dentro do torrent
    nome_arquivo    TEXT NOT NULL,             -- nome do .torrent no disco
    categoria       TEXT,                      -- pasta de topo: Filmes / Series / Jogos
    subcategoria    TEXT,                      -- genero: Acao, Terror, RPG...
    tamanho_total   INTEGER NOT NULL DEFAULT 0,
    n_arquivos      INTEGER NOT NULL DEFAULT 0,
    piece_length    INTEGER NOT NULL DEFAULT 0,
    privado         INTEGER NOT NULL DEFAULT 0,
    n_trackers      INTEGER NOT NULL DEFAULT 0,
    trackers        TEXT,                      -- URLs separadas por quebra de linha
    bytes_torrent   INTEGER NOT NULL DEFAULT 0,
    criado_em       INTEGER,
    corrompido      INTEGER NOT NULL DEFAULT 0,
    erro            TEXT,
    item_id         INTEGER REFERENCES itens(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_torrents_infohash ON torrents(infohash);
CREATE INDEX IF NOT EXISTS ix_torrents_item     ON torrents(item_id);

-- Arquivos de dentro de cada torrent. `indice` e a posicao que o qBittorrent usa
-- em filePrio para marcar/desmarcar o download de cada arquivo.
CREATE TABLE IF NOT EXISTS torrent_files (
    caminho_torrent TEXT NOT NULL REFERENCES torrents(caminho) ON DELETE CASCADE,
    indice          INTEGER NOT NULL,
    caminho         TEXT NOT NULL,
    tamanho         INTEGER NOT NULL DEFAULT 0,
    tipo            TEXT NOT NULL,             -- midia | legenda | lixo | extra | arquivo_jogo
    PRIMARY KEY (caminho_torrent, indice)
);
CREATE INDEX IF NOT EXISTS ix_files_tipo ON torrent_files(tipo);

-- A obra em si: um filme, uma serie inteira, um jogo. Varios torrents apontam para ela.
CREATE TABLE IF NOT EXISTS itens (
    id              INTEGER PRIMARY KEY,
    tipo            TEXT NOT NULL,             -- filme | serie | jogo
    chave           TEXT NOT NULL,             -- chave normalizada de agrupamento
    titulo          TEXT NOT NULL,
    titulo_corrigido TEXT,                     -- correcao manual feita na interface
    ano             INTEGER,
    tmdb_id         INTEGER,
    igdb_id         INTEGER,
    sinopse         TEXT,
    nota            REAL,
    generos         TEXT,
    poster          TEXT,                      -- caminho do arquivo em dados/posters
    backdrop        TEXT,                      -- imagem larga de fundo da tela de detalhes
    fixado          INTEGER NOT NULL DEFAULT 0,-- convencao "! NAO APAGAR"
    etiquetas       TEXT,
    atualizado_em   TEXT,
    UNIQUE (tipo, chave)
);

-- Dados por release: liga o torrent a temporada/episodio/qualidade.
CREATE TABLE IF NOT EXISTS item_torrents (
    caminho_torrent TEXT PRIMARY KEY REFERENCES torrents(caminho) ON DELETE CASCADE,
    item_id         INTEGER NOT NULL REFERENCES itens(id) ON DELETE CASCADE,
    temporada       INTEGER,
    episodios       TEXT,                      -- "1,2,3"
    temporada_completa INTEGER NOT NULL DEFAULT 0,
    qualidade       TEXT,
    fonte           TEXT,
    codec           TEXT,
    idioma          TEXT,
    hdr             TEXT,
    audio           TEXT,
    grupo           TEXT
);
CREATE INDEX IF NOT EXISTS ix_item_torrents_item ON item_torrents(item_id);

-- O que esta fisicamente no disco agora.
CREATE TABLE IF NOT EXISTS disco (
    caminho_local   TEXT PRIMARY KEY,
    infohash        TEXT,
    caminho_torrent TEXT,
    estado          TEXT NOT NULL,             -- indice | parcial | completo | orfao
    bytes_presentes INTEGER NOT NULL DEFAULT 0,
    bytes_esperados INTEGER NOT NULL DEFAULT 0,
    fixado          INTEGER NOT NULL DEFAULT 0,
    gerenciado      INTEGER NOT NULL DEFAULT 0,-- baixado pelo Acervo (via qBittorrent)
    visto_em        TEXT,
    conferido_em    TEXT
);
CREATE INDEX IF NOT EXISTS ix_disco_infohash ON disco(infohash);
CREATE INDEX IF NOT EXISTS ix_disco_estado   ON disco(estado);

-- Seeders por infohash, com data: apagar midia so e seguro se o torrent estiver vivo.
CREATE TABLE IF NOT EXISTS seed_health (
    infohash        TEXT PRIMARY KEY,
    seeders         INTEGER,
    leechers        INTEGER,
    origem          TEXT,                      -- tracker | qbittorrent
    checado_em      TEXT
);

CREATE TABLE IF NOT EXISTS config (
    chave           TEXT PRIMARY KEY,
    valor           TEXT
);
"""


def conectar(caminho_db: str | Path) -> sqlite3.Connection:
    """Abre (criando se preciso) o banco e garante o schema."""
    caminho_db = Path(caminho_db)
    caminho_db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho_db)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    _migrar(con)
    con.execute(
        "INSERT INTO config (chave, valor) VALUES ('versao_schema', ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
        (str(VERSAO_SCHEMA),),
    )
    con.commit()
    return con


def _migrar(con: sqlite3.Connection) -> None:
    """Acrescenta colunas novas a bancos criados por versoes anteriores.

    CREATE TABLE IF NOT EXISTS nao altera tabela que ja existe, entao quem ja
    usava o app perderia a coluna nova e o app quebraria na primeira consulta.
    """
    colunas = {l[1] for l in con.execute("PRAGMA table_info(itens)")}
    if "backdrop" not in colunas:
        con.execute("ALTER TABLE itens ADD COLUMN backdrop TEXT")
    con.commit()


def ler_config(con: sqlite3.Connection, chave: str, padrao: str | None = None) -> str | None:
    linha = con.execute("SELECT valor FROM config WHERE chave = ?", (chave,)).fetchone()
    return linha["valor"] if linha else padrao


def gravar_config(con: sqlite3.Connection, chave: str, valor: str) -> None:
    con.execute(
        "INSERT INTO config (chave, valor) VALUES (?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
        (chave, valor),
    )
    con.commit()
