"""Busca capas, sinopses e notas para as obras do catalogo.

    python -m ferramentas.metadados            so as obras que ainda nao tem capa
    python -m ferramentas.metadados --tudo     refaz todas
    python -m ferramentas.metadados --limite 10   testa com poucas primeiro

Precisa das chaves em config.toml. Ambas sao gratuitas:
  tmdb_api_key         https://www.themoviedb.org/settings/api
  steamgriddb_api_key  https://www.steamgriddb.com/profile/preferences/api
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, db, metadata  # noqa: E402


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = config.carregar()
    con = db.conectar(cfg.banco)

    limite = None
    if "--limite" in sys.argv:
        limite = int(sys.argv[sys.argv.index("--limite") + 1])
    so_faltantes = "--tudo" not in sys.argv

    pendentes = con.execute(
        "SELECT COUNT(*) n FROM itens" + (" WHERE poster IS NULL" if so_faltantes else "")
    ).fetchone()["n"]
    print(f"Obras a consultar: {pendentes}"
          + (f" (limitado a {limite})" if limite else ""))
    print("Isso faz uma chamada por obra; leva alguns minutos.\n")

    try:
        r = metadata.enriquecer(con, cfg, so_faltantes=so_faltantes, limite=limite)
    except metadata.SemChave as e:
        print(f"ERRO: {e}")
        return 1

    print(f"\n  consultadas ................... {r.tentados}")
    print(f"  com correspondencia ........... {r.encontrados}")
    print(f"  capas baixadas ................ {r.posters}")

    if r.sem_correspondencia:
        print(f"\n  sem correspondencia ({len(r.sem_correspondencia)}):")
        for t in r.sem_correspondencia[:25]:
            print(f"    {t}")
        print("\n  Corrija o titulo na interface (clique na obra) e rode de novo.")

    if r.erros:
        print(f"\n  erros de rede ({len(r.erros)}):")
        for e in r.erros[:10]:
            print(f"    {e}")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
