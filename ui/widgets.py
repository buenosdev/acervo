"""Pecas visuais da janela: cartao de obra, etiquetas, avisos.

O cartao e desenhado no paintEvent, nao montado com widgets aninhados. A versao
anterior punha um QFrame dentro de um QPushButton dentro de layouts, e o QFrame
as vezes nao era adotado pelo layout: caia no tamanho padrao 100x30 e o cartao
virava uma faixa fina, engolindo capa e titulo. Pintando, nao ha layout interno
para colapsar, o tamanho vira um parametro simples e a grade com 155 itens fica
bem mais leve.

Acessibilidade: o cartao continua sendo um botao de verdade, com nome e
descricao acessiveis - o Narrador anuncia "A Casa do Dragao, Serie, 2022, so no
indice, 7.7 GB" e o Tab chega em todos.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import (QObject, QRect, QRectF, QRunnable, QSize, Qt,
                            QThreadPool, Signal)
from PySide6.QtGui import (QAbstractTextDocumentLayout, QColor, QFont, QFontMetrics,
                           QImage, QImageReader, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel,
                               QProgressBar, QSizePolicy, QVBoxLayout, QWidget)

from . import tema

PROPORCAO_CAPA = 3 / 2                      # capa 2:3

TAMANHOS_CARTAO = {
    "pequeno": 122,
    "medio": 158,
    "grande": 200,
    "enorme": 248,
}
ROTULOS_TAMANHO = {
    "pequeno": "Pequeno", "medio": "Médio",
    "grande": "Grande", "enorme": "Muito grande",
}
ALTURA_LINHA_LISTA = 62

_cache_capas: dict[tuple[str, int], QPixmap] = {}
# Imagens ja decodificadas pelas linhas de fundo, esperando virar QPixmap.
# QImage pode ser criada fora da linha principal; QPixmap, nao — por isso
# a conversao acontece so quando a grade vem buscar.
_imagens_prontas: dict[tuple[str, int], object] = {}


def formatar_bytes(n: int | None) -> str:
    n = float(n or 0)
    if n <= 0:
        return "0 B"
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unidade == "TB":
            casas = 1 if (n < 10 and unidade not in ("B", "KB")) else 0
            return f"{n:.{casas}f} {unidade}"
        n /= 1024
    return f"{n:.0f} TB"


def _matiz(texto: str) -> int:
    return hashlib.sha1(texto.encode("utf-8", "replace")).digest()[0] * 360 // 256


def capa_de_reserva(titulo: str, largura: int, altura: int) -> QPixmap:
    """Capa desenhada quando nao ha imagem: cor derivada do proprio titulo."""
    pm = QPixmap(largura, altura)
    pm.fill(Qt.transparent)
    h = _matiz(titulo)

    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, largura * 0.6, altura)
    grad.setColorAt(0, QColor.fromHsl(h, 90, 66))
    grad.setColorAt(1, QColor.fromHsl((h + 40) % 360, 100, 28))
    p.fillRect(0, 0, largura, altura, grad)

    p.setPen(QColor("#f2f2f6"))
    fonte = QFont(p.font())
    fonte.setPixelSize(max(10, int(largura * 0.11)))
    fonte.setWeight(QFont.DemiBold)
    p.setFont(fonte)
    margem = max(8, int(largura * 0.09))
    p.drawText(QRectF(margem, margem, largura - 2 * margem, altura - 2 * margem),
               Qt.AlignBottom | Qt.AlignLeft | Qt.TextWordWrap, titulo)
    p.end()
    return pm


def _decodificar(caminho: str, largura: int, altura: int) -> QImage | None:
    """Le a imagem ja no tamanho final. Roda fora da linha da interface.

    `QImageReader.setScaledSize` deixa o decodificador reduzir durante a leitura
    — bem mais barato que decodificar em tamanho cheio e so depois encolher.
    """
    leitor = QImageReader(caminho)
    leitor.setAutoTransform(True)
    tam = leitor.size()
    if tam.isValid() and tam.width() > 0 and tam.height() > 0:
        fator = max(largura / tam.width(), altura / tam.height())
        leitor.setScaledSize(QSize(max(1, round(tam.width() * fator)),
                                   max(1, round(tam.height() * fator))))
    img = leitor.read()
    if img.isNull():
        return None
    if img.width() > largura or img.height() > altura:
        img = img.copy((img.width() - largura) // 2,
                       (img.height() - altura) // 2, largura, altura)
    return img


class _SinaisCapa(QObject):
    pronta = Signal(str, int)                 # caminho, largura


class CarregadorCapas(QObject):
    """Decodifica capas em segundo plano e avisa quem espera.

    Decodificar dentro do `paint` era o que fazia a rolagem engasgar: cada fila
    nova custava ~63 ms — quatro quadros perdidos — porque sete JPEGs eram lidos
    e redimensionados ali mesmo. Aqui o cartao aparece na hora com um retangulo
    neutro e a capa entra quando fica pronta.
    """

    def __init__(self):
        super().__init__()
        self.sinais = _SinaisCapa()
        self._pool = QThreadPool()
        # Duas linhas bastam e deixam o resto da maquina livre; o gargalo e
        # decodificacao, nao espera de disco.
        self._pool.setMaxThreadCount(2)
        self._pedidos: set[tuple] = set()
        self._tarefas: list = []

    def pedir(self, caminho: str, largura: int, altura: int) -> None:
        chave = (caminho, largura)
        if chave in self._pedidos or chave in _imagens_prontas:
            return
        self._pedidos.add(chave)

        sinais, pedidos = self.sinais, self._pedidos

        class _Tarefa(QRunnable):
            def run(self) -> None:
                try:
                    img = _decodificar(caminho, largura, altura)
                except Exception:              # noqa: BLE001
                    img = None
                if img is not None:
                    _imagens_prontas[chave] = img
                pedidos.discard(chave)
                try:
                    sinais.pronta.emit(caminho, largura)
                except RuntimeError:
                    pass                       # a janela fechou

        tarefa = _Tarefa()
        # Mesma licao do Executor: o pool nao pode apagar a tarefa antes de o
        # sinal ser entregue na linha principal.
        tarefa.setAutoDelete(False)
        self._tarefas.append(tarefa)
        if len(self._tarefas) > 400:
            self._tarefas = self._tarefas[-200:]
        self._pool.start(tarefa)

    def esperar(self, ms: int = 2000) -> None:
        self._pool.waitForDone(ms)


carregador = CarregadorCapas()


def carregar_capa(caminho: Path | None, titulo: str, largura: int) -> QPixmap:
    """Capa no tamanho pedido, sincrona. Usada fora da grade."""
    pm = capa_pronta(caminho, titulo, largura)
    if pm is not None:
        return pm
    altura = int(largura * PROPORCAO_CAPA)
    chave = (str(caminho), largura)
    img = _decodificar(str(caminho), largura, altura) if caminho else None
    pm = QPixmap.fromImage(img) if img is not None else QPixmap()
    if pm.isNull():
        chave = (f"?{titulo}", largura)
        pm = capa_de_reserva(titulo, largura, altura)
    _guardar(chave, pm)
    return pm


def capa_pronta(caminho: Path | None, titulo: str, largura: int) -> QPixmap | None:
    """A capa, se ja estiver pronta. `None` quando ainda esta sendo lida."""
    chave = (str(caminho) if caminho else f"?{titulo}", largura)
    pronta = _cache_capas.get(chave)
    if pronta is not None:
        return pronta

    img = _imagens_prontas.pop(chave, None)
    if img is not None:
        pm = QPixmap.fromImage(img)            # so na linha principal
        _guardar(chave, pm)
        return pm

    if caminho is None:
        pm = capa_de_reserva(titulo, largura, int(largura * PROPORCAO_CAPA))
        _guardar(chave, pm)
        return pm
    return None


def pedir_capa(caminho: Path, largura: int) -> None:
    """Poe a capa na fila de leitura, sem bloquear."""
    carregador.pedir(str(caminho), largura, int(largura * PROPORCAO_CAPA))


def converter_prontas(limite: int = 24) -> int:
    """Transforma em QPixmap as imagens que as linhas de fundo terminaram.

    Feito aqui, e nao dentro do `paint`, de proposito. QPixmap so pode ser
    criado na linha principal, entao a conversao acabava caindo no meio do
    desenho — e uma fila que revelasse varias capas novas de uma vez custava
    dobrado, com picos de 17 a 21 ms. Convertendo antes de mandar repintar, a
    pintura so encontra pixmap pronto.
    """
    if not _imagens_prontas:
        return 0
    feitos = 0
    for chave in list(_imagens_prontas)[:limite]:
        img = _imagens_prontas.pop(chave, None)
        if img is None:
            continue
        _guardar(chave, QPixmap.fromImage(img))
        feitos += 1
    return feitos


def _guardar(chave: tuple, pm: QPixmap) -> None:
    if len(_cache_capas) > 600:               # nao cresce sem limite
        _cache_capas.clear()
    _cache_capas[chave] = pm


# Sobe a cada troca de capa. A grade guarda o cartao ja pintado; sem este
# contador, aplicar uma capa nova nao mudaria nada na tela — que era
# exatamente a queixa de "coloquei a capa e continua a mesma".
_geracao_capas = 0


def limpar_cache_capas() -> None:
    global _geracao_capas
    _cache_capas.clear()
    _imagens_prontas.clear()
    _geracao_capas += 1


def geracao_capas() -> int:
    """Muda sempre que alguma capa e trocada. Quem cacheia compara com isto."""
    return _geracao_capas


def _linhas_cabendo(texto: str, fm: QFontMetrics, largura: int,
                    maximo: int = 2) -> list[str]:
    """Quebra o texto em ate `maximo` linhas, com reticencias na ultima."""
    palavras = texto.split()
    linhas: list[str] = []
    atual = ""
    for palavra in palavras:
        teste = f"{atual} {palavra}".strip()
        if fm.horizontalAdvance(teste) <= largura or not atual:
            atual = teste
        else:
            linhas.append(atual)
            atual = palavra
            if len(linhas) == maximo:
                break
    if atual and len(linhas) < maximo:
        linhas.append(atual)
    if not linhas:
        return [fm.elidedText(texto, Qt.ElideRight, largura)]
    # Sobrou texto: a ultima linha ganha reticencias.
    if len(" ".join(linhas)) < len(texto):
        linhas[-1] = fm.elidedText(linhas[-1] + "…", Qt.ElideRight, largura)
    return linhas


ROTULO_TIPO = {"filme": "Filme", "serie": "Série", "jogo": "Jogo"}
_TEXTO_ESTADO = {"completo": "no disco", "parcial": "baixado pela metade",
                 "indice": "só no índice", "orfao": "sem torrent"}


class CartaoObra(QAbstractButton):
    """Um item do catalogo. Desenha capa, selo, titulo e metadados."""

    aberto = Signal(int)

    def __init__(self, obra: dict, pasta_posters: Path, paleta: tema.Paleta,
                 escala: float = 1.0, largura: int = 158, modo: str = "grade",
                 pai: QWidget | None = None):
        super().__init__(pai)
        self.obra = obra
        self.paleta = paleta
        self.escala = escala
        self.modo = modo
        self.pasta_posters = pasta_posters

        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

        if modo == "lista":
            self.altura_linha = tema.px(ALTURA_LINHA_LISTA, escala)
            self.largura_capa = int(self.altura_linha / PROPORCAO_CAPA)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setFixedHeight(self.altura_linha)
        else:
            self.largura_capa = largura
            self.altura_capa = int(largura * PROPORCAO_CAPA)
            self.altura_texto = (tema.px(9, escala)
                                 + tema.px(17, escala) * 2
                                 + tema.px(4, escala)
                                 + tema.px(14, escala)
                                 + tema.px(10, escala))
            self.setFixedSize(largura, self.altura_capa + self.altura_texto)

        self.capa = carregar_capa(
            pasta_posters / obra["poster"] if obra.get("poster") else None,
            obra["titulo"], self.largura_capa)

        self.setAccessibleName(obra["titulo"])
        self.setAccessibleDescription(self._descricao())
        self.setToolTip(obra["titulo"])
        self.clicked.connect(lambda: self.aberto.emit(obra["id"]))

    def _descricao(self) -> str:
        o = self.obra
        partes = [ROTULO_TIPO.get(o.get("tipo"), ""), str(o.get("ano") or ""),
                  (o.get("qualidades") or [""])[-1],
                  _TEXTO_ESTADO.get(o.get("estado", ""), ""),
                  formatar_bytes(o.get("bytes_total"))]
        if o.get("fixado"):
            partes.append("protegido")
        return ", ".join(x for x in partes if x)

    def sizeHint(self) -> QSize:          # noqa: N802  (assinatura do Qt)
        if self.modo == "lista":
            return QSize(400, self.altura_linha)
        return QSize(self.largura_capa, self.altura_capa + self.altura_texto)

    # -------------------------------------------------------------- pintura

    def paintEvent(self, _evento):        # noqa: N802  (assinatura do Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pal = self.paleta
        destacado = self.underMouse() or self.hasFocus()

        if self.modo == "lista":
            self._pintar_lista(p, pal, destacado)
        else:
            self._pintar_grade(p, pal, destacado)
        p.end()

    def _moldura(self, p: QPainter, pal: tema.Paleta, destacado: bool,
                 raio: int = 6) -> QPainterPath:
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        caminho = QPainterPath()
        caminho.addRoundedRect(r, raio, raio)
        p.fillPath(caminho, QColor(pal.cartao))
        p.setPen(QPen(QColor(pal.azul if self.hasFocus() else
                             (pal.borda_txt if destacado else pal.cartao_bd)),
                      2 if self.hasFocus() else 1))
        p.drawPath(caminho)
        return caminho

    def _pintar_grade(self, p: QPainter, pal: tema.Paleta, destacado: bool) -> None:
        moldura = self._moldura(p, pal, destacado)
        p.save()
        p.setClipPath(moldura)

        area_capa = QRect(1, 1, self.largura_capa - 2, self.altura_capa)
        p.drawPixmap(area_capa, self.capa)

        self._selo(p, pal, 8, 8)
        qualidades = self.obra.get("qualidades") or []
        if qualidades:
            self._etiqueta_direita(p, pal, qualidades[-1], 8, 8)
        if self.obra.get("fixado"):
            self._cadeado(p, pal, area_capa)
        p.restore()

        # ---- texto
        margem = tema.px(10, self.escala)
        largura_texto = self.width() - margem * 2
        y = self.altura_capa + tema.px(9, self.escala)

        fonte = QFont(self.font())
        fonte.setPixelSize(tema.px(13, self.escala))
        fonte.setWeight(QFont.DemiBold)
        p.setFont(fonte)
        fm = QFontMetrics(fonte)
        p.setPen(QColor(pal.forte))
        for linha in _linhas_cabendo(self.obra["titulo"], fm, largura_texto):
            y += fm.ascent()
            p.drawText(margem, y, linha)
            y += fm.descent() + tema.px(2, self.escala)

        y = self.height() - tema.px(10, self.escala)
        mono = QFont(tema.fonte_mono().split(",")[0].strip('"'))
        mono.setPixelSize(tema.px(11, self.escala))
        p.setFont(mono)
        p.setPen(QColor(pal.tenue))
        fm2 = QFontMetrics(mono)
        esquerda = formatar_bytes(self.obra.get("bytes_total"))
        direita = (f"{self.obra['temporadas']} temp."
                   if self.obra.get("temporadas") else str(self.obra.get("ano") or ""))
        p.drawText(margem, y, esquerda)
        if direita:
            p.drawText(self.width() - margem - fm2.horizontalAdvance(direita), y, direita)

    def _pintar_lista(self, p: QPainter, pal: tema.Paleta, destacado: bool) -> None:
        moldura = self._moldura(p, pal, destacado, raio=5)
        p.save()
        p.setClipPath(moldura)
        p.drawPixmap(QRect(1, 1, self.largura_capa, self.altura_linha - 2), self.capa)
        p.restore()

        x = self.largura_capa + tema.px(14, self.escala)
        meio = self.height() // 2

        fonte = QFont(self.font())
        fonte.setPixelSize(tema.px(13, self.escala))
        fonte.setWeight(QFont.DemiBold)
        p.setFont(fonte)
        fm = QFontMetrics(fonte)
        p.setPen(QColor(pal.forte))
        largura_titulo = max(80, self.width() - x - tema.px(260, self.escala))
        p.drawText(x, meio - tema.px(2, self.escala),
                   fm.elidedText(self.obra["titulo"], Qt.ElideRight, largura_titulo))

        mono = QFont(tema.fonte_mono().split(",")[0].strip('"'))
        mono.setPixelSize(tema.px(11, self.escala))
        p.setFont(mono)
        p.setPen(QColor(pal.tenue))
        sub = " · ".join(x for x in [
            ROTULO_TIPO.get(self.obra.get("tipo"), ""),
            str(self.obra.get("ano") or ""),
            (self.obra.get("qualidades") or [""])[-1],
        ] if x)
        p.drawText(x, meio + tema.px(15, self.escala), sub)

        fm2 = QFontMetrics(mono)
        tamanho = formatar_bytes(self.obra.get("bytes_total"))
        direita = self.width() - tema.px(14, self.escala)
        p.drawText(direita - fm2.horizontalAdvance(tamanho),
                   meio + tema.px(5, self.escala), tamanho)

        chave_cor, rotulo = tema.CORES_ESTADO.get(self.obra.get("estado", "indice"),
                                                  ("tenue", "?"))
        largura_selo = fm2.horizontalAdvance(rotulo) + tema.px(18, self.escala)
        self._pilula(p, QColor(getattr(pal, chave_cor)), rotulo, mono,
                     direita - fm2.horizontalAdvance(tamanho) - tema.px(16, self.escala)
                     - largura_selo, meio - tema.px(9, self.escala), largura_selo)

    # ------------------------------------------------------------- adornos

    def _selo(self, p: QPainter, pal: tema.Paleta, x: int, y: int) -> None:
        chave_cor, rotulo = tema.CORES_ESTADO.get(self.obra.get("estado", "indice"),
                                                  ("tenue", "?"))
        mono = QFont(tema.fonte_mono().split(",")[0].strip('"'))
        mono.setPixelSize(tema.px(10, self.escala))
        mono.setWeight(QFont.DemiBold)
        fm = QFontMetrics(mono)
        largura = fm.horizontalAdvance(rotulo) + tema.px(20, self.escala)
        self._pilula(p, QColor(getattr(pal, chave_cor)), rotulo, mono, x, y, largura)

    def _pilula(self, p: QPainter, cor: QColor, texto: str, fonte: QFont,
                x: int, y: int, largura: int) -> None:
        """Fundo escuro translucido + ponto colorido + texto. Nunca so cor."""
        fm = QFontMetrics(fonte)
        altura = fm.height() + tema.px(5, self.escala)
        caminho = QPainterPath()
        caminho.addRoundedRect(QRectF(x, y, largura, altura), 3, 3)
        p.fillPath(caminho, QColor(0, 0, 0, 205))

        r = tema.px(5, self.escala)
        p.setBrush(cor)
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(x + tema.px(6, self.escala)),
                      int(y + altura / 2 - r / 2), r, r)
        p.setBrush(Qt.NoBrush)
        p.setFont(fonte)
        p.setPen(cor)
        p.drawText(int(x + tema.px(14, self.escala)),
                   int(y + altura / 2 + fm.capHeight() / 2), texto)

    def _etiqueta_direita(self, p: QPainter, pal: tema.Paleta, texto: str,
                          margem_dir: int, y: int) -> None:
        mono = QFont(tema.fonte_mono().split(",")[0].strip('"'))
        mono.setPixelSize(tema.px(10, self.escala))
        fm = QFontMetrics(mono)
        largura = fm.horizontalAdvance(texto) + tema.px(11, self.escala)
        altura = fm.height() + tema.px(5, self.escala)
        x = self.width() - margem_dir - largura
        caminho = QPainterPath()
        caminho.addRoundedRect(QRectF(x, y, largura, altura), 3, 3)
        p.fillPath(caminho, QColor(0, 0, 0, 190))
        p.setFont(mono)
        p.setPen(QColor("#c8c8d2"))
        p.drawText(int(x + tema.px(5.5, self.escala)),
                   int(y + altura / 2 + fm.capHeight() / 2), texto)

    def _cadeado(self, p: QPainter, pal: tema.Paleta, area: QRect) -> None:
        fonte = QFont(self.font())
        fonte.setPixelSize(tema.px(12, self.escala))
        fm = QFontMetrics(fonte)
        largura = tema.px(22, self.escala)
        altura = fm.height() + tema.px(4, self.escala)
        x = area.right() - largura - tema.px(7, self.escala)
        y = area.bottom() - altura - tema.px(7, self.escala)
        caminho = QPainterPath()
        caminho.addRoundedRect(QRectF(x, y, largura, altura), 3, 3)
        p.fillPath(caminho, QColor(0, 0, 0, 190))
        p.setFont(fonte)
        p.setPen(QColor(pal.ambar))
        p.drawText(QRectF(x, y, largura, altura), Qt.AlignCenter, "🔒")

    # Repinta no hover, senao a borda de destaque nao aparece.
    def enterEvent(self, e):              # noqa: N802
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):              # noqa: N802
        self.update()
        super().leaveEvent(e)


# --------------------------------------------------------------- auxiliares

class Etiqueta(QLabel):
    """Rotulo colorido pequeno. Sempre com texto - cor nunca e o unico sinal."""

    def __init__(self, texto: str, nivel: str = "true", pai: QWidget | None = None):
        super().__init__(texto, pai)
        self.setProperty("etiqueta", nivel)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)


class Retorno(QLabel):
    """Faixa de mensagem (ok / erro / info / aviso) que some quando vazia."""

    def __init__(self, pai: QWidget | None = None):
        super().__init__("", pai)
        self.setObjectName("retorno")
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.hide()

    def mostrar(self, nivel: str, texto: str, detalhe: str = "") -> None:
        self.setProperty("nivel", nivel)
        self.setText(texto + (f"\n{detalhe}" if detalhe else ""))
        self.setAccessibleName(("Erro. " if nivel == "erro" else "") + texto)
        self.style().unpolish(self)
        self.style().polish(self)
        self.show()

    def limpar(self) -> None:
        self.setText("")
        self.hide()


class LinhaDownload(QFrame):
    """Barra de progresso de um download em andamento."""

    def __init__(self, dado: dict, escala: float = 1.0, pai: QWidget | None = None):
        super().__init__(pai)
        self.setObjectName("caixa")
        col = QVBoxLayout(self)
        col.setContentsMargins(13, 10, 13, 11)
        col.setSpacing(7)

        topo = QHBoxLayout()
        nome = QLabel(dado["titulo"])
        nome.setStyleSheet(f"font-size: {tema.px(12, escala)}px;")
        pct = round(dado["progresso"] * 100)
        info = QLabel("concluído" if dado["terminou"] else
                      f"{pct}% · {formatar_bytes(dado['velocidade'])}/s"
                      f" · {dado['seeds']} seeds")
        info.setObjectName("metaCartao")
        topo.addWidget(nome)
        topo.addStretch(1)
        topo.addWidget(info)
        col.addLayout(topo)

        barra = QProgressBar()
        barra.setRange(0, 100)
        barra.setValue(pct)
        barra.setTextVisible(False)
        barra.setFixedHeight(tema.px(5, escala))
        barra.setAccessibleName(f"Progresso de {dado['titulo']}")
        barra.setAccessibleDescription(f"{pct} por cento")
        col.addWidget(barra)


def icone_visao(modo: str, cor: str, lado: int = 14):
    """Desenha o icone de grade ou de lista. Fonte nenhuma precisa colaborar."""
    from PySide6.QtGui import QIcon
    pm = QPixmap(lado, lado)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(cor))
    p.setPen(Qt.NoPen)
    if modo == "grade":
        c = (lado - 3) // 2
        for x in (0, c + 3):
            for y in (0, c + 3):
                p.drawRoundedRect(x, y, c, c, 1, 1)
    else:
        altura = 2
        for i, y in enumerate((1, lado // 2 - 1, lado - 3)):
            p.drawRoundedRect(0, y, 3, altura, 1, 1)
            p.drawRoundedRect(5, y, lado - 5, altura, 1, 1)
    p.end()
    return QIcon(pm)


def rotulo_secao(texto: str) -> QLabel:
    r = QLabel(texto.upper())
    r.setObjectName("tituloSecao")
    return r


def ajuda(texto: str) -> QLabel:
    r = QLabel(texto)
    r.setObjectName("ajuda")
    r.setWordWrap(True)
    return r


def separador(cor: str) -> QFrame:
    linha = QFrame()
    linha.setFrameShape(QFrame.HLine)
    linha.setFixedHeight(1)
    linha.setStyleSheet(f"background: {cor}; border: none;")
    return linha
