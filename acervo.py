"""Acervo — aplicativo de desktop.

    python acervo.py

Janela nativa em Qt. Nada de servidor web, nada de navegador.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import Qt          # noqa: E402
from PySide6.QtGui import QIcon        # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core import config, db, local     # noqa: E402
from ui import tema                    # noqa: E402
from ui.janela import Janela           # noqa: E402


def _icone() -> QIcon:
    caminho = local.pasta_recursos() / "recursos" / "acervo.ico"
    return QIcon(str(caminho)) if caminho.is_file() else QIcon()


def _primeira_abertura(janela: Janela, cfg) -> None:
    """Na primeira vez, o guia. Depois disso, nunca mais sozinho.

    A versao anterior era uma caixa de dialogo com "Configurar agora / Depois".
    Ela dizia o que fazer, mas nao mostrava nada — e quem clicava em "Depois"
    ficava sem saber que o app tinha barra lateral, busca, organizacao. O guia
    aponta para cada parte da janela de verdade.
    """
    if (cfg.bruto.get("aparencia") or {}).get("guia_visto"):
        return
    janela.abrir_guia()


def _registrar_falha(erro: BaseException) -> Path:
    """Grava o erro ao lado do executavel.

    Empacotado sem console nao ha onde uma excecao aparecer: o app simplesmente
    nao abriria, sem dizer nada. Com o arquivo, da para saber o que houve.
    """
    import traceback
    from datetime import datetime

    destino = local.pasta_dados() / "erro.log"
    try:
        with destino.open("a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            f.write("".join(traceback.format_exception(erro)))
    except OSError:
        pass
    return destino


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("Acervo")
    app.setApplicationDisplayName("Acervo")
    app.setOrganizationName("Acervo")
    app.setWindowIcon(_icone())

    cfg = config.carregar()
    try:
        db.conectar(cfg.banco).close()
    except Exception as erro:
        QMessageBox.critical(None, "Acervo",
                             f"Não consegui abrir o banco de dados:\n\n{erro}")
        return 1

    prefs = cfg.bruto.get("aparencia") or {}
    app.setStyleSheet(tema.folha(
        tema.PALETAS.get(prefs.get("tema", "escuro"), tema.ESCURO),
        tema.ESCALAS.get(prefs.get("fonte", "normal"), 1.0)))

    janela = Janela(cfg)
    janela.aplicar_tema(prefs.get("tema", "escuro"), prefs.get("fonte", "normal"))
    janela.resize(1320, 840)
    janela.show()

    _primeira_abertura(janela, cfg)

    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as erro:                    # noqa: BLE001
        caminho = _registrar_falha(erro)
        local.avisar("Acervo — erro ao abrir",
                     f"{type(erro).__name__}: {erro}\n\nDetalhes em:\n{caminho}")
        raise SystemExit(1)
