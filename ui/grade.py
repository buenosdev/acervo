"""Grade do catalogo, virtualizada.

A versao anterior criava um widget por obra e destruia todos a cada troca de
filtro - com 155 itens isso trava a janela por segundos. Aqui a lista e um
modelo e a pintura e um delegate: o Qt desenha apenas as celulas visiveis,
reusa o mesmo pintor para todas, e trocar de filtro vira uma troca de lista em
memoria. Rolar 1.000 itens custa o mesmo que rolar 10.

O delegate desenha o mesmo cartao de antes: capa, selo de estado, etiqueta de
qualidade, barra de progresso quando esta baixando, titulo e metadados.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QEasingCurve, QModelIndex,
                            QPoint, QPropertyAnimation, QRect, QRectF, QSize,
                            Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate

from . import tema
from .widgets import (PROPORCAO_CAPA, ROTULO_TIPO, TAMANHOS_CARTAO, capa_pronta,
                      carregador, converter_prontas, formatar_bytes,
                      geracao_capas, pedir_capa)

PAPEL_OBRA = Qt.UserRole + 1

# Como o cartao reage ao mouse. Cada um custa coisas diferentes e incomoda de
# jeitos diferentes; nenhum e obviamente melhor, por isso e uma escolha.
ESTILOS_HOVER = {
    "borda":  "Só a borda acende, com transição suave",
    "elevar": "A borda acende e o cartão cresce um pouco",
    "rodape": "Borda suave, e a ficha aparece no rodapé da janela",
}
# Quanto tempo a borda leva para acender e apagar. Curto o bastante para
# acompanhar o mouse, longo o bastante para nao parecer um pisca-pisca.
DURACAO_REALCE = 170        # ms
PASSO_REALCE = 16           # ms entre quadros da transicao
# Quanto o cartao encolhe no estado normal, para ter para onde crescer no
# hover sem estourar a celula — crescer de verdade seria recortado pelo Qt.
FOLGA_ELEVAR = 5

_TEXTO_ESTADO = {"completo": "no disco", "parcial": "baixado pela metade",
                 "indice": "só no índice", "orfao": "sem torrent"}


class ModeloObras(QAbstractListModel):
    """Lista de obras. Trocar o conteudo e uma operacao so."""

    def __init__(self, pai=None):
        super().__init__(pai)
        self._obras: list[dict] = []

    def definir(self, obras: list[dict]) -> None:
        self.beginResetModel()
        self._obras = obras
        self.endResetModel()

    def rowCount(self, pai=QModelIndex()) -> int:      # noqa: N802
        return 0 if pai.isValid() else len(self._obras)

    def data(self, indice: QModelIndex, papel=Qt.DisplayRole):
        if not indice.isValid() or indice.row() >= len(self._obras):
            return None
        obra = self._obras[indice.row()]
        if papel == PAPEL_OBRA:
            return obra
        if papel == Qt.DisplayRole:
            return obra["titulo"]
        if papel == Qt.AccessibleTextRole:
            return obra["titulo"]
        if papel == Qt.AccessibleDescriptionRole:
            partes = [ROTULO_TIPO.get(obra.get("tipo"), ""), str(obra.get("ano") or ""),
                      (obra.get("qualidades") or [""])[-1],
                      _TEXTO_ESTADO.get(obra.get("estado", ""), ""),
                      formatar_bytes(obra.get("bytes_total"))]
            if obra.get("fixado"):
                partes.append("protegido")
            return ", ".join(x for x in partes if x)
        if papel == Qt.ToolTipRole:
            return obra["titulo"]
        return None

    def obra_em(self, indice: QModelIndex) -> dict | None:
        if indice.isValid() and indice.row() < len(self._obras):
            return self._obras[indice.row()]
        return None


class DelegateCartao(QStyledItemDelegate):
    """Pinta um cartao. Um so objeto serve para a grade inteira."""

    def __init__(self, pasta_posters: Path, paleta: tema.Paleta, escala: float,
                 largura: int, modo: str = "grade", pai=None):
        super().__init__(pai)
        self.pasta_posters = pasta_posters
        self.paleta = paleta
        self.escala = escala
        self.largura = largura
        self.modo = modo
        self.progresso: dict[str, dict] = {}     # infohash -> dados do download
        self.estilo_hover = "borda"
        # linha -> intensidade do realce, entre 0 e 1.
        self.realces: dict[int, float] = {}
        self._baixando: frozenset[str] = frozenset()
        self._cache_cartao: dict[tuple, QPixmap] = {}
        self._geracao_capas = geracao_capas()
        self._cache_linhas: dict[tuple, list[str]] = {}
        self._recalcular()

    def configurar(self, paleta: tema.Paleta, escala: float, largura: int,
                   modo: str) -> None:
        self.paleta, self.escala, self.largura, self.modo = paleta, escala, largura, modo
        self._recalcular()

    def definir_progresso(self, por_infohash: dict[str, dict]) -> None:
        """Recebe o progresso e so joga o cache fora quando o selo muda.

        A porcentagem e desenhada por cima do cartao ja pronto, entao mudar de
        37% para 38% nao invalida nada. O que invalida e um item comecar ou
        parar de baixar, porque ai o selo do cartao vira "BAIXANDO".
        """
        self.progresso = por_infohash
        agora = frozenset(h for h, d in por_infohash.items() if not d.get("terminou"))
        if agora != self._baixando:
            self._baixando = agora
            self._cache_cartao.clear()

    def _recalcular(self) -> None:
        # Tudo o que nao depende da obra e calculado uma vez aqui. Antes, cada
        # cartao criava QFont, QFontMetrics e QPainterPath a cada repintura —
        # com 155 cartoes na tela isso era o que fazia a rolagem pular quadros.
        self._cache_cartao.clear()
        self._cache_linhas.clear()

        from PySide6.QtGui import QGuiApplication
        tela = QGuiApplication.primaryScreen()
        self._dpr = tela.devicePixelRatio() if tela else 1.0

        nome_mono = tema.fonte_mono().split(",")[0].strip('"')
        self.f_titulo = QFont()
        self.f_titulo.setPixelSize(tema.px(13, self.escala))
        self.f_titulo.setWeight(QFont.DemiBold)
        self.fm_titulo = QFontMetrics(self.f_titulo)

        self.f_mono = QFont(nome_mono)
        self.f_mono.setPixelSize(tema.px(11, self.escala))
        self.fm_mono = QFontMetrics(self.f_mono)

        self.f_selo = QFont(nome_mono)
        self.f_selo.setPixelSize(tema.px(10, self.escala))
        self.fm_selo = QFontMetrics(self.f_selo)

        self.f_selo_forte = QFont(self.f_selo)
        self.f_selo_forte.setWeight(QFont.DemiBold)
        self.fm_selo_forte = QFontMetrics(self.f_selo_forte)

        self.f_cadeado = QFont()
        self.f_cadeado.setPixelSize(tema.px(11, self.escala))

        # medidas em pixel, tambem uma vez so
        e = self.escala
        self.m = {n: tema.px(n, e) for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 14,
                                            15, 16, 17, 19, 20, 21, 30, 300)}
        self.m5_meio = tema.px(5.5, e)

        if self.modo == "lista":
            self.altura_linha = tema.px(64, e)
            self.largura_capa = int(self.altura_linha / PROPORCAO_CAPA)
        else:
            self.altura_capa = int(self.largura * PROPORCAO_CAPA)
            self.altura_texto = (self.m[9] + self.m[17] * 2 + self.m[4]
                                 + self.m[14] + self.m[10])

    def sizeHint(self, opcao, indice) -> QSize:        # noqa: N802
        if self.modo == "lista":
            return QSize(320, self.altura_linha)
        return QSize(self.largura, self.altura_capa + self.altura_texto)

    # ------------------------------------------------------------- pintura

    def paint(self, p: QPainter, opcao, indice) -> None:
        obra = indice.data(PAPEL_OBRA)
        if not obra:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        area = opcao.rect
        destacado = bool(opcao.state & (QStyle.State_MouseOver | QStyle.State_Selected))
        focado = bool(opcao.state & QStyle.State_HasFocus)

        if self.modo == "lista":
            self._lista(p, area, obra, destacado, focado)
        else:
            self._grade(p, area, obra, destacado, focado, indice.row())
        p.restore()

    def _realce(self, p: QPainter, area: QRect, obra: dict, focado: bool,
                forca: float = 1.0) -> None:
        """A borda acendendo. `forca` vai de 0 a 1 ao longo da transicao.

        Tudo e desenhado DENTRO da celula, e por um motivo pratico: a versao
        anterior punha o halo alguns pixels para fora, e como a transicao
        repinta so a celula que mudou, o que vazara para as vizinhas ficava
        la — a borda fantasma que sobrava depois de o mouse sair.

        Sao duas camadas mesmo assim: um halo largo por dentro, recortado pela
        propria celula, e o traco fino na borda. O halo e o que da impressao de
        luz; so o traco pareceria um retangulo ligando e desligando.
        """
        if forca <= 0.01 and not focado:
            return
        pal = self.paleta
        forca = max(0.0, min(1.0, forca))
        cor = QColor(pal.azul)

        p.save()
        p.setClipRect(area)               # nada escapa para a celula vizinha
        p.setBrush(Qt.NoBrush)

        # Halo por dentro: engrossa conforme acende. Metade do traco cai fora
        # do recorte, e o que sobra e uma luz encostada na borda.
        halo = QColor(cor)
        halo.setAlpha(int(58 * forca))
        largura_halo = 3.0 + 5.0 * forca
        p.setPen(QPen(halo, largura_halo))
        p.drawRoundedRect(QRectF(area.x() + 0.5, area.y() + 0.5,
                                 area.width() - 1, area.height() - 1), 6, 6)

        traco = QColor(cor)
        traco.setAlpha(int(70 + 185 * forca))
        p.setPen(QPen(traco, 2.0 if focado else 1.0 + 0.6 * forca))
        p.drawRoundedRect(QRectF(area.x() + 0.5, area.y() + 0.5,
                                 area.width() - 1, area.height() - 1), 6, 6)
        p.restore()

    def _moldura(self, p: QPainter, area: QRect, destacado: bool,
                 focado: bool, raio: int = 6) -> QPainterPath:
        pal = self.paleta
        r = QRectF(area.x() + 0.5, area.y() + 0.5, area.width() - 1, area.height() - 1)
        caminho = QPainterPath()
        caminho.addRoundedRect(r, raio, raio)
        p.fillPath(caminho, QColor(pal.cartao))
        cor = pal.azul if focado else (pal.borda_txt if destacado else pal.cartao_bd)
        p.setPen(QPen(QColor(cor), 2 if focado else 1))
        p.drawPath(caminho)
        return caminho

    def _grade(self, p: QPainter, area: QRect, obra: dict,
               destacado: bool, focado: bool, indice_linha: int = -1) -> None:
        """Cartao pronto vem do cache; so o hover e o progresso mudam.

        Tudo o que reage ao mouse e desenhado aqui, dentro da celula. Nada de
        janela flutuante: ela custa uma janela nativa por vez, pisca ao entrar e
        sair, e cobre o catalogo justamente quando a pessoa esta varrendo com os
        olhos.
        """
        forca = self.realces.get(indice_linha, 1.0 if destacado else 0.0)
        cheio = area
        if self.estilo_hover == "elevar":
            # Cresce sem estourar a celula: no estado normal o cartao fica um
            # pouco menor, e o hover devolve o tamanho inteiro. Crescer para
            # fora seria recortado pelo Qt. Com `forca`, cresce aos poucos.
            folga = int(round(FOLGA_ELEVAR * (1.0 - forca)))
            cheio = area.adjusted(folga, folga, -folga, -folga)

        pm = self._cartao_estatico(obra)
        if cheio.size() != pm.size():
            p.drawPixmap(cheio, pm)
        else:
            p.drawPixmap(cheio.topLeft(), pm)

        if forca > 0.01 or focado:
            self._realce(p, cheio, obra, focado, forca)

        dados = self.progresso.get(obra.get("infohash_ativo") or "")
        if dados and not dados.get("terminou"):
            escala = cheio.width() / max(1, self.largura)
            area_capa = QRect(cheio.x() + 1, cheio.y() + 1,
                              cheio.width() - 2, int(self.altura_capa * escala))
            p.save()
            p.setClipRect(area_capa)
            self._faixa_progresso(p, area_capa, obra)
            p.restore()

    def _cartao_estatico(self, obra: dict) -> QPixmap:
        """A parte do cartao que so muda quando a obra ou o tema muda."""
        geracao = geracao_capas()
        if geracao != self._geracao_capas:    # alguma capa mudou desde a ultima
            self._geracao_capas = geracao
            self._cache_cartao.clear()

        baixando = bool(self.progresso.get(obra.get("infohash_ativo") or ""))
        chave = (obra["id"], baixando)
        pronto = self._cache_cartao.get(chave)
        if pronto is not None:
            return pronto

        largura = self.largura
        altura = self.altura_capa + self.altura_texto
        dpr = self._dpr
        pm = QPixmap(int(largura * dpr), int(altura * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)

        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        area = QRect(0, 0, largura, altura)
        pal = self.paleta

        moldura = self._moldura(p, area, False, False)
        p.save()
        p.setClipPath(moldura)

        arquivo = (self.pasta_posters / obra["poster"]
                   if obra.get("poster") else None)
        capa = capa_pronta(arquivo, obra["titulo"], largura)
        area_capa = QRect(1, 1, largura - 2, self.altura_capa)
        if capa is not None:
            p.drawPixmap(area_capa, capa)
        else:
            # Ainda lendo: um retangulo neutro entra no lugar e a capa aparece
            # sozinha quando estiver pronta. Antes a leitura acontecia aqui
            # dentro e cada fila nova custava ~63 ms de engasgo.
            pedir_capa(arquivo, largura)
            p.fillRect(area_capa, QColor(pal.elevado))

        self._selo(p, area_capa, obra)
        qualidades = obra.get("qualidades") or []
        if qualidades:
            self._etiqueta_dir(p, area_capa, qualidades[-1])
        if obra.get("fixado"):
            self._cadeado(p, area_capa)
        p.restore()

        margem = self.m[10]
        largura_texto = largura - margem * 2
        y = self.altura_capa + self.m[9]

        p.setFont(self.f_titulo)
        fm = self.fm_titulo
        p.setPen(QColor(pal.forte))
        for linha in self._linhas_titulo(obra["titulo"], largura_texto):
            y += fm.ascent()
            p.drawText(margem, y, linha)
            y += fm.descent() + self.m[2]

        p.setFont(self.f_mono)
        p.setPen(QColor(pal.tenue))
        base_y = altura - self.m[10]
        p.drawText(margem, base_y, formatar_bytes(obra.get("bytes_total")))
        direita = (f"{obra['temporadas']} temp." if obra.get("temporadas")
                   else str(obra.get("ano") or ""))
        if direita:
            p.drawText(largura - margem - self.fm_mono.horizontalAdvance(direita),
                       base_y, direita)
        p.end()

        # Cartao com capa provisoria nao entra no cache: ele precisa ser
        # repintado assim que a imagem de verdade chegar.
        if capa is not None:
            if len(self._cache_cartao) > 400:  # nao cresce sem limite
                self._cache_cartao.clear()
            self._cache_cartao[chave] = pm
        return pm

    def _linhas_titulo(self, titulo: str, largura: int) -> list[str]:
        """Quebra de linha e cara e o titulo nao muda: guarda o resultado."""
        chave = (titulo, largura)
        linhas = self._cache_linhas.get(chave)
        if linhas is None:
            linhas = _quebrar(titulo, self.fm_titulo, largura, 2)
            if len(self._cache_linhas) > 2000:
                self._cache_linhas.clear()
            self._cache_linhas[chave] = linhas
        return linhas

    def _lista(self, p: QPainter, area: QRect, obra: dict,
               destacado: bool, focado: bool) -> None:
        pal = self.paleta
        moldura = self._moldura(p, area, destacado, focado, raio=5)
        p.save()
        p.setClipPath(moldura)
        arquivo = (self.pasta_posters / obra["poster"]
                   if obra.get("poster") else None)
        capa = capa_pronta(arquivo, obra["titulo"], self.largura_capa)
        destino = QRect(area.x() + 1, area.y() + 1,
                        self.largura_capa, area.height() - 2)
        if capa is not None:
            p.drawPixmap(destino, capa)
        else:
            pedir_capa(arquivo, self.largura_capa)
            p.fillRect(destino, QColor(pal.elevado))
        p.restore()

        x = area.x() + self.largura_capa + tema.px(14, self.escala)
        meio = area.center().y()

        p.setFont(self.f_titulo)
        fm = self.fm_titulo
        p.setPen(QColor(pal.forte))
        largura_titulo = max(80, area.width() - self.largura_capa - self.m[300])
        p.drawText(x, meio - self.m[2],
                   fm.elidedText(obra["titulo"], Qt.ElideRight, largura_titulo))

        p.setFont(self.f_mono)
        p.setPen(QColor(pal.tenue))
        sub = " · ".join(v for v in [
            ROTULO_TIPO.get(obra.get("tipo"), ""), str(obra.get("ano") or ""),
            (obra.get("qualidades") or [""])[-1]] if v)
        p.drawText(x, meio + self.m[15], sub)

        fm2 = self.fm_mono
        tamanho = formatar_bytes(obra.get("bytes_total"))
        borda_dir = area.right() - self.m[14]
        p.drawText(borda_dir - fm2.horizontalAdvance(tamanho),
                   meio + self.m[5], tamanho)

        chave, rotulo = tema.CORES_ESTADO.get(obra.get("estado", "indice"), ("tenue", ""))
        largura_selo = fm2.horizontalAdvance(rotulo) + self.m[20]
        self._pilula(p, QColor(getattr(pal, chave)), rotulo, self.f_mono,
                     borda_dir - fm2.horizontalAdvance(tamanho)
                     - self.m[16] - largura_selo,
                     meio - self.m[9], largura_selo)

    # ------------------------------------------------------------- adornos

    def _selo(self, p: QPainter, area: QRect, obra: dict) -> None:
        chave, rotulo = tema.CORES_ESTADO.get(obra.get("estado", "indice"), ("tenue", "?"))
        # Baixando ganha destaque proprio, como na referencia.
        dados = self.progresso.get(obra.get("infohash_ativo") or "")
        if dados and not dados.get("terminou"):
            # Pausado nao e o mesmo que baixando: dizer "BAIXANDO" numa barra
            # que nao anda e informacao errada.
            if dados.get("pausado"):
                chave, rotulo = "ambar", "PAUSADO"
            else:
                chave, rotulo = "azul", "BAIXANDO"
        largura = self.fm_selo_forte.horizontalAdvance(rotulo) + self.m[21]
        self._pilula(p, QColor(getattr(self.paleta, chave)), rotulo,
                     self.f_selo_forte, area.x() + self.m[7],
                     area.y() + self.m[7], largura)

    def _pilula(self, p: QPainter, cor: QColor, texto: str, fonte: QFont,
                x: int, y: int, largura: int) -> None:
        fm = (self.fm_selo_forte if fonte is self.f_selo_forte else
              self.fm_selo if fonte is self.f_selo else
              self.fm_mono if fonte is self.f_mono else QFontMetrics(fonte))
        altura = fm.height() + self.m[5]
        caminho = QPainterPath()
        caminho.addRoundedRect(QRectF(x, y, largura, altura), 3, 3)
        p.fillPath(caminho, QColor(0, 0, 0, 205))
        r = self.m[5]
        p.setBrush(cor)
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(x + self.m[6]), int(y + altura / 2 - r / 2), r, r)
        p.setBrush(Qt.NoBrush)
        p.setFont(fonte)
        p.setPen(cor)
        p.drawText(int(x + self.m[15]),
                   int(y + altura / 2 + fm.capHeight() / 2), texto)

    def _etiqueta_dir(self, p: QPainter, area: QRect, texto: str) -> None:
        fm = self.fm_selo
        largura = fm.horizontalAdvance(texto) + self.m[11]
        altura = fm.height() + self.m[5]
        x = area.right() - self.m[7] - largura
        y = area.y() + self.m[7]
        caminho = QPainterPath()
        caminho.addRoundedRect(QRectF(x, y, largura, altura), 3, 3)
        p.fillPath(caminho, QColor(0, 0, 0, 190))
        p.setFont(self.f_selo)
        p.setPen(QColor("#c8c8d2"))
        p.drawText(int(x + self.m5_meio),
                   int(y + altura / 2 + fm.capHeight() / 2), texto)

    def _faixa_progresso(self, p: QPainter, area: QRect, obra: dict) -> None:
        """Percentual, velocidade e barra sobre a capa, como na referencia."""
        dados = self.progresso.get(obra.get("infohash_ativo") or "")
        if not dados or dados.get("terminou"):
            return
        parado = bool(dados.get("pausado"))
        pct = dados["progresso"]
        altura = self.m[30]
        y = area.bottom() - altura
        p.fillRect(QRect(area.x(), y, area.width(), altura), QColor(0, 0, 0, 165))

        p.setFont(self.f_selo)
        fm = self.fm_selo
        margem = self.m[8]
        p.setPen(QColor("#d8d8e2"))
        p.drawText(area.x() + margem, y + fm.height(), f"{round(pct * 100)}%")
        if dados.get("velocidade"):
            v = f"{formatar_bytes(dados['velocidade'])}/s"
            p.setPen(QColor(self.paleta.azul))
            p.drawText(area.right() - margem - fm.horizontalAdvance(v),
                       y + fm.height(), v)

        trilho = QRect(area.x() + margem, area.bottom() - self.m[8],
                       area.width() - margem * 2, self.m[3])
        p.fillRect(trilho, QColor(255, 255, 255, 45))
        p.fillRect(QRect(trilho.x(), trilho.y(), int(trilho.width() * pct),
                         trilho.height()),
                   QColor(self.paleta.ambar if parado else self.paleta.azul))

    def _cadeado(self, p: QPainter, area: QRect) -> None:
        fonte = self.f_cadeado
        largura = self.m[21]
        altura = self.m[19]
        x = area.right() - largura - self.m[7]
        y = area.bottom() - altura - self.m[7]
        caminho = QPainterPath()
        caminho.addRoundedRect(QRectF(x, y, largura, altura), 3, 3)
        p.fillPath(caminho, QColor(0, 0, 0, 190))
        p.setFont(fonte)
        p.setPen(QColor(self.paleta.ambar))
        # Cadeado desenhado: o emoji vinha colorido, fora da paleta, e
        # em alguns sistemas nem existe na fonte.
        p.setPen(QPen(QColor(self.paleta.ambar if hasattr(self, "paleta")
                             else "#f0ad2e"), max(1.4, altura * 0.09),
                      Qt.SolidLine, Qt.RoundCap))
        cx, cy = x + largura / 2, y + altura / 2
        r = altura * 0.19
        p.drawArc(QRectF(cx - r, cy - altura * 0.30, r * 2, r * 2),
                  0, 180 * 16)
        p.fillRect(QRectF(cx - r * 1.25, cy - altura * 0.06,
                          r * 2.5, altura * 0.32),
                   QColor(self.paleta.ambar if hasattr(self, "paleta")
                          else "#f0ad2e"))


def _quebrar(texto: str, fm: QFontMetrics, largura: int, maximo: int) -> list[str]:
    linhas: list[str] = []
    atual = ""
    for palavra in texto.split():
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
    if len(" ".join(linhas)) < len(texto):
        linhas[-1] = fm.elidedText(linhas[-1] + "…", Qt.ElideRight, largura)
    return linhas


class GradeObras(QListView):
    """A grade em si. Alterna entre cartoes e lista sem reconstruir nada."""

    abrir = Signal(int)
    sob_o_mouse = Signal(object)      # a obra sob o cursor, ou None

    def __init__(self, pasta_posters: Path, paleta: tema.Paleta, escala: float,
                 tamanho: str = "medio", modo: str = "grade", pai=None):
        super().__init__(pai)
        self.modelo = ModeloObras(self)
        self.setModel(self.modelo)

        self.delegate = DelegateCartao(
            pasta_posters, paleta, escala, TAMANHOS_CARTAO.get(tamanho, 158), modo)
        self.setItemDelegate(self.delegate)

        self.setUniformItemSizes(True)          # essencial para rolar liso
        self.setResizeMode(QListView.Adjust)
        self.setSelectionMode(QListView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.setMouseTracking(True)
        self.setFrameShape(QListView.NoFrame)
        self.viewport().setAttribute(Qt.WA_Hover)
        self.setAccessibleName("Catálogo")
        self.aplicar_modo(modo, tamanho)

        self.activated.connect(self._abrir)     # Enter e duplo clique
        self.clicked.connect(self._abrir)

        # Capa pronta: repinta so a area visivel. Vem sempre pela linha
        # principal, entao nao ha corrida com o desenho.
        # Rolagem suave: cada golpe de roda vira um deslizar curto em vez de um
        # salto seco. E o que separa "funciona" de "parece fluido".
        self._alvo_rolagem = 0.0
        self._deslizar = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._deslizar.setDuration(210)
        self._deslizar.setEasingCurve(QEasingCurve.OutCubic)

        # Previa ao pousar o mouse. So aparece depois de o mouse ficar parado:
        # surgir no primeiro pixel transformaria varrer a grade com os olhos
        # numa sequencia de paineis piscando.
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._sob_o_mouse = -1
        self._alvos: dict[int, float] = {}
        self._transicao = QTimer(self)
        self._transicao.setInterval(PASSO_REALCE)
        self._transicao.timeout.connect(self._andar_realce)

        carregador.sinais.pronta.connect(self._capa_chegou)
        self._repintar = QTimer(self)
        self._repintar.setSingleShot(True)
        self._repintar.setInterval(60)         # junta as que chegam em rajada
        self._repintar.timeout.connect(self._converter_e_repintar)

    # -------------------------------------------------------------- realce

    def _realcar(self, sai: int, entra: int) -> None:
        """Comeca a transicao: um cartao acendendo, o outro apagando.

        Cada linha tem um alvo (1 para o cartao sob o mouse, 0 para os demais) e
        caminha ate ele alguns milesimos por quadro. Sem isso a borda liga e
        desliga de uma vez, que e o que fazia o hover parecer duro.
        """
        if sai >= 0:
            self._alvos[sai] = 0.0
            self.delegate.realces.setdefault(sai, 1.0)
        if entra >= 0:
            self._alvos[entra] = 1.0
            self.delegate.realces.setdefault(entra, 0.0)
        if self._alvos and not self._transicao.isActive():
            self._transicao.start()

    def _andar_realce(self) -> None:
        """Um quadro da transicao. Repinta so as celulas que mudaram."""
        passo = PASSO_REALCE / max(1, DURACAO_REALCE)
        terminadas = []
        for linha, alvo in list(self._alvos.items()):
            atual = self.delegate.realces.get(linha, 0.0)
            if atual < alvo:
                atual = min(alvo, atual + passo)
            else:
                atual = max(alvo, atual - passo)
            self.delegate.realces[linha] = atual
            # O cache do cartao continua valendo mesmo no "elevar": o pixmap
            # e escalado na hora de desenhar, nao regravado.
            self.update(self.modelo.index(linha, 0))
            if abs(atual - alvo) < 0.001:
                self.delegate.realces[linha] = alvo
                terminadas.append(linha)

        for linha in terminadas:
            self._alvos.pop(linha, None)
            if self.delegate.realces.get(linha) == 0.0:
                self.delegate.realces.pop(linha, None)
        if not self._alvos:
            self._transicao.stop()

    # ---------------------------------------------------------- estilo

    def definir_estilo_hover(self, estilo: str) -> None:
        """Troca o jeito de reagir ao mouse, sem remontar a grade."""
        if estilo == self.delegate.estilo_hover:
            return
        self.delegate.estilo_hover = estilo
        self.delegate.realces.clear()
        self._alvos.clear()
        self.delegate._cache_cartao.clear()
        self.sob_o_mouse.emit(None)
        self.viewport().update()

    def mouseMoveEvent(self, evento) -> None:              # noqa: N802
        super().mouseMoveEvent(evento)
        indice = self.indexAt(evento.position().toPoint())
        linha = indice.row() if indice.isValid() else -1
        if linha == self._sob_o_mouse:
            return
        anterior, self._sob_o_mouse = self._sob_o_mouse, linha
        self._realcar(anterior, linha)
        self.sob_o_mouse.emit(self.modelo.obra_em(indice) if linha >= 0 else None)

    def leaveEvent(self, evento) -> None:                  # noqa: N802
        super().leaveEvent(evento)
        anterior, self._sob_o_mouse = self._sob_o_mouse, -1
        self._realcar(anterior, -1)
        self.sob_o_mouse.emit(None)

    def _capa_chegou(self, caminho: str, largura: int) -> None:
        self._repintar.start()

    def _converter_e_repintar(self) -> None:
        # Converter antes de repintar tira o custo de dentro do `paint`.
        if converter_prontas():
            self.delegate._cache_cartao.clear()
        self.viewport().update()

    def wheelEvent(self, evento) -> None:          # noqa: N802
        """Roda do mouse com deslizamento; touchpad fica com o Qt."""
        graus = evento.angleDelta().y()
        # Touchpad de precisao ja manda deslocamento em pixels e e suave por
        # natureza — animar por cima disso brigaria com o dedo do usuario.
        if evento.pixelDelta().y() or not graus:
            self._alvo_rolagem = float(self.verticalScrollBar().value())
            super().wheelEvent(evento)
            return

        barra = self.verticalScrollBar()
        if self._deslizar.state() != QPropertyAnimation.Running:
            self._alvo_rolagem = float(barra.value())

        passo = (self.delegate.altura_capa * 0.6 if self.delegate.modo != "lista"
                 else self.delegate.altura_linha * 2.2)
        alvo = self._alvo_rolagem - (graus / 120.0) * passo
        self._alvo_rolagem = max(barra.minimum(), min(barra.maximum(), alvo))

        self._deslizar.stop()
        self._deslizar.setStartValue(barra.value())
        self._deslizar.setEndValue(int(self._alvo_rolagem))
        self._deslizar.start()
        evento.accept()

    def _abrir(self, indice) -> None:
        obra = self.modelo.obra_em(indice)
        if obra:
            self.abrir.emit(obra["id"])

    def aplicar_modo(self, modo: str, tamanho: str) -> None:
        largura = TAMANHOS_CARTAO.get(tamanho, 158)
        self.delegate.configurar(self.delegate.paleta, self.delegate.escala,
                                 largura, modo)
        if modo == "lista":
            self.setViewMode(QListView.ListMode)
            self.setFlow(QListView.TopToBottom)
            self.setWrapping(False)
            self.setSpacing(tema.px(4, self.delegate.escala))
        else:
            self.setViewMode(QListView.IconMode)
            self.setFlow(QListView.LeftToRight)
            self.setWrapping(True)
            self.setSpacing(tema.px(7, self.delegate.escala))
        self.scheduleDelayedItemsLayout()

    def aplicar_tema(self, paleta: tema.Paleta, escala: float, tamanho: str,
                     modo: str) -> None:
        self.delegate.configurar(paleta, escala, TAMANHOS_CARTAO.get(tamanho, 158), modo)
        self.aplicar_modo(modo, tamanho)
        self.viewport().update()

    def definir_obras(self, obras: list[dict]) -> None:
        self._alvos.clear()
        self.delegate.realces.clear()
        self._sob_o_mouse = -1
        self.modelo.definir(obras)
        self.scrollToTop()
        self._alvo_rolagem = 0.0
        self._preaquecer(obras)

    def _preaquecer(self, obras: list[dict]) -> None:
        """Poe as primeiras capas na fila antes de alguem rolar ate elas.

        Sem isto o cartao aparece cinza e so depois recebe a imagem. Como a
        leitura ja e em segundo plano, adiantar o pedido custa nada a interface
        e faz a grade chegar pronta na maioria dos casos.
        """
        largura = (self.delegate.largura if self.delegate.modo != "lista"
                   else self.delegate.largura_capa)
        for obra in obras[:120]:
            if obra.get("poster"):
                pedir_capa(self.delegate.pasta_posters / obra["poster"], largura)

    def definir_progresso(self, por_infohash: dict[str, dict]) -> None:
        """Atualiza so a pintura; nao mexe no modelo, entao nao pisca."""
        self.delegate.definir_progresso(por_infohash)
        self.viewport().update()
