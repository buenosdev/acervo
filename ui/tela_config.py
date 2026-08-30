"""Configuracoes: pastas, qBittorrent, capas, seguranca, duplicatas e aparencia.

E uma pagina da janela, nao um dialogo - nada abre por cima de nada.

Tudo se resolve aqui dentro - nenhuma etapa exige abrir arquivo de texto nem
outro programa. Cada campo que depende de algo externo tem um botao de teste
que responde o que fazer quando falha, nao so "erro".
"""
from __future__ import annotations

import sqlite3

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog,
                               QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QRadioButton,
                               QScrollArea, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from core import (ajustes, capas, config, db, duplicatas, metadata, scanner,
                  sobre)

from . import tema, widgets
from .tarefas import vivo
from .widgets import Retorno, formatar_bytes


def _linha_rotulada(rotulo: str, campo: QWidget, ajuda: str = "") -> QWidget:
    caixa = QWidget()
    col = QVBoxLayout(caixa)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(5)
    r = QLabel(rotulo)
    r.setObjectName("rotulo")
    r.setBuddy(campo if isinstance(campo, (QLineEdit, QComboBox, QSpinBox)) else None)
    col.addWidget(r)
    col.addWidget(campo)
    if ajuda:
        col.addWidget(widgets.ajuda(ajuda))
    return caixa


class TelaConfig(QWidget):
    salvou = Signal()
    pedir_voltar = Signal()

    def __init__(self, cfg, con: sqlite3.Connection, executor, pai=None):
        super().__init__(pai)
        self.cfg = cfg
        self.con = con
        self.executor = executor
        self.varreu = 0

        col = QVBoxLayout(self)
        col.setContentsMargins(34, 22, 34, 18)
        col.setSpacing(12)

        self.abas = QTabWidget()
        self.abas.setAccessibleName("Seções das configurações")
        self.abas.addTab(self._aba_pastas(), "Pastas")
        self.abas.addTab(self._aba_torrent(), "Torrent")
        self.abas.addTab(self._aba_capas(), "Capas")
        self.abas.addTab(self._aba_seguranca(), "Segurança")
        self.abas.addTab(self._aba_duplicatas(), "Duplicatas")
        self.abas.addTab(self._aba_reproducao(), "Reprodução")
        self.abas.addTab(self._aba_aparencia(), "Aparência")
        self.abas.addTab(self._aba_sobre(), "Sobre")
        col.addWidget(self.abas, 1)

        self.retorno_salvar = Retorno()
        col.addWidget(self.retorno_salvar)

        botoes = QHBoxLayout()
        botoes.addStretch(1)
        self.b_salvar = QPushButton("Salvar")
        self.b_salvar.setProperty("destaque", "true")
        self.b_salvar.setObjectName("botaoGrande")
        self.b_salvar.clicked.connect(self.salvar)
        botoes.addWidget(self.b_salvar)
        b_voltar = QPushButton("Voltar")
        b_voltar.setObjectName("botaoGrande")
        b_voltar.clicked.connect(self.pedir_voltar.emit)
        botoes.addWidget(b_voltar)
        col.addLayout(botoes)

        self.carregar()

    @staticmethod
    def _rolavel(interno: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(interno)
        return area

    # --------------------------------------------------------------- abas

    def _aba_pastas(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(4, 14, 4, 10)
        col.setSpacing(14)
        col.addWidget(widgets.ajuda(
            "O índice é a pasta com seus arquivos .torrent — é a biblioteca "
            "permanente. A biblioteca é onde a mídia baixada fica."))

        self.campo_indice = QLineEdit()
        self.campo_indice.setProperty("mono", "true")
        self.campo_indice.setAccessibleName("Pasta do índice")
        col.addWidget(_linha_rotulada(
            "Pasta do índice (.torrent)",
            self._com_botoes(self.campo_indice, "Escolher…",
                             lambda: self._escolher_pasta(self.campo_indice),
                             "Conferir", lambda: self._testar_pasta(self.campo_indice))))
        self.retorno_indice = Retorno()
        col.addWidget(self.retorno_indice)

        self.campo_biblioteca = QLineEdit()
        self.campo_biblioteca.setProperty("mono", "true")
        self.campo_biblioteca.setAccessibleName("Pasta da biblioteca")
        col.addWidget(_linha_rotulada(
            "Pasta da biblioteca (mídia)",
            self._com_botoes(self.campo_biblioteca, "Escolher…",
                             lambda: self._escolher_pasta(self.campo_biblioteca))))

        self.campo_staging = QLineEdit()
        self.campo_staging.setProperty("mono", "true")
        col.addWidget(_linha_rotulada(
            "Pasta de download (temporária)", self.campo_staging,
            "Onde o qBittorrent baixa antes de organizar. Deixe vazio para o app "
            "criar dentro da biblioteca."))

        self.campo_ignorar = QLineEdit()
        col.addWidget(_linha_rotulada(
            "Pastas a ignorar na varredura", self.campo_ignorar,
            "Separe por vírgula. Ex.: cópias de backup do índice."))
        col.addStretch(1)
        return self._rolavel(w)

    def _aba_torrent(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(4, 14, 4, 10)
        col.setSpacing(14)

        col.addWidget(widgets.ajuda(
            "O catálogo, as capas e a organização funcionam sem nenhum cliente. "
            "Isto aqui é só para o botão Baixar."))

        grupo = QGroupBox("Como baixar")
        gl = QVBoxLayout(grupo)
        self.grupo_motor = QButtonGroup(self)
        for valor, rotulo, nota in (
            ("aria2", "aria2 — recomendado, não instala nada",
             "Um binário de ~5 MB que o próprio app baixa e cuida. É o caminho "
             "sem configuração: nada para ligar, nada para instalar."),
            ("auto", "Usar o cliente que eu já tenho, se houver",
             "Procura um qBittorrent ou uTorrent com a interface web ligada e "
             "usa; se não achar nenhum, cai no aria2."),
        ):
            r = QRadioButton(rotulo)
            r.valor = valor          # type: ignore[attr-defined]
            self.grupo_motor.addButton(r)
            gl.addWidget(r)
            gl.addWidget(widgets.ajuda("    " + nota))
        col.addWidget(grupo)

        self.campo_aria2 = QLineEdit()
        self.campo_aria2.setProperty("mono", "true")
        col.addWidget(_linha_rotulada(
            "Caminho do aria2c.exe",
            self._com_botoes(self.campo_aria2, "Escolher…", self._escolher_aria2),
            "Deixe vazio para o app procurar sozinho."))

        # qBittorrent e uTorrent saem da frente. Eles continuam funcionando e
        # continuam configuraveis — so nao sao mais a primeira coisa que alguem
        # ve. Quem nunca ouviu falar de "interface web" nao deveria precisar
        # decidir entre tres clientes para conseguir baixar um filme.
        self.avancado = QWidget()
        av = QVBoxLayout(self.avancado)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(9)
        av.addWidget(widgets.ajuda(
            "Só é preciso mexer aqui se você quiser usar o qBittorrent ou o "
            "uTorrent em vez do aria2. Eles continuam semeando depois que o "
            "download termina, o que o aria2 só faz com o app aberto."))

        for chave, campo_nome, rotulo in (
                ("qbittorrent", "campo_qb_url", "Endereço do qBittorrent"),
                ("utorrent", "campo_ut_url", "Endereço do uTorrent")):
            campo = QLineEdit()
            campo.setProperty("mono", "true")
            setattr(self, campo_nome, campo)
            av.addWidget(_linha_rotulada(rotulo, campo))
            radio = QRadioButton(f"Usar sempre o {'qBittorrent' if chave == 'qbittorrent' else 'uTorrent'}")
            radio.valor = chave      # type: ignore[attr-defined]
            self.grupo_motor.addButton(radio)
            av.addWidget(radio)

        linha = QHBoxLayout()
        self.campo_qb_user = QLineEdit()
        self.campo_qb_senha = QLineEdit()
        self.campo_qb_senha.setEchoMode(QLineEdit.Password)
        linha.addWidget(_linha_rotulada("Usuário", self.campo_qb_user))
        linha.addWidget(_linha_rotulada("Senha", self.campo_qb_senha))
        av.addLayout(linha)
        av.addWidget(widgets.ajuda(
            "O uTorrent exige usuário e senha; o qBittorrent aceita vazio quando "
            "está marcado “Ignorar autenticação para clientes no localhost”."))

        passos = QFrame()
        passos.setObjectName("caixa")
        pl = QVBoxLayout(passos)
        pl.setContentsMargins(14, 12, 14, 12)
        titulo = QLabel("Como ligar cada um")
        titulo.setObjectName("rotulo")
        pl.addWidget(titulo)
        pl.addWidget(widgets.ajuda(
            "qBittorrent — Ferramentas → Opções → Web UI: marque “Servidor Web UI”, "
            "porta 8080, e “Ignorar autenticação para clientes no localhost”.\n\n"
            "uTorrent — Opções → Preferências → Interface Web: marque “Ativar "
            "Interface Web” e defina usuário e senha (o uTorrent exige os dois).\n\n"
            "aria2 — nada a ligar: clique em “Baixar o aria2” acima e pronto."))
        av.addWidget(passos)

        self.b_avancado = QPushButton("Usar outro cliente de torrent…")
        self.b_avancado.setCheckable(True)
        self.b_avancado.setAccessibleName(
            "Mostrar as opções de qBittorrent e uTorrent")
        self.b_avancado.toggled.connect(self._mostrar_avancado)
        col.addWidget(self.b_avancado)
        self.avancado.hide()
        col.addWidget(self.avancado)

        acoes = QHBoxLayout()
        self.b_auto = QPushButton("Configurar o download para mim")
        self.b_auto.setObjectName("botaoGrande")
        self.b_auto.setProperty("destaque", "true")
        self.b_auto.setAccessibleName(
            "Descobrir e configurar o cliente de torrent sozinho")
        self.b_auto.setToolTip("Olha o que existe nesta máquina e resolve o que der.")
        self.b_auto.clicked.connect(self._configurar_sozinho)
        acoes.addWidget(self.b_auto)
        b = QPushButton("Testar")
        b.clicked.connect(lambda: self._testar_motor(b))
        acoes.addWidget(b)
        self.b_aria2 = QPushButton("Baixar o aria2")
        self.b_aria2.setToolTip("Baixa o aria2 oficial e guarda ao lado do app.")
        self.b_aria2.clicked.connect(self._baixar_aria2)
        acoes.addWidget(self.b_aria2)
        acoes.addStretch(1)
        col.addLayout(acoes)
        self.retorno_qb = Retorno()
        col.addWidget(self.retorno_qb)


        grupo2 = QGroupBox("Ao adicionar um torrent")
        g2 = QVBoxLayout(grupo2)
        self.marca_trackers = QCheckBox("Injetar trackers públicos")
        self.marca_lixo = QCheckBox("Não baixar arquivos de propaganda")
        self.marca_sequencial = QCheckBox("Baixar em ordem")
        for m, nota in ((self.marca_trackers,
                         "Faz downloads antigos engatarem. Nunca em torrent privado."),
                        (self.marca_lixo,
                         "Pula .url e vídeos de anúncio. Em jogo nada é desmarcado."),
                        (self.marca_sequencial,
                         "Começar a assistir antes de terminar (só no qBittorrent).")):
            g2.addWidget(m)
            g2.addWidget(widgets.ajuda("    " + nota))
        col.addWidget(grupo2)
        col.addStretch(1)
        return self._rolavel(w)

    def _configurar_sozinho(self) -> None:
        """Um clique: olha a maquina, resolve o que der, e diz o que sobrou.

        A alternativa era o usuario ler "ligue a interface web do seu cliente" e
        nao saber o que isso quer dizer. Aqui ele clica, o app faz a parte que e
        do app, e sobra so a parte que so ele pode fazer.
        """
        self.b_auto.setEnabled(False)
        self.retorno_qb.mostrar("info", "Procurando um cliente de torrent…")
        cfg, dados = self.cfg, self.coletar().get("motor", {})

        def pronto(r):
            if not vivo(self.b_auto):
                return
            self.b_auto.setEnabled(True)

            # O que o app descobriu sozinho ja entra nos campos: endereco,
            # porta e usuario. Sobra para a pessoa so o que ela sabe e o
            # computador nao — a senha.
            self._aplicar_descobertas(r.get("ajustes") or {})

            if r.get("precisa_senha"):
                self.retorno_qb.mostrar("aviso", r["mensagem"], r["detalhe"])
                self.campo_qb_senha.setFocus(Qt.OtherFocusReason)
                self.campo_qb_senha.selectAll()
                return

            if r["ok"]:
                self.cfg, _ = ajustes.salvar(self.coletar(), self.cfg)
                if r.get("staging_sugerido"):
                    self.retorno_qb.mostrar("aviso", r["mensagem"], r["detalhe"])
                    self._trocar_pasta_download(r["staging_sugerido"],
                                                r.get("mensagem", ""))
                else:
                    self.retorno_qb.mostrar("ok", r["mensagem"], r["detalhe"])
                self.salvou.emit()
                return

            self.retorno_qb.mostrar("aviso", r["mensagem"], r["detalhe"])
            if r.get("pode_ligar_webui"):
                self._ligar_webui_utorrent()
            elif r.get("precisa_aria2"):
                self._baixar_aria2(depois=self._configurar_sozinho)

        self.executor.rodar(
            "configurar-download",
            lambda: ajustes.configurar_download(dados, cfg), pronto,
            lambda m: (self.b_auto.setEnabled(True),
                       self.retorno_qb.mostrar("erro", m)))

    def _aplicar_descobertas(self, achado: dict) -> None:
        """Escreve nos campos o que a deteccao descobriu."""
        if not achado:
            return
        if achado.get("utorrent_url"):
            self.campo_ut_url.setText(achado["utorrent_url"])
        if achado.get("usuario") and not self.campo_qb_user.text().strip():
            self.campo_qb_user.setText(achado["usuario"])
        if achado.get("senha"):
            self.campo_qb_senha.setText(achado["senha"])
        if achado.get("aria2_caminho"):
            self.campo_aria2.setText(achado["aria2_caminho"])

    def _trocar_pasta_download(self, sugerida: str, motivo: str = "") -> None:
        """Oferece alinhar a pasta de download com a que o motor usa."""
        if QMessageBox.question(
                self, "Pasta de download",
                f"Passar a usar “{sugerida}” como pasta de download?\n\n"
                + (motivo + "\n\n" if motivo else "")
                + "Nada é movido agora: só muda onde o app procura o que "
                "for baixado daqui em diante. A organização continua "
                "levando tudo para a sua biblioteca.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes) != QMessageBox.Yes:
            return
        try:
            Path(sugerida).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.retorno_qb.mostrar("erro", f"não consegui criar a pasta: {e}")
            return
        self.campo_staging.setText(sugerida)
        self.cfg, _ = ajustes.salvar(self.coletar(), self.cfg)
        self.retorno_qb.mostrar(
            "ok", "Pasta de download alinhada.",
            f"O app passa a procurar os downloads em {sugerida}.")
        self.salvou.emit()

    def _ligar_webui_utorrent(self) -> None:
        """Liga a Interface Web do uTorrent, com a permissao do usuario.

        E o unico ponto em que o Acervo escreve na configuracao de outro
        programa, entao pergunta antes e diz o que vai fazer — inclusive que
        guarda uma copia do arquivo anterior.
        """
        from core import utorrent_config as ut

        resposta = QMessageBox.question(
            self, "Ligar a Interface Web do uTorrent",
            "Posso ligar a Interface Web no uTorrent para você?\n\n"
            "• escrevo na configuração dele (ele está fechado, então é seguro)\n"
            "• guardo uma cópia da configuração anterior antes de mexer\n"
            "• crio um usuário e uma senha só para o Acervo\n\n"
            "Se você já tinha uma senha de Interface Web, ela será substituída.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resposta != QMessageBox.Yes:
            return

        r = ajustes.ligar_webui_utorrent(self.cfg)
        if not r.get("ok"):
            self.retorno_qb.mostrar("erro", r.get("erro", "não consegui."))
            return

        self._aplicar_descobertas(r.get("ajustes") or {})
        self.cfg, _ = ajustes.salvar(self.coletar(), self.cfg)
        self.retorno_qb.mostrar("ok", r["mensagem"], r["detalhe"])
        self.salvou.emit()

        if QMessageBox.question(
                self, "Abrir o uTorrent",
                "Abrir o uTorrent agora? Ele precisa subir uma vez para a "
                "Interface Web entrar no ar.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            if ut.abrir_utorrent():
                QTimer.singleShot(6000, self._configurar_sozinho)

    def _mostrar_avancado(self, aberto: bool) -> None:
        self.avancado.setVisible(aberto)
        self.b_avancado.setText("Esconder as outras opções" if aberto
                                else "Usar outro cliente de torrent…")

    def _escolher_aria2(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Escolher o aria2c.exe", "", "Executáveis (aria2c.exe *.exe)")
        if caminho:
            self.campo_aria2.setText(caminho.replace("\\", "/"))

    def _baixar_aria2(self, depois=None) -> None:
        """Baixa o aria2 oficial. Pergunta antes, mostrando origem e tamanho:
        trazer um executável de terceiros é decisão do usuário, não do app."""
        from core.motores import aria2 as motor_aria2

        destino = Path(self.cfg.dados)
        resposta = QMessageBox.question(
            self, "Baixar o aria2",
            f"Baixar o aria2 {motor_aria2.VERSAO_ARIA2} "
            f"(~{motor_aria2.TAMANHO_APROXIMADO_MB} MB)?\n\n"
            f"Origem: {motor_aria2.URL_ARIA2}\n"
            f"Destino: {destino / motor_aria2.NOME_BINARIO}\n\n"
            "É o projeto oficial, publicado no GitHub. Só o aria2c.exe é extraído.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resposta != QMessageBox.Yes:
            return

        self.b_aria2.setEnabled(False)
        self.retorno_qb.mostrar("info", "Baixando o aria2…")

        def pronto(caminho):
            if not vivo(self.b_aria2):
                return
            self.b_aria2.setEnabled(True)
            self.campo_aria2.setText(str(caminho).replace("\\", "/"))
            self.retorno_qb.mostrar("ok", "aria2 instalado.",
                                    f"{caminho}\nJá dá para baixar torrents.")
            self.salvou.emit()
            self.cfg, _ = ajustes.salvar(self.coletar(), self.cfg)
            if callable(depois):
                depois()      # volta e confirma que agora funciona

        def falhou(m):
            self.b_aria2.setEnabled(True)
            self.retorno_qb.mostrar("erro", m)

        self.executor.rodar(
            "aria2", lambda: motor_aria2.baixar_binario(destino), pronto, falhou)

    def _aba_capas(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(4, 14, 4, 10)
        col.setSpacing(14)
        col.addWidget(widgets.ajuda(
            "As duas chaves são gratuitas e opcionais. Sem elas o catálogo funciona "
            "com capas geradas a partir do título. As imagens ficam no seu computador."))

        self.campo_tmdb = QLineEdit()
        self.campo_tmdb.setEchoMode(QLineEdit.Password)
        self.campo_tmdb.setAccessibleName("Chave do TMDB")
        col.addWidget(_linha_rotulada(
            "Chave do TMDB — filmes e séries",
            self._com_botoes(self.campo_tmdb, "Testar",
                             lambda: self._testar_tmdb()),
            "Crie a conta em themoviedb.org, vá em Configurações → API, escolha "
            "Developer e copie a “API Key (v3 auth)” — a curta, de 32 caracteres."))
        self.retorno_tmdb = Retorno()
        col.addWidget(self.retorno_tmdb)

        self.combo_idioma = QComboBox()
        for valor, rotulo in (("pt-BR", "Português (Brasil)"), ("pt-PT", "Português (Portugal)"),
                              ("en-US", "Inglês"), ("es-ES", "Espanhol")):
            self.combo_idioma.addItem(rotulo, valor)
        col.addWidget(_linha_rotulada("Idioma das sinopses", self.combo_idioma))

        self.campo_sgdb = QLineEdit()
        self.campo_sgdb.setEchoMode(QLineEdit.Password)
        self.campo_sgdb.setAccessibleName("Chave do SteamGridDB")
        col.addWidget(_linha_rotulada(
            "Chave do SteamGridDB — jogos",
            self._com_botoes(self.campo_sgdb, "Testar",
                             lambda: self._testar_sgdb()),
            "O login do steamgriddb.com é pela Steam. Depois vá em "
            "Preferences → API e gere a chave."))
        self.retorno_sgdb = Retorno()
        col.addWidget(self.retorno_sgdb)

        linha = QHBoxLayout()
        self.b_fundos = QPushButton("Buscar imagens de fundo")
        self.b_fundos.setToolTip(
            "Baixa a imagem larga que aparece atrás do título na tela da obra.")
        self.b_fundos.clicked.connect(self._buscar_fundos)
        self.b_capas = QPushButton("Buscar capas que faltam")
        self.b_capas.setProperty("destaque", "true")
        self.b_capas.clicked.connect(lambda: self._buscar_capas(False))
        linha.addWidget(self.b_capas)
        b_todas = QPushButton("Rebuscar todas")
        b_todas.clicked.connect(lambda: self._buscar_capas(True))
        linha.addWidget(b_todas)
        linha.addWidget(self.b_fundos)
        linha.addStretch(1)
        col.addLayout(linha)
        self.retorno_capas = Retorno()
        col.addWidget(self.retorno_capas)
        col.addStretch(1)
        return self._rolavel(w)

    def _aba_seguranca(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(4, 14, 4, 10)
        col.setSpacing(14)

        aviso = Retorno()
        aviso.mostrar("aviso", "Por que isto existe",
                      "Apagar a mídia e guardar só o .torrent só é reversível enquanto "
                      "houver quem compartilhe. Estas travas impedem o app de liberar "
                      "espaço de algo que talvez não volte.")
        col.addWidget(aviso)

        self.spin_seeders = QSpinBox()
        self.spin_seeders.setRange(0, 99)
        self.spin_seeders.setMaximumWidth(110)
        col.addWidget(_linha_rotulada(
            "Mínimo de seeders para liberar espaço", self.spin_seeders,
            "Abaixo disso o botão de liberar fica bloqueado. 0 desliga a trava — "
            "não recomendado."))

        self.spin_validade = QSpinBox()
        self.spin_validade.setRange(1, 365)
        self.spin_validade.setMaximumWidth(110)
        col.addWidget(_linha_rotulada(
            "Validade da checagem de seeders (dias)", self.spin_validade,
            "Passado esse prazo o app pede uma checagem nova antes de deixar apagar."))

        self.campo_protegidas = QLineEdit()
        col.addWidget(_linha_rotulada(
            "Pastas protegidas", self.campo_protegidas,
            "Separe por vírgula. Nada dentro delas pode ser apagado pelo app."))
        col.addStretch(1)
        return self._rolavel(w)

    def _aba_duplicatas(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(4, 14, 4, 10)
        col.setSpacing(12)
        col.addWidget(widgets.ajuda(
            "O app já junta sozinho os .torrent com o mesmo conteúdo (mesmo infohash). "
            "Aqui ficam os casos que ele não pode decidir sozinho: a mesma obra "
            "catalogada com nomes diferentes."))

        linha = QHBoxLayout()
        b_procurar = QPushButton("Procurar duplicatas")
        b_procurar.clicked.connect(self._procurar_duplicatas)
        linha.addWidget(b_procurar)
        b_auto = QPushButton("Juntar as confirmadas")
        b_auto.setProperty("destaque", "true")
        b_auto.clicked.connect(self._juntar_confirmadas)
        linha.addWidget(b_auto)
        linha.addStretch(1)
        col.addLayout(linha)
        col.addWidget(widgets.ajuda(
            "“Juntar as confirmadas” só mexe no que o TMDB garantiu ser a mesma obra. "
            "As parecidas ficam para você decidir, uma a uma."))

        self.retorno_dup = Retorno()
        col.addWidget(self.retorno_dup)

        self.area_dup = QWidget()
        self.dup_layout = QVBoxLayout(self.area_dup)
        self.dup_layout.setContentsMargins(0, 0, 0, 0)
        self.dup_layout.setSpacing(10)
        col.addWidget(self.area_dup)
        col.addStretch(1)
        return self._rolavel(w)

    def _ver_guia(self) -> None:
        """Volta ao catalogo e abre o tour: o guia aponta para a tela de la."""
        janela = self.window()
        if hasattr(janela, "abrir_guia"):
            janela.abrir_guia()

    def _aba_sobre(self) -> QWidget:
        """Quem fez, sob que licenca, e de quem sao os dados que aparecem.

        Nao e enfeite: a GPL pede que um programa interativo diga sob que
        licenca roda, e os termos do TMDB exigem a atribuicao onde os dados
        deles aparecem. Ficar so no README nao cumpre nenhuma das duas.
        """
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(4, 14, 4, 10)
        col.setSpacing(12)

        nome = QLabel("Acervo")
        nome.setObjectName("tituloSecaoGrande")
        col.addWidget(nome)
        col.addWidget(widgets.ajuda(
            f"Versão {sobre.VERSAO} — {sobre.DESCRICAO}"))

        grupo = QGroupBox("Software livre")
        gl = QVBoxLayout(grupo)
        gl.addWidget(widgets.ajuda(
            sobre.COPYRIGHT + "\n\n" +
            "Este programa é software livre, sob a Licença Pública Geral GNU, "
            "versão 3 ou posterior. Você pode usá-lo, estudá-lo, modificá-lo e "
            "redistribuí-lo. Se distribuir uma versão modificada, precisa "
            "distribuir o código dela também.\n\n"
            "Ele vem SEM NENHUMA GARANTIA, na medida permitida por lei."))
        linha = QHBoxLayout()
        b_lic = QPushButton("Ver a licença completa")
        b_lic.setAccessibleName("Abrir o texto da Licença Pública Geral GNU")
        b_lic.clicked.connect(self._ver_licenca)
        linha.addWidget(b_lic)
        b_rep = QPushButton("Código-fonte no GitHub")
        b_rep.setAccessibleName("Abrir o repositório do projeto no navegador")
        b_rep.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(sobre.REPOSITORIO)))
        linha.addWidget(b_rep)
        linha.addStretch(1)
        gl.addLayout(linha)
        col.addWidget(grupo)

        grupo2 = QGroupBox("Software e dados de terceiros")
        g2 = QVBoxLayout(grupo2)
        g2.addWidget(widgets.ajuda(
            "PySide6 / Qt — LGPL-3.0, vinculado dinamicamente.\n"
            "aria2 — GPL-2.0 ou posterior. Não é redistribuído: o app baixa o "
            "binário oficial do projeto, com a sua confirmação.\n\n"
            "Este produto usa a API do TMDB, mas não é endossado nem "
            "certificado pelo TMDB.\n"
            "This product uses the TMDB API but is not endorsed or certified "
            "by TMDB.\n\n"
            "Capas de jogos por SteamGridDB."))
        col.addWidget(grupo2)

        col.addStretch(1)
        return w

    def _ver_licenca(self) -> None:
        from core import local

        for base in (local.pasta_recursos(), local.pasta_dados()):
            caminho = Path(base) / "LICENSE"
            if caminho.is_file():
                caixa = QMessageBox(self)
                caixa.setWindowTitle("Licença Pública Geral GNU, versão 3")
                caixa.setText("O Acervo é distribuído sob a GPL-3.0-or-later.")
                caixa.setDetailedText(
                    caminho.read_text(encoding="utf-8", errors="replace"))
                caixa.exec()
                return
        QDesktopServices.openUrl(QUrl(sobre.URL_LICENCA))

    def _aba_reproducao(self) -> QWidget:
        """Player embutido: ligar, escolher motor, e baixar um se faltar."""
        from core import players

        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(4, 14, 4, 10)
        col.setSpacing(14)
        col.addWidget(widgets.ajuda(
            "Com o player embutido ligado, “Reproduzir” abre o vídeo dentro do "
            "Acervo. Desligado, ele abre no programa padrão do Windows."))

        self.marca_embutido = QCheckBox("Reproduzir dentro do Acervo")
        self.marca_embutido.setAccessibleName("Usar o player embutido")
        col.addWidget(self.marca_embutido)

        grupo = QGroupBox("Motor de vídeo")
        gl = QVBoxLayout(grupo)
        gl.addWidget(widgets.ajuda(
            "O motor decodifica o vídeo. VLC e mpv trazem os próprios "
            "decodificadores, então tocam x265, DTS e MKV sem depender de nada "
            "instalado no Windows — que é onde o player do sistema costuma "
            "falhar num acervo de filme baixado."))

        self.retorno_player = Retorno()
        gl.addWidget(self.retorno_player)

        linha = QHBoxLayout()
        b_testar = QPushButton("Ver o que há nesta máquina")
        b_testar.setAccessibleName("Detectar os motores de vídeo disponíveis")
        b_testar.clicked.connect(self._testar_player)
        linha.addWidget(b_testar)

        self.b_mpv = QPushButton("Baixar um motor de vídeo")
        self.b_mpv.setAccessibleName("Baixar o libmpv")
        self.b_mpv.setToolTip("Para quem não tem VLC instalado.")
        self.b_mpv.clicked.connect(self._baixar_mpv)
        linha.addWidget(self.b_mpv)
        linha.addStretch(1)
        gl.addLayout(linha)
        col.addWidget(grupo)

        self.campo_mpv = QLineEdit()
        self.campo_mpv.setProperty("mono", "true")
        col.addWidget(_linha_rotulada(
            "Caminho do libmpv-2.dll",
            self._com_botoes(self.campo_mpv, "Escolher…", self._escolher_mpv),
            "Deixe vazio para o app procurar sozinho."))

        col.addStretch(1)
        QTimer.singleShot(0, self._testar_player)
        return w

    def _testar_player(self) -> None:
        from core import players

        achados = players.detectar(self.cfg)
        linhas = [f"{'OK' if a['disponivel'] else '--'} {a['nome']}: {a['mensagem']}"
                  for a in achados]
        motor, explicacao = players.escolher(self.cfg)
        self.retorno_player.mostrar(
            "ok" if motor.recursos.embutido else "aviso",
            f"Vai usar: {motor.nome}.",
            explicacao + "\n\n" + "\n".join(linhas))
        self.b_mpv.setEnabled(not any(
            a["tipo"] == "mpv" and a["disponivel"] for a in achados))

    def _escolher_mpv(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Escolher o libmpv-2.dll", "", "Bibliotecas (*.dll)")
        if caminho:
            self.campo_mpv.setText(caminho)

    def _baixar_mpv(self) -> None:
        """Baixa o libmpv. Pergunta antes, com origem e tamanho a vista."""
        from core.local import pasta_dados
        from core.players import mpv as motor_mpv

        try:
            url, tamanho = motor_mpv.endereco_do_pacote()
        except Exception as e:                         # noqa: BLE001
            self.retorno_player.mostrar("erro", str(e))
            return

        if QMessageBox.question(
                self, "Baixar um motor de vídeo",
                f"Baixar o libmpv ({tamanho / 1048576:.0f} MB)?\n\n"
                f"Origem: {url}\n\n"
                "É o motor de vídeo do projeto mpv, software livre. Ele fica "
                "numa pasta ao lado do Acervo — nada é instalado no sistema, e "
                "dá para apagar depois.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes) != QMessageBox.Yes:
            return

        self.b_mpv.setEnabled(False)
        self.retorno_player.mostrar("info", "Baixando o motor de vídeo…",
                                    "São ~30 MB; pode levar um minuto.")
        destino = pasta_dados() / "dados"

        def trabalho():
            return motor_mpv.baixar_biblioteca(destino)

        def pronto(caminho):
            if not vivo(self.b_mpv):
                return
            self.campo_mpv.setText(str(caminho))
            self.cfg, _ = ajustes.salvar(self.coletar(), self.cfg)
            self.retorno_player.mostrar("ok", "Motor de vídeo pronto.",
                                        str(caminho))
            self.salvou.emit()
            self._testar_player()

        def falhou(mensagem):
            if vivo(self.b_mpv):
                self.b_mpv.setEnabled(True)
                self.retorno_player.mostrar("erro", mensagem)

        self.executor.rodar("baixar-mpv", trabalho, pronto, falhou)

    def _aba_aparencia(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(4, 14, 4, 10)
        col.setSpacing(14)
        col.addWidget(widgets.ajuda("Estas preferências ficam salvas neste computador."))

        grupo_tema = QGroupBox("Tema")
        gl = QVBoxLayout(grupo_tema)
        self.grupo_tema = QButtonGroup(self)
        for valor, rotulo, nota in (
                ("escuro", "Escuro", "O padrão."),
                ("claro", "Claro", "Para ambientes bem iluminados."),
                ("contraste", "Alto contraste", "Cores e bordas reforçadas.")):
            r = QRadioButton(rotulo)
            r.valor = valor          # type: ignore[attr-defined]
            self.grupo_tema.addButton(r)
            gl.addWidget(r)
            gl.addWidget(widgets.ajuda("    " + nota))
        col.addWidget(grupo_tema)

        grupo_guia = QGroupBox("Guia do app")
        gg = QVBoxLayout(grupo_guia)
        gg.addWidget(widgets.ajuda(
            "Um tour rápido que aponta cada parte da janela — a barra lateral, "
            "a busca, a organização e o que falta para baixar."))
        b_guia = QPushButton("Ver o guia")
        b_guia.setAccessibleName("Abrir o guia do aplicativo")
        b_guia.clicked.connect(self._ver_guia)
        gg.addWidget(b_guia)
        col.addWidget(grupo_guia)

        grupo_fonte = QGroupBox("Tamanho do texto")
        fl = QVBoxLayout(grupo_fonte)
        self.grupo_fonte = QButtonGroup(self)
        for valor, rotulo in (("normal", "Normal"), ("grande", "Grande (+15%)"),
                              ("maior", "Maior (+32%)")):
            r = QRadioButton(rotulo)
            r.valor = valor          # type: ignore[attr-defined]
            self.grupo_fonte.addButton(r)
            fl.addWidget(r)
        col.addWidget(grupo_fonte)

        from .widgets import ROTULOS_TAMANHO, TAMANHOS_CARTAO
        grupo_grade = QGroupBox("Tamanho das capas na grade")
        gg = QVBoxLayout(grupo_grade)
        self.grupo_grade = QButtonGroup(self)
        for valor in ("pequeno", "medio", "grande", "enorme"):
            r = QRadioButton(f"{ROTULOS_TAMANHO[valor]}  ({TAMANHOS_CARTAO[valor]} px)")
            r.valor = valor          # type: ignore[attr-defined]
            self.grupo_grade.addButton(r)
            gg.addWidget(r)
        gg.addWidget(widgets.ajuda(
            "Capas maiores mostram menos por tela; menores cabem mais de uma vez."))
        col.addWidget(grupo_grade)

        grupo_modo = QGroupBox("Modo de exibição")
        gm = QVBoxLayout(grupo_modo)
        self.grupo_modo = QButtonGroup(self)
        for valor, rotulo, nota in (
                ("grade", "Grade de capas", "O padrão."),
                ("lista", "Lista compacta",
                 "Uma linha por obra — bom para varrer muitos itens de uma vez.")):
            r = QRadioButton(rotulo)
            r.valor = valor          # type: ignore[attr-defined]
            self.grupo_modo.addButton(r)
            gm.addWidget(r)
            gm.addWidget(widgets.ajuda("    " + nota))
        col.addWidget(grupo_modo)

        # Aparencia responde na hora: nao faz sentido ter de salvar para ver.
        for grupo in (self.grupo_tema, self.grupo_fonte, self.grupo_grade,
                      self.grupo_modo):
            grupo.buttonClicked.connect(self._aparencia_mudou)

        atalhos = QFrame()
        atalhos.setObjectName("caixa")
        al = QVBoxLayout(atalhos)
        al.setContentsMargins(14, 12, 14, 12)
        t = QLabel("Atalhos de teclado")
        t.setObjectName("rotulo")
        al.addWidget(t)
        al.addWidget(widgets.ajuda(
            "Ctrl+L ou /     ir para a busca\n"
            "F5              reler o índice\n"
            "Ctrl+,          abrir configurações\n"
            "Tab             navegar entre os controles\n"
            "Enter           abrir a obra em foco\n"
            "Esc             fechar a janela aberta\n"
            "Ctrl+Q          sair do programa"))
        col.addWidget(atalhos)
        col.addStretch(1)
        return self._rolavel(w)

    # ------------------------------------------------------------ auxiliar

    @staticmethod
    def _com_botoes(campo: QWidget, *pares) -> QWidget:
        caixa = QWidget()
        linha = QHBoxLayout(caixa)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(6)
        linha.addWidget(campo, 1)
        for i in range(0, len(pares), 2):
            b = QPushButton(pares[i])
            b.clicked.connect(pares[i + 1])
            linha.addWidget(b)
        return caixa

    def _escolher_pasta(self, campo: QLineEdit) -> None:
        caminho = QFileDialog.getExistingDirectory(self, "Escolher pasta", campo.text())
        if caminho:
            campo.setText(caminho.replace("\\", "/"))

    # --------------------------------------------------------------- dados

    def carregar(self) -> None:
        c = ajustes.ler(self.cfg)
        self.campo_indice.setText(c["caminhos"].get("indice") or "")
        self.campo_biblioteca.setText(c["caminhos"].get("biblioteca") or "")
        self.campo_staging.setText(c["caminhos"].get("staging") or "")
        self.campo_ignorar.setText(", ".join(c["caminhos"].get("ignorar") or []))

        m = c["motor"]
        self.campo_qb_url.setText(m.get("qbittorrent_url") or "")
        self.campo_ut_url.setText(m.get("utorrent_url") or "")
        self.campo_aria2.setText(m.get("aria2_caminho") or "")
        self.campo_qb_user.setText(m.get("usuario") or "")
        self.campo_qb_senha.setText(m.get("senha") or "")
        self.marca_trackers.setChecked(bool(m.get("injetar_trackers")))
        self.marca_lixo.setChecked(bool(m.get("pular_lixo")))
        self.marca_sequencial.setChecked(bool(m.get("download_sequencial")))
        alvo_motor = m.get("tipo") or "auto"
        for b in self.grupo_motor.buttons():
            if b.valor == alvo_motor:      # type: ignore[attr-defined]
                b.setChecked(True)

        self.campo_tmdb.setText(c["metadados"].get("tmdb_api_key") or "")
        self.campo_sgdb.setText(c["metadados"].get("steamgriddb_api_key") or "")
        idioma = c["metadados"].get("tmdb_idioma") or "pt-BR"
        i = self.combo_idioma.findData(idioma)
        self.combo_idioma.setCurrentIndex(max(0, i))

        self.spin_seeders.setValue(int(c["seguranca"].get("minimo_seeders") or 1))
        self.spin_validade.setValue(int(c["seguranca"].get("validade_saude_dias") or 14))
        self.campo_protegidas.setText(
            ", ".join(c["seguranca"].get("pastas_protegidas") or []))

        rep = self.cfg.bruto.get("reproducao") or {}
        self.marca_embutido.setChecked(bool(rep.get("embutido", True)))
        self.campo_mpv.setText(rep.get("mpv_caminho") or "")

        prefs = self.cfg.bruto.get("aparencia") or {}
        for grupo, chave, padrao in ((self.grupo_tema, "tema", "escuro"),
                                     (self.grupo_fonte, "fonte", "normal"),
                                     (self.grupo_grade, "tamanho_grade", "medio"),
                                     (self.grupo_modo, "modo", "grade")):
            alvo = prefs.get(chave, padrao)
            for b in grupo.buttons():
                if b.valor == alvo:      # type: ignore[attr-defined]
                    b.setChecked(True)

    def _escolhido(self, grupo, padrao: str) -> str:
        return next((b.valor for b in grupo.buttons() if b.isChecked()), padrao)

    def aparencia(self) -> dict:
        return {"tema": self._escolhido(self.grupo_tema, "escuro"),
                "fonte": self._escolhido(self.grupo_fonte, "normal"),
                "tamanho_grade": self._escolhido(self.grupo_grade, "medio"),
                "modo": self._escolhido(self.grupo_modo, "grade")}

    def _aparencia_mudou(self, _botao=None) -> None:
        """Grava so a secao de aparencia e avisa a janela para repintar."""
        from core import config as _config
        self.cfg = _config.aplicar({"aparencia": self.aparencia()}, self.cfg.arquivo)
        self.salvou.emit()

    def coletar(self) -> dict:
        return {
            "caminhos": {
                "indice": self.campo_indice.text().strip(),
                "biblioteca": self.campo_biblioteca.text().strip(),
                "staging": self.campo_staging.text().strip(),
                "ignorar": self.campo_ignorar.text(),
            },
            "reproducao": {
                "embutido": self.marca_embutido.isChecked(),
                "mpv_caminho": self.campo_mpv.text().strip(),
            },
            "motor": {
                "tipo": self._escolhido(self.grupo_motor, "auto"),
                "qbittorrent_url": self.campo_qb_url.text().strip(),
                "utorrent_url": self.campo_ut_url.text().strip(),
                "aria2_caminho": self.campo_aria2.text().strip(),
                "usuario": self.campo_qb_user.text().strip(),
                "senha": self.campo_qb_senha.text(),
                "injetar_trackers": self.marca_trackers.isChecked(),
                "pular_lixo": self.marca_lixo.isChecked(),
                "download_sequencial": self.marca_sequencial.isChecked(),
            },
            "metadados": {
                "tmdb_api_key": self.campo_tmdb.text(),
                "tmdb_idioma": self.combo_idioma.currentData(),
                "steamgriddb_api_key": self.campo_sgdb.text(),
            },
            "seguranca": {
                "minimo_seeders": self.spin_seeders.value(),
                "validade_saude_dias": self.spin_validade.value(),
                "pastas_protegidas": self.campo_protegidas.text(),
            },
            "aparencia": self.aparencia(),
        }

    def salvar(self) -> None:
        antiga = self.cfg
        nova, avisos = ajustes.salvar(self.coletar(), antiga)

        # Varre na hora se a pasta mudou ou o catalogo esta vazio. Deixar isso
        # para um botao separado fazia o usuario sair daqui para uma tela vazia.
        if ajustes.precisa_varrer(antiga, nova, self.con):
            self.retorno_salvar.mostrar("info", "Lendo o índice…")
            self.repaint()
            r = scanner.varrer(self.con, nova.indice)
            self.varreu = r.lidos
            capas.completar_faltantes(self.con, nova.posters)

        self.cfg = nova
        self.salvou.emit()
        if avisos:
            self.retorno_salvar.mostrar("aviso", "Salvo, mas atenção:", " ".join(avisos))
            return
        self.retorno_salvar.mostrar(
            "ok", "Configurações salvas.",
            f"{self.varreu} arquivos .torrent lidos do índice." if self.varreu else "")

    # --------------------------------------------------------------- testes

    def _testar_pasta(self, campo: QLineEdit) -> None:
        r = ajustes.testar_pasta(campo.text())
        self.retorno_indice.mostrar("ok" if r["ok"] else "erro",
                                    r["mensagem"], r.get("detalhe", ""))

    def _testar_motor(self, botao: QPushButton) -> None:
        botao.setEnabled(False)
        self.retorno_qb.mostrar("info", "Testando…")
        self.repaint()
        r = ajustes.testar_motor(self.coletar().get("motor", {}), self.cfg)
        botao.setEnabled(True)
        self.retorno_qb.mostrar("ok" if r["ok"] else "erro",
                                r["mensagem"], r.get("detalhe", ""))

    def _testar_tmdb(self) -> None:
        r = ajustes.testar_tmdb(self.campo_tmdb.text(), self.cfg)
        self.retorno_tmdb.mostrar("ok" if r["ok"] else "erro",
                                  r["mensagem"], r.get("detalhe", ""))

    def _testar_sgdb(self) -> None:
        r = ajustes.testar_steamgriddb(self.campo_sgdb.text(), self.cfg)
        self.retorno_sgdb.mostrar("ok" if r["ok"] else "erro",
                                  r["mensagem"], r.get("detalhe", ""))

    def _buscar_capas(self, todas: bool) -> None:
        # Salva antes: sem a chave gravada a busca sairia sem credencial.
        self.cfg, _ = ajustes.salvar(self.coletar(), self.cfg)
        cfg = self.cfg
        self.b_capas.setEnabled(False)
        self.retorno_capas.mostrar("info", "Buscando capas…",
                                   "Uma consulta por obra; pode levar minutos.")

        def trabalho():
            con = db.conectar(cfg.banco)
            try:
                r = metadata.enriquecer(con, cfg, so_faltantes=not todas)
                geradas = capas.completar_faltantes(con, cfg.posters)
                return r, geradas
            finally:
                con.close()

        def pronto(resultado):
            if not vivo(self.b_capas):
                return
            r, geradas = resultado
            self.b_capas.setEnabled(True)
            faltou = (f" Sem correspondência: {len(r.sem_correspondencia)} "
                      "(abra a obra e use “Procurar”)." if r.sem_correspondencia else "")
            self.retorno_capas.mostrar(
                "ok", f"{r.posters} capas baixadas de {r.tentados} obras."
                      + (f" {geradas} geradas do título." if geradas else ""), faltou)

        def falhou(msg):
            self.b_capas.setEnabled(True)
            self.retorno_capas.mostrar("erro", msg)

        self.executor.rodar("capas", trabalho, pronto, falhou)

    def _buscar_fundos(self) -> None:
        self.cfg, _ = ajustes.salvar(self.coletar(), self.cfg)
        cfg = self.cfg
        self.b_fundos.setEnabled(False)
        self.retorno_capas.mostrar("info", "Buscando imagens de fundo…")

        def trabalho():
            con = db.conectar(cfg.banco)
            try:
                return metadata.buscar_fundos(con, cfg)
            finally:
                con.close()

        def pronto(r):
            if not vivo(self.b_fundos):
                return
            self.b_fundos.setEnabled(True)
            self.retorno_capas.mostrar(
                "ok", f"{r['baixados']} imagens de fundo baixadas.",
                f"{r['sem_imagem']} obras não têm imagem larga no TMDB."
                if r["sem_imagem"] else "")
            self.salvou.emit()

        def falhou(m):
            self.b_fundos.setEnabled(True)
            self.retorno_capas.mostrar("erro", m)

        self.executor.rodar("fundos", trabalho, pronto, falhou)

    # ----------------------------------------------------------- duplicatas

    def _procurar_duplicatas(self) -> None:
        while self.dup_layout.count():
            w = self.dup_layout.takeAt(0)
            if w.widget():
                w.widget().deleteLater()

        grupos = duplicatas.detectar(self.con)
        if not grupos:
            self.retorno_dup.mostrar("ok", "Nenhuma obra repetida no catálogo.")
            return

        altas = sum(1 for g in grupos if g.confianca == "alta")
        self.retorno_dup.mostrar(
            "info",
            "1 grupo encontrado." if len(grupos) == 1 else f"{len(grupos)} grupos encontrados.",
            f"{altas} com confirmação do TMDB." if altas
            else "Nenhum confirmado pelo TMDB; confira um a um.")

        for grupo in grupos:
            self.dup_layout.addWidget(self._caixa_grupo(grupo))

    def _caixa_grupo(self, grupo) -> QFrame:
        caixa = QFrame()
        caixa.setObjectName("caixa")
        col = QVBoxLayout(caixa)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(8)

        motivo = {"tmdb": "confirmada pelo TMDB — é a mesma obra",
                  "semelhanca": "títulos parecidos — confira antes de juntar"}
        col.addWidget(widgets.Etiqueta(motivo.get(grupo.motivo, grupo.motivo),
                                       "ok" if grupo.confianca == "alta" else "aviso"))
        col.addWidget(widgets.ajuda(
            "Marque a obra que deve ficar. As outras têm os releases movidos para ela."))

        escolha = QButtonGroup(caixa)
        for i, item in enumerate(grupo.itens):
            r = QRadioButton(
                f"{item['titulo']}  ·  {item['ano'] or 'sem ano'}  ·  "
                f"{item['n_torrents']} release(s)  ·  {formatar_bytes(item['bytes'])}"
                + ("  ·  no disco" if item["no_disco"] else "")
                + (f"  ·  TMDB {item['tmdb_id']}" if item["tmdb_id"] else ""))
            r.item_id = item["id"]        # type: ignore[attr-defined]
            r.setChecked(i == 0)
            escolha.addButton(r)
            col.addWidget(r)

        b = QPushButton("Juntar em uma obra")
        b.clicked.connect(lambda: self._juntar(grupo, escolha))
        col.addWidget(b, 0, Qt.AlignLeft)
        return caixa

    def _juntar(self, grupo, escolha: QButtonGroup) -> None:
        marcado = next((b for b in escolha.buttons() if b.isChecked()), None)
        if not marcado:
            return
        manter = marcado.item_id      # type: ignore[attr-defined]
        outros = [i["id"] for i in grupo.itens if i["id"] != manter]
        nome = next(i["titulo"] for i in grupo.itens if i["id"] == manter)

        resposta = QMessageBox.question(
            self, "Juntar obras",
            f"Juntar {len(outros) + 1} obras em “{nome}”?\n\n"
            "Os releases das outras passam para ela. Nenhum .torrent e nenhum "
            "arquivo de mídia é apagado.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resposta != QMessageBox.Yes:
            return

        r = duplicatas.mesclar(self.con, manter, outros)
        if r.get("ok"):
            self.retorno_dup.mostrar("ok", f"{r['juntadas']} obras juntadas.",
                                     f"{r['releases_movidos']} releases movidos.")
            self._procurar_duplicatas()
        else:
            self.retorno_dup.mostrar("erro", r.get("erro", "falhou"))

    def _juntar_confirmadas(self) -> None:
        """Reconsulta as obras de nome parecido e junta o que for a mesma.

        Antes so juntava o que ja compartilhava tmdb_id. Isso deixava de fora o
        caso mais comum em serie: o mesmo programa entrou duas vezes com nomes
        diferentes (ingles e portugues), e cada metade das temporadas ficou numa
        obra. Reconsultar primeiro faz as duas apontarem para o mesmo id.
        """
        self.retorno_dup.mostrar("info", "Conferindo com o TMDB…")
        cfg, con_caminho = self.cfg, self.cfg.banco

        def trabalho():
            con = db.conectar(con_caminho)
            try:
                return duplicatas.reidentificar_variantes(con, cfg)
            finally:
                con.close()

        def pronto(r):
            if not vivo(self.retorno_dup):
                return
            if not r.get("ok"):
                self.retorno_dup.mostrar("erro", r.get("erro", "falhou"))
                return
            if r["obras_juntadas"]:
                self.retorno_dup.mostrar(
                    "ok", f"{r['obras_juntadas']} obras juntadas.",
                    f"{r['releases_movidos']} releases movidos"
                    + (f" · {r['revistos']} reidentificadas no TMDB"
                       if r.get("revistos") else "") + ".")
            else:
                self.retorno_dup.mostrar(
                    "info", "Nada a juntar automaticamente.",
                    "Nenhuma duplicata confirmada pelo TMDB.")
            self.salvou.emit()
            self._procurar_duplicatas()

        self.executor.rodar("juntar-duplicatas", trabalho, pronto,
                            lambda m: self.retorno_dup.mostrar("erro", m))
