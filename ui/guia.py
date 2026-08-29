"""Guia guiado: um tour por cima da janela real, apontando cada parte.

Nao e uma sequencia de telas explicando o app em abstrato. O guia escurece a
janela, abre um holofote sobre o controle de verdade e explica aquele controle
ali, com o catalogo do usuario atras. Quem termina o guia ja sabe onde as coisas
ficam, porque olhou para elas.

Decisoes que valem registro:

  * o holofote desliza de um alvo para o outro em vez de saltar. O movimento e
    o que liga "isto que voce acabou de ver" a "isto aqui do lado";
  * nenhum passo prende ninguem: Esc sai, "Pular guia" sai, e o guia nunca
    aparece de novo sozinho depois de visto uma vez;
  * passo cujo alvo esta escondido (a faixa de organizar, por exemplo) cai para
    o modo centralizado em vez de apontar para o vazio.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF,
                            Qt, QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from . import tema

LARGURA_CARTAO = 384
MARGEM_HOLOFOTE = 10
FOLGA_CARTAO = 18


@dataclass
class Passo:
    """Um passo do guia. `alvo` devolve o que destacar — widget ou lista."""

    titulo: str
    paragrafos: list[str]
    alvo: Callable | None = None
    acao: tuple | None = None          # (rotulo, funcao(janela))
    estado: Callable | None = None     # texto vivo, calculado na hora


def _nav(janela, chave: str):
    return janela.botoes_nav.get(chave)


def _primeiras_capas(janela) -> QRect | None:
    """As primeiras capas da grade, nao a grade inteira.

    Apontar para a grade toda nao ensina nada: ela ocupa quase a janela, e o
    cartao de texto so teria onde ficar por cima do proprio alvo. Algumas capas
    dizem a mesma coisa e sobra espaco ao lado.
    """
    grade = janela.grade
    modelo = grade.model()
    if modelo is None or modelo.rowCount() == 0:
        return None
    primeiro = grade.visualRect(modelo.index(0, 0))
    if primeiro.isNull() or primeiro.width() <= 0:
        return None

    # Uma capa so. Juntar varias fazia um bloco largo demais: numa janela de
    # 980 px nao sobrava espaco lateral, e o cartao de texto acabava por cima do
    # que estava explicando. Uma capa diz a mesma coisa e deixa a tela respirar.
    uniao = primeiro
    canto = grade.viewport().mapTo(janela, QPoint(0, 0))
    return uniao.translated(canto)


def _abrir_pastas(janela) -> None:
    janela.abrir_config()
    try:
        janela.tela_config.abas.setCurrentIndex(0)     # aba Pastas
    except Exception:                                  # noqa: BLE001
        pass


def montar_passos(janela) -> list[Passo]:
    """Os passos, na ordem em que uma pessoa descobre o app.

    Quem ainda nao apontou as pastas ganha um passo a mais, logo no comeco:
    sem elas o app nao tem o que mostrar, e explicar a grade antes disso seria
    falar de uma tela vazia.
    """
    passos = [
        Passo(
            titulo="Bem-vindo ao Acervo",
            paragrafos=[
                "Seus arquivos .torrent viram um catálogo com capa, sinopse e "
                "nota — como um serviço de streaming, só que do que é seu.",
                "Este guia leva menos de um minuto e mostra cada parte da tela. "
                "Dá para sair a qualquer momento com Esc.",
            ],
        ),
        Passo(
            titulo="A biblioteca, por tipo",
            paragrafos=[
                "Filmes, séries e jogos ficam separados aqui. O número ao lado "
                "é quanto você tem de cada um.",
                "O tipo é deduzido do nome do arquivo. Quando ele errar, dá "
                "para corrigir na tela da obra.",
            ],
            alvo=lambda j: [_nav(j, "tipo:"), _nav(j, "tipo:filme"),
                            _nav(j, "tipo:serie"), _nav(j, "tipo:jogo")],
        ),
        Passo(
            titulo="Onde cada coisa está",
            paragrafos=[
                "“No disco” é o que já está baixado e pronto para assistir. "
                "“Só no índice” existe como .torrent, mas ainda não ocupa "
                "espaço nenhum.",
                "É essa separação que deixa o acervo grande sem encher o HD: "
                "você guarda o .torrent e baixa só quando for ver.",
            ],
            alvo=lambda j: [_nav(j, "estado:completo"), _nav(j, "estado:baixando"),
                            _nav(j, "estado:indice")],
        ),
        Passo(
            titulo="Achar e mudar a vista",
            paragrafos=[
                "A busca filtra enquanto você digita. Ao lado dá para mudar a "
                "ordem, e à direita alternar entre grade e lista.",
                "A lista mostra mais itens de uma vez; a grade mostra as capas "
                "maiores. O tamanho dos cartões muda em Configurações → "
                "Aparência.",
            ],
            alvo=lambda j: [j.campo_busca, j.combo_ordem, j.btn_grade, j.btn_lista],
        ),
        Passo(
            titulo="Trazer arquivos para dentro",
            paragrafos=[
                "“+ Adicionar .torrent” aceita vários de uma vez — e você também "
                "pode arrastar arquivos direto para a janela.",
                "“Reler” varre a pasta do índice atrás de novidades. “Conferir "
                "disco” compara o índice com o que existe de verdade no HD e "
                "acerta o que está onde.",
            ],
            alvo=lambda j: [j.btn_adicionar, j.btn_varrer, j.btn_conferir],
        ),
        Passo(
            titulo="As capas chegam sozinhas",
            paragrafos=[
                "O Acervo procura capa, sinopse e nota no TMDB, e capa de jogo "
                "no SteamGridDB, sem você pedir — em segundo plano, enquanto "
                "você usa o app.",
                "Quando não encontra, entra uma capa provisória com o título. "
                "Na tela da obra dá para procurar na mão ou escolher uma imagem "
                "do seu computador.",
            ],
            alvo=_primeiras_capas,
            estado=_estado_capas,
        ),
        Passo(
            titulo="Quanto espaço está em uso",
            paragrafos=[
                "Aqui embaixo ficam o total ocupado pela biblioteca e o tamanho "
                "do índice. A diferença entre os dois é o que o app economiza.",
                "Antes de liberar espaço, o Acervo confere se ainda há quem "
                "compartilhe o arquivo. Se não houver, ele se recusa a apagar: "
                "sem semeadores, apagar é definitivo.",
            ],
            alvo=lambda j: [j.rot_espaco, j.rot_espaco_sub, j.barra_espaco,
                            j.rot_indice],
        ),
        Passo(
            titulo="Organizar sem quebrar nada",
            paragrafos=[
                "O Acervo renomeia para o padrão que Jellyfin, Plex e Kodi leem "
                "sozinhos — mas só depois de mostrar exatamente o que vai mudar, "
                "arquivo por arquivo.",
                "Nada sai do lugar sem sua confirmação e nada é apagado. Quando "
                "o torrent está num cliente, a mudança é feita pela API dele, "
                "então o compartilhamento continua.",
            ],
            alvo=lambda j: (j.faixa_organizar if j.faixa_organizar.isVisible()
                            else j.btn_conferir),
        ),
        Passo(
            titulo="Para baixar, falta um cliente",
            paragrafos=[
                "O catálogo, as capas e a organização funcionam sozinhos. Só o "
                "botão “Baixar” precisa de um cliente de torrent para trabalhar.",
                "O caminho mais curto é o aria2: são ~2 MB, o próprio app baixa "
                "e cuida dele, e nada é instalado no sistema. Se você já usa "
                "qBittorrent ou uTorrent, basta ligar a interface web deles.",
            ],
            estado=_estado_motor,
            acao=("Abrir Configurações → Torrent", lambda j: _abrir_torrent(j)),
        ),
        Passo(
            titulo="É isso",
            paragrafos=[
                "Clique em qualquer capa para abrir a obra: lá ficam os "
                "episódios, os arquivos, o botão de reproduzir e a ficha "
                "completa.",
                "Para rever este guia, ele fica em Configurações → Aparência.",
            ],
        ),
    ]

    if not getattr(janela.cfg, "configurado", True):
        passos.insert(1, Passo(
            titulo="Primeiro, onde ficam seus arquivos",
            paragrafos=[
                "O Acervo precisa de duas pastas: a do índice, onde estão seus "
                "arquivos .torrent, e a da biblioteca, onde a mídia baixada "
                "fica no disco.",
                "Ele nunca apaga nada por conta própria — só lê essas pastas "
                "para montar o catálogo.",
            ],
            acao=("Escolher as pastas agora", _abrir_pastas),
        ))
    return passos


def _estado_capas(janela) -> str:
    try:
        faltam = janela._quantas_sem_capa()
    except Exception:                                  # noqa: BLE001
        return ""
    if not faltam:
        return "Todas as obras já têm capa."
    return f"{faltam} obra(s) ainda sem capa — a busca continua rodando."


def _estado_motor(janela) -> str:
    """Estado real do download nesta maquina, no momento em que o passo abre."""
    from core.motores import escolher

    try:
        motor, explicacao = escolher(janela.cfg)
    except Exception as e:                             # noqa: BLE001
        return str(e)
    return f"Conectado: {explicacao}" if motor is not None else explicacao


def _abrir_torrent(janela) -> None:
    janela.abrir_config()
    try:
        janela.tela_config.abas.setCurrentIndex(1)     # aba Torrent
    except Exception:                                  # noqa: BLE001
        pass


class Guia(QWidget):
    """A camada escura com o holofote, o cartao de texto e a navegacao."""

    fechado = Signal()

    def __init__(self, janela, pai=None):
        super().__init__(pai or janela)
        self.janela = janela
        self.paleta = janela.paleta
        self.escala = janela.escala
        self.passos = montar_passos(janela)
        self.indice = 0

        self._foco = QRectF()
        self._fase = 0.0
        self._acao_ligada = False

        self.setObjectName("guia")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Guia do Acervo")

        self._montar_cartao()

        # O holofote desliza entre alvos: e o movimento que liga um passo ao
        # seguinte. Saltar deixaria a pessoa procurando onde a luz foi parar.
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(340)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._mover_foco)

        self._pulso = QTimer(self)
        self._pulso.timeout.connect(self._bater)
        self._pulso.start(40)

        self.setGeometry(janela.rect())
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        self._aplicar_passo(animar=False)

    # ------------------------------------------------------------- montagem

    def _montar_cartao(self) -> None:
        p, e = self.paleta, self.escala
        self.cartao = QFrame(self)
        self.cartao.setObjectName("cartaoGuia")
        # Em janela pequena o cartao encolhe: um cartao fixo de 384 px nao cabe
        # ao lado de nada num espaco de 980 px, e acabaria centralizado sobre o
        # proprio alvo.
        disponivel = self.janela.width() or tema.px(LARGURA_CARTAO, e) * 3
        self.cartao.setFixedWidth(min(tema.px(LARGURA_CARTAO, e),
                                      max(tema.px(260, e), int(disponivel * 0.38))))
        self.cartao.setStyleSheet(
            f"QFrame#cartaoGuia {{ background: {p.lateral};"
            f" border: 1px solid {p.campo_bd}; border-radius: 10px; }}")

        col = QVBoxLayout(self.cartao)
        m = tema.px(20, e)
        col.setContentsMargins(m, m, m, tema.px(15, e))
        col.setSpacing(tema.px(9, e))

        self.rot_passo = QLabel()
        self.rot_passo.setStyleSheet(
            f"color: {p.azul}; font-size: {tema.px(10, e)}px;"
            f" font-family: {tema.fonte_mono()}; letter-spacing: 1px;")
        col.addWidget(self.rot_passo)

        self.rot_titulo = QLabel()
        self.rot_titulo.setWordWrap(True)
        self.rot_titulo.setStyleSheet(
            f"color: {p.forte}; font-size: {tema.px(19, e)}px; font-weight: 700;")
        col.addWidget(self.rot_titulo)

        self.rot_texto = QLabel()
        self.rot_texto.setWordWrap(True)
        self.rot_texto.setStyleSheet(
            f"color: {p.texto}; font-size: {tema.px(12.5, e)}px;")
        col.addWidget(self.rot_texto)

        self.rot_estado = QLabel()
        self.rot_estado.setWordWrap(True)
        self.rot_estado.setStyleSheet(
            f"color: {p.tenue}; font-size: {tema.px(11, e)}px;"
            f" background: {p.elevado}; border-radius: 5px;"
            f" padding: {tema.px(8, e)}px;")
        self.rot_estado.hide()
        col.addWidget(self.rot_estado)

        self.btn_acao = QPushButton()
        self.btn_acao.setObjectName("botaoGrande")
        self.btn_acao.hide()
        col.addWidget(self.btn_acao)

        col.addSpacing(tema.px(4, e))

        rodape = QHBoxLayout()
        rodape.setSpacing(tema.px(7, e))
        self.pontos = QWidget()
        self.pontos.setFixedHeight(tema.px(12, e))
        self.pontos.paintEvent = self._pintar_pontos       # desenho proprio
        rodape.addWidget(self.pontos, 1)

        self.btn_pular = QPushButton("Pular guia")
        self.btn_pular.setFlat(True)
        self.btn_pular.setStyleSheet(
            f"QPushButton {{ color: {p.tenue}; border: none;"
            f" padding: {tema.px(5, e)}px {tema.px(8, e)}px; }}"
            f"QPushButton:hover {{ color: {p.texto}; }}")
        self.btn_pular.setAccessibleName("Pular o guia e usar o app")
        self.btn_pular.clicked.connect(self.fechar)
        rodape.addWidget(self.btn_pular)

        self.btn_voltar = QPushButton("Voltar")
        self.btn_voltar.setAccessibleName("Passo anterior do guia")
        self.btn_voltar.clicked.connect(self.anterior)
        rodape.addWidget(self.btn_voltar)

        self.btn_proximo = QPushButton("Próximo")
        self.btn_proximo.setObjectName("botaoGrande")
        self.btn_proximo.setProperty("destaque", "true")
        self.btn_proximo.setAccessibleName("Próximo passo do guia")
        self.btn_proximo.clicked.connect(self.proximo)
        rodape.addWidget(self.btn_proximo)
        col.addLayout(rodape)

        self.opacidade = QGraphicsOpacityEffect(self.cartao)
        self.cartao.setGraphicsEffect(self.opacidade)
        self.surgir = QPropertyAnimation(self.opacidade, b"opacity", self)
        self.surgir.setDuration(260)
        self.surgir.setEasingCurve(QEasingCurve.OutCubic)

    # ---------------------------------------------------------------- passos

    def _passo(self) -> Passo:
        return self.passos[self.indice]

    def _aplicar_passo(self, animar: bool = True) -> None:
        # Parar aqui, e nao so no ramo que anima: uma animacao ainda em curso
        # continuava escrevendo em `_foco` depois da troca de passo, e o
        # holofote do passo anterior ficava aceso sobre um passo sem alvo.
        self._anim.stop()

        passo = self._passo()
        total = len(self.passos)

        self.rot_passo.setText(f"PASSO {self.indice + 1} DE {total}")
        self.rot_titulo.setText(passo.titulo)
        self.rot_texto.setText("\n\n".join(passo.paragrafos))

        texto_estado = passo.estado(self.janela) if passo.estado else ""
        self.rot_estado.setText(texto_estado)
        self.rot_estado.setVisible(bool(texto_estado))

        if passo.acao:
            rotulo, funcao = passo.acao
            self.btn_acao.setText(rotulo)
            if self._acao_ligada:
                self.btn_acao.clicked.disconnect()
            self._acao_ligada = True
            self.btn_acao.clicked.connect(
                lambda _=False, f=funcao: self._agir(f))
            self.btn_acao.show()
        else:
            self.btn_acao.hide()

        self.btn_voltar.setEnabled(self.indice > 0)
        ultimo = self.indice == total - 1
        self.btn_proximo.setText("Concluir" if ultimo else "Próximo")
        self.btn_pular.setVisible(not ultimo)

        # O leitor de tela precisa do passo inteiro num lugar so.
        self.cartao.setAccessibleName(
            f"{passo.titulo}. Passo {self.indice + 1} de {total}")
        self.cartao.setAccessibleDescription(
            " ".join(passo.paragrafos) + (" " + texto_estado if texto_estado else ""))

        destino = self._retangulo_alvo(passo)
        if animar and not self._foco.isNull() and not destino.isNull():
            self._anim.setStartValue(self._foco)
            self._anim.setEndValue(destino)
            self._anim.start()
        else:
            self._foco = destino

        self._posicionar_cartao()
        self.pontos.update()
        self.update()

        self.surgir.stop()
        self.surgir.setStartValue(0.0 if animar else 1.0)
        self.surgir.setEndValue(1.0)
        self.surgir.start()

    def _agir(self, funcao) -> None:
        self.fechar()
        funcao(self.janela)

    def _retangulo_alvo(self, passo: Passo) -> QRectF:
        if not passo.alvo:
            return QRectF()
        try:
            alvos = passo.alvo(self.janela)
        except Exception:                              # noqa: BLE001
            return QRectF()
        if alvos is None:
            return QRectF()
        if isinstance(alvos, (QRect, QRectF)):        # ja veio pronto
            m = MARGEM_HOLOFOTE
            return QRectF(alvos).adjusted(-m, -m, m, m)
        if not isinstance(alvos, (list, tuple)):
            alvos = [alvos]

        uniao = QRect()
        for w in alvos:
            if w is None or not w.isVisible():
                continue
            r = QRect(w.mapTo(self.janela, QPoint(0, 0)), w.size())
            uniao = r if uniao.isNull() else uniao.united(r)
        if uniao.isNull():
            return QRectF()
        m = MARGEM_HOLOFOTE
        return QRectF(uniao.adjusted(-m, -m, m, m))

    def proximo(self) -> None:
        if self.indice >= len(self.passos) - 1:
            self.fechar()
            return
        self.indice += 1
        self._aplicar_passo()

    def anterior(self) -> None:
        if self.indice == 0:
            return
        self.indice -= 1
        self._aplicar_passo()

    def fechar(self) -> None:
        self._pulso.stop()
        self._anim.stop()
        self.hide()
        self.fechado.emit()
        self.deleteLater()

    # -------------------------------------------------------------- pintura

    def _bater(self) -> None:
        self._fase = (self._fase + 0.045) % 1.0
        if not self._foco.isNull():
            self.update()

    def _mover_foco(self, valor) -> None:
        self._foco = QRectF(valor)
        self._posicionar_cartao()
        self.update()

    def paintEvent(self, evento) -> None:              # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        fora = QPainterPath()
        fora.addRect(QRectF(self.rect()))
        if not self._foco.isNull():
            buraco = QPainterPath()
            buraco.addRoundedRect(self._foco, 9, 9)
            fora = fora.subtracted(buraco)
        p.fillPath(fora, QColor(0, 0, 0, 194))

        if self._foco.isNull():
            return

        # Anel que respira: chama o olho para o alvo sem piscar na cara.
        pulso = (math.sin(self._fase * 2 * math.pi) + 1) / 2
        cor = QColor(self.paleta.azul)
        cor.setAlpha(int(120 + 110 * pulso))
        p.setPen(QPen(cor, 2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(self._foco, 9, 9)

        halo = QColor(self.paleta.azul)
        halo.setAlpha(int(26 + 34 * pulso))
        p.setPen(QPen(halo, 8))
        p.drawRoundedRect(self._foco.adjusted(-5, -5, 5, 5), 13, 13)

    def _pintar_pontos(self, evento) -> None:
        p = QPainter(self.pontos)
        p.setRenderHint(QPainter.Antialiasing)
        r = tema.px(5, self.escala)
        gap = tema.px(10, self.escala)
        meio = self.pontos.height() / 2
        for i in range(len(self.passos)):
            p.setBrush(QColor(self.paleta.azul if i <= self.indice
                              else self.paleta.campo_bd))
            p.setPen(Qt.NoPen)
            d = r if i == self.indice else max(3, r - 2)
            p.drawEllipse(QRectF(i * gap, meio - d / 2, d, d))

    # ------------------------------------------------------------ colocacao

    def _medir_textos(self) -> None:
        """Da altura aos rotulos que quebram linha, antes de medir o cartao.

        Um QLabel com wordWrap so sabe a propria altura depois de conhecer a
        largura. Sem esta volta, `adjustSize` media o cartao com a altura de
        uma linha so e o segundo paragrafo ficava cortado pela borda.
        """
        margens = self.cartao.layout().contentsMargins()
        util = self.cartao.width() - margens.left() - margens.right()
        for rot in (self.rot_titulo, self.rot_texto, self.rot_estado):
            if rot.isVisible():
                rot.setMinimumHeight(rot.heightForWidth(util))
            else:
                rot.setMinimumHeight(0)

    def _posicionar_cartao(self) -> None:
        self._medir_textos()
        self.cartao.adjustSize()
        largura, altura = self.cartao.width(), self.cartao.height()
        folga = FOLGA_CARTAO
        area = self.rect()

        if self._foco.isNull():
            self.cartao.move(int((area.width() - largura) / 2),
                             int((area.height() - altura) / 2))
            return

        f = self._foco
        # Prefere o lado com espaco; o cartao nunca cobre o proprio alvo.
        if f.right() + folga + largura <= area.width():
            x, ao_lado = int(f.right() + folga), True
        elif f.left() - folga - largura >= 0:
            x, ao_lado = int(f.left() - folga - largura), True
        else:
            x = int(max(0, (area.width() - largura) / 2))
            ao_lado = False

        if ao_lado:
            y = int(f.center().y() - altura / 2)
        elif f.bottom() + folga + altura <= area.height():
            y = int(f.bottom() + folga)
        else:
            y = int(f.top() - folga - altura)

        y = max(folga, min(y, max(folga, area.height() - altura - folga)))
        self.cartao.move(x, y)

    def resizeEvent(self, evento) -> None:             # noqa: N802
        super().resizeEvent(evento)
        self._foco = self._retangulo_alvo(self._passo())
        self._posicionar_cartao()

    # ------------------------------------------------------------- teclado

    def keyPressEvent(self, evento) -> None:           # noqa: N802
        tecla = evento.key()
        if tecla == Qt.Key_Escape:
            self.fechar()
        elif tecla in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.proximo()
        elif tecla in (Qt.Key_Left, Qt.Key_Backspace):
            self.anterior()
        else:
            super().keyPressEvent(evento)
