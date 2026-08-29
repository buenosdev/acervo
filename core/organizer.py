"""Organiza a midia baixada no padrao que Jellyfin, Plex e Kodi leem sozinhos.

Decisao central: para o que o qBittorrent baixou, a organizacao e feita PELA API
dele (renameFile / renameFolder / setLocation), nunca movendo arquivo por fora.
Assim o seeding continua, nao existe copia duplicada ocupando disco, e apagar
depois devolve o espaco na hora. Mover pelas costas do cliente criaria
exatamente o desperdicio que este projeto quer evitar.

Para os arquivos que ja estavam no disco antes do Acervo, a movimentacao e real
- e sempre com previa e confirmacao.
"""
from __future__ import annotations

import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .release import FILME, JOGO, SERIE

# Caracteres que o Windows nao aceita em nome de arquivo.
_PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_EXT_MIDIA = {".mkv", ".mp4", ".avi", ".rmvb", ".mov", ".m4v", ".ts", ".wmv", ".mpg"}
_EXT_LEGENDA = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt"}


@dataclass
class Movimento:
    de: str
    para: str
    bytes: int = 0
    motivo: str = ""


@dataclass
class Plano:
    movimentos: list[Movimento] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def vazio(self) -> bool:
        return not self.movimentos


def limpar_nome(nome: str) -> str:
    """Deixa o nome utilizavel no Windows, sem ponto nem espaco no fim."""
    limpo = _PROIBIDOS.sub("", nome).strip()
    limpo = re.sub(r"\s+", " ", limpo).rstrip(". ")
    return limpo or "sem nome"


def _sufixo(qualidade: str | None, idioma: str | None) -> str:
    partes = [p for p in (qualidade, idioma) if p]
    return f" [{' '.join(partes)}]" if partes else ""


def pasta_do_item(raiz: Path, tipo: str, titulo: str, ano: int | None) -> Path:
    """Filmes/Sisu (2022)  ·  Series/The Boys  ·  Jogos/Hollow Knight"""
    titulo = limpar_nome(titulo)
    if tipo == SERIE:
        return raiz / "Series" / titulo
    if tipo == JOGO:
        return raiz / "Jogos" / titulo
    nome = f"{titulo} ({ano})" if ano else titulo
    return raiz / "Filmes" / nome


def nome_final(tipo: str, titulo: str, ano: int | None, temporada: int | None,
               episodio: int | None, qualidade: str | None, idioma: str | None,
               extensao: str) -> str:
    """Sisu (2022) [1080P DUAL].mkv  ·  The Boys - S04E01 [1080P DUAL].mkv"""
    titulo = limpar_nome(titulo)
    sufixo = _sufixo(qualidade, idioma)
    if tipo == SERIE and temporada is not None:
        marca = f"S{temporada:02d}"
        if episodio is not None:
            marca += f"E{episodio:02d}"
        return f"{titulo} - {marca}{sufixo}{extensao}"
    base = f"{titulo} ({ano})" if ano else titulo
    return f"{base}{sufixo}{extensao}"


def caminho_final(raiz: Path, tipo: str, titulo: str, ano: int | None,
                  temporada: int | None, episodio: int | None,
                  qualidade: str | None, idioma: str | None, extensao: str) -> Path:
    pasta = pasta_do_item(raiz, tipo, titulo, ano)
    if tipo == SERIE and temporada is not None:
        pasta = pasta / f"Season {temporada:02d}"
    return pasta / nome_final(tipo, titulo, ano, temporada, episodio,
                              qualidade, idioma, extensao)


def _mapear_origem(origem: Path, arquivos: list) -> dict:
    """Onde cada arquivo do torrent esta agora, de verdade.

    Nao da para confiar no nome que consta no .torrent: depois de uma primeira
    organizacao o arquivo ja se chama "Mr Robot - S01E01.mkv", e nao mais
    "Mr.Robot.S01E01.720p.WEB-DL...mkv". Enquanto o plano era montado com o nome
    antigo, todo movimento saia como "PULADO (sumiu)" — o aviso de "5 obras fora
    do padrao" nunca ia embora e o botao Organizar parecia nao fazer nada.

    Casa primeiro por nome; o que sobrar, por tamanho em bytes, que renomear nao
    muda.
    """
    from .library import normalizar

    if origem.is_file():
        return {arquivos[0]["caminho"]: origem} if arquivos else {}

    por_nome: dict[str, Path] = {}
    por_tamanho: dict[int, list[Path]] = {}
    try:
        for f in origem.rglob("*"):
            if not f.is_file():
                continue
            try:
                tamanho = f.stat().st_size
            except OSError:
                continue
            por_nome.setdefault(normalizar(f.name), f)
            por_tamanho.setdefault(tamanho, []).append(f)
    except (PermissionError, OSError):
        return {}

    saida: dict = {}
    usados: set = set()
    for a in arquivos:                      # 1a volta: nome igual
        alvo = por_nome.get(normalizar(a["caminho"].rsplit("/", 1)[-1]))
        if alvo is not None and alvo not in usados:
            saida[a["caminho"]] = alvo
            usados.add(alvo)
    for a in arquivos:                      # 2a volta: tamanho unico
        if a["caminho"] in saida:
            continue
        iguais = [f for f in por_tamanho.get(a["tamanho"], []) if f not in usados]
        if len(iguais) == 1:
            saida[a["caminho"]] = iguais[0]
            usados.add(iguais[0])
    return saida


def planejar(con: sqlite3.Connection, raiz_biblioteca: Path,
             caminho_torrent: str) -> Plano:
    """Monta o plano de renomeacao de um download, sem executar nada."""
    plano = Plano()
    linha = con.execute(
        "SELECT t.nome, t.infohash, i.tipo, COALESCE(NULLIF(i.titulo_corrigido,''), i.titulo) "
        "AS titulo, i.ano, it.temporada, it.episodios, it.qualidade, it.idioma, "
        "d.caminho_local FROM torrents t "
        "JOIN itens i ON i.id = t.item_id "
        "LEFT JOIN item_torrents it ON it.caminho_torrent = t.caminho "
        "LEFT JOIN disco d ON d.caminho_torrent = t.caminho "
        "WHERE t.caminho = ?", (caminho_torrent,)
    ).fetchone()
    if not linha:
        plano.avisos.append("torrent nao encontrado no indice")
        return plano

    origem = Path(linha["caminho_local"] or "")
    if not linha["caminho_local"] or not origem.exists():
        plano.avisos.append("nada no disco para organizar ainda")
        return plano

    episodios = [int(e) for e in (linha["episodios"] or "").split(",") if e.strip()]
    arquivos = con.execute(
        "SELECT caminho, tamanho, tipo FROM torrent_files "
        "WHERE caminho_torrent = ? AND tipo IN ('midia','legenda') ORDER BY caminho",
        (caminho_torrent,)
    ).fetchall()

    if linha["tipo"] == JOGO:
        destino = pasta_do_item(Path(raiz_biblioteca), JOGO, linha["titulo"], None)
        plano.movimentos.append(Movimento(
            de=str(origem), para=str(destino),
            motivo="jogo: a pasta inteira vai junto, sem renomear arquivo"))
        return plano

    # Ordena os episodios pelo nome para casar com a numeracao do release.
    midias = [a for a in arquivos if a["tipo"] == "midia"]
    midias.sort(key=lambda a: a["caminho"])
    no_disco = _mapear_origem(origem, midias)

    for i, a in enumerate(midias):
        nome_origem = a["caminho"].rsplit("/", 1)[-1]
        ext = Path(nome_origem).suffix
        ep = None
        if linha["tipo"] == SERIE:
            if episodios:
                ep = episodios[i] if i < len(episodios) else None
            else:
                # Temporada completa: pega o numero do proprio nome do arquivo.
                m = re.search(r"[Ss](\d{1,2})[Ee](\d{1,3})", nome_origem)
                ep = int(m.group(2)) if m else i + 1

        destino = caminho_final(
            Path(raiz_biblioteca), linha["tipo"], linha["titulo"], linha["ano"],
            linha["temporada"], ep, linha["qualidade"], linha["idioma"], ext)
        atual = no_disco.get(a["caminho"])
        if atual is None:
            # Nao esta no disco: planejar um movimento aqui so produziria
            # "PULADO (sumiu)" e manteria a obra na fila para sempre.
            plano.avisos.append(f"não encontrei no disco: {nome_origem}")
            continue
        plano.movimentos.append(Movimento(
            de=str(atual), para=str(destino), bytes=a["tamanho"], motivo="mídia"))

    for a in (x for x in arquivos if x["tipo"] == "legenda"):
        nome_origem = a["caminho"].rsplit("/", 1)[-1]
        plano.avisos.append(f"legenda mantida junto: {nome_origem}")

    if not plano.movimentos:
        plano.avisos.append("nenhum arquivo de mídia identificado neste torrent")
    return plano


def executar(plano: Plano, simular: bool = True, qbit=None,
             infohash: str | None = None) -> list[str]:
    """Executa o plano. `simular=True` (padrao) so descreve o que faria.

    Com `qbit` e `infohash`, a renomeacao passa pela API do cliente
    (renameFile + setLocation) em vez de mover o arquivo por fora. Isso importa:
    mover pelas costas do qBittorrent quebra o seeding e faz o cliente apontar
    para um caminho que nao existe mais. O `shutil.move` fica so para o que
    nao esta no cliente - a midia que ja estava no disco antes do app.
    """
    feitos: list[str] = []
    gerenciado = qbit is not None and infohash

    for m in plano.movimentos:
        de, para = Path(m.de), Path(m.para)
        if not de.exists() and not gerenciado:
            feitos.append(f"PULADO (sumiu): {de}")
            continue
        if para.exists() and para != de:
            feitos.append(f"PULADO (ja existe): {para.name}")
            continue
        if simular:
            feitos.append(f"{de.name}\n    → {para}")
            continue

        if gerenciado:
            feitos.append(_mover_pelo_cliente(qbit, infohash, m, de, para))
        else:
            try:
                para.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(de), str(para))
                feitos.append(f"movido: {de.name} → {para.parent.name}/{para.name}")
            except OSError as e:
                feitos.append(f"FALHOU: {de.name} — {e}")
    return feitos


def _mover_pelo_cliente(qbit, infohash: str, m: Movimento,
                        de: Path, para: Path) -> str:
    """Renomeia dentro do torrent e move a pasta, mantendo o seeding."""
    from .motores import ErroMotor

    try:
        arquivos = qbit.arquivos(infohash)
        atual = next((a for a in arquivos
                      if Path(a.get("name", "")).name == de.name), None)
        if atual is None:
            return f"PULADO (não achei {de.name} no torrent)"

        # O caminho dentro do torrent e relativo; so o nome do arquivo muda aqui.
        novo_relativo = str(Path(atual["name"]).parent / para.name).replace("\\", "/")
        if novo_relativo != atual["name"]:
            qbit.renomear_arquivo(infohash, atual["name"], novo_relativo)

        destino_pasta = str(para.parent)
        qbit.mover(infohash, destino_pasta)
        return f"renomeado no qBittorrent: {para.name} → {destino_pasta}"
    except ErroMotor as e:
        return f"FALHOU pelo cliente: {e}"
