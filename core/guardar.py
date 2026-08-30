"""Leva para a biblioteca o que ja terminou de baixar.

A primeira versao disto reagia ao evento: quando o app via um download passar
de 99% para 100%, arrumava aquele. Parece certo e falha na pratica, porque o
momento e facil de perder — o download termina com o app fechado, ou o cliente
ja esqueceu do torrent quando o app abre, e ninguem mais olha para aquela pasta.
Foi assim que "Gatilheiro" ficou parado em `_baixando`, completo, por um dia.

Aqui a pergunta e outra: **o que esta pronto na pasta de download agora?** Ela
pode ser feita a qualquer momento — ao abrir o app, depois de conferir o disco,
quando um download termina — e sempre da a mesma resposta certa. Nao depende de
ter presenciado nada.

Midia nunca e apagada: os arquivos sao movidos e a tabela `disco` e
reconciliada logo depois, para o catalogo apontar para o lugar novo. A unica
coisa que este modulo remove sao os arquivos que o proprio indice marcou como
propaganda, e so depois de a midia daquele release ter saido em seguranca.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import library, organizer


@dataclass
class Resultado:
    movidos: int = 0
    obras: list[str] = field(default_factory=list)
    problemas: list[str] = field(default_factory=list)
    sobras: list[str] = field(default_factory=list)


def _dentro(caminho: str | None, pasta: Path) -> bool:
    """True se `caminho` esta dentro de `pasta`."""
    if not caminho:
        return False
    try:
        Path(caminho).resolve().relative_to(pasta.resolve())
    except (ValueError, OSError):
        return False
    return True


def prontos_para_guardar(con: sqlite3.Connection, cfg) -> list[dict]:
    """Releases completos que ainda estao na pasta de download."""
    staging = Path(cfg.staging)
    if not staging.is_dir():
        return []
    linhas = con.execute(
        "SELECT t.caminho, t.infohash, d.caminho_local, "
        "       COALESCE(NULLIF(i.titulo_corrigido,''), i.titulo) titulo "
        "FROM torrents t "
        "JOIN itens i ON i.id = t.item_id "
        "JOIN disco d ON d.caminho_torrent = t.caminho "
        "WHERE d.estado = 'completo' AND t.corrompido = 0"
    ).fetchall()
    return [dict(l) for l in linhas if _dentro(l["caminho_local"], staging)]


def guardar(con: sqlite3.Connection, cfg, apenas: list[str] | None = None) -> Resultado:
    """Move para a biblioteca tudo que ja terminou e ainda esta no `staging`.

    `apenas` limita a certos infohashes; sem ele, cuida de tudo que encontrar.
    """
    r = Resultado()
    candidatos = prontos_para_guardar(con, cfg)
    if apenas is not None:
        alvos = set(apenas)
        candidatos = [c for c in candidatos if c["infohash"] in alvos]
    if not candidatos:
        return r

    raiz = Path(cfg.biblioteca)
    for c in candidatos:
        plano = organizer.planejar(con, raiz, c["caminho"])
        uteis = [m for m in plano.movimentos if Path(m.de) != Path(m.para)]
        if not uteis:
            continue
        plano.movimentos = uteis
        origem = Path(c["caminho_local"])
        relatos = organizer.executar(plano, simular=False)
        movidos = sum(1 for x in relatos if not x.startswith(("PULADO", "FALHOU")))
        if movidos:
            r.movidos += movidos
            r.obras.append(c["titulo"])
            # A pasta do release nao pode ficar de pe so com a propaganda: quem
            # olha a pasta de download conclui que o filme continua ali.
            pasta = origem if origem.is_dir() else origem.parent
            r.sobras += limpar_sobras(con, cfg, c["caminho"], pasta)
        r.problemas += [x for x in relatos if x.startswith(("PULADO", "FALHOU"))]

    r.sobras += varrer_sobras(con, cfg)

    if r.movidos:
        seg = cfg.bruto.get("seguranca", {}) or {}
        library.reconciliar(con, raiz, seg.get("ignorar", []) or cfg.ignorar,
                            seg.get("pastas_protegidas", []) or [],
                            extras=[Path(cfg.staging)])
    return r


def _lixo_do_torrent(con: sqlite3.Connection, caminho_torrent: str) -> set[str]:
    """Nomes de arquivo que o indice marcou como propaganda neste torrent."""
    return {l["caminho"].rsplit("/", 1)[-1].lower() for l in con.execute(
        "SELECT caminho FROM torrent_files "
        "WHERE caminho_torrent = ? AND tipo = 'lixo'", (caminho_torrent,))}


def limpar_sobras(con: sqlite3.Connection, cfg, caminho_torrent: str,
                  origem: Path) -> list[str]:
    """Tira da pasta de download o que sobrou depois de a midia sair.

    Depois de mover o filme, ficam para tras os `.url` de propaganda e o
    `LEIA-ME.txt` que vieram no mesmo torrent. Sao 30 KB, mas mantem a pasta do
    release de pe — e uma pasta com o nome do filme ainda em `_baixando` parece,
    com toda razao, que o filme nao foi movido.

    O que e apagado tem tres condicoes, todas obrigatorias: estar dentro da
    pasta de download, pertencer a este torrent, e estar marcado como propaganda
    no indice. Arquivo que nao seja exatamente isso fica onde esta, e a pasta
    fica junto com ele.
    """
    feitos: list[str] = []
    staging = Path(cfg.staging)
    if not _dentro(str(origem), staging) or not origem.exists():
        return feitos

    lixo = _lixo_do_torrent(con, caminho_torrent)
    if origem.is_dir():
        for arquivo in list(origem.rglob("*")):
            if not arquivo.is_file():
                continue
            if arquivo.name.lower() not in lixo:
                return feitos          # sobrou algo que nao e propaganda
        for arquivo in list(origem.rglob("*")):
            try:
                if arquivo.is_file():
                    arquivo.unlink()
                    feitos.append(arquivo.name)
            except OSError:
                return feitos
        for pasta in sorted((p for p in origem.rglob("*") if p.is_dir()),
                            key=lambda p: -len(p.parts)):
            try:
                pasta.rmdir()
            except OSError:
                pass
        try:
            origem.rmdir()
        except OSError:
            pass

    # O arquivo de controle do aria2 fica ao lado da pasta e nao serve mais
    # depois de o download ter terminado e a midia ter saido.
    controle = origem.with_name(origem.name + ".aria2")
    try:
        if controle.is_file():
            controle.unlink()
            feitos.append(controle.name)
    except OSError:
        pass
    return feitos


def varrer_sobras(con: sqlite3.Connection, cfg) -> list[str]:
    """Limpa pastas na area de download cuja midia ja foi embora.

    O caso que sobrava: a midia foi movida numa execucao anterior, entao aquele
    release nao esta mais "na pasta de download" e nada volta a olhar para ele —
    mas a pasta dele continua ali, com os `.url` de propaganda dentro. Quem abre
    a pasta ve o nome do filme e conclui, com razao, que ele nao foi movido.

    A regra e a mesma de sempre: so sai o que o indice marcou como propaganda
    daquele torrent. Pasta com qualquer outro arquivo fica intacta.
    """
    staging = Path(cfg.staging)
    if not staging.is_dir():
        return []

    por_nome = {l["nome"]: l["caminho"] for l in con.execute(
        "SELECT nome, caminho FROM torrents WHERE corrompido = 0")}

    feitos: list[str] = []
    try:
        pastas = [p for p in staging.iterdir() if p.is_dir()]
    except OSError:
        return feitos

    for pasta in pastas:
        caminho_torrent = por_nome.get(pasta.name)
        if not caminho_torrent:
            continue                    # nao sabemos de quem e: nao se mexe
        feitos += limpar_sobras(con, cfg, caminho_torrent, pasta)

    feitos += _torrents_duplicados(con, staging)
    return feitos


def _torrents_duplicados(con: sqlite3.Connection, staging: Path) -> list[str]:
    """Remove os `.torrent` da pasta de download que ja estao no indice.

    O aria2 gravava uma copia de cada torrent recebido, com nome de hash. Sao
    duplicatas exatas do que ja esta guardado, e o nome nao diz o que e — abrir
    a pasta de download nao ajuda ninguem assim.

    So sai o que for comprovadamente duplicata: o infohash e recalculado do
    conteudo do arquivo e tem de bater com um torrent do indice. `.torrent`
    desconhecido fica onde esta, porque pode ter sido posto ali de proposito.
    """
    from . import bencode

    feitos: list[str] = []
    try:
        arquivos = [f for f in staging.glob("*.torrent") if f.is_file()]
    except OSError:
        return feitos

    for f in arquivos:
        try:
            dados, _ = bencode.decodificar(f.read_bytes())
            info = dados.get(b"info")
            if not info:
                continue
            infohash = hashlib.sha1(bencode.codificar(info)).hexdigest()
        except (OSError, ValueError, IndexError, TypeError):
            continue                    # ilegivel: nao se mexe

        conhecido = con.execute(
            "SELECT 1 FROM torrents WHERE lower(infohash) = ? LIMIT 1",
            (infohash.lower(),)).fetchone()
        if not conhecido:
            continue                    # nao esta no indice: pode ser seu
        try:
            f.unlink()
            feitos.append(f.name)
        except OSError:
            pass
    return feitos
