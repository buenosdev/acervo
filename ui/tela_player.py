"""A tela de reproducao, dentro da propria janela do Acervo.

E uma pagina do QStackedWidget, nao uma janela nova. O app tem como principio
que nada abre por cima de nada, e um player em janela solta contradiria isso —
alem de recriar exatamente o vaivem entre programas que este projeto existe para
evitar.

O video nao e desenhado pelo Qt. O motor (VLC ou mpv) recebe o identificador
nativo desta area e pinta ali dentro, por baixo. Por isso a area de video precisa
ser uma janela nativa de verdade (`WA_NativeWindow`) e nao pode ter nada do Qt
desenhado por cima — os controles ficam numa faixa abaixo, nao sobrepostos.

O acervo desta casa e quase todo DUAL com legenda `.srt` ao lado, entao escolher
faixa de audio e legenda nao e um extra: sem isso o player embutido seria pior
que abrir no VLC, e ninguem usaria.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QSlider, QVBoxLayout, QWidget)

from core import players

from . import tema
from .widgets import Retorno

# Abaixo disto e comeco de filme, acima e fim: nos dois casos, retomar atrapalha.
MINIMO_PARA_GUARDAR = 30.0
FRACAO_CONSIDERADA_FIM = 0.95
INTERVALO_RELOGIO = 250          # ms
INTERVALO_GRAVAR = 5000          # ms


def _tempo(segundos: float) -> str:
    segundos = max(0, int(segundos))
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def guardar_posicao(con: sqlite3.Connection, caminho: Path,
                    segundos: float, duracao: float) -> bool:
    """Guarda onde parou. False quando nao vale a pena guardar.

    Nao guarda os primeiros segundos (a pessoa mal comecou) nem o fim (ja
    assistiu). Oferecer "retomar de 0:12" ou "retomar de 1:58 de 2:00" seria
    ruido nos dois casos.
    """
    if duracao and segundos >= duracao * FRACAO_CONSIDERADA_FIM:
        con.execute("DELETE FROM posicoes WHERE caminho = ?", (str(caminho),))
        con.commit()
        return False
    if segundos < MINIMO_PARA_GUARDAR:
        return False
    con.execute(
        "INSERT INTO posicoes (caminho, segundos, duracao, visto_em) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(caminho) DO UPDATE SET "
        "segundos = excluded.segundos, duracao = excluded.duracao, "
        "visto_em = excluded.visto_em",
        (str(caminho), float(segundos), float(duracao or 0),
         datetime.now().isoformat(timespec="seconds")))
    con.commit()
    return True


def posicao_guardada(con: sqlite3.Connection, caminho: Path) -> float:
    linha = con.execute("SELECT segundos FROM posicoes WHERE caminho = ?",
                        (str(caminho),)).fetchone()
    return float(linha["segundos"]) if linha else 0.0


class TelaPlayer(QWidget):
    pedir_voltar = Signal()

    def __init__(self, cfg, con: sqlite3.Connection, paleta: tema.Paleta,
                 escala: float, pai=None):
        super().__init__(pai)
        self.cfg = cfg
        self.con = con
        self.paleta = paleta
        self.escala = escala

        self.motor: players.Player | None = None
        self.caminho: Path | None = None
        self.titulo = ""
        self._arrastando = False
        self._faixas_montadas = False
        self._cheia = False

        self._montar()

        self.relogio = QTimer(self)
        self.relogio.setInterval(INTERVALO_RELOGIO)
        self.relogio.timeout.connect(self._tique)

        self.gravador = QTimer(self)
        self.gravador.setInterval(INTERVALO_GRAVAR)
        self.gravador.timeout.connect(self._gravar_posicao)

        self._atalhos()

    def aplicar_tema(self, paleta: tema.Paleta, escala: float) -> None:
        self.paleta, self.escala = paleta, escala

    # ------------------------------------------------------------ montagem

    def _montar(self) -> None:
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # A area onde o motor pinta. Precisa ser janela nativa: e o `winId()`
        # dela que vai para o VLC/mpv.
        self.video = QWidget(self)
        self.video.setAttribute(Qt.WA_NativeWindow, True)
        self.video.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.video.setStyleSheet("background: #000000;")
        self.video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video.setMinimumHeight(240)
        self.video.setAccessibleName("Área de vídeo")
        col.addWidget(self.video, 1)

        col.addWidget(self._barra())

        self.retorno = Retorno()
        col.addWidget(self.retorno)

    def _barra(self) -> QWidget:
        p, e = self.paleta, self.escala
        barra = QWidget()
        barra.setObjectName("barraPlayer")
        barra.setStyleSheet(
            f"QWidget#barraPlayer {{ background: {p.lateral};"
            f" border-top: 1px solid {p.linha}; }}")
        fora = QVBoxLayout(barra)
        fora.setContentsMargins(tema.px(16, e), tema.px(10, e),
                                tema.px(16, e), tema.px(11, e))
        fora.setSpacing(tema.px(7, e))

        # --- linha do tempo
        linha_tempo = QHBoxLayout()
        linha_tempo.setSpacing(tema.px(10, e))
        self.rot_agora = QLabel("0:00")
        self.rot_agora.setObjectName("monoTexto")
        linha_tempo.addWidget(self.rot_agora)

        self.barra_tempo = QSlider(Qt.Horizontal)
        self.barra_tempo.setRange(0, 1000)
        self.barra_tempo.setAccessibleName("Posição do vídeo")
        self.barra_tempo.sliderPressed.connect(lambda: setattr(self, "_arrastando", True))
        self.barra_tempo.sliderReleased.connect(self._soltou_barra)
        linha_tempo.addWidget(self.barra_tempo, 1)

        self.rot_total = QLabel("0:00")
        self.rot_total.setObjectName("monoTexto")
        linha_tempo.addWidget(self.rot_total)
        fora.addLayout(linha_tempo)

        # --- linha dos controles
        controles = QHBoxLayout()
        controles.setSpacing(tema.px(8, e))

        self.b_tocar = QPushButton("⏸")
        self.b_tocar.setObjectName("botaoGrande")
        self.b_tocar.setProperty("destaque", "true")
        self.b_tocar.setFixedWidth(tema.px(54, e))
        self.b_tocar.setAccessibleName("Pausar ou continuar")
        self.b_tocar.clicked.connect(self.alternar)
        controles.addWidget(self.b_tocar)

        self.b_mudo = QPushButton("🔊")
        self.b_mudo.setFixedWidth(tema.px(42, e))
        self.b_mudo.setCheckable(True)
        self.b_mudo.setAccessibleName("Sem som")
        self.b_mudo.toggled.connect(self._mudo)
        controles.addWidget(self.b_mudo)

        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(90)
        self.volume.setFixedWidth(tema.px(110, e))
        self.volume.setAccessibleName("Volume")
        self.volume.valueChanged.connect(self._volume)
        controles.addWidget(self.volume)

        controles.addSpacing(tema.px(12, e))

        self.combo_audio = QComboBox()
        self.combo_audio.setAccessibleName("Faixa de áudio")
        self.combo_audio.setMinimumWidth(tema.px(150, e))
        self.combo_audio.currentIndexChanged.connect(self._trocar_audio)
        controles.addWidget(QLabel("Áudio"))
        controles.addWidget(self.combo_audio)

        self.combo_legenda = QComboBox()
        self.combo_legenda.setAccessibleName("Legenda")
        self.combo_legenda.setMinimumWidth(tema.px(150, e))
        self.combo_legenda.currentIndexChanged.connect(self._trocar_legenda)
        controles.addWidget(QLabel("Legenda"))
        controles.addWidget(self.combo_legenda)

        controles.addStretch(1)

        self.b_cheia = QPushButton("⛶  Tela cheia")
        self.b_cheia.setAccessibleName("Alternar tela cheia")
        self.b_cheia.clicked.connect(self.alternar_tela_cheia)
        controles.addWidget(self.b_cheia)

        b_fechar = QPushButton("Fechar")
        b_fechar.setAccessibleName("Fechar o player e voltar")
        b_fechar.clicked.connect(self.fechar)
        controles.addWidget(b_fechar)
        fora.addLayout(controles)
        return barra

    def _atalhos(self) -> None:
        for sequencia, funcao in (
                ("Space", self.alternar),
                ("Right", lambda: self._pular(10)),
                ("Left", lambda: self._pular(-10)),
                ("Shift+Right", lambda: self._pular(60)),
                ("Shift+Left", lambda: self._pular(-60)),
                ("M", lambda: self.b_mudo.toggle()),
                ("F", self.alternar_tela_cheia),
                ("Esc", self.fechar)):
            QShortcut(QKeySequence(sequencia), self, activated=funcao)

    # -------------------------------------------------------------- tocar

    def tocar(self, caminho: Path, titulo: str = "") -> bool:
        """Abre o arquivo. False quando o motor escolhido nao e embutido."""
        self.caminho, self.titulo = Path(caminho), titulo
        motor, explicacao = players.escolher(self.cfg)

        if not motor.recursos.embutido:
            # Nao ha player embutido utilizavel: quem chamou abre no sistema.
            try:
                motor.abrir(Path(caminho))
            except players.ErroPlayer:
                return False
            return False

        self.motor = motor
        try:
            self.motor.abrir(Path(caminho), janela=int(self.video.winId()))
        except players.ErroPlayer as e:
            self.retorno.mostrar("erro", str(e))
            self.motor = None
            return False

        self._faixas_montadas = False
        self.motor.definir_volume(self.volume.value())
        self.motor.tocar()
        self.relogio.start()
        self.gravador.start()

        retomar = posicao_guardada(self.con, Path(caminho))
        if retomar > MINIMO_PARA_GUARDAR:
            QTimer.singleShot(700, lambda: self._retomar(retomar))
        self.retorno.hide()
        return True

    def _retomar(self, segundos: float) -> None:
        if not self.motor:
            return
        self.motor.ir_para(segundos)
        self.retorno.mostrar("info", f"Retomando de {_tempo(segundos)}.")

    def alternar(self) -> None:
        if not self.motor:
            return
        if self.motor.tocando():
            self.motor.pausar()
            self.b_tocar.setText("▶")
        else:
            self.motor.tocar()
            self.b_tocar.setText("⏸")

    def _pular(self, segundos: float) -> None:
        if self.motor:
            self.motor.ir_para(max(0, self.motor.posicao() + segundos))

    def _soltou_barra(self) -> None:
        self._arrastando = False
        if self.motor:
            total = self.motor.duracao()
            if total:
                self.motor.ir_para(total * self.barra_tempo.value() / 1000.0)

    def _volume(self, valor: int) -> None:
        if self.motor:
            self.motor.definir_volume(valor)

    def _mudo(self, ligado: bool) -> None:
        if self.motor:
            self.motor.mudo(ligado)
        self.b_mudo.setText("🔇" if ligado else "🔊")

    # -------------------------------------------------------------- faixas

    def _montar_faixas(self) -> None:
        """As faixas so existem depois que o motor leu o arquivo."""
        for combo, faixas, atual in (
                (self.combo_audio, self.motor.faixas_audio(), self.motor.audio_atual()),
                (self.combo_legenda, self.motor.faixas_legenda(),
                 self.motor.legenda_atual())):
            combo.blockSignals(True)
            combo.clear()
            if combo is self.combo_legenda and not any(f.id < 0 for f in faixas):
                combo.addItem("Sem legenda", -1)
            for f in faixas:
                combo.addItem(f.nome, f.id)
            indice = combo.findData(atual)
            if indice >= 0:
                combo.setCurrentIndex(indice)
            combo.setEnabled(combo.count() > 1)
            combo.blockSignals(False)

        # Legenda solta na mesma pasta, que o motor nao acha sozinho.
        if self.caminho:
            for srt in sorted(self.caminho.parent.glob("*.srt")):
                if self.motor.carregar_legenda(srt):
                    break
        self._faixas_montadas = True

    def _trocar_audio(self, indice: int) -> None:
        if self.motor and indice >= 0:
            self.motor.definir_audio(self.combo_audio.itemData(indice))

    def _trocar_legenda(self, indice: int) -> None:
        if self.motor and indice >= 0:
            self.motor.definir_legenda(self.combo_legenda.itemData(indice))

    # -------------------------------------------------------------- relogio

    def _tique(self) -> None:
        if not self.motor:
            return
        agora, total = self.motor.posicao(), self.motor.duracao()
        if not self._faixas_montadas and total > 0:
            self._montar_faixas()
        if not self._arrastando and total:
            self.barra_tempo.setValue(int(1000 * agora / total))
        self.rot_agora.setText(_tempo(agora))
        self.rot_total.setText(_tempo(total))
        self.b_tocar.setText("⏸" if self.motor.tocando() else "▶")
        if self.motor.terminou():
            self.fechar()

    def _gravar_posicao(self) -> None:
        if self.motor and self.caminho and self.motor.duracao():
            guardar_posicao(self.con, self.caminho, self.motor.posicao(),
                            self.motor.duracao())

    # ---------------------------------------------------------- tela cheia

    def alternar_tela_cheia(self) -> None:
        janela = self.window()
        self._cheia = not self._cheia
        if self._cheia:
            janela.showFullScreen()
        else:
            janela.showNormal()
        self.b_cheia.setText("⛶  Sair da tela cheia" if self._cheia
                             else "⛶  Tela cheia")

    def mouseDoubleClickEvent(self, evento) -> None:      # noqa: N802
        self.alternar_tela_cheia()

    # ------------------------------------------------------------- fechar

    def fechar(self) -> None:
        self.relogio.stop()
        self.gravador.stop()
        if self.motor:
            self._gravar_posicao()
            self.motor.encerrar()
            self.motor = None
        if self._cheia:
            self.alternar_tela_cheia()
        self.pedir_voltar.emit()
