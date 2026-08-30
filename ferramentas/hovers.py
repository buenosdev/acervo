"""Experimentar os estilos de hover do catalogo antes de escolher um.

    python -m ferramentas.hovers

Abre a sua grade de verdade, com as suas capas, e um seletor no topo para
trocar de estilo ao vivo. Ao lado do seletor fica o tempo de pintura medido
enquanto voce mexe o mouse — porque "nao trava" e uma afirmacao que se verifica,
nao se promete.

Escolhido um, e so marcar em Configuracoes -> Aparencia.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QTimer                    # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout,  # noqa: E402
                               QLabel, QVBoxLayout, QWidget)

from core import config, consultas, db                   # noqa: E402
from ui import tema                                      # noqa: E402
from ui.grade import ESTILOS_HOVER, GradeObras           # noqa: E402

EXPLICACAO = {
    "borda": "Um halo azul acende em volta do cartão e apaga quando o mouse "
             "sai — em 170 ms, não de uma vez. Nada mais se mexe: nenhum "
             "texto aparece, nenhum vizinho é coberto.",
    "elevar": "O mesmo halo, e o cartão cresce dentro da própria célula "
              "enquanto acende. Continua sem empurrar a grade.",
    "rodape": "O mesmo halo, e a ficha da obra sob o mouse aparece numa linha "
              "no rodapé da janela — informação sem nada piscando na grade.",
}


class Bancada(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.setWindowTitle("Acervo — experimentar os hovers")
        self.resize(1320, 860)
        paleta, escala = tema.ESCURO, 1.0

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        topo = QWidget()
        topo.setStyleSheet(f"background: {paleta.lateral};")
        tl = QHBoxLayout(topo)
        tl.setContentsMargins(16, 10, 16, 10)
        tl.setSpacing(12)

        tl.addWidget(QLabel("Estilo do hover:"))
        self.combo = QComboBox()
        for chave, rotulo in ESTILOS_HOVER.items():
            self.combo.addItem(rotulo, chave)
        self.combo.setMinimumWidth(300)
        self.combo.currentIndexChanged.connect(self._trocar)
        tl.addWidget(self.combo)

        self.rot_custo = QLabel("—")
        self.rot_custo.setStyleSheet(
            f"color: {paleta.fraco}; font-family: {tema.fonte_mono()};")
        tl.addWidget(self.rot_custo)
        tl.addStretch(1)
        col.addWidget(topo)

        self.rot_explicacao = QLabel()
        self.rot_explicacao.setWordWrap(True)
        self.rot_explicacao.setStyleSheet(
            f"color: {paleta.texto}; background: {paleta.ativo};"
            " padding: 10px 16px;")
        col.addWidget(self.rot_explicacao)

        con = db.conectar(cfg.banco)
        self.grade = GradeObras(cfg.posters, paleta, escala, "medio", "grade")
        self.grade.definir_obras(consultas.listar(con))
        col.addWidget(self.grade, 1)

        self.rodape = QLabel("Passe o mouse sobre uma capa.")
        self.rodape.setStyleSheet(
            f"color: {paleta.fraco}; background: {paleta.lateral};"
            f" border-top: 1px solid {paleta.linha}; padding: 9px 16px;")
        col.addWidget(self.rodape)
        self.grade.sob_o_mouse.connect(self._sob_o_mouse)

        # Mede o custo real de repintar enquanto o mouse anda.
        self._medidor = QTimer(self)
        self._medidor.timeout.connect(self._medir)
        self._medidor.start(900)

        self.combo.setCurrentIndex(0)          # comeca na borda
        self._trocar()

    def _trocar(self) -> None:
        estilo = self.combo.currentData()
        self.grade.definir_estilo_hover(estilo)
        self.rot_explicacao.setText(EXPLICACAO.get(estilo, ""))

    def _sob_o_mouse(self, obra) -> None:
        if self.combo.currentData() != "rodape" or obra is None:
            self.rodape.setText("Passe o mouse sobre uma capa.")
            return
        partes = [obra["titulo"]]
        for x in (str(obra.get("ano") or ""),
                  f"{obra['temporadas']} temporadas" if obra.get("temporadas") else "",
                  f"nota {obra['nota']:.1f}" if obra.get("nota") else "",
                  tema.CORES_ESTADO.get(obra.get("estado", "indice"), ("", ""))[1]):
            if x:
                partes.append(x)
        self.rodape.setText("   ·   ".join(partes))

    def _medir(self) -> None:
        inicio = time.perf_counter()
        self.grade.viewport().repaint()
        ms = (time.perf_counter() - inicio) * 1000
        self.rot_custo.setText(f"repintar a grade: {ms:5.1f} ms   "
                               f"(um quadro tem 16,6 ms)")


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    app = QApplication.instance() or QApplication(sys.argv)
    cfg = config.carregar()
    app.setStyleSheet(tema.folha(tema.ESCURO, 1.0))
    janela = Bancada(cfg)
    janela.show()
    print("Experimente os estilos no seletor do topo.")
    print("O que escolher, marque em Configurações → Aparência.")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
