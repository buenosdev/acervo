"""Encontra e junta obras repetidas no catalogo.

Duplicata aparece em tres niveis, do mais certo para o mais incerto:

  1. mesmo infohash        - e literalmente o mesmo arquivo; o scanner ja junta
                             sozinho, sem perguntar nada;
  2. mesmo tmdb_id         - dois titulos diferentes que o TMDB confirmou serem
                             a mesma obra ("Sonic 3 O Filme" e "Sonic 3 - O
                             Filme"); juncao automatica e segura;
  3. titulos parecidos     - so um palpite. Nunca junta sozinho: vira sugestao
                             para o usuario confirmar.

Juntar nunca apaga .torrent nem midia. Move os releases para uma obra so.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .release import chave_busca

# Abaixo disso os titulos sao coisas diferentes que por acaso compartilham palavras.
LIMITE_SEMELHANCA = 0.78


@dataclass
class Grupo:
    motivo: str                  # infohash | tmdb | semelhanca
    confianca: str               # alta | media
    itens: list[dict] = field(default_factory=list)


def semelhanca(a: str, b: str) -> float:
    """Quanto dois titulos se parecem, de 0 a 1 (bigramas + palavras em comum)."""
    a, b = chave_busca(a), chave_busca(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    def bigramas(t: str) -> set[str]:
        t = t.replace(" ", "")
        return {t[i:i + 2] for i in range(len(t) - 1)} or {t}

    ba, bb = bigramas(a), bigramas(b)
    dice = 2 * len(ba & bb) / (len(ba) + len(bb))

    pa, pb = set(a.split()), set(b.split())
    jaccard = len(pa & pb) / len(pa | pb) if (pa | pb) else 0.0
    return 0.65 * dice + 0.35 * jaccard


def _resumo_item(l: sqlite3.Row) -> dict:
    return {"id": l["id"], "tipo": l["tipo"], "titulo": l["titulo"], "ano": l["ano"],
            "tmdb_id": l["tmdb_id"], "poster": l["poster"],
            "n_torrents": l["n_torrents"], "bytes": l["bytes"] or 0,
            "no_disco": bool(l["no_disco"])}


SQL_BASE = """
SELECT i.id, i.tipo, COALESCE(NULLIF(i.titulo_corrigido,''), i.titulo) AS titulo,
       i.ano, i.tmdb_id, i.poster,
       COUNT(DISTINCT t.caminho) AS n_torrents,
       COALESCE(SUM(t.tamanho_total), 0) AS bytes,
       MAX(CASE WHEN d.estado IN ('completo','parcial') THEN 1 ELSE 0 END) AS no_disco
FROM itens i
LEFT JOIN torrents t ON t.item_id = i.id AND t.corrompido = 0
LEFT JOIN disco d    ON d.caminho_torrent = t.caminho
GROUP BY i.id
"""


def detectar(con: sqlite3.Connection) -> list[Grupo]:
    """Grupos de obras que provavelmente sao a mesma coisa."""
    itens = [_resumo_item(l) for l in con.execute(SQL_BASE)]
    grupos: list[Grupo] = []
    ja_agrupados: set[int] = set()

    # Nivel 2: mesmo tmdb_id -> confirmado por uma base externa.
    por_tmdb: dict[tuple, list[dict]] = {}
    for i in itens:
        if i["tmdb_id"]:
            por_tmdb.setdefault((i["tipo"], i["tmdb_id"]), []).append(i)
    for lista in por_tmdb.values():
        if len(lista) > 1:
            grupos.append(Grupo("tmdb", "alta", sorted(lista, key=_ordem_preferencia)))
            ja_agrupados.update(x["id"] for x in lista)

    # Nivel 3: titulos parecidos, so entre obras do mesmo tipo.
    por_tipo: dict[str, list[dict]] = {}
    for i in itens:
        if i["id"] not in ja_agrupados:
            por_tipo.setdefault(i["tipo"], []).append(i)

    for tipo, lista in por_tipo.items():
        lista.sort(key=lambda x: chave_busca(x["titulo"]))
        for a in range(len(lista)):
            if lista[a]["id"] in ja_agrupados:
                continue
            parecidos = [lista[a]]
            for b in range(a + 1, len(lista)):
                if lista[b]["id"] in ja_agrupados:
                    continue
                # Se os dois ja foram identificados no TMDB e deram obras
                # diferentes, a pergunta esta respondida. E o que separa
                # "Todo Mundo em Pânico" de "Todo Mundo em Pânico 2".
                if (lista[a]["tmdb_id"] and lista[b]["tmdb_id"]
                        and lista[a]["tmdb_id"] != lista[b]["tmdb_id"]):
                    continue
                if semelhanca(lista[a]["titulo"], lista[b]["titulo"]) < LIMITE_SEMELHANCA:
                    continue
                # Filme com anos distantes e remake, nao duplicata.
                anos = [x["ano"] for x in (lista[a], lista[b]) if x["ano"]]
                if tipo == "filme" and len(anos) == 2 and abs(anos[0] - anos[1]) > 1:
                    continue
                parecidos.append(lista[b])
            if len(parecidos) > 1:
                grupos.append(Grupo("semelhanca", "media",
                                    sorted(parecidos, key=_ordem_preferencia)))
                ja_agrupados.update(x["id"] for x in parecidos)

    grupos.sort(key=lambda g: (g.confianca != "alta", -len(g.itens)))
    return grupos


def _ordem_preferencia(item: dict) -> tuple:
    """O primeiro do grupo e o melhor candidato a sobreviver a juncao."""
    return (0 if item["tmdb_id"] else 1,          # ja identificado no TMDB
            0 if item["no_disco"] else 1,         # ja tem midia baixada
            -item["n_torrents"],                  # mais releases
            0 if item["poster"] and not item["poster"].endswith("-gerada.svg") else 1,
            item["id"])


def mesclar(con: sqlite3.Connection, manter_id: int, mesclar_ids: list[int]) -> dict:
    """Move todos os releases para `manter_id` e apaga as obras vazias que sobrarem."""
    mesclar_ids = [int(x) for x in mesclar_ids if int(x) != int(manter_id)]
    if not mesclar_ids:
        return {"ok": False, "erro": "nada para juntar"}

    destino = con.execute("SELECT * FROM itens WHERE id = ?", (manter_id,)).fetchone()
    if not destino:
        return {"ok": False, "erro": "a obra escolhida nao existe mais"}

    marcadores = ",".join("?" * len(mesclar_ids))
    movidos = con.execute(
        f"SELECT COUNT(*) n FROM torrents WHERE item_id IN ({marcadores})", mesclar_ids
    ).fetchone()["n"]

    con.execute(f"UPDATE torrents SET item_id = ? WHERE item_id IN ({marcadores})",
                [manter_id, *mesclar_ids])
    con.execute(f"UPDATE item_torrents SET item_id = ? WHERE item_id IN ({marcadores})",
                [manter_id, *mesclar_ids])

    # Aproveita o que as outras tinham e a obra destino nao: nada se perde.
    for origem in con.execute(f"SELECT * FROM itens WHERE id IN ({marcadores})",
                              mesclar_ids).fetchall():
        for campo in ("tmdb_id", "igdb_id", "sinopse", "nota", "generos", "ano"):
            if destino[campo] in (None, "") and origem[campo] not in (None, ""):
                con.execute(f"UPDATE itens SET {campo} = ? WHERE id = ?",
                            (origem[campo], manter_id))
                destino = con.execute("SELECT * FROM itens WHERE id = ?",
                                      (manter_id,)).fetchone()
        # Capa de verdade vale mais que capa gerada.
        if origem["poster"] and not origem["poster"].endswith("-gerada.svg"):
            atual = destino["poster"] or ""
            if not atual or atual.endswith("-gerada.svg"):
                con.execute("UPDATE itens SET poster = ? WHERE id = ?",
                            (origem["poster"], manter_id))
        if origem["fixado"]:
            con.execute("UPDATE itens SET fixado = 1 WHERE id = ?", (manter_id,))

    con.execute(f"DELETE FROM itens WHERE id IN ({marcadores})", mesclar_ids)
    con.commit()
    return {"ok": True, "manter_id": manter_id, "juntadas": len(mesclar_ids),
            "releases_movidos": movidos}


def juntar_por_tmdb(con: sqlite3.Connection) -> dict:
    """Junta sozinho so o que o TMDB confirmou ser a mesma obra."""
    juntadas = 0
    releases = 0
    for grupo in detectar(con):
        if grupo.motivo != "tmdb":
            continue
        manter = grupo.itens[0]["id"]
        outros = [i["id"] for i in grupo.itens[1:]]
        r = mesclar(con, manter, outros)
        if r.get("ok"):
            juntadas += r["juntadas"]
            releases += r["releases_movidos"]
    return {"ok": True, "obras_juntadas": juntadas, "releases_movidos": releases}


def para_json(grupos: list[Grupo]) -> list[dict]:
    return [{"motivo": g.motivo, "confianca": g.confianca, "itens": g.itens}
            for g in grupos]


def _grupos_com_titulo_parecido(con: sqlite3.Connection) -> list[list[sqlite3.Row]]:
    """Obras do mesmo tipo cujo titulo e variante uma da outra.

    "Mr Robot" e "Mr Robot - Sociedade Hacker" sao a mesma serie com nome de
    release diferente (ingles e portugues). Como viraram duas obras, as
    temporadas ficaram espalhadas em duas pastas — 1 e 3 numa, 2 e 4 na outra.
    """
    from .release import chave_busca

    por_tipo: dict[str, list[sqlite3.Row]] = {}
    for l in con.execute(
        "SELECT id, tipo, tmdb_id, ano, "
        "       COALESCE(NULLIF(titulo_corrigido,''), titulo) titulo FROM itens"
    ).fetchall():
        por_tipo.setdefault(l["tipo"], []).append(l)

    grupos: list[list[sqlite3.Row]] = []
    for itens in por_tipo.values():
        usados: set[int] = set()
        for i, a in enumerate(itens):
            if a["id"] in usados:
                continue
            ka = chave_busca(a["titulo"])
            if len(ka) < 5:                    # chave curta demais casa com tudo
                continue
            juntos = [a]
            for b in itens[i + 1:]:
                kb = chave_busca(b["titulo"])
                if b["id"] in usados or len(kb) < 5:
                    continue
                if ka == kb or ka.startswith(kb + " ") or kb.startswith(ka + " "):
                    juntos.append(b)
            if len(juntos) > 1:
                usados.update(x["id"] for x in juntos)
                grupos.append(juntos)
    return grupos


def reidentificar_variantes(con: sqlite3.Connection, cfg) -> dict:
    """Reconsulta o TMDB para obras que parecem a mesma coisa, e junta.

    Nao forca as duas a usar a mesma consulta — cada uma e perguntada com o
    proprio titulo. Se as duas responderem o mesmo id, sao a mesma obra e podem
    ser fundidas; se responderem ids diferentes, sao obras distintas de nome
    parecido e ficam separadas, que e o certo para "Rick and Morty" e
    "Rick and Morty: The Anime".
    """
    from . import metadata

    chave = (cfg.metadados.get("tmdb_api_key") or "").strip()
    if not chave:
        return {"ok": False, "erro": "sem chave do TMDB"}
    idioma = cfg.metadados.get("tmdb_idioma", "pt-BR")

    revistos = 0
    for grupo in _grupos_com_titulo_parecido(con):
        for item in grupo:
            if item["tipo"] == "jogo":
                continue
            serie = item["tipo"] == "serie"
            achado = None
            for tentativa in metadata.variacoes(item["titulo"]):
                achado = metadata.buscar_tmdb(tentativa, item["ano"], serie,
                                              chave, idioma)
                if achado:
                    break
            if achado and achado.get("tmdb_id") != item["tmdb_id"]:
                con.execute("UPDATE itens SET tmdb_id = ? WHERE id = ?",
                            (achado["tmdb_id"], item["id"]))
                revistos += 1
    con.commit()

    juntadas = juntar_por_tmdb(con)
    return {"ok": True, "revistos": revistos,
            "obras_juntadas": juntadas.get("obras_juntadas", 0),
            "releases_movidos": juntadas.get("releases_movidos", 0)}
