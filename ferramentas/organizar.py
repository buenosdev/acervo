"""Renomeia a midia baixada para o padrao Jellyfin/Plex/Kodi.

    python -m ferramentas.organizar                    previa de tudo que esta no disco
    python -m ferramentas.organizar --busca "the boys" previa so de uma obra
    python -m ferramentas.organizar --aplicar          executa (pede confirmacao)

Sem --aplicar nada e tocado: o padrao e so mostrar o que seria feito.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, db, organizer  # noqa: E402
from core.release import chave_busca  # noqa: E402


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = config.carregar()
    con = db.conectar(cfg.banco)
    aplicar = "--aplicar" in sys.argv
    busca = None
    if "--busca" in sys.argv:
        busca = chave_busca(sys.argv[sys.argv.index("--busca") + 1])

    alvos = con.execute(
        "SELECT t.caminho, COALESCE(NULLIF(i.titulo_corrigido,''), i.titulo) titulo "
        "FROM torrents t JOIN itens i ON i.id = t.item_id "
        "JOIN disco d ON d.caminho_torrent = t.caminho "
        "WHERE d.estado IN ('completo','parcial') ORDER BY i.titulo"
    ).fetchall()
    if busca:
        alvos = [a for a in alvos if busca in chave_busca(a["titulo"])]

    print(f"Releases no disco: {len(alvos)}")
    print(f"Modo: {'APLICAR' if aplicar else 'previa (nada e movido)'}\n")

    planos = []
    for a in alvos:
        plano = organizer.planejar(con, Path(cfg.biblioteca), a["caminho"])
        if plano.vazio:
            if plano.avisos:
                print(f"  {a['titulo'][:40]:40} — {plano.avisos[0]}")
            continue
        planos.append((a["titulo"], plano))

    for titulo, plano in planos:
        print(f"\n=== {titulo} ===")
        for passo in organizer.executar(plano, simular=True):
            print(f"  {passo}")
        for aviso in plano.avisos:
            print(f"  nota: {aviso}")

    if not planos:
        print("\nNada a organizar.")
        return 0

    total = sum(len(p.movimentos) for _, p in planos)
    if not aplicar:
        print(f"\n{total} arquivo(s) seriam renomeados. Rode com --aplicar para valer.")
        return 0

    print(f"\n{total} arquivo(s) serao MOVIDOS de verdade.")
    if input("Confirmar? [s/N] ").strip().lower() != "s":
        print("Cancelado — nada foi movido.")
        return 0

    for titulo, plano in planos:
        print(f"\n=== {titulo} ===")
        for passo in organizer.executar(plano, simular=False):
            print(f"  {passo}")

    print("\nPronto. Rode 'python -m ferramentas.biblioteca' para reconciliar.")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
