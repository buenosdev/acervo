"""Apagar arquivos de midia, escolhendo quais.

O app ja sabia liberar espaco de um release inteiro (`core/espaco.py`). Faltava
o caso comum: uma serie de vinte episodios em que voce quer apagar os cinco que
ja assistiu, e nao os vinte.

As travas continuam as mesmas, e nao sao formalidade:

  * **nada fora da biblioteca.** O caminho e conferido contra a raiz antes de
    qualquer `unlink`. Um caminho estranho no banco nao pode virar exclusao em
    qualquer lugar do disco;
  * **nada que ninguem mais semeie.** A premissa do app e que apagar e
    reversivel porque alguem compartilha o arquivo. Sem semeadores isso deixa
    de valer, e o app diz isso em vez de apagar calado. Quem quiser apagar assim
    mesmo precisa dizer explicitamente — e a interface pergunta com todas as
    letras.

Depois de apagar, a tabela `disco` e reconciliada: o catalogo precisa saber que
aquilo nao esta mais la.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import health, library


@dataclass
class Arquivo:
    """Um arquivo de midia que existe no disco agora."""

    caminho: Path
    rotulo: str                  # "T01E03" ou o nome limpo
    bytes: int
    caminho_torrent: str
    infohash: str


@dataclass
class Resultado:
    apagados: int = 0
    bytes: int = 0
    erros: list[str] = field(default_factory=list)


def listar(con: sqlite3.Connection, cfg, item_id: int) -> list[Arquivo]:
    """Os arquivos de midia desta obra que estao no disco, um a um."""
    saida: list[Arquivo] = []
    linhas = con.execute(
        "SELECT t.caminho, t.infohash, d.caminho_local, it.temporada, it.episodios "
        "FROM torrents t "
        "JOIN disco d ON d.caminho_torrent = t.caminho "
        "LEFT JOIN item_torrents it ON it.caminho_torrent = t.caminho "
        "WHERE t.item_id = ? AND d.estado IN ('completo','parcial') "
        "AND t.corrompido = 0", (item_id,)).fetchall()

    for linha in linhas:
        base = Path(linha["caminho_local"] or "")
        if not base.exists():
            continue
        midias = con.execute(
            "SELECT caminho, tamanho FROM torrent_files "
            "WHERE caminho_torrent = ? AND tipo = 'midia' ORDER BY caminho",
            (linha["caminho"],)).fetchall()
        # O nome no disco pode nao ser mais o do torrent: a organizacao
        # renomeia. `mapear_arquivos` casa por nome, marcador de episodio e,
        # em ultimo caso, tamanho.
        no_disco = library.mapear_arquivos(base, midias)

        for a in midias:
            real = no_disco.get(a["caminho"])
            if real is None or not real.is_file():
                continue
            saida.append(Arquivo(
                caminho=real, rotulo=_rotulo(real.name, linha["temporada"]),
                bytes=real.stat().st_size, caminho_torrent=linha["caminho"],
                infohash=linha["infohash"]))
    return saida


def _rotulo(nome: str, temporada) -> str:
    import re

    m = re.search(r"[Ss](\d{1,2})[ ._-]?[Ee](\d{1,3})", nome)
    if m:
        return f"T{int(m.group(1)):02d}E{int(m.group(2)):02d}"
    if temporada is not None:
        return f"T{int(temporada):02d}"
    return Path(nome).stem[:52]


def semeado(con: sqlite3.Connection, cfg, caminho_torrent: str) -> tuple[bool, str]:
    """(da para apagar sem perder, explicacao). Reusa a mesma regra do espaco."""
    return health.pode_liberar(con, cfg, caminho_torrent)


def apagar(con: sqlite3.Connection, cfg, arquivos: list[Arquivo],
           confirmar: bool = False, ignorar_saude: bool = False) -> Resultado:
    """Apaga os arquivos escolhidos. Sem `confirmar`, nao faz nada.

    `ignorar_saude` so deve chegar aqui vindo de uma resposta explicita da
    pessoa a um aviso que disse, com todas as letras, que ninguem mais semeia
    aquilo. E o unico jeito de passar pela trava, e de proposito: sem essa
    exigencia a trava viraria decoracao.
    """
    r = Resultado()
    if not confirmar or not arquivos:
        return r

    raiz = Path(cfg.biblioteca).resolve()
    staging = Path(cfg.staging).resolve()
    conferidos: dict[str, bool] = {}

    for a in arquivos:
        try:
            real = a.caminho.resolve()
        except OSError as e:
            r.erros.append(f"{a.caminho.name}: {e}")
            continue

        # Fora da biblioteca (e da pasta de download) nao se toca, nunca.
        if not any(pasta == real or pasta in real.parents
                   for pasta in (raiz, staging)):
            r.erros.append(f"{real.name}: fora da biblioteca — recusado")
            continue

        if not ignorar_saude:
            if a.caminho_torrent not in conferidos:
                conferidos[a.caminho_torrent] = semeado(
                    con, cfg, a.caminho_torrent)[0]
            if not conferidos[a.caminho_torrent]:
                r.erros.append(f"{real.name}: sem semeadores — apagar seria "
                               "definitivo")
                continue

        try:
            tamanho = real.stat().st_size
            real.unlink()
            r.apagados += 1
            r.bytes += tamanho
        except OSError as e:
            r.erros.append(f"{real.name}: {e}")

    if r.apagados:
        seg = cfg.bruto.get("seguranca", {}) or {}
        library.reconciliar(con, Path(cfg.biblioteca), cfg.ignorar,
                            seg.get("pastas_protegidas", []) or [],
                            extras=[Path(cfg.staging)])
    return r
