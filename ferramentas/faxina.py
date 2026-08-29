"""Relatorio de higiene do indice: duplicatas, corrompidos e orfaos.

    python -m ferramentas.faxina              so o relatorio (nao apaga nada)
    python -m ferramentas.faxina --resgatar   move os falsos duplicados para as
                                              pastas certas (pede confirmacao)

Nada e apagado por este script, em nenhum modo. Remover .torrent e decisao do
usuario, tomada com o relatorio na mao.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, db, scanner  # noqa: E402

GIB = 1024 ** 3
MIB = 1024 ** 2


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = config.carregar()
    con = db.conectar(cfg.banco)
    if not con.execute("SELECT 1 FROM torrents LIMIT 1").fetchone():
        print("Indice vazio. Rode antes: python -m ferramentas.varredura")
        return 1

    # ------------------------------------------------------------ corrompidos
    corrompidos = con.execute(
        "SELECT caminho, erro FROM torrents WHERE corrompido = 1 ORDER BY caminho"
    ).fetchall()
    print("=== .TORRENT ILEGIVEIS ==============================================")
    if corrompidos:
        for l in corrompidos:
            print(f"  {l['caminho']}\n      {l['erro']}")
        print("\n  Estes nao podem ser lidos nem baixados. Baixe o .torrent de novo")
        print("  na origem, ou remova-os do indice.")
    else:
        print("  nenhum")

    # -------------------------------------------------------------- duplicatas
    grupos = scanner.grupos_duplicados(con)
    desperdicio = 0
    print(f"\n=== COPIAS REDUNDANTES: {len(grupos)} grupo(s) =========================")
    for infohash, caminhos in grupos:
        tamanho = con.execute(
            "SELECT bytes_torrent b FROM torrents WHERE caminho = ?", (caminhos[0],)
        ).fetchone()["b"]
        desperdicio += tamanho * (len(caminhos) - 1)
        print(f"\n  mesmo conteudo ({infohash[:12]}):")
        for i, c in enumerate(caminhos):
            marca = "manter " if i == 0 else "redund."
            print(f"    [{marca}] {c}")
    if grupos:
        print(f"\n  Removendo as redundantes o indice encolhe {desperdicio / MIB:.1f} MiB.")
        print("  (Sao arquivos .torrent iguais, nao midia: o ganho e organizacao.)")

    # ------------------------------------------------------- duplicatas falsas
    falsos = scanner.duplicados_falsos(con)
    print(f"\n=== FALSOS DUPLICADOS: {len(falsos)} ==================================")
    if falsos:
        print("  Estao em _Duplicados mas NAO tem copia em nenhuma outra pasta.")
        print("  Sao releases diferentes da mesma obra. Apagar a pasta perderia estes:\n")
        for l in falsos:
            print(f"    {l['tamanho_total'] / GIB:7.1f} GiB  {l['caminho']}")
            print(f"                  obra: {l['titulo']}")
        if "--resgatar" in sys.argv:
            return resgatar(cfg, falsos)
        print("\n  Rode com --resgatar para move-los de volta para as pastas certas.")
    else:
        print("  nenhum - tudo em _Duplicados tem copia em outro lugar")

    # ------------------------------------------------------------------ orfaos
    orfaos = con.execute(
        "SELECT caminho_local, bytes_presentes, fixado FROM disco "
        "WHERE estado = 'orfao' ORDER BY bytes_presentes DESC"
    ).fetchall()
    print(f"\n=== MIDIA SEM .TORRENT: {len(orfaos)} pasta(s) ========================")
    if orfaos:
        total = sum(l["bytes_presentes"] for l in orfaos)
        print(f"  {total / GIB:,.1f} GiB que NAO podem ser recuperados se apagados.\n")
        for l in orfaos[:20]:
            print(f"    {l['bytes_presentes'] / GIB:7.1f} GiB  {l['caminho_local']}")
        print("\n  Para poder liberar esse espaco com seguranca, guarde o .torrent")
        print("  correspondente no indice antes de apagar qualquer coisa.")
    else:
        print("  nenhuma - tudo no disco tem .torrent")

    con.close()
    return 0


def resgatar(cfg, falsos) -> int:
    """Move os falsos duplicados de _Duplicados para a pasta da categoria certa."""
    print("\n  --- RESGATE ---")
    indice = Path(cfg.indice)
    planos = []
    for l in falsos:
        origem = indice / l["caminho"]
        # Sem categoria conhecida, vao para uma pasta de triagem em vez de sumir.
        destino = indice / "_Resgatados" / origem.name
        planos.append((origem, destino))
        print(f"    {origem.name}\n      -> {destino.relative_to(indice)}")

    print(f"\n  {len(planos)} arquivo(s) serao MOVIDOS (nenhum e apagado).")
    resposta = input("  Confirmar? [s/N] ").strip().lower()
    if resposta != "s":
        print("  Cancelado - nada foi movido.")
        return 0

    for origem, destino in planos:
        if not origem.is_file():
            print(f"    PULADO (sumiu): {origem.name}")
            continue
        if destino.exists():
            print(f"    PULADO (ja existe): {destino.name}")
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(origem), str(destino))
        print(f"    movido: {destino.name}")

    print("\n  Pronto. Mova cada um de _Resgatados para a pasta de genero certa")
    print("  e rode: python -m ferramentas.varredura")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
