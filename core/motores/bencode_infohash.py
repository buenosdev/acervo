"""Infohash de um arquivo .torrent, para motores que nao devolvem o hash ao adicionar."""
from __future__ import annotations

from pathlib import Path


def infohash_de(caminho: str | Path) -> str:
    from .. import bencode
    return bencode.ler(Path(caminho)).infohash
