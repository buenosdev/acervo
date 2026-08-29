"""Capas: gerar uma quando nao existe, e trocar a capa na mao.

A capa gerada e um SVG, nao um PNG: o navegador desenha o texto com a fonte
certa, o arquivo tem 1 KB e fica nitido em qualquer tamanho. Gerar PNG com
texto exigiria embutir uma fonte bitmap para nada.

Toda obra acaba com alguma capa, entao a grade nunca fica com buracos.
"""
from __future__ import annotations

import hashlib
import sqlite3
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

from .release import chave_busca

EXTENSOES_OK = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}
TAMANHO_MAXIMO = 8 * 1024 * 1024


def _tom(titulo: str) -> int:
    """Matiz estavel a partir do titulo: a mesma obra tem sempre a mesma cor."""
    digest = hashlib.sha1(chave_busca(titulo).encode("utf-8")).digest()
    return digest[0] * 360 // 256


def _quebrar(texto: str, por_linha: int = 15, maximo: int = 4) -> list[str]:
    linhas: list[str] = []
    atual = ""
    for palavra in texto.split():
        if len(atual) + len(palavra) + 1 <= por_linha or not atual:
            atual = f"{atual} {palavra}".strip()
        else:
            linhas.append(atual)
            atual = palavra
        if len(linhas) == maximo:
            break
    if atual and len(linhas) < maximo:
        linhas.append(atual)
    if len(linhas) == maximo and len(" ".join(linhas)) < len(texto):
        linhas[-1] = linhas[-1][:por_linha - 1].rstrip() + "…"
    return linhas or ["?"]


def _escapar(t: str) -> str:
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


ROTULO = {"filme": "FILME", "serie": "SÉRIE", "jogo": "JOGO"}


def gerar_svg(titulo: str, tipo: str = "filme", ano: int | None = None) -> str:
    """Capa de reserva: gradiente derivado do titulo, com o nome escrito."""
    h = _tom(titulo)
    linhas = _quebrar(titulo)
    # Titulo longo cabe com fonte menor, em vez de estourar a caixa.
    tamanho = 40 if len(linhas) <= 2 else (34 if len(linhas) == 3 else 29)
    altura_bloco = len(linhas) * (tamanho + 8)
    y0 = 600 - 96 - altura_bloco + tamanho

    textos = "".join(
        f'<text x="34" y="{y0 + i * (tamanho + 8)}" fill="#f4f4f8" '
        f'font-size="{tamanho}" font-weight="650">{_escapar(l)}</text>'
        for i, l in enumerate(linhas))

    rodape = " · ".join(x for x in (ROTULO.get(tipo, ""), str(ano) if ano else "") if x)

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 600" '
        'width="400" height="600" role="img" '
        f'aria-label="{_escapar(titulo)}">'
        '<defs>'
        f'<linearGradient id="g" x1="0" y1="0" x2="0.6" y2="1">'
        f'<stop offset="0" stop-color="hsl({h} 36% 30%)"/>'
        f'<stop offset="1" stop-color="hsl({(h + 40) % 360} 42% 11%)"/>'
        '</linearGradient>'
        '</defs>'
        '<rect width="400" height="600" fill="url(#g)"/>'
        f'<rect x="0" y="0" width="400" height="600" fill="none" '
        f'stroke="hsl({h} 30% 45%)" stroke-opacity="0.35" stroke-width="2"/>'
        '<g font-family="Segoe UI, system-ui, sans-serif">'
        f'{textos}'
        f'<text x="34" y="{600 - 44}" fill="#c8c8d4" fill-opacity="0.75" '
        f'font-size="17" letter-spacing="2.5">{_escapar(rodape)}</text>'
        '</g></svg>')


def gravar_gerada(pasta: Path, item_id: int, titulo: str, tipo: str,
                  ano: int | None) -> str:
    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"{item_id}-gerada.svg"
    (pasta / nome).write_text(gerar_svg(titulo, tipo, ano), encoding="utf-8")
    return nome


def _extensao(url: str, tipo_conteudo: str) -> str:
    for ext in EXTENSOES_OK:
        if url.lower().split("?")[0].endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    mapa = {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
            "image/svg+xml": ".svg"}
    return mapa.get((tipo_conteudo or "").split(";")[0].strip(), ".jpg")


def baixar_para_item(url: str, pasta: Path, item_id: int) -> str:
    """Baixa uma imagem e devolve o nome do arquivo salvo. Levanta em caso de erro."""
    from .metadata import CABECALHOS

    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("o endereço precisa começar com http:// ou https://")

    req = urllib.request.Request(url, headers=CABECALHOS)
    with urllib.request.urlopen(req, timeout=25) as r:
        tipo_conteudo = r.headers.get("Content-Type", "")
        dados = r.read(TAMANHO_MAXIMO + 1)

    if len(dados) > TAMANHO_MAXIMO:
        raise ValueError("imagem maior que 8 MB")
    if len(dados) < 512:
        raise ValueError("o endereço não devolveu uma imagem")

    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"{item_id}{_extensao(url, tipo_conteudo)}"
    (pasta / nome).write_bytes(dados)
    return nome


def copiar_do_disco(caminho: str, pasta: Path, item_id: int) -> str:
    """Usa uma imagem que ja esta no computador do usuario."""
    origem = Path(caminho.strip().strip('"'))
    if not origem.is_file():
        raise ValueError(f"arquivo não encontrado: {origem}")
    ext = origem.suffix.lower()
    if ext not in EXTENSOES_OK:
        raise ValueError(f"formato não aceito ({ext}). Use JPG, PNG, WEBP ou SVG.")
    if origem.stat().st_size > TAMANHO_MAXIMO:
        raise ValueError("imagem maior que 8 MB")

    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"{item_id}{'.jpg' if ext == '.jpeg' else ext}"
    (pasta / nome).write_bytes(origem.read_bytes())
    return nome


def aplicar(con: sqlite3.Connection, pasta: Path, item_id: int, nome: str) -> None:
    """Aponta o item para a capa nova e apaga as antigas que sobraram."""
    antigas = [p for p in pasta.glob(f"{item_id}.*")] + \
              [p for p in pasta.glob(f"{item_id}-gerada.*")]
    for p in antigas:
        if p.name != nome:
            try:
                p.unlink()
            except OSError:
                pass
    con.execute("UPDATE itens SET poster = ? WHERE id = ?", (nome, item_id))
    con.commit()


def completar_faltantes(con: sqlite3.Connection, pasta: Path) -> int:
    """Da uma capa gerada para toda obra que ficou sem. Devolve quantas criou."""
    linhas = con.execute(
        "SELECT id, tipo, ano, COALESCE(NULLIF(titulo_corrigido,''), titulo) titulo "
        "FROM itens WHERE poster IS NULL OR poster = ''"
    ).fetchall()
    for l in linhas:
        nome = gravar_gerada(pasta, l["id"], l["titulo"], l["tipo"], l["ano"])
        con.execute("UPDATE itens SET poster = ? WHERE id = ?", (nome, l["id"]))
    con.commit()
    return len(linhas)


def eh_gerada(poster: str | None) -> bool:
    return bool(poster) and poster.endswith("-gerada.svg")
