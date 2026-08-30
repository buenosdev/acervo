"""Reconciliacao entre o indice de .torrent e o que existe de fato no disco.

Responde, para cada obra: esta baixada, esta pela metade, ou so existe como .torrent?
E acha o caminho inverso - pastas de midia no disco que nao tem .torrent nenhum
apontando para elas (orfas), que sao as unicas onde apagar e irreversivel.

Somente leitura: nada e movido, renomeado ou apagado aqui.
"""
from __future__ import annotations

import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

INDICE, PARCIAL, COMPLETO, ORFAO = "indice", "parcial", "completo", "orfao"

# Um download conta como completo com 99% dos bytes esperados: torrents costumam
# trazer .url e .txt de propaganda que o usuario ja pode ter apagado na mao.
FRACAO_COMPLETO = 0.99
PROFUNDIDADE_MAX = 6
_EXT_MIDIA = {".mkv", ".mp4", ".avi", ".rmvb", ".mov", ".m4v", ".ts", ".wmv", ".mpg", ".iso",
              ".rar", ".bin", ".exe", ".zip", ".7z", ".nsp", ".xci"}


@dataclass
class ResumoDisco:
    pastas_visitadas: int = 0
    arquivos_vistos: int = 0
    bytes_no_disco: int = 0
    completos: int = 0
    parciais: int = 0
    so_indice: int = 0
    orfaos: list[tuple[str, int]] = field(default_factory=list)
    fixados: int = 0
    torrents_soltos: list[str] = field(default_factory=list)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalizar(nome: str) -> str:
    """Compara nomes de pasta ignorando acento e caixa (o Windows ja ignora a caixa)."""
    s = unicodedata.normalize("NFKD", nome.strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c))


# Abaixo disto o tamanho nao identifica nada: legenda, .nfo e capa colidem aos
# montes. Acima, um arquivo de midia tem tamanho praticamente unico.
TAMANHO_IDENTIFICA = 8 * 1024 * 1024


@dataclass
class MapaDisco:
    pastas: dict[str, list[Path]] = field(default_factory=lambda: defaultdict(list))
    arquivos: dict[str, list[tuple[Path, int]]] = field(default_factory=lambda: defaultdict(list))
    # Indice por tamanho em bytes. E o que sobrevive a organizacao: renomear e
    # mover muda nome e caminho, nunca o conteudo — e portanto nunca o tamanho.
    tamanhos: dict[int, list[Path]] = field(default_factory=lambda: defaultdict(list))
    reivindicados: set[Path] = field(default_factory=set)
    torrents_soltos: list[Path] = field(default_factory=list)


def mapear(raiz: Path, ignorar: list[str]) -> tuple[MapaDisco, ResumoDisco]:
    """Percorre a biblioteca uma unica vez, indexando pastas e arquivos por nome."""
    mapa = MapaDisco()
    resumo = ResumoDisco()
    ignorar_norm = {normalizar(x) for x in ignorar}

    pilha: list[tuple[Path, int]] = [(raiz, 0)]
    while pilha:
        pasta, nivel = pilha.pop()
        try:
            entradas = list(pasta.iterdir())
        except (PermissionError, OSError):
            continue
        resumo.pastas_visitadas += 1

        for e in entradas:
            try:
                if e.is_dir():
                    if normalizar(e.name) in ignorar_norm:
                        continue
                    mapa.pastas[normalizar(e.name)].append(e)
                    if nivel < PROFUNDIDADE_MAX:
                        pilha.append((e, nivel + 1))
                else:
                    tamanho = e.stat().st_size
                    resumo.arquivos_vistos += 1
                    resumo.bytes_no_disco += tamanho
                    mapa.arquivos[normalizar(e.name)].append((e, tamanho))
                    if tamanho >= TAMANHO_IDENTIFICA:
                        mapa.tamanhos[tamanho].append(e)
                    if e.suffix.lower() == ".torrent":
                        mapa.torrents_soltos.append(e)
            except (PermissionError, OSError):
                continue

    resumo.torrents_soltos = [str(p) for p in mapa.torrents_soltos]
    return mapa, resumo


def _esta_protegido(caminho: Path, raiz: Path, protegidas: list[str]) -> bool:
    """True se o caminho esta sob alguma pasta marcada como intocavel (! NAO APAGAR)."""
    protegidas_norm = {normalizar(p) for p in protegidas}
    try:
        partes = caminho.relative_to(raiz).parts
    except ValueError:
        partes = caminho.parts
    return any(normalizar(p) in protegidas_norm for p in partes)


def _conferir(candidato: Path, arquivos: list[sqlite3.Row]) -> tuple[int, int]:
    """Soma os bytes que estao no disco para os arquivos esperados do torrent.

    Casa por nome de arquivo (nao por caminho completo): downloads antigos foram
    renomeados e reorganizados na mao ao longo dos anos.
    """
    if candidato.is_file():
        tamanho = candidato.stat().st_size
        esperado = sum(a["tamanho"] for a in arquivos)
        return (tamanho if tamanho == esperado else min(tamanho, esperado)), esperado

    presentes: dict[str, int] = {}
    pilha = [candidato]
    while pilha:
        pasta = pilha.pop()
        try:
            for e in pasta.iterdir():
                if e.is_dir():
                    pilha.append(e)
                else:
                    try:
                        presentes[normalizar(e.name)] = e.stat().st_size
                    except OSError:
                        pass
        except (PermissionError, OSError):
            continue

    # So conta o que o app baixaria de verdade. Sem isso, uma pasta onde sobrou
    # apenas um .url de propaganda de 45 bytes apareceria como "parcial".
    #
    # A conferencia e por nome e, quando o nome nao bate, por tamanho: depois de
    # organizar, o arquivo se chama "Bom Garoto (2026).mkv" e nao mais
    # "Bom.Garoto.2026.WEB-DL...mkv". Sem a segunda volta, uma obra organizada
    # aparecia como se nao estivesse no disco.
    from collections import Counter

    sobrando = Counter(t for t in presentes.values() if t >= TAMANHO_IDENTIFICA)
    bytes_ok = 0
    esperado = 0
    pendentes = []
    for a in arquivos:
        if a["tipo"] == "lixo":
            continue
        esperado += a["tamanho"]
        nome = normalizar(a["caminho"].rsplit("/", 1)[-1])
        if presentes.get(nome) == a["tamanho"]:
            bytes_ok += a["tamanho"]
            if sobrando[a["tamanho"]]:
                sobrando[a["tamanho"]] -= 1       # ja usado por este arquivo
        else:
            pendentes.append(a)

    for a in pendentes:
        tam = a["tamanho"]
        if tam >= TAMANHO_IDENTIFICA and sobrando[tam]:
            sobrando[tam] -= 1
            bytes_ok += tam
    return bytes_ok, esperado


def _localizar(mapa: MapaDisco, nome_torrent: str, arquivos: list[sqlite3.Row]) -> Path | None:
    """Acha no disco o conteudo de um torrent, entre todos os candidatos.

    Antes bastava a primeira pista: pasta com o mesmo nome do torrent. Isso
    quebrava depois de organizar, porque a organizacao move a midia para
    `Filmes/Titulo (Ano)` e deixa para tras a pasta original com as sobras
    (legenda, .url de propaganda). A pasta vazia continuava ganhando pelo nome,
    e o filme inteiro virava "orfao" a poucos metros dali.

    Agora todas as pistas viram candidatos — nome da pasta, nome do maior
    arquivo, e tamanho em bytes — e vence quem de fato tem o conteudo.
    """
    candidatos: list[Path] = []

    def juntar(caminho: Path | None) -> None:
        if caminho is not None and caminho not in candidatos:
            candidatos.append(caminho)

    chave = normalizar(nome_torrent)
    for pasta in mapa.pastas.get(chave, []):
        juntar(pasta)
    for caminho, _ in mapa.arquivos.get(chave, []):
        juntar(caminho)

    if arquivos:
        uteis = [a for a in arquivos if a["tipo"] != "lixo"] or list(arquivos)
        maior = max(uteis, key=lambda a: a["tamanho"])
        nome_maior = normalizar(maior["caminho"].rsplit("/", 1)[-1])
        for caminho, tamanho in mapa.arquivos.get(nome_maior, []):
            if tamanho == maior["tamanho"]:
                juntar(caminho if len(uteis) == 1 else caminho.parent)
        juntar(_por_tamanho(mapa, uteis, maior))

    if not candidatos:
        return None
    if len(candidatos) == 1:
        return candidatos[0]

    # Desempate honesto: quem tem mais bytes do torrent no disco.
    melhor, melhor_bytes = candidatos[0], -1
    for c in candidatos:
        presentes, _ = _conferir(c, arquivos)
        if presentes > melhor_bytes:
            melhor, melhor_bytes = c, presentes
    return melhor


def _por_tamanho(mapa: MapaDisco, uteis: list, maior) -> Path | None:
    """Acha o conteudo pelo tamanho dos arquivos, ignorando nome e caminho."""
    if maior["tamanho"] < TAMANHO_IDENTIFICA:
        return None
    candidatos = [c for c in mapa.tamanhos.get(maior["tamanho"], [])
                  if c not in mapa.reivindicados]
    if not candidatos:
        return None
    if len(uteis) == 1:
        return candidatos[0]

    # Varios torrents podem ter um arquivo do mesmo tamanho (uma temporada
    # remuxada duas vezes, por exemplo). Desempata pela pasta que contem mais
    # arquivos do tamanho certo.
    esperados = {a["tamanho"] for a in uteis if a["tamanho"] >= TAMANHO_IDENTIFICA}
    melhor, melhor_nota = None, 0
    for c in candidatos:
        pasta = c.parent
        try:
            nota = sum(1 for f in pasta.iterdir()
                       if f.is_file() and f.stat().st_size in esperados)
        except (PermissionError, OSError):
            continue
        if nota > melhor_nota:
            melhor, melhor_nota = pasta, nota
    return melhor or candidatos[0].parent


def reconciliar(con: sqlite3.Connection, raiz_biblioteca: Path, ignorar: list[str],
                protegidas: list[str], extras: list[Path] | None = None) -> ResumoDisco:
    """Cruza o indice com o disco e regrava a tabela `disco`.

    `extras` sao pastas fora da biblioteca que tambem devem ser olhadas — na
    pratica, a pasta de download. Ela costuma ser irma da biblioteca, nao filha:
    sem varre-la, o que esta baixando agora e o que acabou de baixar ficam
    invisiveis para o app. Era o que fazia "Conferir disco" zerar o contador de
    Baixando no meio de um download, e o que impedia o arquivo concluido de ser
    levado para a biblioteca.
    """
    raiz = Path(raiz_biblioteca)
    mapa, resumo = mapear(raiz, ignorar)

    for extra in extras or []:
        extra = Path(extra)
        if not extra.is_dir():
            continue
        try:
            if extra.resolve() == raiz.resolve() or raiz.resolve() in extra.resolve().parents:
                continue                 # ja foi varrida como parte da biblioteca
        except OSError:
            continue
        # A pasta de download nao entra na lista de ignorados: ali dentro,
        # justamente, esta o que interessa.
        mapa_extra, resumo_extra = mapear(extra, [])
        for chave, caminhos in mapa_extra.pastas.items():
            mapa.pastas[chave].extend(caminhos)
        for chave, arquivos in mapa_extra.arquivos.items():
            mapa.arquivos[chave].extend(arquivos)
        for tamanho, caminhos in mapa_extra.tamanhos.items():
            mapa.tamanhos[tamanho].extend(caminhos)
        resumo.arquivos_vistos += resumo_extra.arquivos_vistos
        resumo.bytes_no_disco += resumo_extra.bytes_no_disco
        resumo.pastas_visitadas += resumo_extra.pastas_visitadas
    con.execute("DELETE FROM disco")

    torrents = con.execute(
        "SELECT caminho, infohash, nome FROM torrents WHERE corrompido = 0"
    ).fetchall()

    for t in torrents:
        arquivos = con.execute(
            "SELECT caminho, tamanho, tipo FROM torrent_files WHERE caminho_torrent = ?",
            (t["caminho"],),
        ).fetchall()

        alvo = _localizar(mapa, t["nome"], arquivos)
        if alvo is None:
            resumo.so_indice += 1
            con.execute(
                "INSERT OR REPLACE INTO disco (caminho_local, infohash, caminho_torrent, "
                "estado, bytes_presentes, bytes_esperados, conferido_em) "
                "VALUES (?, ?, ?, ?, 0, ?, ?)",
                (f"(indice) {t['caminho']}", t["infohash"], t["caminho"], INDICE,
                 sum(a["tamanho"] for a in arquivos), _agora()),
            )
            continue

        mapa.reivindicados.add(alvo)
        presentes, esperados = _conferir(alvo, arquivos)
        completo = esperados > 0 and presentes >= esperados * FRACAO_COMPLETO
        estado = COMPLETO if completo else (PARCIAL if presentes > 0 else INDICE)
        fixado = _esta_protegido(alvo, raiz, protegidas)

        if estado == COMPLETO:
            resumo.completos += 1
        elif estado == PARCIAL:
            resumo.parciais += 1
        else:
            resumo.so_indice += 1
        if fixado:
            resumo.fixados += 1

        con.execute(
            "INSERT OR REPLACE INTO disco (caminho_local, infohash, caminho_torrent, estado, "
            "bytes_presentes, bytes_esperados, fixado, conferido_em) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(alvo), t["infohash"], t["caminho"], estado, presentes, esperados,
             int(fixado), _agora()),
        )

    _registrar_orfaos(con, mapa, raiz, protegidas, resumo)
    con.commit()
    return resumo


def _registrar_orfaos(con: sqlite3.Connection, mapa: MapaDisco, raiz: Path,
                      protegidas: list[str], resumo: ResumoDisco) -> None:
    """Pastas com midia que nenhum .torrent do indice reivindicou.

    Sao o ponto cego da biblioteca: sem .torrent, apagar o arquivo e definitivo.
    """
    dentro_de_reivindicado = {p.resolve() for p in mapa.reivindicados}
    # Torrent de arquivo unico e reivindicado como arquivo, nao como pasta. Sem
    # descontar esses bytes, a pasta que o contem reaparecia como orfa e o mesmo
    # filme era contado duas vezes — uma como "no disco", outra como "sem dono".
    arquivos_reivindicados = {p for p in dentro_de_reivindicado if p.is_file()}

    for caminhos in mapa.pastas.values():
        for pasta in caminhos:
            resolvido = pasta.resolve()
            if resolvido in dentro_de_reivindicado:
                continue
            # Subpasta de algo ja reivindicado nao e orfa por conta propria.
            if any(pai in dentro_de_reivindicado for pai in resolvido.parents):
                continue

            # So conta midia solta diretamente aqui dentro. Sem isso, uma pasta
            # organizadora como "! Filmes e Series" viraria uma orfa de 68 GB
            # junto com cada uma das pastas dentro dela.
            bytes_midia = 0
            try:
                for e in pasta.iterdir():
                    if not (e.is_file() and e.suffix.lower() in _EXT_MIDIA):
                        continue
                    if e.resolve() in arquivos_reivindicados:
                        continue                  # ja tem dono
                    bytes_midia += e.stat().st_size
            except (PermissionError, OSError):
                continue
            if bytes_midia == 0:
                continue

            fixado = _esta_protegido(pasta, raiz, protegidas)
            resumo.orfaos.append((str(pasta), bytes_midia))
            if fixado:
                resumo.fixados += 1
            con.execute(
                "INSERT OR REPLACE INTO disco (caminho_local, infohash, caminho_torrent, "
                "estado, bytes_presentes, bytes_esperados, fixado, conferido_em) "
                "VALUES (?, NULL, NULL, ?, ?, 0, ?, ?)",
                (str(pasta), ORFAO, bytes_midia, int(fixado), _agora()),
            )

    resumo.orfaos.sort(key=lambda x: -x[1])
