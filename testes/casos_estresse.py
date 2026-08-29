"""Regressao de estabilidade.

O app fechava sozinho, com violacao de acesso em Qt6Core e python314. Eram duas
causas, e este teste cobre as duas:

  1. `QRunnable` com auto-delete: o pool destruia a tarefa (e o objeto que emite
     o sinal) assim que `run()` terminava, mas a entrega acontece depois, ja na
     linha principal — encontrando memoria liberada;
  2. callback chegando depois de a tela ser remontada, escrevendo em widget que
     ja tinha sido destruido.

Reproduzir custava alguns segundos de navegacao rapida. Se voltar, quebra aqui.

    python -m testes.casos_estresse
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QThreadPool, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication      # noqa: E402

from core import config                          # noqa: E402
from ui import tema                              # noqa: E402
from ui.tarefas import Executor                  # noqa: E402

VOLTAS_TAREFAS = 8
TAREFAS_POR_VOLTA = 50


def teste_tarefas() -> tuple[int, int]:
    """Muitas tarefas curtas em rajada — era isto que derrubava o processo."""
    app = QApplication.instance() or QApplication([])
    ex = Executor()
    contador = {"ok": 0, "falhou": 0}

    def disparar():
        for i in range(TAREFAS_POR_VOLTA):
            ex.rodar(f"t{i}-{time.time()}",
                     lambda: (time.sleep(0.004), "ok")[1],
                     lambda _r: contador.__setitem__("ok", contador["ok"] + 1),
                     lambda _m: contador.__setitem__("falhou", contador["falhou"] + 1))

    for n in range(VOLTAS_TAREFAS):
        QTimer.singleShot(120 * n, disparar)
    QTimer.singleShot(120 * VOLTAS_TAREFAS + 2500, app.quit)
    app.exec()
    QThreadPool.globalInstance().waitForDone(4000)
    return contador["ok"], contador["falhou"]


def teste_navegacao() -> int:
    """Abre e fecha telas depressa, com o relogio de progresso rodando."""
    from ui.janela import Janela

    app = QApplication.instance() or QApplication([])
    cfg = config.carregar()
    app.setStyleSheet(tema.folha(tema.ESCURO, 1.0))
    j = Janela(cfg)
    j.resize(1200, 780)
    j.show()

    trocas = {"n": 0}

    def girar():
        modelo = j.grade.modelo
        if modelo.rowCount() == 0:
            return
        for linha in range(min(6, modelo.rowCount())):
            obra = modelo.obra_em(modelo.index(linha, 0))
            j.abrir_item(obra["id"])       # remonta a tela inteira
            app.processEvents()
            j.voltar()
            app.processEvents()
            trocas["n"] += 1
        j.abrir_config()
        app.processEvents()
        j.voltar()
        for tipo in ("filme", "serie", "jogo", ""):
            j.filtro["tipo"] = tipo
            j.atualizar_grade()
            app.processEvents()

    for n in range(5):
        QTimer.singleShot(1200 + 700 * n, girar)
    QTimer.singleShot(7000, app.quit)
    app.exec()
    j.close()
    QThreadPool.globalInstance().waitForDone(4000)
    return trocas["n"]


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    esperadas = VOLTAS_TAREFAS * TAREFAS_POR_VOLTA
    ok, falhou = teste_tarefas()
    print(f"tarefas em rajada: {ok} entregues, {falhou} falhas "
          f"(esperado {esperadas})")
    if ok != esperadas:
        print("FALHA: nem toda tarefa foi entregue.")
        return 1

    trocas = teste_navegacao()
    print(f"navegação rápida:  {trocas} aberturas de obra sem crash")
    if trocas == 0:
        print("AVISO: catálogo vazio, a navegação não foi exercitada.")

    print("\nOK: sobreviveu às duas rajadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
