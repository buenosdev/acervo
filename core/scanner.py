"""Varre a pasta de indice (! TORRENT) e popula o banco.

Nao escreve, move nem apaga nada na pasta do usuario: so le os .torrent.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import bencode
from .release import (FILME, JOGO, SERIE, analisar, chave_busca, classificar_arquivo,
                      maior_e_video, parece_jogo)

# Pasta de topo do indice -> tipo de obra.
DICA_POR_PASTA = {
    "filmes": FILME,
    "series": SERIE,
    "séries": SERIE,
    "jogos": JOGO,
    "games": JOGO,
}
# Pasta de trabalho do usuario: itens ali ainda nao foram classificados.
PASTA_DUPLICADOS = "_duplicados"


@dataclass
class Resumo:
    lidos: int = 0
    corrompidos: int = 0
    bytes_indexados: int = 0
    bytes_torrents: int = 0
    infohashes: set[str] = field(default_factory=set)
    itens_criados: int = 0
    arquivos_lixo: int = 0
    bytes_lixo: int = 0
    sem_tracker: int = 0
    erros: list[tuple[str, str]] = field(default_factory=list)

    @property
    def duplicados(self) -> int:
        return self.lidos - self.corrompidos - len(self.infohashes)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _categoria(rel: Path) -> tuple[str | None, str | None, str | None]:
    """Devolve (categoria, subcategoria, dica_de_tipo) a partir do caminho relativo."""
    partes = rel.parts[:-1]  # sem o nome do arquivo
    if not partes:
        return None, None, None
    topo = partes[0]
    if topo.lower() == PASTA_DUPLICADOS:
        return topo, None, None  # sem dica: tipo sai do proprio nome
    sub = partes[1] if len(partes) > 1 else None
    return topo, sub, DICA_POR_PASTA.get(topo.lower())


def _chave_item(rel, tipo: str) -> str:
    """Filmes agrupam por titulo+ano; series e jogos so por titulo (varias temporadas)."""
    base = chave_busca(rel.titulo)
    if tipo == FILME and rel.ano:
        return f"{base}|{rel.ano}"
    return base


def _garantir_item(con: sqlite3.Connection, tipo: str, chave: str, titulo: str,
                   ano: int | None) -> tuple[int, bool]:
    linha = con.execute(
        "SELECT id, ano FROM itens WHERE tipo = ? AND chave = ?", (tipo, chave)
    ).fetchone()
    if linha:
        # Uma serie sem ano no nome pode ganhar o ano de outro release depois.
        if ano and not linha["ano"]:
            con.execute("UPDATE itens SET ano = ? WHERE id = ?", (ano, linha["id"]))
        return linha["id"], False
    cur = con.execute(
        "INSERT INTO itens (tipo, chave, titulo, ano, atualizado_em) VALUES (?, ?, ?, ?, ?)",
        (tipo, chave, titulo, ano, _agora()),
    )
    return int(cur.lastrowid), True


def varrer(con: sqlite3.Connection, raiz_indice: str | Path) -> Resumo:
    """Le todos os .torrent sob `raiz_indice` e regrava as tabelas do indice."""
    raiz = Path(raiz_indice)
    resumo = Resumo()
    item_por_infohash: dict[str, int] = {}

    # O indice e a fonte da verdade: reconstroi do zero a cada varredura.
    con.execute("DELETE FROM item_torrents")
    con.execute("DELETE FROM torrent_files")
    con.execute("DELETE FROM torrents")

    for caminho in sorted(raiz.rglob("*.torrent")):
        rel = caminho.relative_to(raiz)
        chave_caminho = rel.as_posix()
        categoria, subcategoria, dica = _categoria(rel)
        resumo.lidos += 1

        try:
            t = bencode.ler(caminho)
        except (bencode.BencodeInvalido, OSError) as erro:
            resumo.corrompidos += 1
            resumo.erros.append((chave_caminho, str(erro)))
            con.execute(
                "INSERT INTO torrents (infohash, caminho, nome, nome_arquivo, categoria, "
                "subcategoria, corrompido, erro) VALUES ('', ?, ?, ?, ?, ?, 1, ?)",
                (chave_caminho, caminho.stem, caminho.name, categoria, subcategoria, str(erro)),
            )
            continue

        # O nome do arquivo costuma ser mais descritivo que o `name` de dentro do
        # torrent (que as vezes e so "filme.mkv"); o mais longo ganha.
        base = caminho.name if len(caminho.stem) >= len(t.nome) else t.nome
        rel_info = analisar(base, dica)
        tipo = rel_info.tipo
        # O conteudo manda, nos dois sentidos.
        conteudo = [(a.caminho, a.tamanho) for a in t.arquivos]
        if maior_e_video(conteudo):
            # Nenhuma pista do nome vence um .mkv de 2,7 GB. Era assim que o
            # "M3GAN.2.0.2025...mkv" ia parar entre os jogos: o "2.0.2025"
            # passava por numero de versao, e dai todo arquivo do torrent virava
            # "arquivo_jogo" — inclusive o proprio filme.
            if tipo == JOGO:
                tipo = rel_info.tipo = (
                    SERIE if rel_info.temporada is not None else FILME)
        elif tipo != JOGO and parece_jogo(conteudo):
            # E o contrario: um torrent so de .rar/.iso e jogo mesmo que esteja
            # solto em _Duplicados, e assim nenhum arquivo dele e desmarcado.
            tipo = rel_info.tipo = JOGO
        # Mesmo infohash e literalmente o mesmo conteudo: uma obra so, mesmo que
        # os dois arquivos tenham nomes diferentes ou estejam em pastas diferentes.
        # A pasta categorizada vem antes de _Duplicados na ordem alfabetica, entao
        # e ela quem define titulo e tipo.
        if t.infohash in item_por_infohash:
            item_id = item_por_infohash[t.infohash]
        else:
            chave = _chave_item(rel_info, tipo)
            item_id, novo = _garantir_item(con, tipo, chave, rel_info.titulo, rel_info.ano)
            item_por_infohash[t.infohash] = item_id
            if novo:
                resumo.itens_criados += 1

        con.execute(
            "INSERT INTO torrents (infohash, caminho, nome, nome_arquivo, categoria, "
            "subcategoria, tamanho_total, n_arquivos, piece_length, privado, n_trackers, "
            "trackers, bytes_torrent, criado_em, corrompido, item_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (t.infohash, chave_caminho, t.nome, caminho.name, categoria, subcategoria,
             t.tamanho_total, len(t.arquivos), t.piece_length, int(t.privado),
             len(t.trackers), "\n".join(t.trackers) or None,
             t.tamanho_arquivo_torrent, t.criado_em, item_id),
        )
        con.execute(
            "INSERT INTO item_torrents (caminho_torrent, item_id, temporada, episodios, "
            "temporada_completa, qualidade, fonte, codec, idioma, hdr, audio, grupo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (chave_caminho, item_id, rel_info.temporada,
             ",".join(str(e) for e in rel_info.episodios) or None,
             int(rel_info.temporada_completa), rel_info.qualidade, rel_info.fonte,
             rel_info.codec, rel_info.idioma, ",".join(rel_info.hdr) or None,
             rel_info.audio, rel_info.grupo),
        )

        for a in t.arquivos:
            tipo_arq = classificar_arquivo(a.caminho, tipo, a.tamanho)
            if tipo_arq == "lixo":
                resumo.arquivos_lixo += 1
                resumo.bytes_lixo += a.tamanho
            con.execute(
                "INSERT INTO torrent_files (caminho_torrent, indice, caminho, tamanho, tipo) "
                "VALUES (?, ?, ?, ?, ?)",
                (chave_caminho, a.indice, a.caminho, a.tamanho, tipo_arq),
            )

        resumo.infohashes.add(t.infohash)
        resumo.bytes_indexados += t.tamanho_total
        resumo.bytes_torrents += t.tamanho_arquivo_torrent
        if not t.trackers:
            resumo.sem_tracker += 1

    # Itens que ficaram sem nenhum torrent apos a regravacao.
    con.execute("DELETE FROM itens WHERE id NOT IN (SELECT item_id FROM torrents "
                "WHERE item_id IS NOT NULL)")
    con.commit()
    return resumo


def _ordem_canonica(caminho: str) -> tuple[int, str]:
    """O arquivo em pasta de genero e o canonico; o de _Duplicados vem por ultimo."""
    em_duplicados = caminho.split("/", 1)[0].lower() == PASTA_DUPLICADOS
    return (1 if em_duplicados else 0, caminho)


def grupos_duplicados(con: sqlite3.Connection) -> list[tuple[str, list[str]]]:
    """Infohashes com mais de um .torrent apontando para eles.

    Dentro de cada grupo o primeiro e o que vale a pena manter.
    """
    linhas = con.execute(
        "SELECT infohash, GROUP_CONCAT(caminho, char(10)) AS caminhos, COUNT(*) AS n "
        "FROM torrents WHERE corrompido = 0 AND infohash != '' "
        "GROUP BY infohash HAVING n > 1"
    ).fetchall()
    grupos = [(l["infohash"], sorted(l["caminhos"].split("\n"), key=_ordem_canonica))
              for l in linhas]
    grupos.sort(key=lambda g: g[1][0])
    return grupos


def duplicados_falsos(con: sqlite3.Connection) -> list[sqlite3.Row]:
    """Arquivos em _Duplicados que nao tem copia em nenhuma outra pasta.

    Sao releases diferentes da mesma obra, nao duplicatas: apagar a pasta os perderia.
    """
    return con.execute(
        "SELECT t.caminho, t.nome, t.tamanho_total, i.titulo FROM torrents t "
        "LEFT JOIN itens i ON i.id = t.item_id "
        "WHERE t.corrompido = 0 AND lower(t.categoria) = ? "
        "  AND t.infohash NOT IN ("
        "      SELECT infohash FROM torrents "
        "      WHERE corrompido = 0 AND lower(coalesce(categoria, '')) != ?) "
        "ORDER BY t.caminho",
        (PASTA_DUPLICADOS, PASTA_DUPLICADOS),
    ).fetchall()


def reclassificar(con: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Revisa o tipo das obras ja catalogadas usando o conteudo do torrent.

    Ate aqui o tipo era decidido na varredura e nunca mais revisto. Quem entrou
    errado — "M3GAN.2.0.2025.mkv" lido como jogo porque "2.0.2025" parecia
    versao — ficava errado para sempre, na estante errada e sem capa, ja que a
    busca de capa de jogo consulta outra base.

    Devolve [(titulo, de, para)] do que mudou. Nao toca em disco nem em rede.
    """
    mudancas: list[tuple[str, str, str]] = []

    for item in con.execute(
        "SELECT id, tipo, COALESCE(NULLIF(titulo_corrigido,''), titulo) titulo "
        "FROM itens"
    ).fetchall():
        arquivos = [
            (l["caminho"], l["tamanho"])
            for l in con.execute(
                "SELECT f.caminho, f.tamanho FROM torrent_files f "
                "JOIN torrents t ON t.caminho = f.caminho_torrent "
                "WHERE t.item_id = ? AND t.corrompido = 0", (item["id"],))
        ]
        if not arquivos:
            continue

        atual = item["tipo"]
        if maior_e_video(arquivos):
            if atual != JOGO:
                continue
            # Serie ou filme: quem tem varios videos grandes e serie.
            grandes = sum(1 for c, t in arquivos
                          if t > 100 * 1024 * 1024 and maior_e_video([(c, t)]))
            novo = SERIE if grandes > 2 else FILME
        elif atual != JOGO and parece_jogo(arquivos):
            novo = JOGO
        else:
            continue

        con.execute("UPDATE itens SET tipo = ? WHERE id = ?", (novo, item["id"]))
        # O tipo do item decide como cada arquivo e classificado: em jogo nada e
        # desmarcado, em filme a propaganda e. Reclassificar sem isto deixaria o
        # .mkv marcado como "arquivo_jogo".
        for t in con.execute(
                "SELECT caminho FROM torrents WHERE item_id = ?", (item["id"],)):
            for f in con.execute(
                    "SELECT caminho, tamanho FROM torrent_files "
                    "WHERE caminho_torrent = ?", (t["caminho"],)).fetchall():
                con.execute(
                    "UPDATE torrent_files SET tipo = ? "
                    "WHERE caminho_torrent = ? AND caminho = ?",
                    (classificar_arquivo(f["caminho"], novo, f["tamanho"]),
                     t["caminho"], f["caminho"]))
        mudancas.append((item["titulo"], atual, novo))

    con.commit()
    return mudancas
