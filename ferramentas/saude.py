"""Checa quantos seeders os torrents ainda tem.

    python -m ferramentas.saude                  o que esta ocupando disco
    python -m ferramentas.saude --limite 10      so os 10 maiores
    python -m ferramentas.saude --com-qbittorrent  usa o DHT do qBittorrent
                                                 nos torrents sem tracker

Isto responde a pergunta que decide tudo: "se eu apagar, consigo baixar de
volta?". Nada e apagado aqui.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, db, health  # noqa: E402

GIB = 1024 ** 3


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = config.carregar()
    con = db.conectar(cfg.banco)

    limite = None
    if "--limite" in sys.argv:
        limite = int(sys.argv[sys.argv.index("--limite") + 1])
    usar_qb = "--com-qbittorrent" in sys.argv

    alvos = con.execute(
        "SELECT COUNT(DISTINCT t.infohash) n FROM torrents t "
        "JOIN disco d ON d.caminho_torrent = t.caminho "
        "WHERE t.corrompido = 0 AND d.estado IN ('completo','parcial')"
    ).fetchone()["n"]
    print(f"Torrents ocupando disco: {alvos}" + (f" (checando {limite})" if limite else ""))
    print("Scrape UDP tem timeout de 4s por tracker; pode levar um tempo.\n")

    r = health.checar(con, cfg, usar_qbittorrent=usar_qb, limite=limite)

    print(f"  checados ...................... {r.checados}")
    print(f"  com seeders ................... {r.vivos}")
    print(f"  sem nenhum seeder ............. {r.mortos}")
    print(f"  tracker nao respondeu ......... {r.sem_resposta}")

    if r.mortos or r.sem_resposta:
        print("\n  NAO libere o espaco destes — pode nao voltar:\n")
        for s in r.detalhes:
            if s.seeders:
                continue
            linha = con.execute(
                "SELECT COALESCE(NULLIF(i.titulo_corrigido,''), i.titulo) titulo, "
                "d.bytes_presentes b FROM torrents t "
                "LEFT JOIN itens i ON i.id = t.item_id "
                "LEFT JOIN disco d ON d.caminho_torrent = t.caminho "
                "WHERE t.infohash = ? LIMIT 1", (s.infohash,)
            ).fetchone()
            titulo = (linha["titulo"] if linha else None) or s.infohash[:12]
            gib = (linha["b"] or 0) / GIB if linha else 0
            motivo = "0 seeders" if s.seeders == 0 else (s.erro or "sem resposta")
            print(f"    {gib:7.1f} GiB  {titulo[:44]:44} {motivo}")

    if r.vivos:
        print("\n  Seguros para liberar espaco:\n")
        for s in r.detalhes:
            if not s.seeders:
                continue
            linha = con.execute(
                "SELECT COALESCE(NULLIF(i.titulo_corrigido,''), i.titulo) titulo, "
                "d.bytes_presentes b FROM torrents t "
                "LEFT JOIN itens i ON i.id = t.item_id "
                "LEFT JOIN disco d ON d.caminho_torrent = t.caminho "
                "WHERE t.infohash = ? LIMIT 1", (s.infohash,)
            ).fetchone()
            titulo = (linha["titulo"] if linha else None) or s.infohash[:12]
            gib = (linha["b"] or 0) / GIB if linha else 0
            print(f"    {gib:7.1f} GiB  {titulo[:44]:44} {s.seeders} seeders")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
