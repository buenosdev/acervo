"""Varre o indice de .torrent e imprime o relatorio de conferencia.

    python -m ferramentas.varredura            varre e mostra o resumo
    python -m ferramentas.varredura --itens    lista tambem as obras encontradas
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, db, scanner  # noqa: E402

GIB = 1024 ** 3
TIB = 1024 ** 4
MIB = 1024 ** 2


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = config.carregar()
    if not cfg.indice.is_dir():
        print(f"ERRO: pasta de indice nao encontrada: {cfg.indice}")
        return 1

    print(f"Indice: {cfg.indice}")
    con = db.conectar(cfg.banco)
    r = scanner.varrer(con, cfg.indice)

    print("\n=== INDICE =========================================================")
    print(f"  arquivos .torrent lidos ....... {r.lidos}")
    print(f"  corrompidos ................... {r.corrompidos}")
    print(f"  infohashes unicos ............. {len(r.infohashes)}")
    print(f"  copias redundantes ............ {r.duplicados}")
    total_itens = con.execute("SELECT COUNT(*) n FROM itens").fetchone()["n"]
    print(f"  obras (itens) catalogadas ..... {total_itens}")

    print("\n=== ESPACO =========================================================")
    print(f"  conteudo indexado ............. {r.bytes_indexados / TIB:.2f} TiB "
          f"({r.bytes_indexados / GIB:,.0f} GiB)")
    print(f"  tamanho do indice em disco .... {r.bytes_torrents / MIB:.1f} MiB")
    if r.bytes_torrents:
        print(f"  proporcao indice : conteudo ... 1 : {r.bytes_indexados / r.bytes_torrents:,.0f}")

    print("\n=== O QUE O APP VAI RESOLVER =======================================")
    print(f"  torrents sem tracker (so DHT) . {r.sem_tracker}  -> injetar trackers publicos")
    print(f"  arquivos de propaganda ........ {r.arquivos_lixo} "
          f"({r.bytes_lixo / MIB:.1f} MiB) -> nao baixar")

    por_tipo = con.execute(
        "SELECT tipo, COUNT(*) n FROM itens GROUP BY tipo ORDER BY n DESC"
    ).fetchall()
    print("\n  obras por tipo:")
    for linha in por_tipo:
        print(f"    {linha['tipo']:12} {linha['n']:4}")

    dups = scanner.grupos_duplicados(con)
    print(f"\n=== DUPLICADOS ({len(dups)} grupos) ==================================")
    for _, caminhos in dups[:5]:
        print("  " + "\n     ".join(caminhos))
    if len(dups) > 5:
        print(f"  ... e mais {len(dups) - 5} grupos")

    falsos = scanner.duplicados_falsos(con)
    if falsos:
        print(f"\n  ATENCAO: {len(falsos)} arquivo(s) em _Duplicados NAO tem copia em outra")
        print("  pasta - sao releases diferentes, nao duplicatas. Apagar a pasta os perderia:")
        for linha in falsos:
            print(f"    ! {linha['caminho']}")

    if r.erros:
        print("\n=== CORROMPIDOS ====================================================")
        for caminho, erro in r.erros:
            print(f"  {caminho}\n      {erro}")

    if "--itens" in sys.argv:
        print("\n=== OBRAS ==========================================================")
        linhas = con.execute(
            "SELECT i.tipo, i.titulo, i.ano, COUNT(t.caminho) n, SUM(t.tamanho_total) bytes "
            "FROM itens i LEFT JOIN torrents t ON t.item_id = i.id "
            "GROUP BY i.id ORDER BY i.tipo, i.titulo"
        ).fetchall()
        for l in linhas:
            ano = f"({l['ano']})" if l["ano"] else "      "
            print(f"  {l['tipo'][:5]:5} {l['titulo'][:48]:48} {ano:8} "
                  f"{l['n']:3} torrent(s)  {(l['bytes'] or 0) / GIB:8.1f} GiB")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
