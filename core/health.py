"""Quantos seeders um torrent ainda tem.

Isto e a trava de seguranca do projeto inteiro: apagar a midia e guardar so o
.torrent so e reversivel enquanto existir gente compartilhando. Boa parte do
acervo e de 2013-2019, entao a pergunta "ainda da para baixar isto de volta?"
precisa ser respondida ANTES de liberar espaco, nunca depois.

Duas estrategias:
  - torrent COM tracker: scrape UDP direto, barato e rapido;
  - torrent SEM tracker (a maioria do acervo): o proprio qBittorrent anuncia no
    DHT por alguns segundos e devolve a contagem. Reimplementar DHT aqui nao
    valeria o esforco.
"""
from __future__ import annotations

import random
import socket
import sqlite3
import struct
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

PROTOCOLO_UDP = 0x41727101980
ACAO_CONECTAR = 0
ACAO_SCRAPE = 2
TEMPO_LIMITE = 4.0


@dataclass
class Saude:
    infohash: str
    seeders: int | None = None
    leechers: int | None = None
    origem: str = ""
    erro: str = ""

    @property
    def vivo(self) -> bool:
        return bool(self.seeders)


@dataclass
class ResumoSaude:
    checados: int = 0
    vivos: int = 0
    mortos: int = 0
    sem_resposta: int = 0
    detalhes: list[Saude] = field(default_factory=list)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def scrape_udp(tracker: str, infohash: str, tempo_limite: float = TEMPO_LIMITE) -> Saude:
    """Protocolo de scrape UDP (BEP 15). Devolve seeders/leechers de um infohash."""
    resultado = Saude(infohash=infohash, origem="tracker")
    url = urllib.parse.urlparse(tracker)
    if url.scheme != "udp" or not url.hostname:
        resultado.erro = "tracker nao e UDP"
        return resultado

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(tempo_limite)
    try:
        destino = (url.hostname, url.port or 80)

        transacao = random.getrandbits(32)
        sock.sendto(struct.pack(">QII", PROTOCOLO_UDP, ACAO_CONECTAR, transacao), destino)
        resposta = sock.recv(16)
        if len(resposta) < 16:
            resultado.erro = "resposta de conexao curta demais"
            return resultado
        acao, transacao_volta, conexao = struct.unpack(">IIQ", resposta[:16])
        if acao != ACAO_CONECTAR or transacao_volta != transacao:
            resultado.erro = "tracker respondeu fora do protocolo"
            return resultado

        transacao = random.getrandbits(32)
        sock.sendto(
            struct.pack(">QII", conexao, ACAO_SCRAPE, transacao) + bytes.fromhex(infohash),
            destino,
        )
        resposta = sock.recv(20)
        if len(resposta) < 20:
            resultado.erro = "resposta de scrape curta demais"
            return resultado
        acao, transacao_volta = struct.unpack(">II", resposta[:8])
        if acao != ACAO_SCRAPE or transacao_volta != transacao:
            resultado.erro = "scrape respondeu fora do protocolo"
            return resultado
        seeders, _completos, leechers = struct.unpack(">III", resposta[8:20])
        resultado.seeders, resultado.leechers = seeders, leechers
    except (socket.timeout, socket.gaierror, OSError, ValueError) as e:
        resultado.erro = f"{type(e).__name__}: {e}"
    finally:
        sock.close()
    return resultado


def melhor_scrape(trackers: list[str], infohash: str) -> Saude:
    """Tenta os trackers em ordem e fica com a maior contagem que responder."""
    melhor = Saude(infohash=infohash, origem="tracker", erro="nenhum tracker respondeu")
    for t in trackers[:6]:
        s = scrape_udp(t, infohash)
        if s.seeders is not None:
            if melhor.seeders is None or s.seeders > melhor.seeders:
                melhor = s
            if s.seeders > 0:
                break
    return melhor


def checar_via_qbittorrent(q, infohash: str, arquivo_torrent, staging,
                           trackers: list[str], segundos: int = 25) -> Saude:
    """Adiciona pausado, deixa anunciar, le a contagem e remove sem baixar nada.

    Usado nos torrents sem tracker: o qBittorrent ja fala DHT, entao ele responde
    a pergunta que o scrape UDP nao alcanca.
    """
    from .motores import ErroMotor

    resultado = Saude(infohash=infohash, origem="qbittorrent")
    ja_estava = False
    try:
        ja_estava = bool(q.listar([infohash]))
        if not ja_estava:
            q.adicionar(arquivo_torrent, staging, categoria=None, pausado=True)
            fim = time.monotonic() + 10
            while time.monotonic() < fim and not q.listar([infohash]):
                time.sleep(0.4)
        q.adicionar_trackers(infohash, trackers)

        # Precisa estar rodando para anunciar; nada e baixado nesse tempo alem
        # de metadados, e removemos logo em seguida.
        q.iniciar(infohash)
        fim = time.monotonic() + segundos
        melhor = 0
        while time.monotonic() < fim:
            time.sleep(2)
            lista = q.listar([infohash])
            if lista:
                melhor = max(melhor, lista[0].seeds)
                resultado.leechers = lista[0].peers
                if melhor > 0:
                    break
        resultado.seeders = melhor
    except ErroMotor as e:
        resultado.erro = str(e)
    finally:
        if not ja_estava:
            try:
                q.remover(infohash, apagar_arquivos=True)
            except Exception:
                pass
    return resultado


def gravar(con: sqlite3.Connection, s: Saude) -> None:
    con.execute(
        "INSERT INTO seed_health (infohash, seeders, leechers, origem, checado_em) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(infohash) DO UPDATE SET "
        "seeders = excluded.seeders, leechers = excluded.leechers, "
        "origem = excluded.origem, checado_em = excluded.checado_em",
        (s.infohash, s.seeders, s.leechers, s.origem, _agora()),
    )
    con.commit()


def checar(con: sqlite3.Connection, cfg, infohashes: list[str] | None = None,
           usar_qbittorrent: bool = False, limite: int | None = None) -> ResumoSaude:
    """Checa a saude dos torrents. Sem `infohashes`, checa os que estao no disco."""
    resumo = ResumoSaude()

    if infohashes:
        marcadores = ",".join("?" * len(infohashes))
        sql = (f"SELECT DISTINCT infohash, trackers, caminho FROM torrents "
               f"WHERE corrompido = 0 AND infohash IN ({marcadores})")
        linhas = con.execute(sql, infohashes).fetchall()
    else:
        # Prioridade: o que ocupa disco e ainda nao foi checado.
        sql = ("SELECT DISTINCT t.infohash, t.trackers, t.caminho FROM torrents t "
               "JOIN disco d ON d.caminho_torrent = t.caminho "
               "WHERE t.corrompido = 0 AND d.estado IN ('completo','parcial') "
               "ORDER BY d.bytes_presentes DESC")
        if limite:
            sql += f" LIMIT {int(limite)}"
        linhas = con.execute(sql).fetchall()

    q = None
    if usar_qbittorrent:
        from .downloads import cliente
        q = cliente(cfg)
        if q is not None:
            no_ar, _ = q.disponivel()
            if not no_ar:
                q = None

    from .downloads import _trackers_do_acervo
    from .motores.qbittorrent import carregar_trackers
    from pathlib import Path
    publicos = carregar_trackers(Path(cfg.dados) / "trackers.txt", _trackers_do_acervo(con))

    for linha in linhas:
        proprios = [t for t in (linha["trackers"] or "").splitlines() if t.strip()]
        s = melhor_scrape(proprios or publicos, linha["infohash"])

        if (s.seeders is None or s.seeders == 0) and q is not None:
            s = checar_via_qbittorrent(
                q, linha["infohash"], Path(cfg.indice) / linha["caminho"],
                Path(cfg.staging), publicos)

        resumo.checados += 1
        resumo.detalhes.append(s)
        if s.seeders is None:
            resumo.sem_resposta += 1
        elif s.seeders > 0:
            resumo.vivos += 1
            gravar(con, s)
        else:
            resumo.mortos += 1
            gravar(con, s)

    return resumo


def pode_liberar(con: sqlite3.Connection, cfg, caminho_torrent: str) -> tuple[bool, str]:
    """Decide se e seguro apagar a midia deste torrent para recuperar espaco."""
    linha = con.execute(
        "SELECT t.infohash, d.estado, d.fixado, d.caminho_local, d.bytes_presentes, "
        "       i.fixado AS item_fixado, s.seeders, s.checado_em "
        "FROM torrents t "
        "LEFT JOIN disco d ON d.caminho_torrent = t.caminho "
        "LEFT JOIN itens i ON i.id = t.item_id "
        "LEFT JOIN seed_health s ON s.infohash = t.infohash "
        "WHERE t.caminho = ?", (caminho_torrent,)
    ).fetchone()

    if not linha:
        return False, "torrent nao encontrado no indice"
    if not linha["caminho_local"] or linha["estado"] not in ("completo", "parcial"):
        return False, "nao ha nada no disco para liberar"
    if linha["fixado"] or linha["item_fixado"]:
        return False, "este item esta marcado como protegido"

    minimo = int(cfg.seguranca.get("minimo_seeders", 1))
    validade = int(cfg.seguranca.get("validade_saude_dias", 14))

    if linha["seeders"] is None:
        return False, ("a saude deste torrent nunca foi checada. Sem saber se ainda "
                       "ha seeders, apagar pode ser definitivo.")
    if linha["checado_em"]:
        checado = datetime.fromisoformat(linha["checado_em"])
        if datetime.now(timezone.utc) - checado > timedelta(days=validade):
            return False, (f"a ultima checagem tem mais de {validade} dias. "
                           "Cheque a saude de novo antes de liberar.")
    if linha["seeders"] < minimo:
        return False, (f"apenas {linha['seeders']} seeder(s) — abaixo do minimo de "
                       f"{minimo}. Apagar provavelmente seria definitivo.")

    return True, (f"{linha['seeders']} seeders. Liberar devolve "
                  f"{linha['bytes_presentes'] / 1024 ** 3:.1f} GiB.")
