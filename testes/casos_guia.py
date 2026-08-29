"""Regressao do guia guiado.

Duas coisas quebram um tour com holofote e sao invisiveis ate alguem reclamar:

  1. o cartao de texto sair pela borda da janela — acontece no ultimo passo de
     uma janela pequena, ou quando o alvo esta encostado na direita;
  2. o cartao cobrir justamente o controle que ele esta explicando.

Este teste percorre todos os passos em varios tamanhos de janela e cobra as
duas. Tambem confere que passo sem alvo apaga o holofote, que foi um defeito
real: a animacao do passo anterior continuava escrevendo o retangulo.

    python -m testes.casos_guia
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication          # noqa: E402

from core import config                             # noqa: E402
from ui import tema                                 # noqa: E402

TAMANHOS = [(1320, 880), (1100, 740), (980, 640)]


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from ui.janela import Janela

    app = QApplication.instance() or QApplication([])
    cfg = config.carregar()
    app.setStyleSheet(tema.folha(tema.ESCURO, 1.0))

    falhas = 0
    for largura, altura in TAMANHOS:
        janela = Janela(cfg)
        janela.resize(largura, altura)
        janela.show()
        app.processEvents()

        janela.abrir_guia(marcar=False)
        guia = janela.guia
        app.processEvents()

        total = len(guia.passos)
        fora = cobrindo = sem_alvo_aceso = 0

        for i in range(total):
            guia.indice = i
            guia._aplicar_passo(animar=False)
            app.processEvents()

            cartao = guia.cartao.geometry()
            if not janela.rect().contains(cartao):
                fora += 1
                print(f"  FALHA {largura}x{altura} passo {i + 1}: "
                      f"cartão {cartao.x()},{cartao.y()} "
                      f"{cartao.width()}x{cartao.height()} sai da janela")

            foco = guia._foco
            if not foco.isNull():
                if foco.toRect().intersects(cartao):
                    cobrindo += 1
                    print(f"  FALHA {largura}x{altura} passo {i + 1}: "
                          f"o cartão cobre o que está explicando")
            elif not guia.passos[i].alvo and not foco.isNull():
                sem_alvo_aceso += 1

        guia.fechar()
        janela.close()
        app.processEvents()

        marca = "OK    " if not (fora or cobrindo or sem_alvo_aceso) else "FALHOU"
        print(f"{marca} {largura}x{altura} — {total} passos")
        falhas += fora + cobrindo + sem_alvo_aceso

    if falhas:
        print(f"\nFALHA: {falhas} problema(s) de posicionamento.")
        return 1
    print("\nOK: o cartão cabe na janela e nunca cobre o alvo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
