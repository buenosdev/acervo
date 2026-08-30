"""Previa da organizacao: mostra o que seria renomeado, antes de mexer em nada.

Foi a escolha do usuario: organizar so depois de confirmar. A tela lista cada
movimento como "de → para" e agrupa por obra. Nada sai do lugar sem um clique.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from core import consultas, db, library, organizer
from core.downloads import cliente

from . import tema, widgets
from .tarefas import vivo
from .widgets import Retorno, formatar_bytes


class TelaOrganizar(QScrollArea):
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
        self.planos: list[tuple[dict, organizer.Plano]] = []
        self.marcas: dict[str, QCheckBox] = {}

        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def aplicar_tema(self, paleta: tema.Paleta, escala: float) -> None:
        self.paleta, self.escala = paleta, escala

    # ------------------------------------------------------------ montagem

    def mostrar(self) -> None:
        self.planos = self._montar_planos()
        corpo = QWidget()
        col = QVBoxLayout(corpo)
        m = tema.px(34, self.escala)
        col.setContentsMargins(m, tema.px(22, self.escala), m, m)
        col.setSpacing(tema.px(14, self.escala))

        t = QLabel("Organizar a biblioteca")
        t.setObjectName("tituloSecaoGrande")
        col.addWidget(t)
        col.addWidget(widgets.ajuda(
            "Renomeia os arquivos para o padrão que Jellyfin, Plex e Kodi leem "
            "sozinhos. Nada é movido até você confirmar.\n"
            "Quando o torrent está no qBittorrent, a mudança é feita pela API dele "
            "— o seeding continua e não sobra cópia ocupando disco."))

        self.retorno = Retorno()
        col.addWidget(self.retorno)

        if not self.planos:
            vazio = Retorno()
            vazio.mostrar("info", "Nada para organizar agora.",
                          "Só aparece aqui o que já está no disco e ainda não está "
                          "no formato final. Use “Conferir disco” se acabou de baixar.")
            col.addWidget(vazio)
        else:
            total = sum(len(p.movimentos) for _, p in self.planos)
            col.addWidget(widgets.ajuda(
                f"{len(self.planos)} obras · {total} arquivos seriam renomeados."))
            self.marcas.clear()
            for release, plano in self.planos:
                col.addWidget(self._caixa(release, plano))

            acoes = QHBoxLayout()
            b = QPushButton("Organizar os marcados")
            b.setObjectName("botaoGrande")
            b.setProperty("destaque", "true")
            b.clicked.connect(self._aplicar)
            acoes.addWidget(b)
            acoes.addStretch(1)
            col.addLayout(acoes)

        col.addStretch(1)
        self.setWidget(corpo)

    def _montar_planos(self) -> list[tuple[dict, organizer.Plano]]:
        """Um plano por release que esta no disco e ainda nao esta organizado."""
        saida = []
        linhas = self.con.execute(
            "SELECT t.caminho, t.nome, t.infohash, d.caminho_local, d.gerenciado, "
            "       COALESCE(NULLIF(i.titulo_corrigido,''), i.titulo) titulo, i.tipo "
            "FROM torrents t "
            "JOIN disco d ON d.caminho_torrent = t.caminho "
            "JOIN itens i ON i.id = t.item_id "
            "WHERE d.estado = 'completo' AND t.corrompido = 0"
        ).fetchall()

        raiz = Path(self.cfg.biblioteca)
        for linha in linhas:
            plano = organizer.planejar(self.con, raiz, linha["caminho"])
            # Ja organizado: todo destino coincide com a origem.
            uteis = [mv for mv in plano.movimentos if Path(mv.de) != Path(mv.para)]
            if not uteis:
                continue
            plano.movimentos = uteis
            saida.append((dict(linha), plano))
        return saida

    def _caixa(self, release: dict, plano: organizer.Plano) -> QFrame:
        caixa = QFrame()
        caixa.setObjectName("release")
        col = QVBoxLayout(caixa)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(8)

        topo = QHBoxLayout()
        marca = QCheckBox(release["titulo"] or release["nome"])
        marca.setChecked(True)
        marca.setStyleSheet(f"font-weight: 600; color: {self.paleta.forte};")
        self.marcas[release["caminho"]] = marca
        topo.addWidget(marca)
        topo.addStretch(1)
        if release["gerenciado"]:
            topo.addWidget(widgets.Etiqueta("pelo qBittorrent", "info"))
        else:
            topo.addWidget(widgets.Etiqueta("mover no disco", "aviso"))
        col.addLayout(topo)

        for mv in plano.movimentos[:8]:
            linha = QLabel(f"{Path(mv.de).name}\n     →  "
                           f"{Path(mv.para).relative_to(Path(self.cfg.biblioteca))}"
                           if str(mv.para).startswith(str(self.cfg.biblioteca))
                           else f"{Path(mv.de).name}\n     →  {mv.para}")
            linha.setObjectName("ajuda")
            linha.setWordWrap(True)
            col.addWidget(linha)
        if len(plano.movimentos) > 8:
            col.addWidget(widgets.ajuda(f"… e mais {len(plano.movimentos) - 8} arquivos"))
        for aviso in plano.avisos[:2]:
            col.addWidget(widgets.ajuda(f"nota: {aviso}"))
        return caixa

    # -------------------------------------------------------------- aplicar

    def _aplicar(self) -> None:
        escolhidos = [(r, p) for r, p in self.planos
                      if self.marcas.get(r["caminho"], None)
                      and self.marcas[r["caminho"]].isChecked()]
        if not escolhidos:
            self.retorno.mostrar("info", "Nada marcado.")
            return

        total = sum(len(p.movimentos) for _, p in escolhidos)
        resposta = QMessageBox.question(
            self, "Organizar",
            f"Renomear {total} arquivo(s) de {len(escolhidos)} obra(s)?\n\n"
            "Nada é apagado — os arquivos só mudam de nome e de pasta.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resposta != QMessageBox.Yes:
            return

        self.retorno.mostrar("info", "Organizando…")
        cfg = self.cfg
        pedidos = [(dict(r), p) for r, p in escolhidos]

        def trabalho():
            q = cliente(cfg)
            no_ar = q is not None and q.disponivel()[0]
            relatos, feitos = [], 0
            for release, plano in pedidos:
                usar_cliente = bool(release["gerenciado"]) and no_ar
                linhas = organizer.executar(
                    plano, simular=False,
                    qbit=q if usar_cliente else None,
                    infohash=release["infohash"] if usar_cliente else None)
                feitos += sum(1 for x in linhas
                              if not x.startswith(("PULADO", "FALHOU")))
                relatos.extend(linhas)

            # Reconciliar aqui nao e um extra: organizar move os arquivos, e a
            # tabela `disco` guarda onde eles estavam. Sem esta volta, o app
            # perdia de vista tudo o que acabara de arrumar — a biblioteca
            # mostrava "só no índice" para filmes que estavam ali do lado.
            if feitos:
                proprio = db.conectar(cfg.banco)
                try:
                    seg = cfg.bruto.get("seguranca", {}) or {}
                    library.reconciliar(proprio, Path(cfg.biblioteca),
                                        seg.get("ignorar", []) or [],
                                        seg.get("protegidas", []) or [],
                                        extras=[Path(cfg.staging)])
                finally:
                    proprio.close()
            return feitos, relatos

        def pronto(resultado):
            if not vivo(self.retorno):
                return
            feitos, relatos = resultado
            problemas = [x for x in relatos if x.startswith(("PULADO", "FALHOU"))]
            self.retorno.mostrar(
                "ok" if not problemas else "aviso",
                f"{feitos} arquivo(s) organizados.",
                "\n".join(problemas[:6]) if problemas else "")
            self.mudou.emit()
            self.mostrar()

        self.executor.rodar("organizar", trabalho, pronto,
                            lambda m: self.retorno.mostrar("erro", m))


def quantos_pendentes(con: sqlite3.Connection, cfg) -> int:
    """Quantos releases no disco ainda nao estao no formato final.

    Alimenta o aviso discreto no topo do catalogo, sem abrir nada.
    """
    raiz = Path(cfg.biblioteca)
    n = 0
    for linha in con.execute(
        "SELECT t.caminho FROM torrents t JOIN disco d ON d.caminho_torrent = t.caminho "
        "WHERE d.estado = 'completo' AND t.corrompido = 0"
    ).fetchall():
        plano = organizer.planejar(con, raiz, linha["caminho"])
        if any(Path(mv.de) != Path(mv.para) for mv in plano.movimentos):
            n += 1
    return n
