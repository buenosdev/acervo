"""A tela de reproducao: video ocupando tudo, controles que somem sozinhos.

E uma pagina do QStackedWidget, nao uma janela nova — o app tem como principio
que nada abre por cima de nada.

Duas coisas guiaram o desenho:

**O video nao e desenhado pelo Qt.** O motor recebe o identificador nativo da
area e pinta ali por baixo. Um widget Qt comum posto por cima ficaria ATRAS do
video, porque o desenho nativo ignora a ordem do Qt. Por isso as barras de
controle sao, elas tambem, janelas nativas (`WA_NativeWindow`) e sobem com
`raise_()` — foi verificado que assim aparecem sobre o video.

**Mouse sobre a area de video nem sempre chega ao Qt**, porque o motor e dono
daquele HWND enquanto toca. Entao o aparecer-e-sumir dos controles nao depende
de evento de mouse: um relogio compara a posicao global do cursor. Funciona
independentemente de quem esteja segurando a janela.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QSlider, QVBoxLayout, QWidget)

from core import players

from . import tema, widgets

# Abaixo disto e comeco de filme, acima e fim: nos dois casos, retomar atrapalha.
MINIMO_PARA_GUARDAR = 30.0
FRACAO_CONSIDERADA_FIM = 0.95

INTERVALO_RELOGIO = 200          # ms — atualiza tempo e barra
INTERVALO_GRAVAR = 5000          # ms — grava onde parou
INTERVALO_CURSOR = 150           # ms — verifica se o mouse mexeu
ESPERA_PARA_SUMIR = 2600         # ms parado ate os controles sumirem

ALTURA_BARRA = 92
ALTURA_TOPO = 58


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


class _Faixa(QWidget):
    """Barra nativa que se desenha por cima do video e desliza para fora.

    Desliza, e nao desaparece com transparencia: `QGraphicsOpacityEffect` e
    simplesmente ignorado em widget com janela nativa — foi testado, a
    opacidade ficava em 1.0 e a barra nunca sumia. Mover a geometria funciona
    em qualquer caso, e o deslize ainda fica mais parecido com o que um player
    de video faz.
    """

    def __init__(self, pai: QWidget, cor_fundo: str, para_cima: bool):
        super().__init__(pai)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {cor_fundo};")
        self.para_cima = para_cima          # topo sai por cima; barra, por baixo
        self.dentro = QPoint()
        self.fora = QPoint()
        self.mostrando = True

        self.animacao = QPropertyAnimation(self, b"pos", self)
        self.animacao.setDuration(240)
        self.animacao.setEasingCurve(QEasingCurve.OutCubic)

    def acomodar(self, x: int, y: int, largura: int, altura: int) -> None:
        self.resize(largura, altura)
        self.dentro = QPoint(x, y)
        self.fora = QPoint(x, y - altura if self.para_cima else y + altura)
        self.move(self.dentro if self.mostrando else self.fora)

    def aparecer(self) -> None:
        if self.mostrando:
            return
        self.mostrando = True
        self.show()
        self.raise_()
        self.animacao.stop()
        self.animacao.setStartValue(self.pos())
        self.animacao.setEndValue(self.dentro)
        self.animacao.start()

    def sumir(self) -> None:
        if not self.mostrando:
            return
        self.mostrando = False
        self.animacao.stop()
        self.animacao.setStartValue(self.pos())
        self.animacao.setEndValue(self.fora)
        self.animacao.start()


class BarraTempo(QSlider):
    """Barra de progresso onde clicar em qualquer ponto leva aquele ponto.

    O QSlider comum nao faz isso: clicar fora do castiçal avanca so um passo de
    pagina, e como o relogio do player reescreve o valor 200 ms depois, o efeito
    na tela e a barra pular um tico e voltar — que e exatamente a sensacao de
    "nao consigo ir pra frente". Todo player de video trata o clique como
    "quero ir para ali", e e o que isto faz.
    """

    buscar = Signal(float)              # fracao de 0 a 1

    def __init__(self, pai=None):
        super().__init__(Qt.Horizontal, pai)
        self.setRange(0, 10000)

    def _fracao(self, x: float) -> float:
        util = max(1, self.width())
        return min(1.0, max(0.0, x / util))

    def mousePressEvent(self, evento) -> None:            # noqa: N802
        if evento.button() != Qt.LeftButton:
            super().mousePressEvent(evento)
            return
        fracao = self._fracao(evento.position().x())
        self.setValue(round(fracao * self.maximum()))
        self.setSliderDown(True)          # segue arrastando sem soltar o botao
        self.sliderMoved.emit(self.value())
        evento.accept()

    def mouseMoveEvent(self, evento) -> None:             # noqa: N802
        if self.isSliderDown():
            fracao = self._fracao(evento.position().x())
            self.setValue(round(fracao * self.maximum()))
            self.sliderMoved.emit(self.value())
            evento.accept()
            return
        super().mouseMoveEvent(evento)

    def mouseReleaseEvent(self, evento) -> None:          # noqa: N802
        if evento.button() == Qt.LeftButton and self.isSliderDown():
            self.setSliderDown(False)
            self.buscar.emit(self.value() / self.maximum())
            evento.accept()
            return
        super().mouseReleaseEvent(evento)


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
        self.fila: list = []          # (caminho, rotulo) da serie
        self.indice = 0
        self._faixas_montadas = False
        self._cheia = False
        self._cursor_antes = QPoint()
        self._parado_ha = 0
        self._audio_conferido = False

        self.setStyleSheet("background: #000000;")
        self._montar()

        self.relogio = QTimer(self)
        self.relogio.setInterval(INTERVALO_RELOGIO)
        self.relogio.timeout.connect(self._tique)

        self.gravador = QTimer(self)
        self.gravador.setInterval(INTERVALO_GRAVAR)
        self.gravador.timeout.connect(self._gravar_posicao)

        self.vigia = QTimer(self)
        self.vigia.setInterval(INTERVALO_CURSOR)
        self.vigia.timeout.connect(self._olhar_cursor)

        self._atalhos()

    def aplicar_tema(self, paleta: tema.Paleta, escala: float) -> None:
        self.paleta, self.escala = paleta, escala

    # ------------------------------------------------------------ montagem

    def _montar(self) -> None:
        # A area de video ocupa a pagina inteira; as barras flutuam por cima.
        self.video = QWidget(self)
        self.video.setAttribute(Qt.WA_NativeWindow, True)
        self.video.setStyleSheet("background: #000000;")
        self.video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video.setAccessibleName("Área de vídeo")

        self.topo = _Faixa(self, "rgb(8, 8, 12)", para_cima=True)
        self.barra = _Faixa(self, "rgb(8, 8, 12)", para_cima=False)
        self._montar_topo()
        self._montar_barra()

    def _botao(self, icone: str, dica: str, funcao, pai_layout,
               largura: int = 44) -> QPushButton:
        b = QPushButton()
        b.setIcon(widgets.icone_player(icone, self.paleta.forte,
                                       tema.px(22, self.escala)))
        b.setFixedSize(tema.px(largura, self.escala), tema.px(34, self.escala))
        b.setAccessibleName(dica)
        b.setToolTip(dica)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(funcao)
        pai_layout.addWidget(b)
        return b

    def _montar_topo(self) -> None:
        lay = QHBoxLayout(self.topo)
        m = tema.px(14, self.escala)
        lay.setContentsMargins(m, tema.px(9, self.escala), m, tema.px(9, self.escala))
        lay.setSpacing(tema.px(12, self.escala))

        self.b_voltar = self._botao("voltar", "Voltar ao catálogo", self.fechar, lay)
        self.rot_titulo = QLabel()
        self.rot_titulo.setStyleSheet(
            f"color: {self.paleta.forte}; font-size: {tema.px(15, self.escala)}px;"
            " font-weight: 600; background: transparent;")
        lay.addWidget(self.rot_titulo, 1)

        self.rot_aviso = QLabel()
        self.rot_aviso.setStyleSheet(
            f"color: {self.paleta.ambar}; font-size: {tema.px(11.5, self.escala)}px;"
            " background: transparent;")
        lay.addWidget(self.rot_aviso)

    def _montar_barra(self) -> None:
        p, e = self.paleta, self.escala
        col = QVBoxLayout(self.barra)
        m = tema.px(16, e)
        col.setContentsMargins(m, tema.px(9, e), m, tema.px(10, e))
        col.setSpacing(tema.px(6, e))

        linha = QHBoxLayout()
        linha.setSpacing(tema.px(10, e))
        estilo_tempo = (f"color: {p.forte}; font-family: {tema.fonte_mono()};"
                        f" font-size: {tema.px(11.5, e)}px; background: transparent;")
        self.rot_agora = QLabel("0:00")
        self.rot_agora.setStyleSheet(estilo_tempo)
        linha.addWidget(self.rot_agora)

        self.barra_tempo = BarraTempo()
        self.barra_tempo.setAccessibleName("Posição do vídeo")
        self.barra_tempo.setFocusPolicy(Qt.NoFocus)   # as setas sao do player
        self.barra_tempo.sliderMoved.connect(self._movendo_barra)
        self.barra_tempo.buscar.connect(self._buscar_fracao)
        linha.addWidget(self.barra_tempo, 1)

        self.rot_total = QLabel("0:00")
        self.rot_total.setStyleSheet(estilo_tempo)
        linha.addWidget(self.rot_total)
        col.addLayout(linha)

        ctl = QHBoxLayout()
        ctl.setSpacing(tema.px(7, e))
        self.b_anterior = self._botao("anterior", "Episódio anterior",
                                      self.anterior, ctl)
        self.b_tocar = self._botao("pausar", "Pausar ou continuar (Espaço)",
                                   self.alternar, ctl, largura=52)
        self.b_proximo = self._botao("proximo", "Próximo episódio", self.proximo, ctl)
        self.b_recomecar = self._botao(
            "recomecar", "Reiniciar o vídeo, mantendo o ponto (R)",
            self.reiniciar, ctl)
        self.b_mudo = self._botao("som", "Sem som (M)", self._alternar_mudo, ctl)

        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int((self.cfg.bruto.get("reproducao") or {})
                                 .get("volume", 90)))
        self.volume.setFixedWidth(tema.px(104, e))
        self.volume.setAccessibleName("Volume")
        self.volume.valueChanged.connect(self._volume)
        ctl.addWidget(self.volume)

        ctl.addSpacing(tema.px(14, e))
        estilo_rot = (f"color: {p.fraco}; font-size: {tema.px(11.5, e)}px;"
                      " background: transparent;")
        for rotulo, atributo, dica, funcao in (
                ("Áudio", "combo_audio", "Faixa de áudio", self._trocar_audio),
                ("Legenda", "combo_legenda", "Legenda", self._trocar_legenda)):
            r = QLabel(rotulo)
            r.setStyleSheet(estilo_rot)
            ctl.addWidget(r)
            combo = QComboBox()
            combo.setAccessibleName(dica)
            combo.setMinimumWidth(tema.px(146, e))
            combo.currentIndexChanged.connect(funcao)
            setattr(self, atributo, combo)
            ctl.addWidget(combo)

        ctl.addStretch(1)
        self.b_cheia = self._botao("cheia", "Tela cheia (F)",
                                   self.alternar_tela_cheia, ctl)
        col.addLayout(ctl)

    def _atalhos(self) -> None:
        for sequencia, funcao in (
                ("Space", self.alternar),
                ("Right", lambda: self._pular(10)),
                ("Left", lambda: self._pular(-10)),
                ("Shift+Right", lambda: self._pular(60)),
                ("Shift+Left", lambda: self._pular(-60)),
                ("Up", lambda: self.volume.setValue(self.volume.value() + 5)),
                ("Down", lambda: self.volume.setValue(self.volume.value() - 5)),
                ("M", self._alternar_mudo),
                ("R", self.reiniciar),
                ("Ctrl+Right", self.proximo),
                ("Ctrl+Left", self.anterior),
                ("F", self.alternar_tela_cheia),
                ("Esc", self._escapar)):
            QShortcut(QKeySequence(sequencia), self, activated=funcao)

    # ------------------------------------------------------------- layout

    def resizeEvent(self, evento) -> None:               # noqa: N802
        super().resizeEvent(evento)
        self._posicionar()

    def _posicionar(self) -> None:
        largura, altura = self.width(), self.height()
        self.video.setGeometry(0, 0, largura, altura)
        alto_topo = tema.px(ALTURA_TOPO, self.escala)
        alto_barra = tema.px(ALTURA_BARRA, self.escala)
        self.topo.acomodar(0, 0, largura, alto_topo)
        self.barra.acomodar(0, altura - alto_barra, largura, alto_barra)
        self.topo.raise_()
        self.barra.raise_()

    # -------------------------------------------------------------- tocar

    def tocar(self, caminho: Path, titulo: str = "", fila: list | None = None,
              indice: int = 0, retomar: float | None = None) -> bool:
        """Abre o arquivo. False quando o motor escolhido nao e embutido."""
        self.caminho, self.titulo = Path(caminho), titulo
        self.fila = list(fila or [])
        self.indice = indice
        self._ajustar_fila()
        motor, _ = players.escolher(self.cfg)

        if not motor.recursos.embutido:
            try:
                motor.abrir(Path(caminho))
            except players.ErroPlayer:
                return False
            return False

        self.motor = motor
        self._posicionar()
        try:
            self.motor.abrir(Path(caminho), janela=int(self.video.winId()))
        except players.ErroPlayer as e:
            self.rot_aviso.setText(str(e)[:90])
            self.motor = None
            return False

        self.rot_titulo.setText(titulo or Path(caminho).stem)
        self.rot_aviso.setText("")
        self._faixas_montadas = False
        self._audio_conferido = False
        self.motor.tocar()
        # O volume so pega depois que a saida de audio existe.
        QTimer.singleShot(400, lambda: self._volume(self.volume.value()))

        self.relogio.start()
        self.gravador.start()
        self.vigia.start()
        self._acordar()

        ponto = retomar if retomar is not None else posicao_guardada(
            self.con, Path(caminho))
        if ponto and ponto > 1:
            QTimer.singleShot(700, lambda: self._retomar(ponto,
                                                         avisar=retomar is None))
        return True

    def _retomar(self, segundos: float, avisar: bool = True) -> None:
        if self.motor:
            self.motor.ir_para(segundos)
            if avisar:
                self._avisar(f"Retomando de {_tempo(segundos)}.")

    def _avisar(self, texto: str, segundos: int = 6) -> None:
        self.rot_aviso.setText(texto)
        QTimer.singleShot(segundos * 1000, lambda: self.rot_aviso.setText(""))

    def alternar(self) -> None:
        if not self.motor:
            return
        if self.motor.tocando():
            self.motor.pausar()
        else:
            self.motor.tocar()
        self._acordar()

    def _ajustar_fila(self) -> None:
        """Liga ou desliga os botoes de episodio conforme onde estamos."""
        tem_fila = len(self.fila) > 1
        self.b_anterior.setVisible(tem_fila)
        self.b_proximo.setVisible(tem_fila)
        self.b_anterior.setEnabled(tem_fila and self.indice > 0)
        self.b_proximo.setEnabled(tem_fila and self.indice < len(self.fila) - 1)

    def _ir_para_episodio(self, novo_indice: int) -> None:
        if not (0 <= novo_indice < len(self.fila)):
            return
        self._gravar_posicao()
        if self.motor:
            self.motor.encerrar()
            self.motor = None
        caminho, rotulo = self.fila[novo_indice]
        fila, indice = self.fila, novo_indice
        self.tocar(caminho, rotulo, fila=fila, indice=indice)

    def anterior(self) -> None:
        self._ir_para_episodio(self.indice - 1)

    def proximo(self) -> None:
        self._ir_para_episodio(self.indice + 1)

    def reiniciar(self) -> None:
        """Recarrega o video no ponto em que estava.

        Decodificador as vezes trava — quadro congelado, som some, barra para de
        andar — e nao ha o que fazer de dentro: o motor precisa reabrir o
        arquivo. Isto faz exatamente isso, e volta para onde voce estava, para
        travar nao custar procurar a cena de novo.
        """
        if not self.motor or not self.caminho:
            return
        ponto = self.motor.posicao()
        audio, legenda = self.motor.audio_atual(), self.motor.legenda_atual()
        self.motor.encerrar()
        self.motor = None

        if not self.tocar(self.caminho, self.titulo, fila=self.fila,
                          indice=self.indice, retomar=ponto):
            return
        # Devolve as faixas escolhidas; reabrir volta ao padrao do arquivo.
        def restaurar():
            if not self.motor:
                return
            if audio > 0:
                self.motor.definir_audio(audio)
            if legenda is not None:
                self.motor.definir_legenda(legenda)
        QTimer.singleShot(1200, restaurar)
        self._avisar(f"Reiniciado em {_tempo(ponto)}.")

    def _pular(self, segundos: float) -> None:
        if self.motor:
            self.motor.ir_para(max(0, self.motor.posicao() + segundos))
            self._acordar()

    # ----------------------------------------------------- barra de tempo

    def _movendo_barra(self, valor: int) -> None:
        """Enquanto arrasta, so mostra o alvo — nao busca a cada pixel.

        Buscar a cada movimento faz o motor descartar e redecodificar o quadro
        dezenas de vezes por segundo, e e isso que trava a imagem. Uma busca
        so, quando o dedo solta.
        """
        if self.motor:
            total = self.motor.duracao()
            if total:
                self.rot_agora.setText(_tempo(total * valor / 10000.0))
        self._acordar()

    def _buscar_fracao(self, fracao: float) -> None:
        if self.motor:
            total = self.motor.duracao()
            if total:
                self.motor.ir_para(total * fracao)
        self._acordar()

    def _volume(self, valor: int) -> None:
        if self.motor:
            self.motor.definir_volume(valor)
        if self.b_mudo.isEnabled():
            self.b_mudo.setIcon(widgets.icone_player(
                "mudo" if valor == 0 else "som", self.paleta.forte,
                tema.px(22, self.escala)))

    def _alternar_mudo(self) -> None:
        if not self.motor:
            return
        mudo = self.volume.value() > 0
        self.motor.mudo(mudo)
        self.b_mudo.setIcon(widgets.icone_player(
            "mudo" if mudo else "som", self.paleta.forte, tema.px(22, self.escala)))
        self._acordar()

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

        if self.caminho:
            for srt in sorted(self.caminho.parent.glob("*.srt")):
                if self.motor.carregar_legenda(srt):
                    break
        self._faixas_montadas = True

    def _conferir_audio(self) -> None:
        """Se a faixa escolhida nao produziu som, tenta a proxima.

        Ha faixas — certos 5.1 — que o motor nao consegue abrir. Sem isto, o
        filme roda em silencio absoluto e nada na tela explica por que.
        """
        if self._audio_conferido or not self.motor:
            return
        self._audio_conferido = True
        if not getattr(self.motor, "audio_falhou", False):
            return

        atual = self.motor.audio_atual()
        outras = [f for f in self.motor.faixas_audio() if f.id > 0 and f.id != atual]
        if not outras:
            self._avisar("O áudio deste arquivo não pôde ser aberto.", 10)
            return
        self.motor.definir_audio(outras[0].id)
        indice = self.combo_audio.findData(outras[0].id)
        if indice >= 0:
            self.combo_audio.blockSignals(True)
            self.combo_audio.setCurrentIndex(indice)
            self.combo_audio.blockSignals(False)
        self._avisar(f"A faixa anterior não abriu; usando “{outras[0].nome}”.", 10)

    def _trocar_audio(self, indice: int) -> None:
        if self.motor and indice >= 0:
            self.motor.definir_audio(self.combo_audio.itemData(indice))
            self._audio_conferido = False
            QTimer.singleShot(1500, self._conferir_audio)

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
            QTimer.singleShot(1800, self._conferir_audio)
        if not self.barra_tempo.isSliderDown():
            if total:
                self.barra_tempo.setValue(int(10000 * agora / total))
            self.rot_agora.setText(_tempo(agora))
        self.rot_total.setText(_tempo(total))
        self.b_tocar.setIcon(widgets.icone_player(
            "pausar" if self.motor.tocando() else "tocar",
            self.paleta.forte, tema.px(22, self.escala)))
        if self.motor.terminou():
            # Numa serie, terminar um episodio e o momento de comecar o
            # seguinte — nao de voltar ao catalogo.
            if self.indice < len(self.fila) - 1:
                self.proximo()
            else:
                self.fechar()

    def _gravar_posicao(self) -> None:
        if self.motor and self.caminho and self.motor.duracao():
            guardar_posicao(self.con, self.caminho, self.motor.posicao(),
                            self.motor.duracao())

    # --------------------------------------------------- aparecer e sumir

    def _olhar_cursor(self) -> None:
        """Mostra os controles quando o mouse mexe; some quando ele para."""
        agora = QCursor.pos()
        if agora != self._cursor_antes:
            self._cursor_antes = agora
            self._acordar()
            return
        self._parado_ha += INTERVALO_CURSOR
        if (self._parado_ha >= ESPERA_PARA_SUMIR
                and not self.barra_tempo.isSliderDown()):
            self.topo.sumir()
            self.barra.sumir()
            if self._cheia:
                self.setCursor(Qt.BlankCursor)

    def _acordar(self) -> None:
        self._parado_ha = 0
        self.topo.aparecer()
        self.barra.aparecer()
        self.unsetCursor()

    def mouseMoveEvent(self, evento) -> None:            # noqa: N802
        self._acordar()

    def mouseDoubleClickEvent(self, evento) -> None:     # noqa: N802
        self.alternar_tela_cheia()

    # ---------------------------------------------------------- tela cheia

    def alternar_tela_cheia(self) -> None:
        self._cheia = not self._cheia
        janela = self.window()
        if hasattr(janela, "modo_cinema"):
            janela.modo_cinema(self._cheia)
        self.b_cheia.setIcon(widgets.icone_player(
            "restaurar" if self._cheia else "cheia", self.paleta.forte,
            tema.px(22, self.escala)))
        self._acordar()
        QTimer.singleShot(60, self._posicionar)

    def _escapar(self) -> None:
        """Esc sai da tela cheia; fora dela, fecha o player."""
        if self._cheia:
            self.alternar_tela_cheia()
        else:
            self.fechar()

    # ------------------------------------------------------------- fechar

    def fechar(self) -> None:
        self.relogio.stop()
        self.gravador.stop()
        self.vigia.stop()
        self.unsetCursor()
        if self.motor:
            self._gravar_posicao()
            self.motor.encerrar()
            self.motor = None
        if self._cheia:
            self.alternar_tela_cheia()
        self.pedir_voltar.emit()
