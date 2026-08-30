"""Consultas do catalogo, compartilhadas pela janela e pelo servidor.

Ficam aqui para que as duas interfaces mostrem exatamente os mesmos numeros -
se a regra de "o que conta como no disco" mudasse em um lugar so, as telas
passariam a discordar entre si.
"""
from __future__ import annotations

import sqlite3

from .release import chave_busca

_RANK = "CASE d.estado WHEN 'completo' THEN 3 WHEN 'parcial' THEN 2 ELSE 1 END"
_ESTADO_POR_RANK = {3: "completo", 2: "parcial", 1: "indice"}

SQL_ITENS = f"""
SELECT i.id, i.tipo, COALESCE(NULLIF(i.titulo_corrigido, ''), i.titulo) AS titulo,
       i.ano, i.poster, i.nota, i.generos, i.fixado, i.sinopse, i.backdrop,
       COUNT(DISTINCT t.caminho)           AS n_torrents,
       COALESCE(SUM(t.tamanho_total), 0)   AS bytes_total,
       COALESCE(MAX({_RANK}), 1)           AS rank_estado,
       COALESCE(SUM(d.bytes_presentes), 0) AS bytes_no_disco,
       GROUP_CONCAT(DISTINCT it.qualidade) AS qualidades,
       GROUP_CONCAT(DISTINCT it.idioma)    AS idiomas,
       MAX(it.temporada)                   AS temporadas,
       MAX(s.seeders)                      AS seeders
FROM itens i
LEFT JOIN torrents t       ON t.item_id = i.id AND t.corrompido = 0
LEFT JOIN item_torrents it ON it.caminho_torrent = t.caminho
LEFT JOIN disco d          ON d.caminho_torrent = t.caminho
LEFT JOIN seed_health s    ON s.infohash = t.infohash
GROUP BY i.id
"""


def _linha(l: sqlite3.Row) -> dict:
    return {
        "id": l["id"], "tipo": l["tipo"], "titulo": l["titulo"], "ano": l["ano"],
        "poster": l["poster"], "nota": l["nota"], "generos": l["generos"],
        "fixado": bool(l["fixado"]), "n_torrents": l["n_torrents"],
        "bytes_total": l["bytes_total"], "bytes_no_disco": l["bytes_no_disco"],
        "estado": _ESTADO_POR_RANK.get(l["rank_estado"], "indice"),
        "qualidades": sorted({q for q in (l["qualidades"] or "").split(",") if q}),
        "idiomas": sorted({q for q in (l["idiomas"] or "").split(",") if q}),
        "temporadas": l["temporadas"], "seeders": l["seeders"],
        # A previa ao passar o mouse mostra imagem de fundo e sinopse; sem
        # elas aqui, cada previa faria uma consulta ao banco.
        "backdrop": l["backdrop"] if "backdrop" in l.keys() else None,
        "sinopse": l["sinopse"] if "sinopse" in l.keys() else None,
    }


ORDENS = {
    "titulo": lambda x: (x["titulo"] or "").lower(),
    "ano": lambda x: -(x["ano"] or 0),
    "tamanho": lambda x: -x["bytes_total"],
    "disco": lambda x: -x["bytes_no_disco"],
}


def listar(con: sqlite3.Connection, tipo: str = "", estado: str = "",
           busca: str = "", ordem: str = "titulo",
           no_cliente: dict[int, str] | None = None) -> list[dict]:
    """Lista as obras do catalogo.

    `no_cliente` mapeia id da obra para "baixando" ou "pausado" segundo o
    cliente de torrent. Ele tem a ultima palavra sobre o estado: um torrent
    pausado no meio do caminho continua sendo um download em andamento, mesmo
    que no disco ele seja apenas um arquivo incompleto — e um pausado com tudo
    baixado nao devia sumir para "No disco" enquanto o cliente ainda o segura.
    """
    linhas = [_linha(l) for l in con.execute(SQL_ITENS)]
    for x in linhas:
        vindo = (no_cliente or {}).get(x["id"])
        if vindo:
            x["estado"] = vindo
    if tipo:
        linhas = [x for x in linhas if x["tipo"] == tipo]
    if estado:
        # "Baixando" na barra lateral abrange os tres jeitos de estar no meio do
        # caminho: baixando agora, pausado no cliente, ou um arquivo incompleto
        # no disco de um download que ninguem esta mais segurando.
        alvos = ({"parcial", "baixando", "pausado"} if estado == "parcial"
                 else {estado})
        linhas = [x for x in linhas if x["estado"] in alvos]
    if busca.strip():
        alvo = chave_busca(busca)
        linhas = [x for x in linhas if alvo in chave_busca(x["titulo"])]
    linhas.sort(key=ORDENS.get(ordem, ORDENS["titulo"]))
    return linhas


def detalhe(con: sqlite3.Connection, item_id: int) -> dict | None:
    item = con.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
    if not item:
        return None

    releases = []
    for t in con.execute(
        "SELECT t.caminho, t.nome, t.infohash, t.tamanho_total, t.n_arquivos, "
        "       t.n_trackers, t.categoria, t.subcategoria, it.temporada, it.episodios, "
        "       it.temporada_completa, it.qualidade, it.fonte, it.codec, it.idioma, "
        "       it.hdr, it.audio, it.grupo, d.estado, d.caminho_local, "
        "       d.bytes_presentes, s.seeders, s.checado_em "
        "FROM torrents t "
        "LEFT JOIN item_torrents it ON it.caminho_torrent = t.caminho "
        "LEFT JOIN disco d ON d.caminho_torrent = t.caminho "
        "LEFT JOIN seed_health s ON s.infohash = t.infohash "
        "WHERE t.item_id = ? AND t.corrompido = 0 "
        "ORDER BY it.temporada, it.episodios, t.nome", (item_id,)
    ):
        arquivos = con.execute(
            "SELECT indice, caminho, tamanho, tipo FROM torrent_files "
            "WHERE caminho_torrent = ? ORDER BY tamanho DESC", (t["caminho"],)
        ).fetchall()
        d = dict(t)
        d["estado"] = t["estado"] or "indice"
        d["arquivos"] = [dict(a) for a in arquivos]
        d["bytes_lixo"] = sum(a["tamanho"] for a in arquivos if a["tipo"] == "lixo")
        d["n_lixo"] = sum(1 for a in arquivos if a["tipo"] == "lixo")
        releases.append(d)

    return {"item": dict(item), "releases": releases}


def resumo(con: sqlite3.Connection, cfg) -> dict:
    def um(sql: str):
        linha = con.execute(sql).fetchone()
        return linha[0] if linha else 0

    estados = {
        l["estado"]: {"n": l["n"], "bytes": l["b"] or 0}
        for l in con.execute(
            "SELECT estado, COUNT(*) n, SUM(bytes_presentes) b FROM disco GROUP BY estado")
    }
    return {
        "itens": um("SELECT COUNT(*) FROM itens"),
        "por_tipo": {l["tipo"]: l["n"] for l in
                     con.execute("SELECT tipo, COUNT(*) n FROM itens GROUP BY tipo")},
        "torrents": um("SELECT COUNT(*) FROM torrents WHERE corrompido = 0"),
        "corrompidos": um("SELECT COUNT(*) FROM torrents WHERE corrompido = 1"),
        "bytes_indexados": um("SELECT COALESCE(SUM(tamanho_total),0) FROM torrents "
                              "WHERE corrompido = 0"),
        "bytes_indice": um("SELECT COALESCE(SUM(bytes_torrent),0) FROM torrents"),
        "sem_tracker": um("SELECT COUNT(*) FROM torrents WHERE corrompido = 0 "
                          "AND n_trackers = 0"),
        "arquivos_lixo": um("SELECT COUNT(*) FROM torrent_files WHERE tipo = 'lixo'"),
        "bytes_lixo": um("SELECT COALESCE(SUM(tamanho),0) FROM torrent_files "
                         "WHERE tipo='lixo'"),
        "sem_capa": um("SELECT COUNT(*) FROM itens WHERE poster IS NULL"),
        "estados": estados,
        "bytes_recuperaveis": um("SELECT COALESCE(SUM(bytes_presentes),0) FROM disco "
                                 "WHERE estado IN ('completo','parcial') AND fixado = 0"),
        "orfaos": estados.get("orfao", {"n": 0, "bytes": 0}),
        "biblioteca": str(cfg.biblioteca),
        "indice": str(cfg.indice),
        "configurado": cfg.configurado,
        "pendencias": cfg.pendencias(),
    }
