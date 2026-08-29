"""Leitura de arquivos .torrent: bencode, infohash e metadados.

Sem dependencias externas - so biblioteca padrao.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path


class BencodeInvalido(ValueError):
    """O arquivo nao e um bencode valido (torrent corrompido ou truncado)."""


def decodificar(dados: bytes, i: int = 0) -> tuple[object, int]:
    """Decodifica um valor bencode a partir da posicao i. Devolve (valor, proxima_posicao)."""
    if i >= len(dados):
        raise BencodeInvalido(f"fim inesperado dos dados na posicao {i}")

    c = dados[i : i + 1]

    if c == b"d":
        i += 1
        d: dict[bytes, object] = {}
        while True:
            if i >= len(dados):
                raise BencodeInvalido("dicionario nao terminado")
            if dados[i : i + 1] == b"e":
                return d, i + 1
            chave, i = decodificar(dados, i)
            if not isinstance(chave, bytes):
                raise BencodeInvalido(f"chave de dicionario nao e string: {chave!r}")
            d[chave], i = decodificar(dados, i)

    if c == b"l":
        i += 1
        lista: list[object] = []
        while True:
            if i >= len(dados):
                raise BencodeInvalido("lista nao terminada")
            if dados[i : i + 1] == b"e":
                return lista, i + 1
            valor, i = decodificar(dados, i)
            lista.append(valor)

    if c == b"i":
        fim = dados.find(b"e", i)
        if fim == -1:
            raise BencodeInvalido("inteiro nao terminado")
        try:
            return int(dados[i + 1 : fim]), fim + 1
        except ValueError as erro:
            raise BencodeInvalido(f"inteiro invalido: {dados[i + 1:fim]!r}") from erro

    sep = dados.find(b":", i)
    if sep == -1:
        raise BencodeInvalido(f"string sem separador na posicao {i}")
    try:
        n = int(dados[i:sep])
    except ValueError as erro:
        raise BencodeInvalido(f"tamanho de string invalido: {dados[i:sep]!r}") from erro
    if n < 0 or sep + 1 + n > len(dados):
        raise BencodeInvalido(f"string com tamanho {n} ultrapassa os dados")
    return dados[sep + 1 : sep + 1 + n], sep + 1 + n


def codificar(obj: object) -> bytes:
    """Codifica de volta para bencode. Necessario para recalcular o infohash."""
    if isinstance(obj, bool):
        raise TypeError("bencode nao tem booleano")
    if isinstance(obj, int):
        return b"i" + str(obj).encode() + b"e"
    if isinstance(obj, bytes):
        return str(len(obj)).encode() + b":" + obj
    if isinstance(obj, str):
        b = obj.encode("utf-8")
        return str(len(b)).encode() + b":" + b
    if isinstance(obj, (list, tuple)):
        return b"l" + b"".join(codificar(x) for x in obj) + b"e"
    if isinstance(obj, dict):
        # A especificacao exige chaves ordenadas por byte.
        itens = sorted(obj.items(), key=lambda kv: kv[0])
        return b"d" + b"".join(codificar(k) + codificar(v) for k, v in itens) + b"e"
    raise TypeError(f"tipo nao suportado em bencode: {type(obj)}")


def _texto(valor: object, padrao: str = "") -> str:
    """Bytes de torrent nem sempre sao UTF-8 valido; nunca deixa estourar."""
    if isinstance(valor, bytes):
        return valor.decode("utf-8", "replace")
    if isinstance(valor, str):
        return valor
    return padrao


@dataclass
class ArquivoTorrent:
    caminho: str          # caminho relativo dentro do torrent, com "/"
    tamanho: int
    indice: int           # posicao original - o qBittorrent usa esse indice em filePrio


@dataclass
class Torrent:
    infohash: str
    nome: str
    tamanho_total: int
    arquivos: list[ArquivoTorrent]
    piece_length: int
    privado: bool
    trackers: list[str] = field(default_factory=list)
    web_seeds: list[str] = field(default_factory=list)
    comentario: str = ""
    criado_por: str = ""
    criado_em: int | None = None
    tamanho_arquivo_torrent: int = 0
    caminho_arquivo: Path | None = None

    @property
    def multi_arquivo(self) -> bool:
        return len(self.arquivos) > 1


def ler(caminho: str | Path) -> Torrent:
    """Le um .torrent do disco. Levanta BencodeInvalido se estiver corrompido."""
    caminho = Path(caminho)
    dados = caminho.read_bytes()
    meta, _ = decodificar(dados)

    if not isinstance(meta, dict) or b"info" not in meta:
        raise BencodeInvalido("arquivo sem dicionario 'info'")
    info = meta[b"info"]
    if not isinstance(info, dict):
        raise BencodeInvalido("'info' nao e um dicionario")

    infohash = hashlib.sha1(codificar(info)).hexdigest()
    nome = _texto(info.get(b"name"), caminho.stem)

    arquivos: list[ArquivoTorrent] = []
    if b"files" in info:
        for i, f in enumerate(info[b"files"]):
            partes = [_texto(p) for p in f.get(b"path", [])]
            arquivos.append(ArquivoTorrent("/".join(partes), int(f.get(b"length", 0)), i))
    else:
        arquivos.append(ArquivoTorrent(nome, int(info.get(b"length", 0)), 0))

    trackers: list[str] = []
    if b"announce" in meta:
        trackers.append(_texto(meta[b"announce"]))
    for camada in meta.get(b"announce-list", []) or []:
        if isinstance(camada, list):
            for t in camada:
                url = _texto(t)
                if url and url not in trackers:
                    trackers.append(url)

    url_list = meta.get(b"url-list")
    if isinstance(url_list, bytes):
        web_seeds = [_texto(url_list)]
    elif isinstance(url_list, list):
        web_seeds = [_texto(u) for u in url_list]
    else:
        web_seeds = []

    return Torrent(
        infohash=infohash,
        nome=nome,
        tamanho_total=sum(a.tamanho for a in arquivos),
        arquivos=arquivos,
        piece_length=int(info.get(b"piece length", 0)),
        privado=bool(info.get(b"private", 0)),
        trackers=trackers,
        web_seeds=[u for u in web_seeds if u],
        comentario=_texto(meta.get(b"comment")),
        criado_por=_texto(meta.get(b"created by")),
        criado_em=meta.get(b"creation date") if isinstance(meta.get(b"creation date"), int) else None,
        tamanho_arquivo_torrent=len(dados),
        caminho_arquivo=caminho,
    )
