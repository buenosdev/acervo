"""Janela principal do Acervo.

Uma janela so: catalogo, detalhes da obra e configuracoes sao paginas de um
QStackedWidget, com um botao Voltar no topo. Nada abre por cima de nada — a
unica excecao sao as caixas de confirmacao, que e o lugar certo para uma
pergunta de sim ou nao.

A grade e virtualizada (ui/grade.py): trocar de filtro passou de ~625 ms para
~5 ms, porque nao ha mais 155 widgets sendo destruidos e recriados.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressBar, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from core import (config, consultas, db, downloads, guardar, importar,
                  metadata, scanner)
from core import library as biblioteca

from . import tema, widgets
from .grade import GradeObras
from .tarefas import Executor, vivo
from .widgets import formatar_bytes

LARGURA_LATERAL = 196
ALTURA_TOPO = 54

PAGINA_CATALOGO, PAGINA_ITEM, PAGINA_CONFIG, PAGINA_ORGANIZAR = 0, 1, 2, 3
PAGINA_PLAYER = 4

# Capas por leva. O TMDB pede uma pausa entre consultas, entao buscar as 150
# de uma vez deixaria uma tarefa presa por minutos. Em levas, o catalogo vai
# se preenchendo na frente do usuario.
CAPAS_POR_LEVA = 12


class Janela(QWidget):
    def __init__(self, cfg, pai: QWidget | None = None):
        super().__init__(pai)
        self.cfg = cfg
        prefs = cfg.bruto.get("aparencia") or {}
        self.paleta = tema.PALETAS.get(prefs.get("tema", "escuro"), tema.ESCURO)
        self.escala = tema.ESCALAS.get(prefs.get("fonte", "normal"), 1.0)
        self.tamanho_grade = prefs.get("tamanho_grade", "medio")
        self.modo = prefs.get("modo", "grade")

        self.executor = Executor()
        self.con: sqlite3.Connection = db.conectar(cfg.banco)
        self.filtro = {"tipo": "", "estado": "", "busca": "", "ordem": "titulo"}
        self._capas_pular = 0            # avanca sobre as que o TMDB nao conhece
        self.guia = None
        self._ja_guardados: set[str] = set()
        # id da obra -> "baixando" ou "pausado", segundo o cliente.
        self._no_cliente: dict[int, str] = {}

        self.setObjectName("raiz")
        self.setWindowTitle("Acervo")
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)          # arrastar .torrent para a janela

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        self.lateral = self._montar_lateral()
        raiz.addWidget(self.lateral)
        raiz.addWidget(self._montar_centro(), 1)

        self._atalhos()
        QTimer.singleShot(50, self.recarregar_tudo)
        self.relogio = QTimer(self)
        self.relogio.timeout.connect(self.atualizar_downloads)
        self.relogio.start(3000)

    # ------------------------------------------------------------- lateral

    def _montar_lateral(self) -> QWidget:
        lateral = QWidget()
        lateral.setObjectName("lateral")
        lateral.setFixedWidth(tema.px(LARGURA_LATERAL, self.escala))
        col = QVBoxLayout(lateral)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        marca = QWidget()
        ml = QVBoxLayout(marca)
        ml.setContentsMargins(20, 18, 20, 14)
        ml.setSpacing(2)
        titulo = QLabel("ACERVO")
        titulo.setObjectName("marca")
        sub = QLabel("Gerenciador local")
        sub.setObjectName("marcaSub")
        ml.addWidget(titulo)
        ml.addWidget(sub)
        col.addWidget(marca)
        col.addWidget(widgets.separador(self.paleta.linha))

        nav = QWidget()
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(10, 12, 10, 12)
        nl.setSpacing(1)
        self.grupo_nav = QButtonGroup(self)
        self.grupo_nav.setExclusive(True)
        self.botoes_nav: dict[str, QPushButton] = {}

        nl.addWidget(widgets.rotulo_secao("Biblioteca"))
        for chave, rotulo in (("", "Tudo"), ("filme", "Filmes"),
                              ("serie", "Séries"), ("jogo", "Jogos")):
            nl.addWidget(self._botao_nav("tipo", chave, rotulo))
        nl.addSpacing(14)

        nl.addWidget(widgets.rotulo_secao("Onde está"))
        for chave, rotulo in (("completo", "No disco"), ("parcial", "Baixando"),
                              ("indice", "Só no índice")):
            nl.addWidget(self._botao_nav("estado", chave, rotulo))
        nl.addStretch(1)
        col.addWidget(nav, 1)

        col.addWidget(widgets.separador(self.paleta.linha))
        arm = QWidget()
        al = QVBoxLayout(arm)
        al.setContentsMargins(18, 12, 18, 12)
        al.setSpacing(4)
        al.addWidget(widgets.rotulo_secao("Armazenamento"))
        self.rot_espaco = QLabel("—")
        self.rot_espaco.setObjectName("marca")
        self.rot_espaco_sub = QLabel("carregando…")
        self.rot_espaco_sub.setObjectName("ajuda")
        self.barra_espaco = QProgressBar()
        self.barra_espaco.setRange(0, 100)
        self.barra_espaco.setTextVisible(False)
        self.barra_espaco.setFixedHeight(tema.px(5, self.escala))
        self.rot_indice = QLabel("")
        self.rot_indice.setObjectName("ajuda")
        for w in (self.rot_espaco, self.rot_espaco_sub, self.barra_espaco,
                  self.rot_indice):
            al.addWidget(w)
        col.addWidget(arm)

        col.addWidget(widgets.separador(self.paleta.linha))
        rodape = QWidget()
        rl = QVBoxLayout(rodape)
        rl.setContentsMargins(10, 10, 10, 12)
        b = QPushButton("Configurações")
        b.setAccessibleName("Abrir configurações")
        b.clicked.connect(self.abrir_config)
        rl.addWidget(b)
        col.addWidget(rodape)
        return lateral

    def _botao_nav(self, campo: str, valor: str, rotulo: str) -> QPushButton:
        b = QPushButton()
        b.setObjectName("itemNav")
        b.setCheckable(True)
        b.setChecked(campo == "tipo" and valor == "")
        b.setCursor(Qt.PointingHandCursor)
        b.setAccessibleName(rotulo)
        lay = QHBoxLayout(b)
        lay.setContentsMargins(10, 0, 10, 0)
        numero = QLabel("—")
        numero.setObjectName("numeroNav")
        lay.addWidget(QLabel(rotulo))
        lay.addStretch(1)
        lay.addWidget(numero)
        b.numero = numero               # type: ignore[attr-defined]
        self.grupo_nav.addButton(b)
        self.botoes_nav[f"{campo}:{valor}"] = b
        b.clicked.connect(lambda: self._filtrar(campo, valor, rotulo))
        return b

    # -------------------------------------------------------------- centro

    def _montar_centro(self) -> QWidget:
        area = QWidget()
        area.setObjectName("areaCentral")
        col = QVBoxLayout(area)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._montar_topo())

        self.paginas = QStackedWidget()
        self.paginas.addWidget(self._pagina_catalogo())

        from .tela_item import TelaItem
        self.tela_item = TelaItem(self.cfg, self.con, self.executor,
                                  self.paleta, self.escala)
        self.tela_item.mudou.connect(self.recarregar_tudo)
        self.tela_item.pedir_voltar.connect(self.voltar)
        self.paginas.addWidget(self.tela_item)

        from .tela_config import TelaConfig
        self.tela_config = TelaConfig(self.cfg, self.con, self.executor)
        self.tela_config.salvou.connect(self._config_salva)
        self.tela_config.pedir_voltar.connect(self.voltar)
        self.paginas.addWidget(self.tela_config)

        from .tela_organizar import TelaOrganizar
        from .tela_player import TelaPlayer
        self.tela_organizar = TelaOrganizar(self.cfg, self.con, self.executor,
                                            self.paleta, self.escala)
        self.tela_organizar.mudou.connect(self.recarregar_tudo)
        self.tela_organizar.pedir_voltar.connect(self.voltar)
        self.paginas.addWidget(self.tela_organizar)

        # A previa do catalogo: uma so, reaproveitada por todos os cartoes.
        from .previa import PreviaObra

        self.previa = PreviaObra(self.cfg.posters, self.paleta, self.escala, self)
        self.previa.abrir.connect(self.abrir_item)
        self.previa.reproduzir.connect(self._previa_reproduzir)
        self.previa.baixar.connect(self._previa_baixar)
        self.grade.ligar_previa(self.previa)
        self.grade.definir_estilo_hover(
            (self.cfg.bruto.get("aparencia") or {}).get("hover", "elevar"))
        self.grade.sob_o_mouse.connect(self._obra_sob_o_mouse)

        self.tela_player = TelaPlayer(self.cfg, self.con, self.paleta, self.escala)
        self.tela_player.pedir_voltar.connect(self.voltar)
        self.paginas.addWidget(self.tela_player)

        col.addWidget(self.paginas, 1)
        return area

    def _montar_topo(self) -> QWidget:
        topo = QWidget()
        self.faixa_topo = topo
        topo.setObjectName("topo")
        topo.setFixedHeight(tema.px(ALTURA_TOPO, self.escala))
        lay = QHBoxLayout(topo)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(12)

        self.btn_voltar = QPushButton("‹  Voltar")
        self.btn_voltar.setObjectName("voltar")
        self.btn_voltar.clicked.connect(self.voltar)
        self.btn_voltar.hide()
        lay.addWidget(self.btn_voltar)

        self.rot_titulo = QLabel("Toda a biblioteca")
        self.rot_titulo.setObjectName("tituloTopo")
        lay.addWidget(self.rot_titulo)

        self.campo_busca = QLineEdit()
        self.campo_busca.setPlaceholderText("Filtrar…")
        self.campo_busca.setClearButtonEnabled(True)
        self.campo_busca.setFixedWidth(tema.px(230, self.escala))
        self.campo_busca.setAccessibleName("Filtrar o acervo pelo título")
        self.campo_busca.textChanged.connect(self._busca_mudou)
        lay.addWidget(self.campo_busca)
        lay.addStretch(1)

        self.rot_velocidade = QLabel("")
        self.rot_velocidade.setStyleSheet(
            f"color: {self.paleta.azul}; font-family: {tema.fonte_mono()};")
        lay.addWidget(self.rot_velocidade)

        self.combo_ordem = QComboBox()
        self.combo_ordem.setAccessibleName("Ordenar por")
        for valor, rotulo in (("titulo", "Título"), ("ano", "Mais recentes"),
                              ("tamanho", "Maiores"), ("disco", "Ocupando mais disco")):
            self.combo_ordem.addItem(rotulo, valor)
        self.combo_ordem.currentIndexChanged.connect(self._ordem_mudou)
        lay.addWidget(self.combo_ordem)

        self.btn_grade = QPushButton()
        self.btn_lista = QPushButton()
        for b, modo, nome in ((self.btn_grade, "grade", "Ver em grade"),
                              (self.btn_lista, "lista", "Ver em lista")):
            b.setIcon(widgets.icone_visao(modo, self.paleta.fraco))
            b.setObjectName("alternador")
            b.setCheckable(True)
            b.setChecked(self.modo == modo)
            b.setAccessibleName(nome)
            b.setToolTip(nome)
            b.clicked.connect(lambda _=False, m=modo: self.definir_modo(m))
            lay.addWidget(b)

        self.btn_adicionar = QPushButton("+  Adicionar .torrent")
        self.btn_adicionar.setProperty("destaque", "true")
        self.btn_adicionar.setAccessibleName("Adicionar arquivos .torrent ao índice")
        self.btn_adicionar.clicked.connect(self.escolher_torrents)
        lay.addWidget(self.btn_adicionar)

        self.btn_varrer = QPushButton("Reler")
        self.btn_varrer.setToolTip("Reler os .torrent do índice (F5)")
        self.btn_varrer.clicked.connect(self.varrer_indice)
        lay.addWidget(self.btn_varrer)

        self.btn_conferir = QPushButton("Conferir disco")
        self.btn_conferir.clicked.connect(self.conferir_disco)
        lay.addWidget(self.btn_conferir)
        return topo

    def _pagina_catalogo(self) -> QWidget:
        pagina = QWidget()
        col = QVBoxLayout(pagina)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self.area_downloads = QWidget()
        self.downloads_layout = QVBoxLayout(self.area_downloads)
        self.downloads_layout.setContentsMargins(18, 12, 18, 2)
        self.downloads_layout.setSpacing(8)
        self.area_downloads.hide()
        col.addWidget(self.area_downloads)


        self.faixa_organizar = QFrame()
        self.faixa_organizar.setObjectName("caixa")
        fl = QHBoxLayout(self.faixa_organizar)
        fl.setContentsMargins(14, 9, 14, 9)
        self.rot_organizar = QLabel("")
        fl.addWidget(self.rot_organizar)
        fl.addStretch(1)
        b_org = QPushButton("Ver e organizar")
        b_org.setProperty("destaque", "true")
        b_org.clicked.connect(self.abrir_organizar)
        fl.addWidget(b_org)
        self.faixa_organizar.hide()
        col.addWidget(self.faixa_organizar)

        self.rot_status = QLabel("")
        self.rot_status.setObjectName("ajuda")
        self.rot_status.setContentsMargins(20, 12, 20, 6)
        self.rot_status.setAccessibleName("Status")
        col.addWidget(self.rot_status)

        self.grade = GradeObras(self.cfg.posters, self.paleta, self.escala,
                                self.tamanho_grade, self.modo)
        self.grade.abrir.connect(self.abrir_item)
        col.addWidget(self.grade, 1)
        return pagina

    def _atalhos(self) -> None:
        for sequencia, alvo in (
            ("Ctrl+L", lambda: self.campo_busca.setFocus()),
            ("/", lambda: self.campo_busca.setFocus()),
            ("F5", self.varrer_indice),
            ("Ctrl+,", self.abrir_config),
            ("Ctrl+O", self.escolher_torrents),
            ("Esc", self.voltar),
            ("Ctrl+Q", self.close),
        ):
            QShortcut(QKeySequence(sequencia), self, activated=alvo)

    # ---------------------------------------------------------- navegacao

    def ir_para(self, pagina: int) -> None:
        self.paginas.setCurrentIndex(pagina)
        no_catalogo = pagina == PAGINA_CATALOGO
        self.btn_voltar.setVisible(not no_catalogo)
        for w in (self.campo_busca, self.combo_ordem, self.btn_grade,
                  self.btn_lista, self.btn_varrer, self.btn_conferir,
                  self.btn_adicionar):
            w.setVisible(no_catalogo)
        if no_catalogo:
            self.rot_titulo.setText(self._titulo_do_filtro())

    def voltar(self) -> None:
        # Sair do player sem encerrar o motor deixaria o video tocando por tras
        # do catalogo, invisivel e com som.
        if (self.paginas.currentIndex() == PAGINA_PLAYER
                and self.tela_player.motor is not None):
            self.tela_player.fechar()
            return

        self._mostrar_moldura(True)
        if self.paginas.currentIndex() != PAGINA_CATALOGO:
            self.ir_para(PAGINA_CATALOGO)

    def abrir_item(self, item_id: int) -> None:
        self.tela_item.mostrar(item_id)
        self.rot_titulo.setText("")
        self.ir_para(PAGINA_ITEM)

    def abrir_organizar(self) -> None:
        self.tela_organizar.cfg = self.cfg
        self.tela_organizar.mostrar()
        self.rot_titulo.setText("Organizar")
        self.ir_para(PAGINA_ORGANIZAR)

    def _mostrar_moldura(self, visivel: bool) -> None:
        """A barra lateral e o topo do app. Somem enquanto o player esta aberto.

        O player tem barra propria, com titulo e Voltar. Manter as duas juntas
        deixava a mesma informacao repetida em duas alturas diferentes, e o
        video espremido entre elas — o contrario do que se espera ao dar play.
        """
        self.lateral.setVisible(visivel)
        self.faixa_topo.setVisible(visivel)

    def _obra_sob_o_mouse(self, obra) -> None:
        """Alimenta a linha de rodape, quando esse e o estilo escolhido."""
        if self.grade.delegate.estilo_hover != "rodape":
            return
        if obra is None:
            self.atualizar_grade_status()
            return
        partes = [obra["titulo"]]
        for x in (str(obra.get("ano") or ""),
                  f"{obra['temporadas']} temporadas" if obra.get("temporadas") else "",
                  f"nota {obra['nota']:.1f}" if obra.get("nota") else "",
                  tema.CORES_ESTADO.get(obra.get("estado", "indice"), ("", ""))[1],
                  formatar_bytes(obra.get("bytes_total"))):
            if x:
                partes.append(x)
        self.status("   ·   ".join(partes))

    def atualizar_grade_status(self) -> None:
        n = self.grade.modelo.rowCount()
        self.status(f"{n} {'obra' if n == 1 else 'obras'}")

    def _previa_reproduzir(self, item_id: int) -> None:
        """O botao da previa faz o mesmo que o da tela da obra.

        Passa pela tela da obra de proposito: e la que mora a logica de achar o
        arquivo no disco, montar a fila de episodios e perguntar onde assistir.
        Duplicar isso aqui seria criar um segundo caminho para divergir do
        primeiro.
        """
        self.previa.esconder()
        self.abrir_item(item_id)
        QTimer.singleShot(80, self.tela_item.reproduzir_principal)

    def _previa_baixar(self, item_id: int) -> None:
        self.previa.esconder()
        self.abrir_item(item_id)
        QTimer.singleShot(80, self.tela_item.baixar_principal)

    def modo_cinema(self, ligado: bool) -> None:
        """Tela cheia de verdade: so o video na tela, mais nada.

        `showFullScreen()` sozinho nao bastava — ele estica a janela, mas a
        barra de titulo do sistema e o resto da moldura continuavam ali,
        comendo a tela e quebrando a ilusao.
        """
        self._mostrar_moldura(False)
        if ligado:
            self._geometria_antes = self.saveGeometry()
            self.showFullScreen()
        else:
            self.showNormal()
            if getattr(self, "_geometria_antes", None):
                self.restoreGeometry(self._geometria_antes)

    def abrir_player(self, caminho, titulo: str = "", fila=None,
                     indice: int = 0, retomar: float | None = None) -> bool:
        """Abre o video na pagina do player. False se coube ao sistema abrir.

        `fila` sao os episodios da serie, para o player oferecer proximo e
        anterior sem passar pelo catalogo.
        """
        self.tela_player.cfg = self.cfg
        self.rot_titulo.setText(titulo or "Reproduzindo")
        self.ir_para(PAGINA_PLAYER)
        self._mostrar_moldura(False)
        if self.tela_player.tocar(caminho, titulo, fila=fila, indice=indice,
                                  retomar=retomar):
            return True
        # Sem motor embutido: o proprio `tocar` ja mandou para o sistema.
        self.voltar()
        return False

    def abrir_guia(self, marcar: bool = True) -> None:
        """Abre o tour por cima da janela. Um de cada vez."""
        from .guia import Guia

        if getattr(self, "guia", None) is not None and vivo(self.guia):
            return
        self.ir_para(PAGINA_CATALOGO)
        self.guia = Guia(self)
        self.guia.fechado.connect(self._guia_fechou)
        if marcar:
            self._marcar_guia_visto()

    def _guia_fechou(self) -> None:
        self.guia = None
        self._ja_guardados: set[str] = set()
        # id da obra -> "baixando" ou "pausado", segundo o cliente.
        self._no_cliente: dict[int, str] = {}

    def _marcar_guia_visto(self) -> None:
        """Grava que o guia ja foi mostrado, para nao voltar a cada abertura."""
        try:
            config.aplicar({"aparencia": {"guia_visto": True}})
        except OSError:
            pass          # nao poder gravar nao pode impedir de usar o app

    def abrir_config(self) -> None:
        self.tela_config.carregar()
        self.rot_titulo.setText("Configurações")
        self.ir_para(PAGINA_CONFIG)

    def _config_salva(self) -> None:
        nova = config.carregar(self.cfg.arquivo)
        mudou_banco = str(nova.banco) != str(self.cfg.banco)
        self.cfg = nova
        self.tela_item.cfg = nova
        if mudou_banco:
            self.con.close()
            self.con = db.conectar(nova.banco)
            self.tela_item.con = self.con
            self.tela_config.con = self.con

        prefs = nova.bruto.get("aparencia") or {}
        self.aplicar_tema(prefs.get("tema", "escuro"), prefs.get("fonte", "normal"),
                          prefs.get("tamanho_grade", "medio"), prefs.get("modo", "grade"))
        self.recarregar_tudo()

    # ------------------------------------------------------------- aparencia

    def aplicar_tema(self, nome_paleta: str, nome_escala: str,
                     tamanho: str | None = None, modo: str | None = None) -> None:
        self.paleta = tema.PALETAS.get(nome_paleta, tema.ESCURO)
        self.escala = tema.ESCALAS.get(nome_escala, 1.0)
        if tamanho:
            self.tamanho_grade = tamanho
        if modo:
            self.modo = modo
            self.btn_grade.setChecked(modo == "grade")
            self.btn_lista.setChecked(modo == "lista")

        self.window().setStyleSheet(tema.folha(self.paleta, self.escala))
        widgets.limpar_cache_capas()
        self.grade.aplicar_tema(self.paleta, self.escala, self.tamanho_grade, self.modo)
        self.grade.definir_estilo_hover(
            (self.cfg.bruto.get("aparencia") or {}).get("hover", "elevar"))
        self.tela_item.aplicar_tema(self.paleta, self.escala)
        self.tela_organizar.aplicar_tema(self.paleta, self.escala)
        self.tela_player.aplicar_tema(self.paleta, self.escala)
        self.previa.aplicar_tema(self.paleta, self.escala)
        self.rot_velocidade.setStyleSheet(
            f"color: {self.paleta.azul}; font-family: {tema.fonte_mono()};")
        self.btn_grade.setIcon(widgets.icone_visao("grade", self.paleta.fraco))
        self.btn_lista.setIcon(widgets.icone_visao("lista", self.paleta.fraco))

    def definir_modo(self, modo: str) -> None:
        self.modo = modo
        self.btn_grade.setChecked(modo == "grade")
        self.btn_lista.setChecked(modo == "lista")
        self.grade.aplicar_modo(modo, self.tamanho_grade)
        config.aplicar({"aparencia": {"modo": modo}}, self.cfg.arquivo)

    # ---------------------------------------------------------------- dados

    def status(self, texto: str) -> None:
        self.rot_status.setText(texto)
        self.rot_status.setAccessibleDescription(texto)

    def recarregar_tudo(self) -> None:
        # Revisar o tipo custa 5 ms e conserta o que entrou errado numa varredura
        # antiga — um filme catalogado como jogo nunca acharia capa, porque a
        # busca de jogo consulta outra base.
        try:
            scanner.reclassificar(self.con)
        except sqlite3.Error:
            pass
        self.atualizar_resumo()
        self.atualizar_grade()
        self.atualizar_downloads()
        self.checar_organizacao()
        self.buscar_capas_faltando()
        self.guardar_o_que_esta_pronto()

    # --------------------------------------------------------------- capas

    def _quantas_sem_capa(self) -> int:
        """Capa gerada conta como faltando: e so o titulo sobre um gradiente."""
        return self.con.execute(
            "SELECT COUNT(*) FROM itens WHERE poster IS NULL OR poster = '' "
            "OR poster LIKE '%-gerada.svg'").fetchone()[0]

    def buscar_capas_faltando(self) -> None:
        """Procura capa sozinho, em segundo plano, ate nao faltar mais nenhuma.

        Antes isto so acontecia se o usuario achasse o botao em Configuracoes →
        Capas. Quem abria o app pela primeira vez via um catalogo de retangulos
        cinzentos e nao tinha como saber que faltava apertar algo.
        """
        if self.executor.rodando("capas-auto"):
            return
        chaves = self.cfg.metadados or {}
        if not (chaves.get("tmdb_api_key") or chaves.get("steamgriddb_api_key")):
            return                       # sem chave nao ha o que buscar
        faltam = self._quantas_sem_capa()
        if not faltam:
            return

        self.status(f"Procurando capas… faltam {faltam}")
        cfg = self.cfg

        def trabalho():
            con = db.conectar(cfg.banco)
            try:
                r = metadata.enriquecer(con, cfg, so_faltantes=True,
                                        limite=CAPAS_POR_LEVA,
                                        pular=self._capas_pular)
                con.commit()
                return r
            finally:
                con.close()

        def pronto(r):
            if not vivo(self):
                return
            if r.posters:
                widgets.limpar_cache_capas()
                self.atualizar_grade()
            # As que falharam continuam na consulta; pular por cima delas e o
            # que faz a proxima leva avancar em vez de repetir as mesmas.
            self._capas_pular += max(0, r.tentados - r.posters)
            faltam_agora = self._quantas_sem_capa()

            if r.tentados == 0 or self._capas_pular >= faltam_agora + r.posters:
                if r.posters:
                    self.status(f"{r.posters} capa(s) encontradas.")
                return                    # deu a volta na lista inteira
            self.status(f"Procurando capas… faltam {faltam_agora}"
                        + (f" · {r.posters} encontradas" if r.posters else ""))
            QTimer.singleShot(600, self.buscar_capas_faltando)

        self.executor.rodar("capas-auto", trabalho, pronto, lambda _: None)

    def checar_organizacao(self) -> None:
        """Conta o que esta pronto para organizar. Percorre disco: vai para outra linha."""
        if self.executor.rodando("pendentes"):
            return
        cfg = self.cfg

        def trabalho():
            con = db.conectar(cfg.banco)
            try:
                from .tela_organizar import quantos_pendentes
                return quantos_pendentes(con, cfg)
            finally:
                con.close()

        def pronto(n):
            if not vivo(self.faixa_organizar):
                return
            if n:
                self.rot_organizar.setText(
                    f"{n} {'obra baixada está' if n == 1 else 'obras baixadas estão'} "
                    "fora do padrão de nomes.")
                self.faixa_organizar.show()
            else:
                self.faixa_organizar.hide()

        self.executor.rodar("pendentes", trabalho, pronto, lambda _: None)

    def atualizar_resumo(self) -> None:
        r = consultas.resumo(self.con, self.cfg)
        no_disco = (r["estados"].get("completo", {}).get("bytes", 0)
                    + r["estados"].get("parcial", {}).get("bytes", 0))
        total = r["bytes_indexados"] or 1
        self.rot_espaco.setText(formatar_bytes(no_disco))
        self.rot_espaco_sub.setText(f"de {formatar_bytes(r['bytes_indexados'])} no acervo")
        pct = min(100, round(no_disco * 100 / total))
        self.barra_espaco.setValue(pct)
        self.barra_espaco.setAccessibleName(
            f"{formatar_bytes(no_disco)} ocupados de {formatar_bytes(r['bytes_indexados'])}")
        proporcao = (r["bytes_indexados"] // r["bytes_indice"]) if r["bytes_indice"] else 0
        self.rot_indice.setText(
            f"índice: {formatar_bytes(r['bytes_indice'])} · 1:{proporcao:,}".replace(",", "."))

        for chave, valor in {
            "tipo:": r["itens"],
            "tipo:filme": r["por_tipo"].get("filme", 0),
            "tipo:serie": r["por_tipo"].get("serie", 0),
            "tipo:jogo": r["por_tipo"].get("jogo", 0),
            "estado:completo": r["estados"].get("completo", {}).get("n", 0),
            # "Baixando" conta o que o cliente tem em maos — inclusive pausado.
            # Antes contava arquivo incompleto no disco, que e outra coisa: um
            # download pausado com tudo baixado sumia dali.
            "estado:parcial": (len(self._no_cliente)
                               or r["estados"].get("parcial", {}).get("n", 0)),
            "estado:indice": r["estados"].get("indice", {}).get("n", 0),
        }.items():
            b = self.botoes_nav.get(chave)
            if b:
                b.numero.setText(str(valor))     # type: ignore[attr-defined]
                b.setAccessibleDescription(f"{valor} obras")

    def atualizar_grade(self) -> None:
        obras = consultas.listar(self.con, **self.filtro,
                                 no_cliente=self._no_cliente)
        self.grade.definir_obras(obras)
        n = len(obras)
        if n:
            self.status(f"{n} {'obra' if n == 1 else 'obras'}")
        else:
            self.status(f"Nada encontrado para “{self.filtro['busca']}”."
                        if self.filtro["busca"] else
                        "Nenhuma obra aqui. Confira a pasta do índice em Configurações.")

    def _titulo_do_filtro(self) -> str:
        if not self.filtro["tipo"] and not self.filtro["estado"]:
            return "Toda a biblioteca"
        chave = (f"tipo:{self.filtro['tipo']}" if self.filtro["tipo"]
                 else f"estado:{self.filtro['estado']}")
        b = self.botoes_nav.get(chave)
        return b.accessibleName() if b else "Biblioteca"

    def _filtrar(self, campo: str, valor: str, rotulo: str) -> None:
        # Tipo e estado sao irmaos: escolher um limpa o outro, senao a combinacao
        # vazia deixa a tela sem nada e sem explicacao.
        self.filtro["tipo"] = valor if campo == "tipo" else ""
        self.filtro["estado"] = valor if campo == "estado" else ""
        self.ir_para(PAGINA_CATALOGO)
        self.rot_titulo.setText("Toda a biblioteca"
                                if campo == "tipo" and not valor else rotulo)
        self.atualizar_grade()

    def _busca_mudou(self, texto: str) -> None:
        self.filtro["busca"] = texto
        if not hasattr(self, "_timer_busca"):
            self._timer_busca = QTimer(self)
            self._timer_busca.setSingleShot(True)
            self._timer_busca.timeout.connect(self.atualizar_grade)
        self._timer_busca.start(160)

    def _ordem_mudou(self) -> None:
        self.filtro["ordem"] = self.combo_ordem.currentData()
        self.atualizar_grade()

    # --------------------------------------------------------------- acoes

    def varrer_indice(self) -> None:
        if not self.cfg.configurado:
            self.status("Configure a pasta do índice antes de reler.")
            self.abrir_config()
            return
        self.btn_varrer.setEnabled(False)
        self.status("Lendo o índice…")
        cfg = self.cfg

        def trabalho():
            con = db.conectar(cfg.banco)
            try:
                r = scanner.varrer(con, cfg.indice)
                return {"lidos": r.lidos, "corrompidos": r.corrompidos,
                        "unicos": len(r.infohashes)}
            finally:
                con.close()

        def pronto(r):
            self.btn_varrer.setEnabled(True)
            self.recarregar_tudo()
            self.status(f"{r['lidos']} arquivos .torrent lidos, {r['unicos']} únicos, "
                        f"{r['corrompidos']} ilegíveis.")

        self.executor.rodar("varrer", trabalho, pronto,
                            lambda m: (self.btn_varrer.setEnabled(True),
                                       self.status(f"Falhou ao ler o índice: {m}")))

    def conferir_disco(self) -> None:
        self.btn_conferir.setEnabled(False)
        self.status("Conferindo o disco…")
        cfg = self.cfg

        def trabalho():
            con = db.conectar(cfg.banco)
            try:
                r = biblioteca.reconciliar(
                    con, cfg.biblioteca, cfg.ignorar,
                    cfg.seguranca.get("pastas_protegidas", []),
                    extras=[Path(cfg.staging)])
                return {"completos": r.completos, "parciais": r.parciais,
                        "orfaos": len(r.orfaos), "bytes": r.bytes_no_disco}
            finally:
                con.close()

        def pronto(r):
            self.btn_conferir.setEnabled(True)
            self.recarregar_tudo()
            self.status(f"{r['completos']} no disco, {r['parciais']} pela metade, "
                        f"{r['orfaos']} pastas órfãs · "
                        f"{formatar_bytes(r['bytes'])} ocupados.")
            self.guardar_o_que_esta_pronto()

        self.executor.rodar("conferir", trabalho, pronto,
                            lambda m: (self.btn_conferir.setEnabled(True),
                                       self.status(f"Falhou ao conferir: {m}")))

    def atualizar_downloads(self) -> None:
        if self.executor.rodando("downloads"):
            return
        cfg = self.cfg

        def trabalho():
            con = db.conectar(cfg.banco)
            try:
                return downloads.progresso(con, cfg)
            finally:
                con.close()

        self.executor.rodar("downloads", trabalho, self._mostrar_downloads,
                            lambda _: None)

    def _mostrar_downloads(self, r) -> None:
        if not vivo(self.area_downloads):
            return
        while self.downloads_layout.count():
            item = self.downloads_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        lista = r.get("downloads") or []
        self.grade.definir_progresso({d["infohash"]: d for d in lista})

        # O que o cliente esta segurando agora manda sobre o estado no disco:
        # um torrent pausado continua sendo um download em andamento, e some da
        # lista de "Baixando" se a gente olhar so para o arquivo incompleto.
        antes = dict(self._no_cliente)
        self._no_cliente = {
            d["item_id"]: ("pausado" if d.get("pausado") else "baixando")
            for d in lista
            if d.get("item_id") and not d.get("terminou")
            and (d.get("progresso") or 0) < 1
        }
        if self._no_cliente != antes:
            self.atualizar_resumo()
            self.atualizar_grade()

        self._guardar_concluidos(lista)
        if not r.get("disponivel") or not lista:
            self.area_downloads.hide()
            self.rot_velocidade.setText("")
            return
        for d in lista[:3]:
            self.downloads_layout.addWidget(widgets.LinhaDownload(d, self.escala))
        self.area_downloads.show()
        soma = sum(d["velocidade"] for d in lista)
        self.rot_velocidade.setText(f"↓ {formatar_bytes(soma)}/s" if soma else "")

    # -------------------------------------------------- guardar o concluido

    def _guardar_concluidos(self, lista: list[dict]) -> None:
        """Um download terminou agora: aproveita e ja guarda."""
        novos = [d["infohash"] for d in lista
                 if d.get("terminou") or (d.get("progresso") or 0) >= 1.0]
        pendentes = [h for h in novos if h and h not in self._ja_guardados]
        if not pendentes:
            return
        self._ja_guardados.update(pendentes)
        self.guardar_o_que_esta_pronto()

    def guardar_o_que_esta_pronto(self) -> None:
        """Leva para a biblioteca tudo que ja terminou e ficou no `_baixando`.

        Pergunta "o que esta pronto agora?" em vez de reagir ao instante em que
        um download termina. O evento e facil de perder — o download acaba com o
        app fechado, ou o cliente ja esqueceu do torrent na proxima abertura — e
        ai o arquivo fica parado na pasta de download para sempre. Esta pergunta
        pode ser feita a qualquer hora e sempre responde certo.
        """
        if not (self.cfg.bruto.get("caminhos") or {}).get("organizar_ao_concluir",
                                                          True):
            return
        if self.executor.rodando("guardar"):
            return
        cfg = self.cfg

        def trabalho():
            con = db.conectar(cfg.banco)
            try:
                # Conferir antes: o arquivo pode ter acabado de chegar, e a
                # tabela `disco` ainda nao saber dele.
                seg = cfg.bruto.get("seguranca", {}) or {}
                biblioteca.reconciliar(con, Path(cfg.biblioteca),
                                       cfg.ignorar,
                                       seg.get("pastas_protegidas", []) or [],
                                       extras=[Path(cfg.staging)])
                return guardar.guardar(con, cfg)
            finally:
                con.close()

        def pronto(r):
            if not vivo(self) or not r.movidos:
                return
            quais = ", ".join(r.obras[:2]) + ("…" if len(r.obras) > 2 else "")
            self.status(f"{quais} guardado na biblioteca "
                        f"({r.movidos} arquivo(s) movidos).")
            self.recarregar_tudo()

        self.executor.rodar("guardar", trabalho, pronto, lambda _: None)

    # ------------------------------------------------------------ importar

    def escolher_torrents(self) -> None:
        arquivos, _ = QFileDialog.getOpenFileNames(
            self, "Adicionar arquivos .torrent", "", "Torrents (*.torrent)")
        if arquivos:
            self.importar_torrents(arquivos)

    def dragEnterEvent(self, e):          # noqa: N802
        if e.mimeData().hasUrls() and any(
                u.toLocalFile().lower().endswith(".torrent") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):               # noqa: N802
        caminhos = [u.toLocalFile() for u in e.mimeData().urls()
                    if u.toLocalFile().lower().endswith(".torrent")]
        if caminhos:
            self.importar_torrents(caminhos)
            e.acceptProposedAction()

    def importar_torrents(self, arquivos: list[str]) -> None:
        if not self.cfg.configurado:
            self.status("Configure a pasta do índice antes de adicionar torrents.")
            self.abrir_config()
            return

        propostas = importar.avaliar_varios(self.con, self.cfg.indice, arquivos)
        novos = [p for p in propostas if p.pode_importar]
        repetidos = [p for p in propostas if p.ja_existe]
        ruins = [p for p in propostas if p.erro]

        if not novos:
            partes = []
            for p in repetidos:
                partes.append(f"• {p.origem.name}\n   já está no acervo, "
                              f"como “{p.obra_existente}”")
            for p in ruins:
                partes.append(f"• {p.origem.name}\n   {p.erro}")
            QMessageBox.information(self, "Nada a adicionar",
                                    "Nenhum arquivo novo.\n\n" + "\n".join(partes))
            return

        resumo = "\n".join(
            f"• {p.titulo}  ({formatar_bytes(p.tamanho)})\n   → {p.destino_relativo}"
            for p in novos[:10])
        if len(novos) > 10:
            resumo += f"\n… e mais {len(novos) - 10}"
        extra = ""
        if repetidos:
            extra += f"\n\n{len(repetidos)} já estavam no acervo e foram ignorados."
        if ruins:
            extra += f"\n{len(ruins)} não puderam ser lidos."

        caixa = QMessageBox(self)
        caixa.setWindowTitle("Adicionar ao índice")
        caixa.setIcon(QMessageBox.Question)
        caixa.setText(f"Adicionar {len(novos)} arquivo(s) .torrent?")
        caixa.setInformativeText(resumo + extra)
        caixa.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        caixa.setDefaultButton(QMessageBox.Yes)
        if caixa.exec() != QMessageBox.Yes:
            return

        ok, falhas = 0, []
        for p in novos:
            r = importar.importar(self.cfg.indice, p)
            if r.get("ok"):
                ok += 1
            else:
                falhas.append(f"{p.origem.name}: {r.get('erro')}")

        self.status(f"{ok} .torrent adicionados ao índice. Relendo…")
        self.varrer_indice()
        if falhas:
            QMessageBox.warning(self, "Alguns não entraram", "\n".join(falhas))

    # ----------------------------------------------------------- encerrar

    def resizeEvent(self, evento):        # noqa: N802
        super().resizeEvent(evento)
        if getattr(self, "guia", None) is not None and vivo(self.guia):
            self.guia.setGeometry(self.rect())

    def closeEvent(self, evento):         # noqa: N802
        self.relogio.stop()
        self.executor.aguardar(1500)
        # As linhas que leem capas tambem precisam terminar antes de o Qt ser
        # desmontado: uma tarefa emitindo sinal para um objeto ja destruido foi
        # o que derrubava o app com violacao de acesso.
        widgets.carregador.esperar(1500)

        # O aria2 e um processo que o proprio app iniciou: sem isto ele ficaria
        # rodando invisivel depois que a janela fecha.
        try:
            motor = downloads.cliente(self.cfg)
            if motor is not None:
                motor.encerrar()
        except Exception:
            pass

        try:
            self.con.close()
        except Exception:
            pass
        super().closeEvent(evento)
