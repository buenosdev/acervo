"""Busca capa, sinopse e nota: TMDB para filmes e series, SteamGridDB para jogos.

Tudo fica em cache no banco e em dados/posters/, entao a segunda abertura do
catalogo funciona offline. So o titulo e enviado para fora - nada de caminho de
arquivo, nome de pasta ou infohash.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .release import chave_busca

TMDB = "https://api.themoviedb.org/3"
TMDB_IMAGENS = "https://image.tmdb.org/t/p/w500"
TMDB_FUNDOS = "https://image.tmdb.org/t/p/w1280"
SGDB = "https://www.steamgriddb.com/api/v2"

PAUSA = 0.25  # respeita o limite de requisicoes das duas APIs

# O SteamGridDB fica atras do Cloudflare, que devolve 403 (erro 1010) para o
# User-Agent padrao do urllib. Sem isto a chave certa parece invalida.
CABECALHOS = {
    "User-Agent": "Acervo/1.0 (gerenciador local de biblioteca; +https://github.com)",
    "Accept": "application/json",
}


class SemChave(RuntimeError):
    pass


@dataclass
class ResumoMetadados:
    tentados: int = 0
    encontrados: int = 0
    posters: int = 0
    sem_correspondencia: list[str] = None
    erros: list[str] = None

    def __post_init__(self):
        self.sem_correspondencia = self.sem_correspondencia or []
        self.erros = self.erros or []


def _json(url: str, cabecalhos: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={**CABECALHOS, **(cabecalhos or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _baixar_imagem(url: str, destino: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers=CABECALHOS)
        with urllib.request.urlopen(req, timeout=25) as r:
            dados = r.read()
        if len(dados) < 1024:
            return False
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(dados)
        return True
    except (urllib.error.URLError, OSError):
        return False


def _pontuar(titulo_busca: str, candidato: str, ano_busca: int | None,
             ano_candidato: int | None) -> float:
    """Quanto o resultado combina com o que procuramos. Titulo pesa mais que ano."""
    a, b = chave_busca(titulo_busca), chave_busca(candidato)
    if not a or not b:
        return 0.0
    if a == b:
        nota = 1.0
    elif a in b or b in a:
        nota = 0.75
    else:
        palavras_a, palavras_b = set(a.split()), set(b.split())
        comuns = palavras_a & palavras_b
        nota = len(comuns) / max(len(palavras_a), len(palavras_b)) * 0.7
    if ano_busca and ano_candidato:
        nota += 0.25 if ano_busca == ano_candidato else (0.1 if abs(ano_busca - ano_candidato) <= 1 else -0.2)
    return nota


def buscar_tmdb(titulo: str, ano: int | None, serie: bool, chave: str,
                idioma: str = "pt-BR") -> dict | None:
    rota = "tv" if serie else "movie"
    params = {"api_key": chave, "query": titulo, "language": idioma,
              "include_adult": "false"}
    # Em serie o ano do release e o da temporada, nao o da estreia: filtrar por
    # ele descartaria "Mr. Robot" (estreou em 2015) ao procurar a 2a temporada.
    # O ano continua pesando na pontuacao, so nao corta a busca.
    if ano and not serie:
        params["year"] = ano

    def consultar(p: dict) -> dict:
        try:
            return _json(f"{TMDB}/search/{rota}?" + urllib.parse.urlencode(p))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SemChave("chave do TMDB recusada (401). Use a “API Key (v3 auth)”, "
                               "a curta de 32 caracteres.") from e
            raise

    dados = consultar(params)
    # Filme com ano errado no nome do arquivo: tenta de novo sem o filtro.
    if not dados.get("results") and "year" in params:
        del params["year"]
        dados = consultar(params)

    melhor, melhor_nota = None, 0.0
    for r in dados.get("results", [])[:8]:
        nome = r.get("name") if serie else r.get("title")
        # A busca e feita em pt-BR, entao o TMDB responde com o titulo traduzido
        # — e o nome do arquivo quase sempre esta no original. Comparar so o
        # traduzido dava nota zero para "Summer Time Rendering" (que volta como
        # "A Ilha das Sombras") e para "The Butterfly Effect 3" ("Efeito
        # Borboleta"). Pontuar os dois e ficar com o melhor resolve a classe
        # inteira desses casos.
        original = r.get("original_name") if serie else r.get("original_title")
        data = r.get("first_air_date") if serie else r.get("release_date")
        ano_r = int(data[:4]) if data and data[:4].isdigit() else None
        # Em serie o ano do arquivo e o da temporada, nao o da estreia. Deixar
        # ele pontuar fazia "Mr. Robot" (estreia 2015) perder 0,2 ao procurar a
        # 2a temporada (2017) e o "Mr. Robot Digital After Show" (2016) ganhar
        # por proximidade — foi assim que a serie acabou partida em duas obras.
        ano_para_nota = None if serie else ano
        nota = max(_pontuar(titulo, nome or "", ano_para_nota, ano_r),
                   _pontuar(titulo, original or "", ano_para_nota, ano_r))
        if nota > melhor_nota:
            melhor, melhor_nota = r, nota

    # Abaixo disso e chute: melhor deixar sem capa do que colar a capa errada.
    if not melhor or melhor_nota < 0.5:
        return None
    data = melhor.get("first_air_date") if serie else melhor.get("release_date")
    return {
        "tmdb_id": melhor.get("id"),
        "titulo": melhor.get("name") if serie else melhor.get("title"),
        "ano": int(data[:4]) if data and data[:4].isdigit() else None,
        "sinopse": (melhor.get("overview") or "").strip() or None,
        "nota": melhor.get("vote_average") or None,
        "poster_url": TMDB_IMAGENS + melhor["poster_path"] if melhor.get("poster_path") else None,
        "fundo_url": TMDB_FUNDOS + melhor["backdrop_path"] if melhor.get("backdrop_path") else None,
    }


def buscar_steamgriddb(titulo: str, chave: str) -> dict | None:
    cabecalhos = {"Authorization": f"Bearer {chave}"}
    termo = urllib.parse.quote(titulo)
    try:
        dados = _json(f"{SGDB}/search/autocomplete/{termo}", cabecalhos)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SemChave("chave do SteamGridDB recusada (401). Gere outra em "
                           "steamgriddb.com/profile/preferences/api.") from e
        if e.code == 403:
            raise SemChave("o SteamGridDB bloqueou a requisicao (403). Costuma ser "
                           "o Cloudflare, nao a chave; tente de novo em alguns minutos.") from e
        raise

    jogos = dados.get("data") or []
    melhor, melhor_nota = None, 0.0
    for j in jogos[:8]:
        nota = _pontuar(titulo, j.get("name", ""), None, None)
        if nota > melhor_nota:
            melhor, melhor_nota = j, nota
    if not melhor or melhor_nota < 0.5:
        return None

    poster = None
    try:
        grades = _json(f"{SGDB}/grids/game/{melhor['id']}?dimensions=600x900&limit=1",
                       cabecalhos)
        itens = grades.get("data") or []
        if itens:
            poster = itens[0].get("url")
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError):
        pass

    return {"igdb_id": melhor.get("id"), "titulo": melhor.get("name"),
            "poster_url": poster, "sinopse": None, "nota": None, "ano": None}


def variacoes(titulo: str) -> list[str]:
    """Outras formas de procurar o mesmo titulo, da mais fiel para a mais solta.

    Os nomes de release trazem subtitulo colado, tradução livre e prefixo de
    franquia; o TMDB costuma achar com a versao curta.
    """
    vistos: list[str] = []

    def somar(t: str) -> None:
        t = t.strip(" -–—:·.")
        if t and len(t) > 2 and t.lower() not in [x.lower() for x in vistos]:
            vistos.append(t)

    somar(titulo)
    for separador in (" - ", ": ", " – ", " — "):
        if separador in titulo:
            esquerda, direita = titulo.split(separador, 1)
            somar(esquerda)      # "Miraculous - As Aventuras..." -> "Miraculous"
            somar(direita)       # "Tomb Raider - A Lenda..."     -> "A Lenda..."
    # Sem numero romano ou arabe no fim: "The Legend of Hei II" -> "The Legend of Hei"
    sem_numero = re.sub(r"\s+(?:[IVXLC]+|\d{1,2})$", "", titulo)
    somar(sem_numero)
    # Sem artigo inicial, que algumas bases nao usam.
    somar(re.sub(r"^(?:O|A|Os|As|The|Um|Uma)\s+", "", titulo, flags=re.IGNORECASE))

    # Apostrofo perdido no caminho. A pasta vira "The Shadow s Edge" e
    # "Marvel s Agent Carter" porque o caractere nao sobrevive a alguns
    # sistemas de arquivos; devolve-lo faz o TMDB reconhecer na hora.
    if re.search(r"\b\w+\s+s\b", titulo):
        somar(re.sub(r"\b(\w+)\s+s\b", r"\1's", titulo))
    # Prefixo de franquia que so a base de origem usa: "Marvel's Agent Carter".
    somar(re.sub(r"^\w+'s\s+", "", titulo))
    # Subtitulo colado depois do numero: "The Butterfly Effect 3 Revelations".
    somar(re.sub(r"^(.*?\s\d{1,2})\s+(\w.*)$", r"\1: \2", titulo))
    return vistos[:6]


def procurar(titulo: str, tipo: str, cfg, ano: int | None = None,
             limite: int = 12) -> list[dict]:
    """Lista candidatos para o usuario escolher a capa na mao."""
    opcoes = cfg.metadados
    if tipo == "jogo":
        chave = (opcoes.get("steamgriddb_api_key") or "").strip()
        if not chave:
            raise SemChave("configure a chave do SteamGridDB para procurar capas de jogo.")
        cabecalhos = {"Authorization": f"Bearer {chave}"}
        dados = _json(f"{SGDB}/search/autocomplete/{urllib.parse.quote(titulo)}", cabecalhos)
        saida = []
        for j in (dados.get("data") or [])[:limite]:
            capa = None
            try:
                grades = _json(f"{SGDB}/grids/game/{j['id']}?dimensions=600x900&limit=1",
                               cabecalhos)
                itens = grades.get("data") or []
                capa = itens[0].get("url") if itens else None
            except (urllib.error.HTTPError, urllib.error.URLError, KeyError):
                pass
            saida.append({"id": j.get("id"), "titulo": j.get("name"), "ano": None,
                          "poster": capa, "sinopse": None, "nota": None})
        return saida

    chave = (opcoes.get("tmdb_api_key") or "").strip()
    if not chave:
        raise SemChave("configure a chave do TMDB para procurar capas.")
    rota = "tv" if tipo == "serie" else "movie"
    params = {"api_key": chave, "query": titulo,
              "language": opcoes.get("tmdb_idioma", "pt-BR"), "include_adult": "false"}
    dados = _json(f"{TMDB}/search/{rota}?" + urllib.parse.urlencode(params))

    saida = []
    for r in (dados.get("results") or [])[:limite]:
        data = r.get("first_air_date") if rota == "tv" else r.get("release_date")
        saida.append({
            "id": r.get("id"),
            "titulo": r.get("name") if rota == "tv" else r.get("title"),
            "ano": int(data[:4]) if data and data[:4].isdigit() else None,
            "poster": TMDB_IMAGENS + r["poster_path"] if r.get("poster_path") else None,
            "fundo": TMDB_FUNDOS + r["backdrop_path"] if r.get("backdrop_path") else None,
            "sinopse": (r.get("overview") or "").strip() or None,
            "nota": r.get("vote_average") or None,
        })
    return saida


def enriquecer(con: sqlite3.Connection, cfg, so_faltantes: bool = True,
               limite: int | None = None, pular: int = 0) -> ResumoMetadados:
    """Preenche capa/sinopse/nota das obras que ainda nao tem."""
    r = ResumoMetadados()
    opcoes = cfg.metadados
    chave_tmdb = (opcoes.get("tmdb_api_key") or "").strip()
    chave_sgdb = (opcoes.get("steamgriddb_api_key") or "").strip()
    idioma = opcoes.get("tmdb_idioma", "pt-BR")

    if not chave_tmdb and not chave_sgdb:
        raise SemChave("nenhuma chave de API configurada. Preencha a do TMDB "
                       "(themoviedb.org) e/ou a do SteamGridDB em Configuracoes.")

    sql = ("SELECT id, tipo, COALESCE(NULLIF(titulo_corrigido,''), titulo) titulo, ano "
           "FROM itens")
    if so_faltantes:
        # Capa gerada e reserva, nao resposta: e so o titulo escrito sobre um
        # gradiente. Enquanto ela contava como "ja tem capa", 43 obras ficavam
        # presas nela para sempre, porque a busca automatica nunca as revisitava.
        sql += (" WHERE poster IS NULL OR poster = ''"
                " OR poster LIKE '%-gerada.svg'")
    sql += " ORDER BY tipo, titulo"
    if limite:
        sql += f" LIMIT {int(limite)}"
        # `pular` existe para quem busca em levas: sem ele, uma leva de titulos
        # que o TMDB nao conhece seria repetida para sempre e as obras
        # seguintes nunca chegariam a ser tentadas.
        if pular:
            sql += f" OFFSET {int(pular)}"

    for item in con.execute(sql).fetchall():
        r.tentados += 1
        try:
            achado = None
            if item["tipo"] == "jogo":
                if not chave_sgdb:
                    continue
                for tentativa in variacoes(item["titulo"]):
                    achado = buscar_steamgriddb(tentativa, chave_sgdb)
                    if achado:
                        break
                    time.sleep(PAUSA)
                # Catalogado como jogo mas o SteamGridDB nao conhece: pode ser
                # filme com nome de jogo. Perguntar ao TMDB custa uma consulta e
                # resolve casos como "M3GAN" e "Nidhogg 2".
                if not achado and chave_tmdb:
                    for eh_serie in (False, True):
                        achado = buscar_tmdb(item["titulo"], item["ano"], eh_serie,
                                             chave_tmdb, idioma)
                        if achado:
                            break
                        time.sleep(PAUSA)
            else:
                if not chave_tmdb:
                    continue
                serie = item["tipo"] == "serie"
                for tentativa in variacoes(item["titulo"]):
                    achado = buscar_tmdb(tentativa, item["ano"], serie, chave_tmdb, idioma)
                    if achado:
                        break
                    time.sleep(PAUSA)
                # O tipo pode ter vindo errado da pasta: tenta o outro lado.
                if not achado:
                    achado = buscar_tmdb(item["titulo"], item["ano"], not serie,
                                         chave_tmdb, idioma)
                # E se o TMDB nao conhece de jeito nenhum, pode ser jogo
                # catalogado como filme — o contrario do caso acima.
                if not achado and chave_sgdb:
                    time.sleep(PAUSA)
                    achado = buscar_steamgriddb(item["titulo"], chave_sgdb)
        except SemChave as e:
            # Desliga so este provedor e segue com o outro.
            if item["tipo"] == "jogo":
                chave_sgdb = ""
            else:
                chave_tmdb = ""
            r.erros.append(f"{item['tipo']}: {e}")
            continue
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
            r.erros.append(f"{item['titulo']}: {e}")
            continue
        finally:
            time.sleep(PAUSA)

        if not achado:
            r.sem_correspondencia.append(item["titulo"])
            continue
        r.encontrados += 1

        nome_poster = None
        if achado.get("poster_url"):
            destino = Path(cfg.posters) / f"{item['id']}.jpg"
            if _baixar_imagem(achado["poster_url"], destino):
                nome_poster = destino.name
                r.posters += 1

        nome_fundo = None
        if achado.get("fundo_url"):
            destino = Path(cfg.posters) / f"{item['id']}-fundo.jpg"
            if _baixar_imagem(achado["fundo_url"], destino):
                nome_fundo = destino.name

        con.execute(
            "UPDATE itens SET tmdb_id = COALESCE(?, tmdb_id), igdb_id = COALESCE(?, igdb_id), "
            "sinopse = COALESCE(?, sinopse), nota = COALESCE(?, nota), "
            "ano = COALESCE(ano, ?), poster = COALESCE(?, poster), "
            "backdrop = COALESCE(?, backdrop), atualizado_em = ? "
            "WHERE id = ?",
            (achado.get("tmdb_id"), achado.get("igdb_id"), achado.get("sinopse"),
             achado.get("nota"), achado.get("ano"), nome_poster, nome_fundo,
             datetime.now(timezone.utc).isoformat(timespec="seconds"), item["id"]),
        )
        con.commit()

    return r


def buscar_fundos(con: sqlite3.Connection, cfg, limite: int | None = None) -> dict:
    """Baixa so a imagem larga das obras que ja foram identificadas no TMDB.

    Separado de `enriquecer` porque quem ja tem tmdb_id nao precisa passar de
    novo pela busca e pela pontuacao - basta pedir o detalhe pelo id.
    """
    chave = (cfg.metadados.get("tmdb_api_key") or "").strip()
    if not chave:
        raise SemChave("configure a chave do TMDB para buscar as imagens de fundo.")

    sql = ("SELECT id, tipo, tmdb_id FROM itens "
           "WHERE tmdb_id IS NOT NULL AND (backdrop IS NULL OR backdrop = '') "
           "AND tipo IN ('filme','serie')")
    if limite:
        sql += f" LIMIT {int(limite)}"

    baixados, sem_imagem, erros = 0, 0, []
    for item in con.execute(sql).fetchall():
        rota = "tv" if item["tipo"] == "serie" else "movie"
        try:
            dados = _json(f"{TMDB}/{rota}/{item['tmdb_id']}?"
                          + urllib.parse.urlencode({"api_key": chave}))
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as e:
            erros.append(f"item {item['id']}: {e}")
            time.sleep(PAUSA)
            continue

        caminho = dados.get("backdrop_path")
        if not caminho:
            sem_imagem += 1
            time.sleep(PAUSA)
            continue

        nome = f"{item['id']}-fundo.jpg"
        if _baixar_imagem(TMDB_FUNDOS + caminho, Path(cfg.posters) / nome):
            con.execute("UPDATE itens SET backdrop = ? WHERE id = ?", (nome, item["id"]))
            con.commit()
            baixados += 1
        time.sleep(PAUSA)

    return {"baixados": baixados, "sem_imagem": sem_imagem, "erros": erros[:10]}
