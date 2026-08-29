"""Escolher o que baixar de dentro de um torrent.

Um torrent de temporada completa traz 10 episodios e 40 GB. Quem quer rever um
episodio nao precisa dos outros nove — e essa e justamente a promessa do app:
guardar o .torrent e trazer so o que vai assistir.

Os tres motores sabem desmarcar arquivo antes de comecar (`Motor.nao_baixar`),
e o app ja usava isso para pular propaganda. Faltava deixar a pessoa escolher.

Em jogo a escolha nao aparece: faltando uma parte do .rar, nada instala.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFrame,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from . import tema
from .widgets import formatar_bytes


class EscolherArquivos(QDialog):
    """Lista os arquivos do torrent com caixas de marcação."""

    def __init__(self, arquivos: list[dict], titulo: str, paleta: tema.Paleta,
                 escala: float, limpar_nome=None, pai=None):
        super().__init__(pai)
        self.paleta = paleta
        self.escala = escala
        self.arquivos = arquivos
        self._limpar = limpar_nome or (lambda x: x)
        self.marcas: dict[int, QCheckBox] = {}

        self.setWindowTitle("O que baixar")
        self.setModal(True)
        self.setMinimumWidth(tema.px(560, escala))
        # QDialog nao herda a folha da janela: sem isto o fundo sai no cinza
        # padrao do sistema e o titulo, escrito para tema escuro, some nele.
        self.setStyleSheet(f"QDialog {{ background: {paleta.fundo}; }}")

        col = QVBoxLayout(self)
        m = tema.px(18, escala)
        col.setContentsMargins(m, m, m, m)
        col.setSpacing(tema.px(10, escala))

        cab = QLabel(f"Escolha o que baixar de “{titulo}”")
        cab.setObjectName("tituloSecaoGrande")
        cab.setWordWrap(True)
        col.addWidget(cab)

        self.rot_total = QLabel()
        self.rot_total.setObjectName("ajuda")
        col.addWidget(self.rot_total)

        atalhos = QHBoxLayout()
        for rotulo, valor in (("Marcar todos", True), ("Desmarcar todos", False)):
            b = QPushButton(rotulo)
            b.setFlat(True)
            b.clicked.connect(lambda _=False, v=valor: self._todos(v))
            atalhos.addWidget(b)
        atalhos.addStretch(1)
        col.addLayout(atalhos)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setMinimumHeight(tema.px(300, escala))
        dentro = QWidget()
        lista = QVBoxLayout(dentro)
        lista.setContentsMargins(0, 0, tema.px(6, escala), 0)
        lista.setSpacing(tema.px(5, escala))

        # A ordem dentro do .torrent nao e a ordem dos episodios; ordenar pelo
        # caminho poe E01, E02, E03 na sequencia que a pessoa espera ler.
        for a in sorted(arquivos, key=lambda x: x["caminho"].lower()):
            lista.addWidget(self._linha(a))
        lista.addStretch(1)
        area.setWidget(dentro)
        col.addWidget(area, 1)

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.button(QDialogButtonBox.Ok).setText("Baixar os marcados")
        botoes.button(QDialogButtonBox.Ok).setObjectName("botaoGrande")
        botoes.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        self.botoes = botoes
        col.addWidget(botoes)

        self._recontar()

    # ------------------------------------------------------------- montagem

    def _linha(self, a: dict) -> QFrame:
        caixa = QFrame()
        caixa.setObjectName("linhaArquivo")
        lay = QHBoxLayout(caixa)
        lay.setContentsMargins(tema.px(11, self.escala), tema.px(7, self.escala),
                               tema.px(12, self.escala), tema.px(7, self.escala))
        lay.setSpacing(tema.px(10, self.escala))

        # Propaganda ja vem desmarcada: e o padrao do app, e ver isso explicado
        # ensina o que ele faz sozinho.
        lixo = a.get("tipo") == "lixo"
        marca = QCheckBox()
        marca.setChecked(not lixo)
        marca.setAccessibleName(f"Baixar {self._limpar(a['caminho'])}")
        marca.stateChanged.connect(self._recontar)
        self.marcas[a["indice"]] = marca
        lay.addWidget(marca)

        texto = QVBoxLayout()
        texto.setContentsMargins(0, 0, 0, 0)
        texto.setSpacing(tema.px(1, self.escala))
        nome = QLabel(self._limpar(a["caminho"]))
        nome.setObjectName("nomeEpisodio")
        texto.addWidget(nome)
        bruto = QLabel(a["caminho"])
        bruto.setObjectName("nomeArquivoBruto")
        bruto.setToolTip(a["caminho"])
        texto.addWidget(bruto)
        lay.addLayout(texto, 1)

        if lixo:
            etiqueta = QLabel("propaganda")
            etiqueta.setObjectName("metaCartao")
            lay.addWidget(etiqueta)

        tam = QLabel(formatar_bytes(a["tamanho"]))
        tam.setObjectName("metaCartao")
        lay.addWidget(tam, 0, Qt.AlignTop)
        return caixa

    # --------------------------------------------------------------- estado

    def _todos(self, valor: bool) -> None:
        for m in self.marcas.values():
            m.setChecked(valor)

    def _recontar(self) -> None:
        escolhidos = [a for a in self.arquivos
                      if self.marcas[a["indice"]].isChecked()]
        total = sum(a["tamanho"] for a in escolhidos)
        de_tudo = sum(a["tamanho"] for a in self.arquivos)
        self.rot_total.setText(
            f"{len(escolhidos)} de {len(self.arquivos)} arquivos · "
            f"{formatar_bytes(total)} de {formatar_bytes(de_tudo)}")
        self.botoes.button(QDialogButtonBox.Ok).setEnabled(bool(escolhidos))

    def pular(self) -> list[int]:
        """Indices que o usuario deixou desmarcados."""
        return [a["indice"] for a in self.arquivos
                if not self.marcas[a["indice"]].isChecked()]
