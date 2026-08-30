"""Previa que aparece ao pousar o mouse sobre um cartao do catalogo.

E o gesto que o Netflix popularizou: parar o mouse sobre uma capa e receber, ali
mesmo, o suficiente para decidir — imagem de fundo, sinopse e os botoes de agir.
Sem isso, saber do que se trata custa um clique de ida e outro de volta, e numa
grade de 150 capas isso e muito clique para pouca informacao.

Duas decisoes que valem registro:

  * a previa so aparece depois de o mouse ficar parado um instante. Aparecer no
    primeiro pixel transformaria varrer a grade com os olhos numa sequencia de
    paineis piscando;
  * ela e uma janela sem moldura, e nao um widget dentro da grade. Assim pode
    passar da borda da grade sem ser cortada, que e o que acontece com o cartao
    da ultima coluna.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

from . import tema, widgets

LARGURA = 372
ALTURA_IMAGEM = 174
ESPERA = 520              # ms de mouse parado antes de aparecer


class _Capa(QWidget):
    """Imagem de fundo com escurecimento na base, para o texto caber por cima."""

    def __init__(self, pai=None):
        super().__init__(pai)
        self.imagem: QPixmap | None = None
        self.setMinimumHeight(10)

    def definir(self, imagem: QPixmap | None) -> None:
        self.imagem = imagem
        self.update()

    def paintEvent(self, evento) -> None:                 # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        area = self.rect()
        if self.imagem and not self.imagem.isNull():
            escala = self.imagem.scaled(area.size(), Qt.KeepAspectRatioByExpanding,
                                        Qt.SmoothTransformation)
            p.drawPixmap(
                area,
                escala.copy(max(0, (escala.width() - area.width()) // 2),
                            max(0, (escala.height() - area.height()) // 2),
                            area.width(), area.height()))
        else:
            p.fillRect(area, QColor(20, 20, 26))
        # Escurece a base, senao o titulo some sobre uma imagem clara.
        from PySide6.QtGui import QLinearGradient

        grad = QLinearGradient(0, area.height() * 0.35, 0, area.height())
        grad.setColorAt(0, QColor(10, 10, 14, 0))
        grad.setColorAt(1, QColor(10, 10, 14, 235))
        p.fillRect(area, grad)


class PreviaObra(QFrame):
    """O painel em si. Uma instancia so, reaproveitada para todas as obras."""

    reproduzir = Signal(int)
    baixar = Signal(int)
    abrir = Signal(int)

    def __init__(self, pasta_posters: Path, paleta: tema.Paleta, escala: float,
                 pai=None):
        super().__init__(pai, Qt.ToolTip | Qt.FramelessWindowHint
                         | Qt.NoDropShadowWindowHint)
        self.pasta_posters = Path(pasta_posters)
        self.paleta = paleta
        self.escala = escala
        self.obra: dict | None = None

        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setObjectName("previa")
        self.setFixedWidth(tema.px(LARGURA, escala))
        self._montar()

        sombra = QGraphicsDropShadowEffect(self)
        sombra.setBlurRadius(38)
        sombra.setOffset(0, 10)
        sombra.setColor(QColor(0, 0, 0, 190))
        self.setGraphicsEffect(sombra)

        self.surgir = QPropertyAnimation(self, b"windowOpacity", self)
        self.surgir.setDuration(140)
        self.surgir.setEasingCurve(QEasingCurve.OutCubic)

    def aplicar_tema(self, paleta: tema.Paleta, escala: float) -> None:
        self.paleta, self.escala = paleta, escala

    def _montar(self) -> None:
        p, e = self.paleta, self.escala
        self.setStyleSheet(
            f"QFrame#previa {{ background: {p.lateral};"
            f" border: 1px solid {p.campo_bd}; border-radius: 10px; }}")

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self.capa = _Capa()
        self.capa.setFixedHeight(tema.px(ALTURA_IMAGEM, e))
        col.addWidget(self.capa)

        corpo = QWidget()
        cl = QVBoxLayout(corpo)
        m = tema.px(14, e)
        cl.setContentsMargins(m, tema.px(10, e), m, tema.px(12, e))
        cl.setSpacing(tema.px(7, e))

        self.rot_titulo = QLabel()
        self.rot_titulo.setWordWrap(True)
        self.rot_titulo.setStyleSheet(
            f"color: {p.forte}; font-size: {tema.px(15, e)}px; font-weight: 700;")
        cl.addWidget(self.rot_titulo)

        self.rot_meta = QLabel()
        self.rot_meta.setStyleSheet(
            f"color: {p.fraco}; font-family: {tema.fonte_mono()};"
            f" font-size: {tema.px(10.5, e)}px;")
        cl.addWidget(self.rot_meta)

        self.rot_sinopse = QLabel()
        self.rot_sinopse.setWordWrap(True)
        self.rot_sinopse.setStyleSheet(
            f"color: {p.texto}; font-size: {tema.px(11.5, e)}px;")
        self.rot_sinopse.setMaximumHeight(tema.px(56, e))
        cl.addWidget(self.rot_sinopse)

        acoes = QHBoxLayout()
        acoes.setSpacing(tema.px(7, e))
        self.b_principal = QPushButton()
        self.b_principal.setObjectName("botaoGrande")
        self.b_principal.setProperty("destaque", "true")
        self.b_principal.clicked.connect(self._agir)
        acoes.addWidget(self.b_principal)

        b_abrir = QPushButton("Ver tudo")
        b_abrir.setAccessibleName("Abrir a tela da obra")
        b_abrir.clicked.connect(
            lambda: self.obra and self.abrir.emit(self.obra["id"]))
        acoes.addWidget(b_abrir)
        acoes.addStretch(1)
        cl.addLayout(acoes)
        col.addWidget(corpo)

    # ------------------------------------------------------------ conteudo

    def mostrar_obra(self, obra: dict, ancora) -> None:
        """Preenche e posiciona a previa junto ao cartao apontado."""
        self.obra = obra
        no_disco = obra.get("estado") == "completo"

        self.rot_titulo.setText(obra["titulo"])
        partes = [tema.CORES_ESTADO.get(obra.get("estado", "indice"), ("", ""))[1]]
        for valor in (str(obra.get("ano") or ""),
                      f"{obra['temporadas']} temp." if obra.get("temporadas") else "",
                      (obra.get("qualidades") or [""])[-1],
                      f"nota {obra['nota']:.1f}" if obra.get("nota") else "",
                      widgets.formatar_bytes(obra.get("bytes_total"))):
            if valor:
                partes.append(valor)
        self.rot_meta.setText("  ·  ".join(partes))

        sinopse = (obra.get("sinopse") or "").strip()
        self.rot_sinopse.setText(sinopse[:210] + ("…" if len(sinopse) > 210 else ""))
        self.rot_sinopse.setVisible(bool(sinopse))

        jogo = obra.get("tipo") == "jogo"
        self.b_principal.setText("  Jogar" if (no_disco and jogo)
                                 else "  Reproduzir" if no_disco else "  Baixar")
        self.b_principal.setIcon(widgets.icone_player(
            "tocar" if no_disco else "baixar", self.paleta.contraste_botao,
            tema.px(16, self.escala)))
        self.b_principal.setAccessibleName(
            f"{self.b_principal.text().strip()} {obra['titulo']}")

        self.capa.definir(self._imagem(obra))
        self.adjustSize()
        self._posicionar(ancora)

        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.surgir.stop()
        self.surgir.setStartValue(0.0)
        self.surgir.setEndValue(1.0)
        self.surgir.start()

    def _imagem(self, obra: dict) -> QPixmap | None:
        """Prefere a imagem de fundo; sem ela, o proprio poster serve."""
        for chave in ("backdrop", "poster"):
            nome = obra.get(chave)
            if not nome:
                continue
            caminho = self.pasta_posters / nome
            if caminho.is_file():
                imagem = QPixmap(str(caminho))
                if not imagem.isNull():
                    return imagem
        return None

    def _posicionar(self, ancora) -> None:
        """Ao lado do cartao, sem sair da tela."""
        from PySide6.QtGui import QGuiApplication

        tela = QGuiApplication.screenAt(ancora.center()) or \
            QGuiApplication.primaryScreen()
        area = tela.availableGeometry()
        largura, altura = self.width(), self.sizeHint().height()

        x = ancora.center().x() - largura // 2
        y = ancora.bottom() + tema.px(8, self.escala)
        if y + altura > area.bottom():
            y = ancora.top() - altura - tema.px(8, self.escala)
        x = max(area.left() + 8, min(x, area.right() - largura - 8))
        y = max(area.top() + 8, y)
        self.move(QPoint(x, y))

    def _agir(self) -> None:
        if not self.obra:
            return
        if self.obra.get("estado") == "completo":
            self.reproduzir.emit(self.obra["id"])
        else:
            self.baixar.emit(self.obra["id"])

    def esconder(self) -> None:
        self.surgir.stop()
        self.hide()
