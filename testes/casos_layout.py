"""Regressao de layout.

O cartao ja colapsou para 100x30 em certas janelas, virando uma faixa fina que
engolia capa e titulo. Este teste mede a celula em varias larguras de janela e
em todos os tamanhos de capa: se voltar a depender do contexto, quebra aqui.

    python -m testes.casos_layout
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from core import config, consultas, db      # noqa: E402
from ui import tema                         # noqa: E402
from ui.grade import GradeObras             # noqa: E402
from ui.widgets import PROPORCAO_CAPA, TAMANHOS_CARTAO  # noqa: E402

JANELAS = [(1320, 840), (1366, 740), (980, 640), (1920, 1080), (1100, 700)]


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    app = QApplication.instance() or QApplication([])
    cfg = config.carregar()
    con = db.conectar(cfg.banco)
    obras = consultas.listar(con)[:40]
    if not obras:
        print("Catálogo vazio; rode a varredura antes.")
        return 1

    falhas = 0
    for tamanho, largura in TAMANHOS_CARTAO.items():
        g = GradeObras(cfg.posters, tema.ESCURO, 1.0, tamanho)
        g.definir_obras(obras)
        alturas = set()
        for larg, alt in JANELAS:
            g.resize(larg, alt)
            g.show()
            app.processEvents()
            tam = g.delegate.sizeHint(None, None)
            alturas.add((tam.width(), tam.height()))
        g.hide()

        esperado = (largura, int(largura * PROPORCAO_CAPA) + g.delegate.altura_texto)
        if len(alturas) != 1 or alturas.pop() != esperado:
            print(f"FALHA  tamanho {tamanho}: célula variou com a janela "
                  f"({alturas}), esperado {esperado}")
            falhas += 1
        else:
            print(f"OK     {tamanho:8} {esperado[0]}x{esperado[1]} "
                  f"— igual nas {len(JANELAS)} janelas")

    g = GradeObras(cfg.posters, tema.ESCURO, 1.0, "medio", "lista")
    g.definir_obras(obras)
    g.resize(900, 600)
    g.show()
    app.processEvents()
    altura_lista = g.delegate.sizeHint(None, None).height()
    g.hide()
    if altura_lista != g.delegate.altura_linha:
        print(f"FALHA  modo lista: altura {altura_lista}")
        falhas += 1
    else:
        print(f"OK     lista    altura fixa {altura_lista}")

    con.close()
    if falhas:
        print(f"\n{falhas} falha(s).")
        return 1
    print(f"\nOK: célula estável em {len(TAMANHOS_CARTAO)} tamanhos "
          f"x {len(JANELAS)} janelas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
