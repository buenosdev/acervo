"""Liberar espaco: apagar a midia e manter o .torrent.

E a unica parte do Acervo que apaga arquivo do usuario, entao tem tres travas:

  1. `health.pode_liberar` precisa aprovar (seeders suficientes, checagem
     recente, item nao protegido);
  2. quem chama precisa passar `confirmar=True` explicitamente;
  3. nada fora da pasta da biblioteca e tocado, nunca.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from . import health


def _dentro_da_biblioteca(alvo: Path, raiz: Path) -> bool:
    """Trava contra apagar fora da biblioteca por causa de um caminho estranho."""
    try:
        alvo.resolve().relative_to(raiz.resolve())
        return True
    except ValueError:
        return False


def avaliar(con: sqlite3.Connection, cfg, caminho_torrent: str) -> dict:
    """Diz se da para liberar e quanto voltaria, sem apagar nada."""
    ok, motivo = health.pode_liberar(con, cfg, caminho_torrent)
    linha = con.execute(
        "SELECT d.caminho_local, d.bytes_presentes, d.gerenciado, s.seeders, s.checado_em "
        "FROM torrents t LEFT JOIN disco d ON d.caminho_torrent = t.caminho "
        "LEFT JOIN seed_health s ON s.infohash = t.infohash WHERE t.caminho = ?",
        (caminho_torrent,)
    ).fetchone()
    return {
        "pode": ok,
        "motivo": motivo,
        "caminho_local": linha["caminho_local"] if linha else None,
        "bytes": linha["bytes_presentes"] if linha else 0,
        "seeders": linha["seeders"] if linha else None,
        "checado_em": linha["checado_em"] if linha else None,
    }


def liberar(con: sqlite3.Connection, cfg, caminho_torrent: str,
            confirmar: bool = False) -> dict:
    """Apaga a midia deste torrent. O .torrent continua no indice."""
    avaliacao = avaliar(con, cfg, caminho_torrent)
    if not avaliacao["pode"]:
        return {"ok": False, "erro": avaliacao["motivo"]}
    if not confirmar:
        return {"ok": False, "erro": "falta confirmacao explicita",
                "avaliacao": avaliacao}

    alvo = Path(avaliacao["caminho_local"])
    raiz = Path(cfg.biblioteca)
    if not _dentro_da_biblioteca(alvo, raiz):
        return {"ok": False,
                "erro": f"recusado: {alvo} esta fora da biblioteca ({raiz})"}
    if not alvo.exists():
        con.execute("UPDATE disco SET estado = 'indice', bytes_presentes = 0 "
                    "WHERE caminho_local = ?", (str(alvo),))
        con.commit()
        return {"ok": True, "bytes_liberados": 0, "nota": "ja nao existia no disco"}

    linha = con.execute(
        "SELECT t.infohash, d.gerenciado FROM torrents t "
        "LEFT JOIN disco d ON d.caminho_torrent = t.caminho WHERE t.caminho = ?",
        (caminho_torrent,)
    ).fetchone()

    liberados = avaliacao["bytes"]
    via = "disco"

    # Se o qBittorrent e quem cuida deste torrent, e ele quem apaga: assim o
    # cliente nao fica com um torrent orfao apontando para arquivo que sumiu.
    if linha and linha["gerenciado"]:
        from .downloads import cliente
        from .motores import ErroMotor
        q = cliente(cfg)
        no_ar = q is not None and q.disponivel()[0]
        if no_ar:
            try:
                q.remover(linha["infohash"], apagar_arquivos=True)
                via = q.nome
            except ErroMotor:
                via = "disco"

    if via == "disco":
        try:
            if alvo.is_dir():
                shutil.rmtree(alvo)
            else:
                alvo.unlink()
        except OSError as e:
            return {"ok": False, "erro": f"nao consegui apagar: {e}"}

    con.execute("UPDATE disco SET estado = 'indice', bytes_presentes = 0, "
                "gerenciado = 0 WHERE caminho_local = ?", (str(alvo),))
    con.commit()
    return {"ok": True, "bytes_liberados": liberados, "via": via,
            "caminho": str(alvo),
            "nota": "o .torrent continua no indice: da para baixar de novo"}
