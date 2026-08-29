"""Tela de detalhes da obra.

Segue as referencias: faixa com imagem de fundo, titulo grande, linha de status,
sinopse e uma acao principal que muda conforme o caso —

    filme/serie no disco .... ▶ Reproduzir
    jogo no disco ........... ▶ Jogar
    baixando ................ barra de progresso + Pausar
    pausado ................. Retomar
    so no indice ............ ↓ Baixar

Abaixo, duas colunas: a esquerda vira **Episódios** em serie e **Arquivos** em
filme e jogo; a direita e a ficha tecnica com Abrir pasta, Remover torrent e o
hash. Tudo e pagina da janela, nunca janela nova por cima.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from core import capas, consultas, db, downloads, espaco, health, metadata

from . import tema, widgets
from .tarefas import vivo
from .widgets import Etiqueta, Retorno, formatar_bytes

ALTURA_BANNER = 340
ROTULO_TIPO = {"filme": "Filme", "serie": "Série", "jogo": "Jogo"}
_EXT_VIDEO = {".mkv", ".mp4", ".avi", ".rmvb", ".mov", ".m4v", ".ts", ".wmv"}


def _rgb(cor_hex: str) -> tuple[int, int, int]:
    c = QColor(cor_hex)
    return c.red(), c.green(), c.blue()


class RotuloElidido(QLabel):
    """Texto de uma linha que encolhe em vez de empurrar a largura da janela.

    Um QLabel comum pede como largura minima o texto inteiro. Com o nome cru do
    release — "A.Casa.do.Dragao.S03E06.WEB-DL.2160p.HMAX.DV.HDR.x265.DUAL.5.1-
    STARCKFILMES.mkv" — isso alargava a coluna alem da janela, e como a pagina
    tem a barra horizontal desligada, a coluna Detalhes simplesmente sumia pela
    direita. Aqui o texto e cortado com reticencias e a largura minima e 1.
    """

    def __init__(self, texto: str = "", pai=None):
        super().__init__(texto, pai)
        self._inteiro = texto
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setToolTip(texto)

    def setText(self, texto: str) -> None:      # noqa: N802
        self._inteiro = texto
        self.setToolTip(texto)
        super().setText(texto)
        self._encurtar()

    def resizeEvent(self, evento) -> None:      # noqa: N802
        super().resizeEvent(evento)
        self._encurtar()

    def _encurtar(self) -> None:
        largura = max(1, self.width())
        super().setText(self.fontMetrics().elidedText(
            self._inteiro, Qt.ElideMiddle, largura))


class Banner(QWidget):
    """Imagem larga com gradiente, para o texto ficar legivel por cima."""

    def __init__(self, paleta: tema.Paleta, altura: int, pai=None):
        super().__init__(pai)
        self.paleta = paleta
        self.imagem: QPixmap | None = None
        self.setFixedHeight(altura)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def definir(self, fundo: Path | None, poster: Path | None) -> None:
        """Usa a imagem larga; sem ela, o proprio poster ampliado."""
        self.imagem = None
        for origem in (fundo, poster):
            if origem and origem.is_file():
                pm = QPixmap(str(origem))
                if not pm.isNull():
                    self.imagem = pm
                    break
        self.update()

    def paintEvent(self, _e):             # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        area = self.rect()
        pal = self.paleta
        p.fillRect(area, QColor(pal.fundo))

        if self.imagem is not None and area.width() > 0:
            escalada = self.imagem.scaled(area.size(), Qt.KeepAspectRatioByExpanding,
                                          Qt.SmoothTransformation)
            x = max(0, (escalada.width() - area.width()) // 2)
            y = max(0, (escalada.height() - area.height()) // 3)
            p.drawPixmap(area, escalada, QRect(x, y, area.width(), area.height()))

        horizontal = QLinearGradient(0, 0, area.width(), 0)
        horizontal.setColorAt(0.0, QColor(pal.fundo))
        horizontal.setColorAt(0.40, QColor(*_rgb(pal.fundo), 225))
        horizontal.setColorAt(1.0, QColor(*_rgb(pal.fundo), 40))
        p.fillRect(area, horizontal)

        vertical = QLinearGradient(0, area.height() * 0.42, 0, area.height())
        vertical.setColorAt(0.0, QColor(*_rgb(pal.fundo), 0))
        vertical.setColorAt(1.0, QColor(pal.fundo))
        p.fillRect(area, vertical)
        p.end()


class TelaItem(QScrollArea):
    mudou = Signal()
    pedir_voltar = Signal()

    def __init__(self, cfg, con: sqlite3.Connection, executor,
                 paleta: tema.Paleta, escala: float, pai=None):
        super().__init__(pai)
        self.cfg = cfg
        self.con = con
        self.executor = executor
        self.paleta = paleta
        self.escala = escala
        self.item_id: int | None = None
        self.candidatos: list[dict] = []
        self.ativo: dict = {}                 # dados do torrent no cliente
        # Cada remontagem invalida os widgets antigos; os callbacks em voo
        # comparam com este numero antes de tocar em qualquer coisa.
        self.geracao = 0

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.NoFrame)

        self.relogio = QTimer(self)
        self.relogio.setInterval(2000)
        self.relogio.timeout.connect(self._atualizar_progresso)

    def aplicar_tema(self, paleta: tema.Paleta, escala: float) -> None:
        self.paleta, self.escala = paleta, escala
        if self.item_id is not None:
            self.mostrar(self.item_id)

    # ------------------------------------------------------------ montagem

    def mostrar(self, item_id: int) -> None:
        self.item_id = item_id
        self.geracao += 1
        dados = consultas.detalhe(self.con, item_id)
        if not dados:
            self.pedir_voltar.emit()
            return
        self.dados = dados
        item = dados["item"]
        self.titulo = item["titulo_corrigido"] or item["titulo"]
        self.release_principal = self._principal(dados["releases"])

        corpo = QWidget()
        col = QVBoxLayout(corpo)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._faixa(item, dados["releases"]))

        miolo = QWidget()
        ml = QVBoxLayout(miolo)
        m = tema.px(34, self.escala)
        ml.setContentsMargins(m, tema.px(10, self.escala), m, m)
        ml.setSpacing(tema.px(26, self.escala))
        ml.addLayout(self._colunas(item, dados["releases"]))
        if len(dados["releases"]) > 1:
            ml.addWidget(self._secao_releases(dados["releases"]))
        ml.addWidget(self._secao_capa(item))
        ml.addWidget(self._secao_ajustes(item))
        ml.addStretch(1)
        col.addWidget(miolo)

        self.setWidget(corpo)
        self.verticalScrollBar().setValue(0)
        self._buscar_estado_ativo()

    @staticmethod
    def _principal(releases: list[dict]) -> dict | None:
        """O release que a acao principal usa: o que esta no disco, ou o maior."""
        if not releases:
            return None
        for alvo in ("completo", "parcial"):
            no_estado = [t for t in releases if t["estado"] == alvo]
            if no_estado:
                return max(no_estado, key=lambda t: t["bytes_presentes"] or 0)
        return max(releases, key=lambda t: t["tamanho_total"])

    def _faixa(self, item: dict, releases: list[dict]) -> QWidget:
        altura = tema.px(ALTURA_BANNER, self.escala)
        caixa = QWidget()
        caixa.setFixedHeight(altura)

        self.banner = Banner(self.paleta, altura, caixa)
        self.banner.definir(
            self.cfg.posters / item["backdrop"] if item["backdrop"] else None,
            self.cfg.posters / item["poster"] if item["poster"] else None)

        sobre = QWidget(caixa)
        sobre.setAttribute(Qt.WA_TranslucentBackground)
        col = QVBoxLayout(sobre)
        m = tema.px(34, self.escala)
        col.setContentsMargins(m, tema.px(26, self.escala), m, tema.px(20, self.escala))
        col.setSpacing(tema.px(9, self.escala))
        col.addStretch(1)

        generos = [g.strip() for g in (item["generos"] or "").split(",") if g.strip()]
        if generos:
            linha = QHBoxLayout()
            linha.setSpacing(6)
            for g in generos[:4]:
                linha.addWidget(Etiqueta(g))
            linha.addStretch(1)
            col.addLayout(linha)

        h1 = QLabel(self.titulo)
        h1.setObjectName("tituloGrande")
        h1.setWordWrap(True)
        h1.setMaximumWidth(tema.px(640, self.escala))
        col.addWidget(h1)
        col.addLayout(self._linha_status(item, releases))

        if item["sinopse"]:
            completa = " ".join(item["sinopse"].split())
            resumida = _resumir(completa)
            s = QLabel(resumida)
            s.setObjectName("sinopse")
            s.setWordWrap(True)
            s.setMaximumWidth(tema.px(540, self.escala))
            s.setMaximumHeight(tema.px(66, self.escala))
            s.setToolTip(completa)
            col.addWidget(s)

            # A sinopse era cortada e so aparecia inteira como dica de mouse —
            # ou seja, nao aparecia. Aqui ela abre no lugar, e a faixa cresce
            # junto para nao esconder o que foi revelado.
            if resumida != completa:
                mais = QPushButton("mostrar mais")
                mais.setFlat(True)
                mais.setCursor(Qt.PointingHandCursor)
                mais.setAccessibleName("Mostrar a descrição completa")
                mais.setStyleSheet(
                    f"QPushButton {{ color: {self.paleta.azul}; border: none;"
                    f" padding: 0; text-align: left;"
                    f" font-size: {tema.px(11.5, self.escala)}px; }}"
                    f"QPushButton:hover {{ text-decoration: underline; }}")
                col.addWidget(mais, 0, Qt.AlignLeft)

                def abrir():
                    s.setMaximumHeight(16777215)
                    s.setText(completa)
                    mais.hide()
                    self._crescer_faixa(caixa, sobre)

                mais.clicked.connect(abrir)

        col.addSpacing(tema.px(6, self.escala))
        col.addWidget(self._area_acao())

        # O banner e a camada de texto ocupam a faixa inteira, sempre. A altura
        # vem da caixa, nao da constante: quando a sinopse e aberta a faixa
        # cresce, e usar o valor original faria tudo voltar ao tamanho antigo no
        # primeiro redimensionamento da janela.
        def ajustar():
            self.banner.setGeometry(0, 0, caixa.width(), caixa.height())
            sobre.setGeometry(0, 0, caixa.width(), caixa.height())
        caixa.resizeEvent = lambda e: ajustar()
        ajustar()
        return caixa

    def _crescer_faixa(self, caixa: QWidget, sobre: QWidget) -> None:
        """Aumenta a faixa ate a sinopse aberta caber inteira.

        A altura vem do proprio layout, nao de uma estimativa: a camada de texto
        tem margens, espacamentos e outros widgets, e chutar a sobra fazia o
        texto ser cortado em cima e embaixo — que era justamente o defeito que
        esta funcao existe para resolver.
        """
        layout = sobre.layout()
        if layout is None:
            return
        layout.invalidate()
        layout.activate()
        preciso = layout.sizeHint().height()
        if preciso <= caixa.height():
            return
        caixa.setFixedHeight(preciso)
        self.banner.setFixedHeight(preciso)
        self.banner.setGeometry(0, 0, caixa.width(), preciso)
        sobre.setGeometry(0, 0, caixa.width(), preciso)
        caixa.updateGeometry()

    def _linha_status(self, item: dict, releases: list[dict]) -> QHBoxLayout:
        estado = "indice"
        for alvo in ("completo", "parcial"):
            if any(t["estado"] == alvo for t in releases):
                estado = alvo
                break
        chave, rotulo = tema.CORES_ESTADO.get(estado, ("tenue", ""))

        linha = QHBoxLayout()
        linha.setSpacing(tema.px(13, self.escala))
        self.rot_estado = QLabel(f"●  {rotulo}")
        self.rot_estado.setObjectName("statusObra")
        self.rot_estado.setStyleSheet(f"color: {getattr(self.paleta, chave)};")
        linha.addWidget(self.rot_estado)

        partes = []
        if item["ano"]:
            partes.append(str(item["ano"]))
        temporadas = [t["temporada"] for t in releases if t["temporada"] is not None]
        if temporadas:
            n = max(temporadas)
            partes.append(f"{n} temporada" + ("s" if n > 1 else ""))
        qualidades = sorted({t["qualidade"] for t in releases if t["qualidade"]})
        if qualidades:
            partes.append(qualidades[-1])
        idiomas = sorted({t["idioma"] for t in releases if t["idioma"]})
        if idiomas:
            partes.append(idiomas[0].capitalize())
        if item["nota"]:
            partes.append(f"nota {float(item['nota']):.1f}")
        for texto in partes:
            r = QLabel(texto)
            r.setObjectName("subPainel")
            linha.addWidget(r)
        linha.addStretch(1)
        return linha

    # ---------------------------------------------------------- acao principal

    def _area_acao(self) -> QWidget:
        self.caixa_acao = QWidget()
        self.caixa_acao.setAttribute(Qt.WA_TranslucentBackground)
        self.layout_acao = QVBoxLayout(self.caixa_acao)
        self.layout_acao.setContentsMargins(0, 0, 0, 0)
        self.layout_acao.setSpacing(tema.px(6, self.escala))
        self.retorno_acao = Retorno()
        self._montar_acao()
        return self.caixa_acao

    def _limpar_acao(self) -> None:
        while self.layout_acao.count():
            item = self.layout_acao.takeAt(0)
            if item.widget() and item.widget() is not self.retorno_acao:
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    x = item.layout().takeAt(0)
                    if x.widget():
                        x.widget().deleteLater()

    def _montar_acao(self) -> None:
        """Redesenha a acao principal conforme o estado atual do torrent."""
        self._limpar_acao()
        t = self.release_principal
        if not t:
            return

        baixando = bool(self.ativo) and not self.ativo.get("pausado") \
            and self.ativo.get("progresso", 1) < 1
        pausado = bool(self.ativo) and self.ativo.get("pausado") \
            and self.ativo.get("progresso", 1) < 1

        if baixando or pausado:
            self.layout_acao.addLayout(self._progresso_grande(pausado))
        elif t["estado"] == "completo":
            self.layout_acao.addLayout(self._acoes_pronto(t))
        else:
            self.layout_acao.addLayout(self._acao_baixar(t))
        self.layout_acao.addWidget(self.retorno_acao)

    def _progresso_grande(self, pausado: bool) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(tema.px(5, self.escala))
        pct = self.ativo.get("progresso", 0)

        topo = QHBoxLayout()
        topo.setSpacing(tema.px(14, self.escala))
        esquerda = QVBoxLayout()
        esquerda.setSpacing(tema.px(5, self.escala))

        linha = QHBoxLayout()
        rot = QLabel(f"{round(pct * 100)}% baixado")
        rot.setObjectName("subPainel")
        linha.addWidget(rot)
        linha.addStretch(1)
        if not pausado and self.ativo.get("velocidade"):
            vel = QLabel(f"{formatar_bytes(self.ativo['velocidade'])}/s")
            vel.setStyleSheet(f"color: {self.paleta.azul};"
                              f"font-family: {tema.fonte_mono()};"
                              f"font-size: {tema.px(12, self.escala)}px;")
            linha.addWidget(vel)
        esquerda.addLayout(linha)

        barra = QProgressBar()
        barra.setRange(0, 100)
        barra.setValue(round(pct * 100))
        barra.setTextVisible(False)
        barra.setFixedHeight(tema.px(5, self.escala))
        barra.setFixedWidth(tema.px(320, self.escala))
        barra.setAccessibleName(f"{round(pct * 100)} por cento baixado")
        esquerda.addWidget(barra)

        eta = self.ativo.get("eta") or 0
        detalhe = []
        if not pausado and 0 < eta < 8640000:
            detalhe.append(f"ETA {_tempo(eta)}")
        detalhe.append(f"{formatar_bytes(self.ativo.get('baixado'))}"
                       f" / {formatar_bytes(self.ativo.get('tamanho'))}")
        sub = QLabel(" · ".join(detalhe))
        sub.setObjectName("ajuda")
        esquerda.addWidget(sub)
        topo.addLayout(esquerda)

        b = QPushButton("Retomar" if pausado else "Pausar")
        b.setObjectName("botaoGrande")
        if pausado:
            b.setProperty("destaque", "true")
        b.clicked.connect(self._retomar if pausado else self._pausar)
        topo.addWidget(b, 0, Qt.AlignBottom)
        topo.addStretch(1)
        col.addLayout(topo)
        return col

    def _acoes_pronto(self, t: dict) -> QHBoxLayout:
        linha = QHBoxLayout()
        linha.setSpacing(8)
        jogo = self.dados["item"]["tipo"] == "jogo"

        b = QPushButton("▶   Jogar" if jogo else "▶   Reproduzir")
        b.setObjectName("botaoGrande")
        b.setProperty("destaque", "true")
        b.setAccessibleName("Abrir no programa padrão do sistema")
        b.clicked.connect(lambda: self._reproduzir(t, jogo))
        linha.addWidget(b)

        b2 = QPushButton("Abrir pasta")
        b2.setObjectName("botaoGrande")
        b2.clicked.connect(lambda: self._abrir_pasta(t))
        linha.addWidget(b2)
        linha.addStretch(1)
        return linha

    def _acao_baixar(self, t: dict) -> QHBoxLayout:
        linha = QHBoxLayout()
        linha.setSpacing(8)
        b = QPushButton("↓   Baixar")
        b.setObjectName("botaoGrande")
        b.setProperty("destaque", "true")
        b.setAccessibleName(f"Baixar {t['nome']}")
        b.clicked.connect(lambda: self._baixar(t, b, self.retorno_acao))
        linha.addWidget(b)
        linha.addStretch(1)
        return linha

    # ---------------------------------------------------- colunas do miolo

    def _colunas(self, item: dict, releases: list[dict]) -> QHBoxLayout:
        linha = QHBoxLayout()
        linha.setSpacing(tema.px(26, self.escala))
        linha.addLayout(self._coluna_conteudo(item, releases), 3)
        linha.addLayout(self._coluna_ficha(releases), 2)
        return linha

    def _coluna_conteudo(self, item: dict, releases: list[dict]) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(tema.px(8, self.escala))
        serie = item["tipo"] == "serie"
        t = QLabel("Episódios" if serie else "Arquivos")
        t.setObjectName("tituloSecaoGrande")
        col.addWidget(t)

        if serie:
            linhas = self._episodios(releases)
            if not linhas:
                col.addWidget(widgets.ajuda("Nenhum episódio identificado."))
            for e in linhas[:60]:
                col.addWidget(self._linha_episodio(e))
        else:
            arquivos = [(a, r) for r in releases for a in r["arquivos"]
                        if a["tipo"] in ("midia", "arquivo_jogo", "legenda")]
            if not arquivos:
                col.addWidget(widgets.ajuda("Nenhum arquivo de mídia neste torrent."))
            for a, r in sorted(arquivos, key=lambda x: -x[0]["tamanho"])[:20]:
                col.addWidget(self._linha_arquivo(a, r))
        col.addStretch(1)
        return col

    def _episodios(self, releases: list[dict]) -> list[dict]:
        """Um item por episodio, juntando o que vem de varios .torrent."""
        saida = []
        for r in releases:
            numeros = [int(x) for x in (r["episodios"] or "").split(",") if x.strip()]
            midias = [a for a in r["arquivos"] if a["tipo"] == "midia"]
            midias.sort(key=lambda a: a["caminho"])

            if numeros and len(numeros) == len(midias):
                for n, a in zip(numeros, midias):
                    saida.append({"temporada": r["temporada"], "episodio": n,
                                  "nome": a["caminho"].rsplit("/", 1)[-1],
                                  "tamanho": a["tamanho"], "release": r})
            elif numeros:
                for n in numeros:
                    saida.append({"temporada": r["temporada"], "episodio": n,
                                  "nome": r["nome"],
                                  "tamanho": r["tamanho_total"] // max(1, len(numeros)),
                                  "release": r})
            else:
                import re
                for a in midias:
                    nome = a["caminho"].rsplit("/", 1)[-1]
                    m = re.search(r"[Ss](\d{1,2})[Ee](\d{1,3})", nome)
                    saida.append({
                        "temporada": int(m.group(1)) if m else r["temporada"],
                        "episodio": int(m.group(2)) if m else None,
                        "nome": nome, "tamanho": a["tamanho"], "release": r})
        saida.sort(key=lambda e: ((e["temporada"] or 0), (e["episodio"] or 0)))
        return saida

    def _linha_episodio(self, e: dict) -> QFrame:
        caixa = QFrame()
        caixa.setObjectName("linhaArquivo")
        lay = QHBoxLayout(caixa)
        lay.setContentsMargins(tema.px(10, self.escala), tema.px(8, self.escala),
                               tema.px(13, self.escala), tema.px(8, self.escala))
        lay.setSpacing(tema.px(12, self.escala))

        no_disco = e["release"]["estado"] == "completo"
        b = QPushButton("▶" if no_disco else "○")
        b.setObjectName("botaoEpisodio")
        b.setFixedSize(tema.px(28, self.escala), tema.px(28, self.escala))
        b.setEnabled(no_disco)
        rotulo = (f"T{e['temporada']:02d} E{e['episodio']:02d}"
                  if e["temporada"] is not None and e["episodio"] is not None
                  else e["nome"])
        b.setAccessibleName(f"Reproduzir {rotulo}" if no_disco
                            else f"{rotulo} — ainda não baixado")
        if no_disco:
            b.clicked.connect(lambda: self._reproduzir_arquivo(e))
        lay.addWidget(b)

        titulo = rotulo
        if e["temporada"] is not None and e["episodio"] is not None:
            titulo = f"T{e['temporada']:02d} E{e['episodio']:02d} — {_limpo(e['nome'])}"

        # Duas linhas: o nome legivel manda, o nome do arquivo fica de
        # legenda. O nome cru diz de qual arquivo se trata, mas nao e o
        # que a pessoa procura quando bate o olho na lista.
        texto = QVBoxLayout()
        texto.setContentsMargins(0, 0, 0, 0)
        texto.setSpacing(tema.px(1, self.escala))
        nome = QLabel(titulo)
        nome.setObjectName("nomeEpisodio" if no_disco else "nomeEpisodioPendente")
        nome.setToolTip(e["nome"])
        texto.addWidget(nome)
        bruto = RotuloElidido(Path(e["nome"]).name)
        bruto.setObjectName("nomeArquivoBruto")
        texto.addWidget(bruto)
        lay.addLayout(texto, 1)

        tam = QLabel(formatar_bytes(e["tamanho"]))
        tam.setObjectName("metaCartao")
        lay.addWidget(tam)

        marca = QLabel("✓" if no_disco else "")
        marca.setStyleSheet(f"color: {self.paleta.verde}; font-size: "
                            f"{tema.px(13, self.escala)}px;")
        marca.setFixedWidth(tema.px(16, self.escala))
        lay.addWidget(marca)
        return caixa

    def _linha_arquivo(self, a: dict, r: dict) -> QFrame:
        caixa = QFrame()
        caixa.setObjectName("linhaArquivo")
        col = QVBoxLayout(caixa)
        col.setContentsMargins(tema.px(13, self.escala), tema.px(9, self.escala),
                               tema.px(13, self.escala), tema.px(9, self.escala))
        col.setSpacing(tema.px(5, self.escala))

        lay = QHBoxLayout()
        texto = QVBoxLayout()
        texto.setContentsMargins(0, 0, 0, 0)
        texto.setSpacing(tema.px(1, self.escala))
        nome = RotuloElidido(_limpo(a["caminho"]))
        nome.setObjectName("nomeEpisodio")
        texto.addWidget(nome)
        bruto = RotuloElidido(a["caminho"])
        bruto.setObjectName("nomeArquivoBruto")
        texto.addWidget(bruto)
        tam = QLabel(formatar_bytes(a["tamanho"]))
        tam.setObjectName("metaCartao")
        lay.addLayout(texto, 1)
        lay.addWidget(tam, 0, Qt.AlignTop)
        col.addLayout(lay)

        # Parcial: a barra fininha embaixo do nome, como na referencia.
        if r["estado"] == "parcial" and r["tamanho_total"]:
            barra = QProgressBar()
            barra.setRange(0, 100)
            barra.setValue(round(100 * r["bytes_presentes"] / r["tamanho_total"]))
            barra.setTextVisible(False)
            barra.setFixedHeight(tema.px(2, self.escala))
            col.addWidget(barra)
        return caixa

    def _coluna_ficha(self, releases: list[dict]) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(tema.px(7, self.escala))
        t = QLabel("Detalhes")
        t.setObjectName("tituloSecaoGrande")
        col.addWidget(t)

        total = sum(r["tamanho_total"] for r in releases)
        baixado = sum(r["bytes_presentes"] or 0 for r in releases)
        seeds = [r["seeders"] for r in releases if r["seeders"] is not None]
        t_principal = self.release_principal or {}

        self.linhas_ficha: dict[str, QLabel] = {}
        campos = [
            ("TAMANHO", formatar_bytes(total)),
            ("BAIXADO", formatar_bytes(baixado)),
            ("SEEDS", str(max(seeds)) if seeds else "não checado"),
            ("PEERS", "—"),
            ("RATIO", "—"),
            ("ADICIONADO", "—"),
        ]
        if len(releases) > 1:
            campos.insert(2, ("RELEASES", str(len(releases))))
        for rotulo, valor in campos:
            lay = QHBoxLayout()
            r1 = QLabel(rotulo)
            r1.setObjectName("rotuloFicha")
            r2 = QLabel(valor)
            r2.setObjectName("valorFicha")
            self.linhas_ficha[rotulo] = r2
            lay.addWidget(r1)
            lay.addStretch(1)
            lay.addWidget(r2)
            col.addLayout(lay)

        col.addSpacing(tema.px(10, self.escala))
        if t_principal.get("caminho_local"):
            b = QPushButton("Abrir pasta")
            b.clicked.connect(lambda: self._abrir_pasta(t_principal))
            col.addWidget(b)
        if t_principal:
            b2 = QPushButton("Remover torrent")
            b2.setProperty("perigo", "true")
            b2.clicked.connect(lambda: self._remover(t_principal))
            col.addWidget(b2)

            col.addSpacing(tema.px(6, self.escala))
            r = QLabel("HASH")
            r.setObjectName("rotuloFicha")
            col.addWidget(r)
            h = QLabel(t_principal.get("infohash", ""))
            h.setObjectName("hash")
            h.setWordWrap(True)
            h.setTextInteractionFlags(Qt.TextSelectableByMouse)
            col.addWidget(h)

        self.retorno_ficha = Retorno()
        col.addWidget(self.retorno_ficha)
        col.addStretch(1)
        return col

    # ------------------------------------------------- estado do qBittorrent

    def _buscar_estado_ativo(self) -> None:
        t = self.release_principal
        if not t:
            return
        cfg, infohash, geracao = self.cfg, t["infohash"], self.geracao

        def trabalho():
            return downloads.detalhes_do_torrent(cfg, infohash)

        def pronto(d):
            if geracao != self.geracao:      # a tela ja foi remontada
                return
            self.ativo = d or {}
            self._aplicar_estado_ativo()
            if self.ativo and self.ativo.get("progresso", 1) < 1:
                self.relogio.start()
            else:
                self.relogio.stop()

        self.executor.rodar(f"ativo-{infohash}", trabalho, pronto, lambda _: None)

    def _atualizar_progresso(self) -> None:
        if self.item_id is None:
            self.relogio.stop()
            return
        self._buscar_estado_ativo()

    def _aplicar_estado_ativo(self) -> None:
        if not hasattr(self, "linhas_ficha") or not vivo(self.rot_estado):
            return
        if any(not vivo(w) for w in self.linhas_ficha.values()):
            return
        a = self.ativo
        if a:
            self.linhas_ficha["PEERS"].setText(str(a.get("peers", 0)))
            if a.get("seeds") is not None:
                self.linhas_ficha["SEEDS"].setText(str(a["seeds"]))
            if a.get("ratio") is not None:
                self.linhas_ficha["RATIO"].setText(f"{float(a['ratio']):.2f}")
            if a.get("adicionado"):
                from datetime import datetime
                try:
                    self.linhas_ficha["ADICIONADO"].setText(
                        datetime.fromtimestamp(a["adicionado"]).strftime("%Y-%m-%d"))
                except (OSError, ValueError, TypeError):
                    pass
            if a.get("baixado"):
                self.linhas_ficha["BAIXADO"].setText(formatar_bytes(a["baixado"]))
            rotulo = ("PAUSADO" if a.get("pausado")
                      else "BAIXANDO" if a.get("progresso", 1) < 1 else "CONCLUÍDO")
            cor = (self.paleta.ambar if a.get("pausado")
                   else self.paleta.azul if a.get("progresso", 1) < 1
                   else self.paleta.verde)
            self.rot_estado.setText(f"●  {rotulo}")
            self.rot_estado.setStyleSheet(f"color: {cor};")
        self._montar_acao()

    # --------------------------------------------------------------- acoes

    def _caminho_de_midia(self, t: dict, so_video: bool = True) -> Path | None:
        base = Path(t.get("caminho_local") or "")
        if not base.exists():
            return None
        if base.is_file():
            return base
        candidatos = [a for a in t["arquivos"] if a["tipo"] == "midia"]
        for a in sorted(candidatos, key=lambda x: -x["tamanho"]):
            nome = a["caminho"].rsplit("/", 1)[-1]
            for achado in base.rglob(nome):
                return achado
        extensoes = _EXT_VIDEO if so_video else {".exe", ".msi", ".bat"}
        arquivos = [p for p in base.rglob("*") if p.suffix.lower() in extensoes]
        return max(arquivos, key=lambda p: p.stat().st_size) if arquivos else None

    def _reproduzir(self, t: dict, jogo: bool) -> None:
        alvo = self._caminho_de_midia(t, so_video=not jogo)
        if not alvo:
            if jogo:
                self._abrir_pasta(t)
                return
            self.retorno_acao.mostrar("erro", "Não achei o arquivo no disco.",
                                      "Use “Conferir disco” e tente de novo.")
            return
        self._abrir_no_sistema(alvo)

    def _reproduzir_arquivo(self, e: dict) -> None:
        base = Path(e["release"].get("caminho_local") or "")
        if base.is_file():
            self._abrir_no_sistema(base)
            return
        for achado in base.rglob(e["nome"]):
            self._abrir_no_sistema(achado)
            return
        self.retorno_ficha.mostrar("erro", f"Não achei {e['nome']} no disco.")

    def _abrir_no_sistema(self, caminho: Path) -> None:
        try:
            os.startfile(str(caminho))     # player/programa padrao do Windows
        except OSError as e:
            self.retorno_acao.mostrar("erro", f"Não consegui abrir: {e}")

    def _abrir_pasta(self, t: dict) -> None:
        bruto = str(t.get("caminho_local") or "")
        # Obra que so existe no indice guarda o texto "(indice) caminho/do.torrent"
        # no lugar do caminho — nao e um caminho, e um aviso. Testar existencia
        # nele dava "A pasta nao existe mais no disco", que soa como arquivo
        # perdido quando na verdade a obra simplesmente ainda nao foi baixada.
        if bruto.startswith("(indice)"):
            relativo = bruto.split(" ", 1)[-1]
            no_indice = Path(self.cfg.indice) / relativo
            if no_indice.exists():
                self.retorno_acao.mostrar(
                    "info", "Esta obra ainda não foi baixada.",
                    "Abrindo a pasta do .torrent no índice.")
                self._revelar(no_indice)
            else:
                self.retorno_acao.mostrar(
                    "info", "Esta obra ainda não foi baixada.",
                    "Ela existe só como .torrent no índice — use Baixar acima.")
            return

        alvo = self._caminho_de_midia(t) or Path(bruto)
        if not bruto or not alvo.exists():
            self.retorno_acao.mostrar(
                "aviso", "Não achei esses arquivos no disco.",
                "Use “Conferir disco” no topo do catálogo para reencontrá-los.")
            return
        self._revelar(alvo)

    def _revelar(self, alvo: Path) -> None:
        """Abre o Explorer com o arquivo ja selecionado."""
        try:
            # Mesmo cuidado do aria2: sem console, o Popen precisa de handles
            # explicitos, senao "Abrir pasta" falha so no .exe.
            subprocess.Popen(["explorer", "/select,", str(alvo)],
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            self.retorno_acao.mostrar("erro", f"Não consegui abrir a pasta: {e}")

    def _pausar(self) -> None:
        self._acao_torrent(downloads.pausar, "Pausando…")

    def _retomar(self) -> None:
        self._acao_torrent(downloads.retomar, "Retomando…")

    def _acao_torrent(self, funcao, mensagem: str) -> None:
        t = self.release_principal
        if not t:
            return
        self.retorno_acao.mostrar("info", mensagem)
        cfg, infohash = self.cfg, t["infohash"]

        def pronto(r):
            if r.get("ok"):
                self.retorno_acao.limpar()
                self._buscar_estado_ativo()
            else:
                self.retorno_acao.mostrar("erro", r.get("erro", "falhou"))

        self.executor.rodar(f"acao-{infohash}", lambda: funcao(cfg, infohash),
                            pronto, lambda m: self.retorno_acao.mostrar("erro", m))

    def _remover(self, t: dict) -> None:
        caixa = QMessageBox(self)
        caixa.setWindowTitle("Remover torrent")
        caixa.setIcon(QMessageBox.Question)
        caixa.setText(f"Remover “{t['nome']}” do qBittorrent?")
        caixa.setInformativeText(
            "O arquivo .torrent continua no índice — a obra segue no catálogo.")
        b_so = caixa.addButton("Remover, manter arquivos", QMessageBox.AcceptRole)
        b_tudo = caixa.addButton("Remover e apagar arquivos", QMessageBox.DestructiveRole)
        caixa.addButton("Cancelar", QMessageBox.RejectRole)
        caixa.exec()
        clicado = caixa.clickedButton()
        if clicado not in (b_so, b_tudo):
            return

        cfg, infohash = self.cfg, t["infohash"]
        apagar = clicado is b_tudo

        def pronto(r):
            if r.get("ok"):
                self.retorno_ficha.mostrar("ok", "Removido do qBittorrent.")
                self.mudou.emit()
            else:
                self.retorno_ficha.mostrar("erro", r.get("erro", "falhou"))

        self.executor.rodar(f"remover-{infohash}",
                            lambda: downloads.remover(cfg, infohash, apagar),
                            pronto, lambda m: self.retorno_ficha.mostrar("erro", m))

    def _arquivos_do_torrent(self, caminho_torrent: str) -> list[dict]:
        return [dict(l) for l in self.con.execute(
            "SELECT indice, caminho, tamanho, tipo FROM torrent_files "
            "WHERE caminho_torrent = ? ORDER BY indice", (caminho_torrent,))]

    def _perguntar_o_que_baixar(self, t: dict) -> list[int] | None:
        """Deixa escolher os arquivos. None = cancelou; [] = baixar tudo.

        So aparece quando ha mais de um arquivo util. Em jogo nunca: faltando
        uma parte do .rar, nada instala — e desmarcar seria dar um pe na porta.
        """
        if (self.dados or {}).get("item", {})["tipo"] == "jogo":
            return []
        arquivos = self._arquivos_do_torrent(t["caminho"])
        uteis = [a for a in arquivos if a["tipo"] != "lixo"]
        if len(uteis) < 2:
            return []

        from .escolher_arquivos import EscolherArquivos

        dialogo = EscolherArquivos(arquivos, self.titulo, self.paleta,
                                   self.escala, _limpo, self)
        if dialogo.exec() != QDialog.Accepted:
            return None
        return dialogo.pular()

    def _baixar(self, t: dict, botao: QPushButton, retorno: Retorno) -> None:
        pular = self._perguntar_o_que_baixar(t)
        if pular is None:
            return                     # cancelou a escolha
        botao.setEnabled(False)
        # Nao dizer "qBittorrent": o motor pode ser o uTorrent ou o aria2, e
        # dizer o nome errado fez parecer que o app tinha travado falando com
        # um programa que nem estava instalado na maquina.
        retorno.mostrar("info", "Procurando um cliente de torrent…")
        cfg = self.cfg

        def trabalho():
            con = db.conectar(cfg.banco)
            try:
                return downloads.baixar(con, cfg, t["caminho"], pular)
            finally:
                con.close()

        def pronto(r):
            if r.get("ok"):
                retorno.mostrar("ok", "Baixando.", "\n".join("• " + p for p in r["passos"]))
                self.mudou.emit()
                self._buscar_estado_ativo()
            else:
                botao.setEnabled(True)
                if r.get("sem_motor"):
                    retorno.mostrar(
                        "erro", "Nenhum cliente de torrent conectado.",
                        r.get("erro", "") + "\n\nAbra Configurações → Torrent: "
                        "lá dá para baixar o aria2 (não instala nada, um clique) "
                        "ou apontar o cliente que você já usa.")
                else:
                    retorno.mostrar("erro", r.get("erro", "Falhou."))

        self.executor.rodar(f"baixar-{t['caminho']}", trabalho, pronto,
                            lambda m: (botao.setEnabled(True), retorno.mostrar("erro", m)))

    # ------------------------------------------------------------ releases

    def _secao_releases(self, releases: list[dict]) -> QWidget:
        caixa = QWidget()
        col = QVBoxLayout(caixa)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(tema.px(9, self.escala))
        t = QLabel("Versões disponíveis")
        t.setObjectName("tituloSecaoGrande")
        col.addWidget(t)
        for r in releases:
            col.addWidget(self._caixa_release(r))
        return caixa

    def _caixa_release(self, t: dict) -> QFrame:
        caixa = QFrame()
        caixa.setObjectName("release")
        col = QVBoxLayout(caixa)
        col.setContentsMargins(14, 11, 14, 11)
        col.setSpacing(7)

        nome = QLabel(t["nome"])
        nome.setWordWrap(True)
        nome.setStyleSheet(f"font-size: {tema.px(12, self.escala)}px;")
        col.addWidget(nome)

        tags = QHBoxLayout()
        tags.setSpacing(6)
        if t["temporada"] is not None:
            marca = f"T{int(t['temporada']):02d}"
            if t["episodios"]:
                numeros = [int(x) for x in t["episodios"].split(",") if x.strip()]
                marca += "E" + "+".join(f"{x:02d}" for x in numeros)
            elif t["temporada_completa"]:
                marca += " completa"
            tags.addWidget(Etiqueta(marca))
        for campo in ("qualidade", "fonte", "idioma"):
            if t.get(campo):
                tags.addWidget(Etiqueta(str(t[campo])))
        if t["estado"] == "completo":
            tags.addWidget(Etiqueta("no disco", "ok"))
        elif t["estado"] == "parcial":
            pct = round(100 * t["bytes_presentes"] / (t["tamanho_total"] or 1))
            tags.addWidget(Etiqueta(f"{pct}%", "aviso"))
        if t["seeders"] is not None:
            tags.addWidget(Etiqueta(f"{t['seeders']} seeds",
                                    "ok" if t["seeders"] else "erro"))
        if not t["n_trackers"]:
            tags.addWidget(Etiqueta("sem tracker", "info"))
        tags.addStretch(1)
        col.addLayout(tags)

        retorno = Retorno()
        acoes = QHBoxLayout()
        acoes.setSpacing(6)
        b1 = QPushButton("Checar seeds")
        b1.clicked.connect(lambda: self._checar_seeds(t, b1, retorno))
        acoes.addWidget(b1)
        b2 = QPushButton("Baixar de novo" if t["estado"] == "completo" else "Baixar")
        b2.clicked.connect(lambda: self._baixar(t, b2, retorno))
        acoes.addWidget(b2)
        if t["estado"] in ("completo", "parcial"):
            b3 = QPushButton(f"Liberar {formatar_bytes(t['bytes_presentes'])}")
            b3.setProperty("perigo", "true")
            b3.clicked.connect(lambda: self._liberar(t, b3, retorno))
            acoes.addWidget(b3)
        acoes.addStretch(1)
        col.addLayout(acoes)
        col.addWidget(retorno)
        return caixa

    def _checar_seeds(self, t: dict, botao: QPushButton, retorno: Retorno) -> None:
        botao.setEnabled(False)
        retorno.mostrar("info", "Perguntando aos trackers…")
        cfg = self.cfg

        def trabalho():
            con = db.conectar(cfg.banco)
            try:
                r = health.checar(con, cfg, infohashes=[t["infohash"]])
                return r.detalhes[0] if r.detalhes else None
            finally:
                con.close()

        def pronto(s):
            botao.setEnabled(True)
            if s is None or s.seeders is None:
                retorno.mostrar("erro", "Nenhum tracker respondeu.",
                                "Não prova que morreu — pode ser o tracker fora do ar.")
            elif s.seeders == 0:
                retorno.mostrar("erro", "0 seeders.",
                                "Apagar a mídia provavelmente seria definitivo.")
            else:
                retorno.mostrar("ok", f"{s.seeders} seeders.",
                                "Dá para apagar e baixar de novo depois.")
            self.mudou.emit()

        self.executor.rodar(f"seeds-{t['infohash']}", trabalho, pronto,
                            lambda m: (botao.setEnabled(True), retorno.mostrar("erro", m)))

    def _liberar(self, t: dict, botao: QPushButton, retorno: Retorno) -> None:
        avaliacao = espaco.avaliar(self.con, self.cfg, t["caminho"])
        if not avaliacao["pode"]:
            retorno.mostrar("erro", "Não vou liberar.", avaliacao["motivo"])
            return
        resposta = QMessageBox.question(
            self, "Apagar a mídia deste release?",
            f"{avaliacao['caminho_local']}\n\n"
            f"Volta {formatar_bytes(avaliacao['bytes'])} de espaço. "
            f"{avaliacao['seeders']} seeders confirmados, então dá para baixar de novo.\n\n"
            "O arquivo .torrent continua no índice.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resposta != QMessageBox.Yes:
            retorno.mostrar("info", "Cancelado — nada foi apagado.")
            return
        r = espaco.liberar(self.con, self.cfg, t["caminho"], confirmar=True)
        if r.get("ok"):
            self.mudou.emit()
            self.mostrar(self.item_id)
        else:
            retorno.mostrar("erro", r.get("erro", "Falhou."))

    # ---------------------------------------------------------------- capa

    def _secao_capa(self, item: dict) -> QFrame:
        caixa = QFrame()
        caixa.setObjectName("release")
        col = QVBoxLayout(caixa)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(10)
        cab = QLabel("Capa")
        cab.setObjectName("rotulo")
        col.addWidget(cab)

        linha = QHBoxLayout()
        linha.setSpacing(14)
        mostra = QLabel()
        mostra.setPixmap(widgets.carregar_capa(
            self.cfg.posters / item["poster"] if item["poster"] else None,
            self.titulo, 78))
        mostra.setFixedSize(78, int(78 * widgets.PROPORCAO_CAPA))
        mostra.setAccessibleName(f"Capa atual de {self.titulo}")
        linha.addWidget(mostra, 0, Qt.AlignTop)

        lado = QVBoxLayout()
        lado.setSpacing(8)
        gerada = bool(item["poster"]) and str(item["poster"]).endswith("-gerada.svg")
        lado.addWidget(widgets.ajuda(
            "Esta obra ainda não tem capa." if not item["poster"] else
            "Capa gerada do título. Procure a de verdade abaixo." if gerada else
            "Capa encontrada automaticamente."))

        busca = QHBoxLayout()
        self.campo_capa = QLineEdit(self.titulo)
        self.campo_capa.setAccessibleName("Nome para procurar a capa")
        busca.addWidget(self.campo_capa, 1)
        b = QPushButton("Procurar")
        b.setProperty("destaque", "true")
        b.clicked.connect(lambda: self._procurar_capa(item, b))
        busca.addWidget(b)
        lado.addLayout(busca)

        outros = QHBoxLayout()
        outros.setSpacing(6)
        b1 = QPushButton("Escolher imagem…")
        b1.clicked.connect(self._escolher_arquivo)
        outros.addWidget(b1)
        b2 = QPushButton("Gerar do título")
        b2.clicked.connect(lambda: self._gerar_capa(item))
        outros.addWidget(b2)
        outros.addStretch(1)
        lado.addLayout(outros)
        lado.addStretch(1)
        linha.addLayout(lado, 1)
        col.addLayout(linha)

        self.retorno_capa = Retorno()
        col.addWidget(self.retorno_capa)
        self.area_candidatos = QWidget()
        self.grade_candidatos = QGridLayout(self.area_candidatos)
        self.grade_candidatos.setContentsMargins(0, 0, 0, 0)
        self.grade_candidatos.setSpacing(10)
        self.area_candidatos.hide()
        col.addWidget(self.area_candidatos)
        return caixa

    def _procurar_capa(self, item: dict, botao: QPushButton) -> None:
        termo = self.campo_capa.text().strip()
        if not termo:
            return
        botao.setEnabled(False)
        self.retorno_capa.mostrar("info", "Procurando…")
        cfg, tipo, ano = self.cfg, item["tipo"], item["ano"]
        geracao = self.geracao

        def pronto(resultados):
            if geracao != self.geracao or not vivo(botao):
                return
            botao.setEnabled(True)
            self.candidatos = [x for x in resultados if x.get("poster")]
            if not self.candidatos:
                self.retorno_capa.mostrar("erro", f"Nada com capa para “{termo}”.",
                                          "Tente outro nome, ou gere do título.")
                self.area_candidatos.hide()
                return
            self.retorno_capa.mostrar("info", f"{len(self.candidatos)} resultados.",
                                      "Clique no que for a obra certa.")
            self._mostrar_candidatos()

        self.executor.rodar(f"procurar-capa-{self.item_id}",
                            lambda: metadata.procurar(termo, tipo, cfg, ano), pronto,
                            lambda m: (botao.setEnabled(True),
                                       self.retorno_capa.mostrar("erro", m)))

    def _mostrar_candidatos(self) -> None:
        while self.grade_candidatos.count():
            w = self.grade_candidatos.takeAt(0)
            if w.widget():
                w.widget().deleteLater()
        for i, x in enumerate(self.candidatos[:12]):
            b = QPushButton()
            b.setFlat(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(90, int(90 * widgets.PROPORCAO_CAPA) + 30)
            b.setStyleSheet(
                "QPushButton { background: transparent; border: 2px solid transparent;"
                " padding: 0; }"
                f"QPushButton:hover, QPushButton:focus {{ border-color: {self.paleta.azul}; }}")
            nome = x["titulo"] + (f" ({x['ano']})" if x.get("ano") else "")
            b.setAccessibleName(f"Usar a capa de {nome}")
            b.setToolTip(nome)
            interno = QVBoxLayout(b)
            interno.setContentsMargins(0, 0, 0, 0)
            interno.setSpacing(3)
            img = QLabel("…")
            img.setFixedSize(86, int(86 * widgets.PROPORCAO_CAPA))
            interno.addWidget(img)
            legenda = QLabel(nome)
            legenda.setObjectName("metaCartao")
            legenda.setWordWrap(True)
            interno.addWidget(legenda)
            b.clicked.connect(lambda _=False, dado=x: self._aplicar_capa_de(dado))
            self.grade_candidatos.addWidget(b, i // 5, i % 5)
            self._miniatura(x["poster"], img)
        self.area_candidatos.show()

    def _miniatura(self, url: str, alvo: QLabel) -> None:
        def trabalho():
            import urllib.request
            from core.metadata import CABECALHOS
            req = urllib.request.Request(url, headers=CABECALHOS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read()

        geracao = self.geracao

        def pronto(dados):
            if geracao != self.geracao or not vivo(alvo):
                return
            pm = QPixmap()
            if pm.loadFromData(dados):
                alvo.setPixmap(pm.scaled(86, int(86 * widgets.PROPORCAO_CAPA),
                                         Qt.KeepAspectRatioByExpanding,
                                         Qt.SmoothTransformation))
                alvo.setText("")

        self.executor.rodar(f"mini-{url}", trabalho, pronto, lambda _: None)

    def _aplicar_capa_de(self, dado: dict) -> None:
        """Baixa a capa escolhida e aplica. O download vai para outra linha.

        Antes isto baixava capa e fundo na linha da interface: a janela
        congelava por segundos no clique e parecia que o botao nao funcionava.
        """
        self.retorno_capa.mostrar("info", "Aplicando…")
        cfg, item_id, geracao = self.cfg, self.item_id, self.geracao

        def trabalho():
            import urllib.request

            from core.metadata import CABECALHOS

            nome = capas.baixar_para_item(dado["poster"], cfg.posters, item_id)
            nome_fundo = None
            if dado.get("fundo"):
                try:
                    req = urllib.request.Request(dado["fundo"], headers=CABECALHOS)
                    with urllib.request.urlopen(req, timeout=25) as r:
                        conteudo = r.read()
                    nome_fundo = f"{item_id}-fundo.jpg"
                    (Path(cfg.posters) / nome_fundo).write_bytes(conteudo)
                except Exception:
                    nome_fundo = None     # a faixa cai no poster ampliado
            return nome, nome_fundo

        def pronto(resultado):
            if geracao != self.geracao or not vivo(self.retorno_capa):
                return
            nome, nome_fundo = resultado
            capas.aplicar(self.con, self.cfg.posters, self.item_id, nome)
            if nome_fundo:
                self.con.execute("UPDATE itens SET backdrop = ? WHERE id = ?",
                                 (nome_fundo, self.item_id))
            for campo, valor in (("tmdb_id", dado.get("id")),
                                 ("sinopse", dado.get("sinopse")),
                                 ("nota", dado.get("nota")), ("ano", dado.get("ano"))):
                if valor not in (None, "", 0):
                    self.con.execute(f"UPDATE itens SET {campo} = ? WHERE id = ?",
                                     (valor, self.item_id))
            self.con.commit()
            widgets.limpar_cache_capas()
            self.mudou.emit()
            self.mostrar(self.item_id)

        self.executor.rodar(
            f"aplicar-capa-{item_id}", trabalho, pronto,
            lambda m: self.retorno_capa.mostrar("erro", m)
            if vivo(self.retorno_capa) else None)

    def _escolher_arquivo(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Escolher imagem para a capa", "",
            "Imagens (*.jpg *.jpeg *.png *.webp *.svg)")
        if not caminho:
            return
        try:
            nome = capas.copiar_do_disco(caminho, self.cfg.posters, self.item_id)
        except Exception as e:
            self.retorno_capa.mostrar("erro", str(e))
            return
        capas.aplicar(self.con, self.cfg.posters, self.item_id, nome)
        widgets.limpar_cache_capas()
        self.mudou.emit()
        self.mostrar(self.item_id)

    def _gerar_capa(self, item: dict) -> None:
        nome = capas.gravar_gerada(self.cfg.posters, self.item_id, self.titulo,
                                   item["tipo"], item["ano"])
        capas.aplicar(self.con, self.cfg.posters, self.item_id, nome)
        widgets.limpar_cache_capas()
        self.mudou.emit()
        self.mostrar(self.item_id)

    # ------------------------------------------------------------ ajustes

    def _secao_ajustes(self, item: dict) -> QFrame:
        from PySide6.QtWidgets import QCheckBox

        caixa = QFrame()
        caixa.setObjectName("release")
        col = QVBoxLayout(caixa)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(10)
        cab = QLabel("Ajustes desta obra")
        cab.setObjectName("rotulo")
        col.addWidget(cab)

        linha = QHBoxLayout()
        self.campo_titulo = QLineEdit(self.titulo)
        self.campo_titulo.setAccessibleName("Título da obra")
        linha.addWidget(self.campo_titulo, 1)
        b = QPushButton("Corrigir")
        b.clicked.connect(self._corrigir_titulo)
        linha.addWidget(b)
        col.addLayout(linha)
        col.addWidget(widgets.ajuda(
            "Corrija se o nome do arquivo enganou o app; a busca de capas usa este título."))

        marca = QCheckBox("Proteger esta obra")
        marca.setChecked(bool(item["fixado"]))
        marca.toggled.connect(self._alternar_fixado)
        col.addWidget(marca)
        col.addWidget(widgets.ajuda("O app nunca vai oferecer para apagar a mídia dela."))
        return caixa

    def _corrigir_titulo(self) -> None:
        self.con.execute("UPDATE itens SET titulo_corrigido = ? WHERE id = ?",
                         (self.campo_titulo.text().strip() or None, self.item_id))
        self.con.commit()
        self.mudou.emit()
        self.mostrar(self.item_id)

    def _alternar_fixado(self, marcado: bool) -> None:
        self.con.execute("UPDATE itens SET fixado = ? WHERE id = ?",
                         (int(marcado), self.item_id))
        self.con.commit()
        self.mudou.emit()


def _resumir(texto: str, limite: int = 260) -> str:
    """Corta a sinopse para caber na faixa sem empurrar o resto do layout."""
    texto = " ".join(texto.split())
    if len(texto) <= limite:
        return texto
    corte = texto[:limite]
    espaco = corte.rfind(" ")
    return (corte[:espaco] if espaco > limite * 0.6 else corte).rstrip(" ,.;") + "…"


def _tempo(segundos: int) -> str:
    if segundos < 60:
        return f"{segundos}s"
    if segundos < 3600:
        return f"{segundos // 60} min"
    return f"{segundos // 3600}h {(segundos % 3600) // 60:02d}min"


def _limpo(nome: str) -> str:
    """Nome legivel do arquivo, para ficar no lugar de destaque.

    A versao anterior era um punhado de regex escrito na mao e ainda deixava
    passar tag de site, nome de grupo e separador solto. `release.analisar` ja
    sabe desmontar um nome de release inteiro — aqui e so aproveitar o titulo
    que ele extrai, caindo no nome do arquivo quando nao da para entender.
    """
    from core import release as _rel

    base = Path(nome).name
    base = base.rsplit(".", 1)[0] if "." in base else base
    try:
        titulo = (_rel.analisar(base).titulo or "").strip()
    except Exception:                     # nome esquisito nunca derruba a tela
        titulo = ""
    return titulo or base.replace(".", " ").strip()

