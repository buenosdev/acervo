"""Trazer arquivos .torrent para dentro do indice, pelo proprio app.

A defesa contra duplicata comeca aqui, na entrada: antes de copiar qualquer
coisa, o infohash e comparado com o que ja esta catalogado. Se ja existe, o app
diz de qual obra se trata em vez de criar uma segunda entrada. O
`core/duplicatas.py` cuida do que entrou antes desta checagem existir.
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import bencode
from .release import FILME, JOGO, SERIE, analisar, parece_jogo

PASTA_POR_TIPO = {FILME: "Filmes", SERIE: "Series", JOGO: "Jogos"}
# Onde cai o que o app nao consegue classificar sozinho.
PASTA_TRIAGEM = "_Novos"

_PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class Proposta:
    """O que o app pretende fazer com um .torrent solto."""
    origem: Path
    infohash: str
    nome: str
    titulo: str
    tipo: str
    tamanho: int
    n_arquivos: int
    destino_relativo: str          # caminho dentro do indice
    ja_existe: bool = False
    obra_existente: str = ""
    caminho_existente: str = ""
    erro: str = ""

    @property
    def pode_importar(self) -> bool:
        return not self.erro and not self.ja_existe


def _limpar(nome: str) -> str:
    limpo = _PROIBIDOS.sub("", nome).strip()
    return re.sub(r"\s+", " ", limpo).rstrip(". ") or "sem nome"


def _sem_acento(t: str) -> str:
    s = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _subpasta_existente(raiz: Path, categoria: str, alvo: str) -> str | None:
    """Reaproveita a pasta de genero/serie que o usuario ja usa, se houver."""
    base = raiz / categoria
    if not base.is_dir() or not alvo:
        return None
    procurado = _sem_acento(alvo)
    for p in base.iterdir():
        if p.is_dir() and _sem_acento(p.name) == procurado:
            return p.name
    return None


def avaliar(con: sqlite3.Connection, raiz_indice: Path, arquivo: str | Path) -> Proposta:
    """Le o .torrent e propoe onde ele deveria ficar. Nao copia nada."""
    origem = Path(arquivo)
    vazia = Proposta(origem=origem, infohash="", nome=origem.name, titulo=origem.stem,
                     tipo=FILME, tamanho=0, n_arquivos=0, destino_relativo="")

    if origem.suffix.lower() != ".torrent":
        vazia.erro = "não é um arquivo .torrent"
        return vazia
    if not origem.is_file():
        vazia.erro = "arquivo não encontrado"
        return vazia

    try:
        t = bencode.ler(origem)
    except (bencode.BencodeInvalido, OSError) as e:
        vazia.erro = f"não consegui ler: {e}"
        return vazia

    base = origem.name if len(origem.stem) >= len(t.nome) else t.nome
    rel = analisar(base)
    tipo = rel.tipo
    if tipo != JOGO and parece_jogo([(a.caminho, a.tamanho) for a in t.arquivos]):
        tipo = JOGO

    proposta = Proposta(
        origem=origem, infohash=t.infohash, nome=t.nome, titulo=rel.titulo,
        tipo=tipo, tamanho=t.tamanho_total, n_arquivos=len(t.arquivos),
        destino_relativo="")

    ja = con.execute(
        "SELECT t.caminho, COALESCE(NULLIF(i.titulo_corrigido,''), i.titulo) titulo "
        "FROM torrents t LEFT JOIN itens i ON i.id = t.item_id "
        "WHERE t.infohash = ? LIMIT 1", (t.infohash,)).fetchone()
    if ja:
        proposta.ja_existe = True
        proposta.obra_existente = ja["titulo"] or t.nome
        proposta.caminho_existente = ja["caminho"]
        return proposta

    proposta.destino_relativo = sugerir_destino(con, raiz_indice, proposta)
    return proposta


def sugerir_destino(con: sqlite3.Connection, raiz_indice: Path,
                    p: Proposta) -> str:
    """Caminho relativo sugerido dentro do indice, seguindo as pastas que ja existem."""
    categoria = PASTA_POR_TIPO.get(p.tipo, PASTA_TRIAGEM)
    nome_arquivo = _limpar(p.origem.name)

    if p.tipo == SERIE:
        # Series ficam em Series/<genero>/<nome da serie>/. Se a serie ja existe
        # em algum genero, o episodio novo vai para junto dos irmaos.
        linha = con.execute(
            "SELECT subcategoria, caminho FROM torrents "
            "WHERE categoria = ? AND item_id IN ("
            "  SELECT id FROM itens WHERE tipo = 'serie' AND lower(titulo) = lower(?)) "
            "LIMIT 1", (categoria, p.titulo)).fetchone()
        if linha and linha["caminho"]:
            pasta_serie = str(Path(linha["caminho"]).parent).replace("\\", "/")
            return f"{pasta_serie}/{nome_arquivo}"
        return f"{categoria}/{PASTA_TRIAGEM}/{_limpar(p.titulo)}/{nome_arquivo}"

    # Filme e jogo: sem genero conhecido, vao para a triagem daquela categoria.
    sub = _subpasta_existente(raiz_indice, categoria, PASTA_TRIAGEM) or PASTA_TRIAGEM
    return f"{categoria}/{sub}/{nome_arquivo}"


def generos_existentes(raiz_indice: Path, tipo: str) -> list[str]:
    """Pastas de genero que o usuario ja usa, para oferecer na hora de importar."""
    base = Path(raiz_indice) / PASTA_POR_TIPO.get(tipo, "")
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir()
                  if p.is_dir() and not p.name.startswith("_"))


def importar(raiz_indice: Path, p: Proposta, destino_relativo: str | None = None) -> dict:
    """Copia o .torrent para o indice. O arquivo original nao e movido nem apagado."""
    if p.erro:
        return {"ok": False, "erro": p.erro}
    if p.ja_existe:
        return {"ok": False, "erro": f"já está no acervo, como “{p.obra_existente}”",
                "caminho_existente": p.caminho_existente}

    alvo = Path(raiz_indice) / (destino_relativo or p.destino_relativo)
    if alvo.exists():
        return {"ok": False, "erro": f"já existe um arquivo em {alvo.name}"}

    try:
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p.origem, alvo)
    except OSError as e:
        return {"ok": False, "erro": f"não consegui copiar: {e}"}

    return {"ok": True, "caminho": str(alvo),
            "relativo": alvo.relative_to(Path(raiz_indice)).as_posix(),
            "titulo": p.titulo, "tipo": p.tipo}


def avaliar_varios(con: sqlite3.Connection, raiz_indice: Path,
                   arquivos: list[str]) -> list[Proposta]:
    """Avalia uma leva (arrastar-e-soltar), sem repetir infohash dentro da propria leva."""
    vistos: set[str] = set()
    saida: list[Proposta] = []
    for a in arquivos:
        p = avaliar(con, raiz_indice, a)
        if p.infohash and p.infohash in vistos:
            p.ja_existe = True
            p.obra_existente = "outro arquivo desta mesma leva"
        elif p.infohash:
            vistos.add(p.infohash)
        saida.append(p)
    return saida
