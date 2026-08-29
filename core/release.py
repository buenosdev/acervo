"""Parser de nome de release, afinado para o acervo brasileiro.

Recebe o nome de um .torrent (ou o campo `name` de dentro dele) e devolve
titulo limpo, ano, temporada/episodio, qualidade, idioma e grupo.

O titulo cru e sempre preservado: quando o parser erra, a correcao e feita
na interface e gravada no banco, sem mexer no codigo.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

FILME, SERIE, JOGO, DESCONHECIDO = "filme", "serie", "jogo", "desconhecido"

# ---------------------------------------------------------------- limpeza

# Assinaturas de site que os grupos brasileiros cravam no nome do arquivo.
_SITES = [
    r"\[\s*ACESSE[^\]]*\]",
    r"\{\s*WWW\.[^}]*\}",
    r"\[\s*www\.[^\]]*\]",
    r"^COMANDO\.?\s*(TO|LA)\s*-\s*",
    r"\bWWW\.BLUDV\.COM\b",
    r"\bWWW\.AZTORRENTS\.ORG\b",
    r"\bWOLVERDONFILMES\.COM\b",
    r"\bCOMANDOTORRENTS\.COM\b",
    r"\bwww\.animestotais\.xyz\b",
    r"\bwww\.theseriesdubladas\.com\b",
    r"\bDUBLASERIES\.TV\b",
    r"\bTorrentDosFilmes\.SE\b",
    r"\bBaixe\s+do\s+Original\b",
    r"\bAcesse\s+o\s+ORIGINAL\b",
    r"\bBLUDV\b",
    r"\bSTARCKFILMES\b",
    r"-\s*Gilkerberus\b",
    r"\bBy\.?\s*Luan\.?\s*Harper\b",
]
_RE_SITES = [re.compile(p, re.IGNORECASE) for p in _SITES]

# Extensoes que aparecem coladas no nome (".mkv.1.torrent", ".rar.torrent").
_RE_EXT_TORRENT = re.compile(r"\.torrent$", re.IGNORECASE)
_RE_EXT_CONTEUDO = re.compile(r"\.(?:mkv|mp4|avi|rmvb|rar|iso|exe|bin|zip|7z)$", re.IGNORECASE)
# Sufixo que o navegador cria ao baixar o mesmo arquivo duas vezes: "nome.1.torrent".
_RE_SUFIXO_COPIA = re.compile(r"\.\d{1,2}$")

_RE_ESPACOS = re.compile(r"\s+")
_RE_LIXO_BORDA = re.compile(r"^[\s\-–—_.,:;|~+]+|[\s\-–—_.,:;|~+(\[{]+$")

# ---------------------------------------------------------------- marcadores
# Tudo aqui indica "acabou o titulo, comecou a ficha tecnica".

_MARCADORES = [
    # (categoria, regex) -- a ordem so importa para desempate na mesma posicao
    # extras so aceita numeros ligados por hifen: "S04E01-02-03". Aceitar espaco
    # faria "The Boys S03E06 2022" virar episodio 202.
    ("temporada_ep", r"\bS(?P<st>\d{1,2})\s?E(?P<ep>\d{1,3})(?P<extras>(?:-\d{1,3})*)\b"),
    ("temporada_faixa", r"\b(?P<t1>\d{1,2})\s*[ºªo°a]?\s*(?:à|a|ao|-)\s*(?P<t2>\d{1,2})\s*[ºªo°a]?\s*temporadas?\b"),
    ("temporada_pt", r"\b(?P<tp>\d{1,2})\s*[ºª°]\s*\.?\s*Temporada\b"),
    ("temporada_en", r"\bS(?P<sp>\d{1,2})\b(?!\s?E\d)"),
    ("temporada_season", r"\bSeason\s?(?P<ss>\d{1,2})\b"),
    ("ano", r"[\(\[]?\b(?P<ano>19\d{2}|20[0-3]\d)\b[\)\]]?"),
    ("qualidade", r"\b(?P<q>2160p|1080p|720p|576p|480p|4K|FULL\s?HD)\b"),
    ("fonte", r"\b(?P<f>WEB-?DL|WEB-?Rip|BluRay|Blu-Ray|BDRip|BRRip|BDRemux|DVDRip|DVD-?Rip|HDTV|REMUX|HDRip|WEB|DVD)\b"),
    ("codec", r"\b(?P<c>x\s?26[45]|H\.?\s?26[45]|HEVC|AVC|XviD|DivX|10bit)\b"),
    ("idioma", r"\b(?P<i>DUAL|DUBLAD[OA]S?|NACIONAL|LEGENDAD[OA]|dual\s+audio)\b"),
    ("hdr", r"\b(?P<h>HDR10\+|HDR10|HDR|DV|Dolby\s?Vision)\b"),
    ("audio", r"\b(?P<a>DTS-HD(?:\s?MA)?|DDP\s?\d\.\d|EAC3|AC3|AAC\d?(?:\.\d)?|FLAC|Atmos|TrueHD|\d\.\d)\b"),
    ("jogo_repack", r"\[?\b(?P<r>FitGirl\s+Repack|R\.?G\.?\s+Mechanics|Repack|GOG|Codex|Plaza|Skidrow|Empress|ElAmigos)\b\]?"),
    # Versao de jogo: ou tem "v" na frente ("v41.78.16"), ou tem tres ou mais
    # partes ("1.0.20385"). Aceitar "5.1" faria o layout de audio virar versao.
    ("jogo_versao", r"\b(?P<v>v\d+(?:\.\d+)*[a-z]?|\d+\.\d+\.\d+[\d.]*[a-z]?)\b(?![\s]*[ºª°])"),
    ("jogo_por", r"\bby\s+\w+"),
    ("jogo_plataforma", r"\b(?P<p>win_gog|win|PC|Switch|PS[2-5]|NSP|XCI)\b"),
]
_RE_MARCADORES = [(cat, re.compile(rx, re.IGNORECASE)) for cat, rx in _MARCADORES]

# Grupo de release colado no fim: "-SF", "-EMPRESS", "[YTS.MX]".
_RE_GRUPO_FIM = re.compile(
    r"[-–]\s*(?P<g>[A-Za-z][A-Za-z0-9._]{1,20})\s*$|\[(?P<g2>[A-Za-z][A-Za-z0-9._\s]{1,20})\]\s*$"
)
# Grupos que nao sao caixa-alta e por isso nao passam no teste generico abaixo.
_GRUPOS_CONHECIDOS = {
    "zigzag", "pia", "yts.mx", "yts.am", "yts.bz", "rich_jc", "xatab", "pioneer",
    "mop030b", "rune", "alias", "flt", "empress", "hoodlum", "codex", "plaza",
    "skidrow", "elamigos", "rarbg", "qoob",
}


def _parece_grupo(token: str) -> bool:
    """"-EMPRESS" e grupo; "-Villains" e parte do titulo ("LEGO DC Super-Villains")."""
    t = token.strip()
    if t.lower() in _GRUPOS_CONHECIDOS:
        return True
    return len(t) >= 2 and t.upper() == t and not t.isdigit()
# Bloco entre colchetes no comeco: "[Avalon] ", "[R.G. Mechanics] ".
_RE_GRUPO_INICIO = re.compile(r"^\s*\[(?P<g>[^\]]{1,30})\]\s*")

# Artigo jogado para o fim, tipico de ROM: "Legend of Zelda, The - ...".
_RE_ARTIGO_INVERTIDO = re.compile(
    r"^(?P<resto>.+?),\s*(?P<artigo>The|A|An|O|Os|As|Um|Uma|Le|La|Les)\b", re.IGNORECASE
)
# Parenteses de metadado de ROM: "(World)", "(En,Ja,Fr)", "(Rev 3)".
_RE_ROM_META = re.compile(
    r"\((?:World|USA|Europe|Japan|Rev\s*\d+|[A-Z][a-z](?:,[A-Z][a-z])+)\)", re.IGNORECASE
)

_ARQUIVOS_LIXO_EXT = {".url", ".txt", ".nfo", ".html", ".htm", ".lnk", ".jpg", ".png", ".gif"}
# So o que e propaganda de fato. Nome de site NAO entra aqui: o filme de verdade
# muitas vezes se chama "A.Presenca.2021.1080p.BluRay.DUAL.COMANDO.TO.mkv" e marca-lo
# como lixo faria o app baixar tudo menos o filme.
_RE_VIDEO_PROPAGANDA = re.compile(
    r"acesse|baixar\s+outros|leia-?me|readme|\bsample\b|\bamostra\b|^trailer\b",
    re.IGNORECASE,
)
# Video de propaganda tem alguns MB; episodio ou filme de verdade nao.
_LIMITE_VIDEO_REAL = 20 * 1024 * 1024
_EXT_MIDIA = {".mkv", ".mp4", ".avi", ".rmvb", ".mov", ".m4v", ".ts", ".wmv", ".mpg", ".mpeg"}
_EXT_LEGENDA = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt"}


@dataclass
class Release:
    titulo: str
    titulo_cru: str
    tipo: str = DESCONHECIDO
    ano: int | None = None
    temporada: int | None = None
    episodios: list[int] = field(default_factory=list)
    temporada_completa: bool = False
    qualidade: str | None = None
    fonte: str | None = None
    codec: str | None = None
    idioma: str | None = None
    hdr: list[str] = field(default_factory=list)
    audio: str | None = None
    grupo: str | None = None

    @property
    def rotulo(self) -> str:
        """Como o item aparece na interface."""
        p = self.titulo
        if self.ano:
            p += f" ({self.ano})"
        if self.temporada is not None:
            p += f" - T{self.temporada:02d}"
            if self.episodios:
                if len(self.episodios) == 1:
                    p += f"E{self.episodios[0]:02d}"
                else:
                    p += f"E{self.episodios[0]:02d}-{self.episodios[-1]:02d}"
            elif self.temporada_completa:
                p += " (completa)"
        return p


def _normalizar_separadores(texto: str) -> str:
    """Troca . e _ por espaco, preservando pontos entre digitos (5.1, v1.0.3)."""
    texto = texto.replace("_", " ")
    texto = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", texto)
    return _RE_ESPACOS.sub(" ", texto).strip()


def _limpar(nome: str) -> str:
    # Ordem importa: ".torrent", depois o ".1" de copia, depois a extensao do conteudo.
    # Repetir cegamente comeria a versao do jogo ("Project.Zomboid.v41.78.16.rar").
    texto = _RE_EXT_TORRENT.sub("", nome)
    texto = _RE_SUFIXO_COPIA.sub("", texto)
    texto = _RE_EXT_CONTEUDO.sub("", texto)
    for rx in _RE_SITES:
        texto = rx.sub(" ", texto)
    m = _RE_GRUPO_INICIO.match(texto)
    if m and not re.search(r"\d{4}", m.group("g")):
        texto = texto[m.end():]
    # Slug tudo-minusculo com hifens: "need-for-speed-underground".
    if " " not in texto and "-" in texto and texto == texto.lower():
        texto = texto.replace("-", " ")
    texto = _normalizar_separadores(texto)
    return _RE_ESPACOS.sub(" ", texto).strip()


def _expandir_episodios(primeiro: int, extras: str) -> list[int]:
    """E01-02-03 -> [1,2,3];  E01-03 -> [1,2,3] (faixa inclusiva)."""
    numeros = [int(n) for n in re.findall(r"\d{1,3}", extras or "")]
    if not numeros:
        return [primeiro]
    if len(numeros) == 1 and numeros[0] > primeiro:
        return list(range(primeiro, numeros[0] + 1))
    return [primeiro] + numeros


def _tem_ano(versao: str) -> bool:
    """True se algum componente do 'numero de versao' e, na verdade, um ano.

    "M3GAN.2.0.2025" e "Meu.Malvado.Favorito.4.2024.1080p" tinham tres ou mais
    componentes e passavam por versao de jogo — o filme ia para a estante
    errada e nunca achava capa. Versao de jogo com um ano no meio praticamente
    nao existe; titulo seguido de ano existe o tempo todo.

    Nao vale para token com "v" na frente ("v41.78.16"), que e inequivoco.
    """
    if versao[:1].lower() == "v":
        return False
    for parte in versao.rstrip("abcdefghijklmnopqrstuvwxyz").split("."):
        if len(parte) == 4 and parte.isdigit() and 1900 <= int(parte) <= 2099:
            return True
    return False


def analisar(nome: str, dica_tipo: str | None = None) -> Release:
    """Analisa o nome de um release. `dica_tipo` vem da pasta (Filmes/Series/Jogos)."""
    texto = _limpar(nome)
    r = Release(titulo=texto, titulo_cru=nome, tipo=dica_tipo or DESCONHECIDO)

    # Marcadores de jogo (versao, "by fulano", plataforma) sao genericos demais para
    # filme/serie: cortariam "Meu Malvado Favorito 4.2024" no "4.2024".
    pode_ser_jogo = dica_tipo in (None, JOGO)
    # "5.1", "2.0", "DV", "HDR" aparecem em titulo real ("M3GAN 2.0"); servem para
    # preencher a ficha tecnica, nunca para decidir onde o titulo acaba.
    nao_cortam = {"audio", "hdr"}

    corte = len(texto)
    for categoria, rx in _RE_MARCADORES:
        if categoria.startswith("jogo_") and not pode_ser_jogo:
            continue
        for m in rx.finditer(texto):
            if m.start() == 0:  # marcador na posicao 0 deixaria o titulo vazio
                continue
            g = m.groupdict()

            if categoria == "temporada_ep":
                r.temporada = int(g["st"])
                r.episodios = _expandir_episodios(int(g["ep"]), g.get("extras", ""))
                r.tipo = SERIE
            # As tres regras abaixo sao menos especificas que S00E00 e podem casar
            # com o mesmo trecho: "1º à 4º temporada" tambem casa "4º temporada".
            # A primeira que acerta manda.
            elif categoria == "temporada_faixa":
                if r.temporada is None:
                    r.temporada = int(g["t1"])
                r.temporada_completa = True
                r.tipo = SERIE
            elif categoria == "temporada_pt":
                if r.temporada is None:
                    r.temporada = int(g["tp"])
                r.temporada_completa = True
                r.tipo = SERIE
            elif categoria in ("temporada_en", "temporada_season"):
                if r.temporada is None:
                    r.temporada = int(g.get("sp") or g.get("ss"))
                r.temporada_completa = True
                r.tipo = SERIE
            elif categoria == "ano":
                if r.ano is None:
                    r.ano = int(g["ano"])
            elif categoria == "qualidade":
                r.qualidade = r.qualidade or g["q"].upper().replace(" ", "")
            elif categoria == "fonte":
                r.fonte = r.fonte or g["f"]
            elif categoria == "codec":
                r.codec = r.codec or g["c"].replace(" ", "").replace(".", "")
            elif categoria == "idioma":
                r.idioma = r.idioma or g["i"].upper()
            elif categoria == "hdr":
                # Um release pode ter varios: "DV HDR10+ HDR".
                for mh in rx.finditer(texto):
                    v = mh.group("h").upper()
                    if v not in r.hdr:
                        r.hdr.append(v)
            elif categoria == "audio":
                r.audio = r.audio or g["a"]
            elif categoria in ("jogo_repack", "jogo_versao", "jogo_por", "jogo_plataforma"):
                # "M3GAN.2.0.2025" tem tres componentes e passava por versao de
                # jogo — o filme inteiro ia parar na estante errada. Numero que
                # termina em ano nao e versao: e titulo seguido do ano.
                if categoria == "jogo_versao" and _tem_ano(g.get("v", "")):
                    pass
                elif r.tipo in (DESCONHECIDO, JOGO):
                    r.tipo = JOGO

            if categoria not in nao_cortam:
                corte = min(corte, m.start())
            break  # so a primeira ocorrencia de cada categoria interessa

    if re.search(r"Temporada\s+Completa|\bComplete\b", texto, re.IGNORECASE):
        r.temporada_completa = True
        if r.tipo == DESCONHECIDO:
            r.tipo = SERIE

    titulo = texto[:corte]
    titulo = _RE_ROM_META.sub(" ", titulo)
    titulo = _RE_LIXO_BORDA.sub("", titulo)
    m = _RE_GRUPO_FIM.search(titulo)
    if m and _parece_grupo(m.group("g") or m.group("g2") or ""):
        titulo = titulo[: m.start()]
    m = _RE_ARTIGO_INVERTIDO.match(titulo)
    if m:
        titulo = f"{m.group('artigo')} {m.group('resto')}{titulo[m.end():]}"
    titulo = _RE_LIXO_BORDA.sub("", _RE_ESPACOS.sub(" ", titulo))
    if titulo and titulo == titulo.lower():  # veio de slug: "need for speed underground"
        titulo = titulo.title()

    r.titulo = titulo or texto
    if r.tipo == DESCONHECIDO:
        r.tipo = FILME

    m = _RE_GRUPO_FIM.search(texto)
    if m:
        r.grupo = (m.group("g") or m.group("g2") or "").strip() or None

    return r


def classificar_arquivo(caminho: str, tipo_item: str, tamanho: int | None = None) -> str:
    """Classifica um arquivo de dentro do torrent: midia, legenda, lixo, extra, arquivo_jogo.

    Em torrent de jogo nada vira lixo: partes .rar/.bin sao todas obrigatorias.
    """
    nome = caminho.rsplit("/", 1)[-1]
    ponto = nome.rfind(".")
    ext = nome[ponto:].lower() if ponto > 0 else ""

    if tipo_item == JOGO:
        return "arquivo_jogo"
    if ext in _EXT_MIDIA:
        # Propaganda em video se disfarca de midia: "ACESSE O OFICIAL - ....mp4".
        if _RE_VIDEO_PROPAGANDA.search(nome):
            return "lixo"
        if tamanho is not None and tamanho < _LIMITE_VIDEO_REAL:
            return "lixo"
        return "midia"
    if ext in _EXT_LEGENDA:
        return "legenda"
    if ext in _ARQUIVOS_LIXO_EXT:
        return "lixo"
    return "extra"


_EXT_ARQUIVO_JOGO = {".rar", ".zip", ".7z", ".iso", ".bin", ".exe", ".msi", ".cue", ".nsp", ".xci"}


def maior_e_video(arquivos: list[tuple[str, int]]) -> bool:
    """True se o maior arquivo do torrent e um video.

    E a pista que nao mente. O nome do release pode ter numero que parece versao
    ("M3GAN.2.0.2025"), a pasta pode estar errada, o grupo pode ser desconhecido
    — mas um torrent cujo maior arquivo e um .mkv de 2,7 GB nao e um jogo. Esta
    funcao existe para ter a ultima palavra sobre `parece_jogo`.
    """
    if not arquivos:
        return False
    caminho, _ = max(arquivos, key=lambda a: a[1])
    nome = caminho.rsplit("/", 1)[-1].lower()
    ponto = nome.rfind(".")
    return (nome[ponto:] if ponto > 0 else "") in _EXT_MIDIA


def parece_jogo(arquivos: list[tuple[str, int]]) -> bool:
    """True se arquivos compactados/executaveis dominam o torrent.

    Trava de seguranca: um jogo classificado como filme (por estar fora da pasta
    Jogos) teria .rar e .txt desmarcados e baixaria quebrado.
    """
    total = sum(t for _, t in arquivos)
    if not total:
        return False
    de_jogo = 0
    for caminho, tamanho in arquivos:
        nome = caminho.rsplit("/", 1)[-1].lower()
        ponto = nome.rfind(".")
        ext = nome[ponto:] if ponto > 0 else ""
        # ".r00", ".r01"... sao continuacoes de .rar
        if ext in _EXT_ARQUIVO_JOGO or re.fullmatch(r"\.r\d{2}", ext):
            de_jogo += tamanho
    return de_jogo > total / 2


def chave_busca(titulo: str) -> str:
    """Chave normalizada para casar titulos entre si e com o TMDB (sem acento nem pontuacao)."""
    s = unicodedata.normalize("NFKD", titulo.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return _RE_ESPACOS.sub(" ", s).strip()
