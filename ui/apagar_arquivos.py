"""Escolher quais arquivos apagar do disco.

Ate aqui so dava para "remover torrent", que tira a obra do cliente e deixa a
midia no disco — util para parar de semear, inutil para liberar espaco. E
quando dava para apagar, apagava o release inteiro: numa serie de vinte
episodios nao havia como apagar so os cinco ja assistidos.

A tela mostra o que existe no disco agora, um arquivo por linha, com tamanho, e
soma o que voce marcou. Antes de apagar, diz quanto vai sair e se ainda ha quem
semeie — porque so nesse caso apagar e reversivel.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from core import apagar as nucleo

from . import tema, widgets
from .widgets import formatar_bytes


class ApagarArquivos(QDialog):
    """Lista os arquivos no disco e apaga os marcados."""

    def __init__(self, con: sqlite3.Connection, cfg, item_id: int, titulo: str,
                 paleta: tema.Paleta, escala: float, pai=None):
        super().__init__(pai)
        self.con = con
        self.cfg = cfg
        self.paleta = paleta
        self.escala = escala
        self.titulo = titulo
        self.arquivos = nucleo.listar(con, cfg, item_id)
        self.marcas: list[tuple[QCheckBox, nucleo.Arquivo]] = []
        self.apagados = 0
        self.bytes_livres = 0

        self.setWindowTitle("Apagar arquivos")
        self.setModal(True)
        self.resize(tema.px(620, escala), tema.px(560, escala))
        self._montar()
        self._recontar()

    # ------------------------------------------------------------ montagem

    def _montar(self) -> None:
        p, e = self.paleta, self.escala
        col = QVBoxLayout(self)
        m = tema.px(20, e)
        col.setContentsMargins(m, m, m, tema.px(14, e))
        col.setSpacing(tema.px(10, e))

        t = QLabel(f"Apagar arquivos de “{self.titulo}”")
        t.setObjectName("tituloSecaoGrande")
        t.setWordWrap(True)
        col.addWidget(t)

        col.addWidget(widgets.ajuda(
            "Só a mídia é apagada. O arquivo .torrent continua no índice, então "
            "a obra segue no catálogo e dá para baixar de novo depois."))

        if not self.arquivos:
            col.addWidget(widgets.ajuda(
                "Nada desta obra está no disco agora."))
            self._rodape(col, so_fechar=True)
            return

        # --- semeadores: e o que decide se apagar e reversivel
        self.sem_semeadores = sorted({
            a.caminho_torrent for a in self.arquivos
            if not nucleo.semeado(self.con, self.cfg, a.caminho_torrent)[0]})
        if self.sem_semeadores:
            aviso = QLabel(
                "Atenção: parte disto não tem semeadores conhecidos. Sem alguém "
                "compartilhando, apagar é definitivo — não dá para baixar de "
                "volta. Use “Conferir semeadores” na tela da obra se a "
                "informação estiver velha.")
            aviso.setWordWrap(True)
            aviso.setStyleSheet(
                f"color: {self.paleta.ambar}; background: {self.paleta.ambar_fundo};"
                f" border-radius: 6px; padding: {tema.px(10, e)}px;")
            col.addWidget(aviso)

        topo = QHBoxLayout()
        b_todos = QPushButton("Marcar todos")
        b_todos.clicked.connect(lambda: self._marcar(True))
        topo.addWidget(b_todos)
        b_nenhum = QPushButton("Desmarcar todos")
        b_nenhum.clicked.connect(lambda: self._marcar(False))
        topo.addWidget(b_nenhum)
        topo.addStretch(1)
        col.addLayout(topo)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        dentro = QWidget()
        lista = QVBoxLayout(dentro)
        lista.setContentsMargins(0, 0, 0, 0)
        lista.setSpacing(tema.px(5, e))
        for a in self.arquivos:
            lista.addWidget(self._linha(a))
        lista.addStretch(1)
        area.setWidget(dentro)
        col.addWidget(area, 1)

        self.rot_total = QLabel()
        self.rot_total.setStyleSheet(
            f"color: {p.forte}; font-size: {tema.px(13, e)}px; font-weight: 600;")
        col.addWidget(self.rot_total)
        self._rodape(col)

    def _linha(self, a: nucleo.Arquivo) -> QFrame:
        caixa = QFrame()
        caixa.setObjectName("linhaArquivo")
        lay = QHBoxLayout(caixa)
        lay.setContentsMargins(tema.px(11, self.escala), tema.px(7, self.escala),
                               tema.px(13, self.escala), tema.px(7, self.escala))
        lay.setSpacing(tema.px(10, self.escala))

        marca = QCheckBox(a.rotulo)
        marca.setAccessibleName(f"Apagar {a.rotulo}, {formatar_bytes(a.bytes)}")
        marca.stateChanged.connect(self._recontar)
        lay.addWidget(marca)
        self.marcas.append((marca, a))

        nome = QLabel(a.caminho.name)
        nome.setObjectName("nomeArquivoBruto")
        nome.setToolTip(str(a.caminho))
        lay.addWidget(nome, 1)

        tam = QLabel(formatar_bytes(a.bytes))
        tam.setObjectName("metaCartao")
        lay.addWidget(tam)
        return caixa

    def _rodape(self, col: QVBoxLayout, so_fechar: bool = False) -> None:
        linha = QHBoxLayout()
        linha.addStretch(1)
        if not so_fechar:
            self.b_apagar = QPushButton("Apagar os marcados")
            self.b_apagar.setObjectName("botaoGrande")
            self.b_apagar.setProperty("perigo", "true")
            self.b_apagar.setAccessibleName("Apagar do disco os arquivos marcados")
            self.b_apagar.clicked.connect(self._apagar)
            linha.addWidget(self.b_apagar)
        b_fechar = QPushButton("Fechar")
        b_fechar.clicked.connect(self.reject)
        linha.addWidget(b_fechar)
        col.addLayout(linha)

    # ------------------------------------------------------------- acoes

    def _marcar(self, valor: bool) -> None:
        for marca, _ in self.marcas:
            marca.setChecked(valor)

    def _escolhidos(self) -> list[nucleo.Arquivo]:
        return [a for marca, a in self.marcas if marca.isChecked()]

    def _recontar(self) -> None:
        escolhidos = self._escolhidos()
        total = sum(a.bytes for a in escolhidos)
        self.rot_total.setText(
            f"{len(escolhidos)} de {len(self.arquivos)} marcados  ·  "
            f"{formatar_bytes(total)} seriam liberados")
        if hasattr(self, "b_apagar"):
            self.b_apagar.setEnabled(bool(escolhidos))

    def _apagar(self) -> None:
        escolhidos = self._escolhidos()
        if not escolhidos:
            return
        total = sum(a.bytes for a in escolhidos)

        sem_semear = [a for a in escolhidos
                      if a.caminho_torrent in getattr(self, "sem_semeadores", [])]
        texto = (f"Apagar {len(escolhidos)} arquivo(s) do disco?\n\n"
                 f"{formatar_bytes(total)} serão liberados.")
        if sem_semear:
            texto += (f"\n\n{len(sem_semear)} deles não têm semeadores "
                      "conhecidos. Esses não voltam: apagar é definitivo.")

        caixa = QMessageBox(self)
        caixa.setWindowTitle("Apagar do disco")
        caixa.setIcon(QMessageBox.Warning)
        caixa.setText(texto)
        b_sim = caixa.addButton("Apagar", QMessageBox.DestructiveRole)
        caixa.addButton("Cancelar", QMessageBox.RejectRole)
        caixa.exec()
        if caixa.clickedButton() is not b_sim:
            return

        r = nucleo.apagar(self.con, self.cfg, escolhidos, confirmar=True,
                          ignorar_saude=bool(sem_semear))
        self.apagados, self.bytes_livres = r.apagados, r.bytes
        if r.erros:
            QMessageBox.warning(
                self, "Nem tudo saiu",
                f"{r.apagados} apagado(s).\n\n" + "\n".join(r.erros[:6]))
        self.accept()
