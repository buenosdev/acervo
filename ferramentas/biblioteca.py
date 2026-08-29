"""Cruza o indice com o que esta no disco e imprime o estado da biblioteca.

    python -m ferramentas.biblioteca

Somente leitura: nao move, renomeia nem apaga nada.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, db, library  # noqa: E402

GIB = 1024 ** 3


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = config.carregar()
    con = db.conectar(cfg.banco)
    if not con.execute("SELECT 1 FROM torrents LIMIT 1").fetchone():
        print("Indice vazio. Rode antes: python -m ferramentas.varredura")
        return 1

    protegidas = cfg.seguranca.get("pastas_protegidas", [])
    print(f"Biblioteca: {cfg.biblioteca}")
    print(f"Ignorando:  {', '.join(cfg.ignorar)}\n")

    r = library.reconciliar(con, cfg.biblioteca, cfg.ignorar, protegidas)

    print("=== DISCO ==========================================================")
    print(f"  pastas percorridas ............ {r.pastas_visitadas}")
    print(f"  arquivos vistos ............... {r.arquivos_vistos}")
    print(f"  ocupado na biblioteca ......... {r.bytes_no_disco / GIB:,.1f} GiB")

    print("\n=== CRUZAMENTO COM O INDICE ========================================")
    print(f"  baixados por completo ......... {r.completos}")
    print(f"  baixados pela metade .......... {r.parciais}")
    print(f"  so no indice (nada no disco) .. {r.so_indice}")
    print(f"  protegidos ({', '.join(protegidas) or 'nenhum'}) ....... {r.fixados}")

    espaco = con.execute(
        "SELECT COALESCE(SUM(bytes_presentes), 0) b FROM disco "
        "WHERE estado IN ('completo', 'parcial') AND fixado = 0"
    ).fetchone()["b"]
    print(f"\n  espaco recuperavel (tem .torrent e nao esta protegido):")
    print(f"    {espaco / GIB:,.1f} GiB")

    if r.orfaos:
        total_orfao = sum(b for _, b in r.orfaos)
        print(f"\n=== ORFAOS: {len(r.orfaos)} pasta(s), {total_orfao / GIB:,.1f} GiB ==========")
        print("  Midia no disco sem nenhum .torrent apontando para ela.")
        print("  Apagar qualquer uma destas e IRREVERSIVEL - nao da para rebaixar.\n")
        for caminho, tamanho in r.orfaos[:20]:
            rel = Path(caminho)
            try:
                rel = rel.relative_to(cfg.biblioteca)
            except ValueError:
                pass
            print(f"    {tamanho / GIB:8.1f} GiB  {rel}")
        if len(r.orfaos) > 20:
            print(f"    ... e mais {len(r.orfaos) - 20} pasta(s)")

    parciais = con.execute(
        "SELECT d.caminho_local, d.bytes_presentes, d.bytes_esperados, i.titulo "
        "FROM disco d LEFT JOIN torrents t ON t.caminho = d.caminho_torrent "
        "LEFT JOIN itens i ON i.id = t.item_id "
        "WHERE d.estado = 'parcial' ORDER BY d.bytes_presentes DESC LIMIT 15"
    ).fetchall()
    if parciais:
        print("\n=== PELA METADE ====================================================")
        for l in parciais:
            pct = 100 * l["bytes_presentes"] / l["bytes_esperados"] if l["bytes_esperados"] else 0
            print(f"    {pct:5.1f}%  {(l['titulo'] or '?')[:40]:40} "
                  f"{l['bytes_presentes'] / GIB:7.1f} de {l['bytes_esperados'] / GIB:.1f} GiB")

    if r.torrents_soltos:
        print("\n=== .TORRENT FORA DO INDICE ========================================")
        print("  Arquivos .torrent na biblioteca que nao estao em ! TORRENT.")
        print("  Agrupados por pasta: muitos juntos costumam ser uma copia do indice.")
        por_pasta: dict[Path, list[str]] = {}
        for caminho in r.torrents_soltos:
            p = Path(caminho)
            por_pasta.setdefault(p.parent, []).append(p.name)
        for pasta, nomes in sorted(por_pasta.items(), key=lambda kv: -len(kv[1]))[:10]:
            try:
                rel = pasta.relative_to(cfg.biblioteca)
            except ValueError:
                rel = pasta
            print(f"    {len(nomes):4} em  {rel or '.'}")
            if len(nomes) <= 3:
                for n in nomes:
                    print(f"           {n}")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
