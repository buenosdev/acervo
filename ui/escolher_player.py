"""Onde assistir: aqui dentro ou no programa do Windows.

A pergunta aparece antes de reproduzir e some assim que a pessoa disser que nao
quer ser perguntada. Duas razoes para ela existir:

  * player embutido nao serve a todo mundo. Quem ja tem um player configurado
    do jeito que gosta — legendas, atalhos, filtros — nao quer trocar;
  * e a escolha feita aqui e a mesma de Configuracoes -> Reproducao. Sao duas
    portas para o mesmo ajuste, e nao dois ajustes parecidos que se contradizem
    depois.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout)

from . import tema, widgets

AQUI = "aqui"
FORA = "fora"


class EscolherPlayer(QDialog):
    """Devolve (escolha, lembrar). `escolha` e AQUI ou FORA; None se cancelou."""

    def __init__(self, titulo: str, motor_embutido: str, paleta: tema.Paleta,
                 escala: float, pai=None):
        super().__init__(pai)
        self.escolha: str | None = None
        self.setWindowTitle("Onde assistir")
        self.setModal(True)

        col = QVBoxLayout(self)
        m = tema.px(22, escala)
        col.setContentsMargins(m, m, m, tema.px(16, escala))
        col.setSpacing(tema.px(12, escala))

        t = QLabel(f"Onde você quer assistir “{titulo}”?")
        t.setObjectName("tituloSecaoGrande")
        t.setWordWrap(True)
        col.addWidget(t)

        col.addWidget(widgets.ajuda(
            "Dá para mudar depois em Configurações → Reprodução — é o mesmo "
            "ajuste."))

        b_aqui = QPushButton(f"  Aqui no Acervo   ·   {motor_embutido}")
        b_aqui.setObjectName("botaoGrande")
        b_aqui.setProperty("destaque", "true")
        b_aqui.setIcon(widgets.icone_player("tocar", paleta.contraste_botao,
                                            tema.px(17, escala)))
        b_aqui.setAccessibleName("Assistir dentro do Acervo")
        b_aqui.clicked.connect(lambda: self._escolher(AQUI))
        col.addWidget(b_aqui)

        b_fora = QPushButton("  No programa padrão do Windows")
        b_fora.setObjectName("botaoGrande")
        b_fora.setAccessibleName("Abrir no programa padrão do sistema")
        b_fora.clicked.connect(lambda: self._escolher(FORA))
        col.addWidget(b_fora)

        self.marca = QCheckBox("Não perguntar de novo")
        self.marca.setAccessibleName("Usar sempre a escolha feita agora")
        col.addWidget(self.marca)

        rodape = QHBoxLayout()
        rodape.addStretch(1)
        b_cancelar = QPushButton("Cancelar")
        b_cancelar.clicked.connect(self.reject)
        rodape.addWidget(b_cancelar)
        col.addLayout(rodape)

        b_aqui.setFocus(Qt.OtherFocusReason)

    def _escolher(self, qual: str) -> None:
        self.escolha = qual
        self.accept()

    def lembrar(self) -> bool:
        return self.marca.isChecked()


def perguntar(cfg, titulo: str, paleta: tema.Paleta, escala: float,
              pai=None) -> tuple[str | None, bool]:
    """Pergunta onde assistir. Devolve (escolha, lembrar).

    Quando a pessoa ja pediu para nao ser perguntada, devolve direto o que ficou
    guardado — sem dialogo nenhum.
    """
    from core import players

    opcoes = cfg.bruto.get("reproducao") or {}
    if not opcoes.get("perguntar", True):
        return (AQUI if opcoes.get("embutido", True) else FORA), False

    motor, _ = players.escolher(cfg)
    if not motor.recursos.embutido:
        # Nao ha player embutido utilizavel: perguntar seria oferecer uma
        # opcao que nao existe.
        return FORA, False

    dialogo = EscolherPlayer(titulo, motor.nome, paleta, escala, pai)
    if dialogo.exec() != QDialog.Accepted:
        return None, False
    return dialogo.escolha, dialogo.lembrar()


class ContinuarDe(QDialog):
    """Pergunta se retoma de onde parou. Devolve o ponto, ou 0 para o inicio."""

    def __init__(self, titulo: str, segundos: float, duracao: float,
                 paleta: tema.Paleta, escala: float, pai=None):
        super().__init__(pai)
        self.ponto = 0.0
        self.setWindowTitle("Continuar assistindo")
        self.setModal(True)

        col = QVBoxLayout(self)
        m = tema.px(22, escala)
        col.setContentsMargins(m, m, m, tema.px(16, escala))
        col.setSpacing(tema.px(12, escala))

        t = QLabel(f"Você parou “{titulo}” em {_tempo(segundos)}.")
        t.setObjectName("tituloSecaoGrande")
        t.setWordWrap(True)
        col.addWidget(t)

        if duracao:
            col.addWidget(widgets.ajuda(
                f"São {_tempo(duracao - segundos)} até o fim."))

        b_continuar = QPushButton(f"  Continuar de {_tempo(segundos)}")
        b_continuar.setObjectName("botaoGrande")
        b_continuar.setProperty("destaque", "true")
        b_continuar.setIcon(widgets.icone_player("tocar", paleta.contraste_botao,
                                                 tema.px(17, escala)))
        b_continuar.setAccessibleName(f"Continuar de {_tempo(segundos)}")
        b_continuar.clicked.connect(lambda: self._responder(segundos))
        col.addWidget(b_continuar)

        b_inicio = QPushButton("  Começar do início")
        b_inicio.setObjectName("botaoGrande")
        b_inicio.setIcon(widgets.icone_player("recomecar", paleta.forte,
                                              tema.px(17, escala)))
        b_inicio.setAccessibleName("Começar do início")
        b_inicio.clicked.connect(lambda: self._responder(0.0))
        col.addWidget(b_inicio)

        b_continuar.setFocus(Qt.OtherFocusReason)

    def _responder(self, ponto: float) -> None:
        self.ponto = ponto
        self.accept()


def _tempo(segundos: float) -> str:
    segundos = max(0, int(segundos))
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def onde_parou(con, caminho, titulo: str, paleta: tema.Paleta, escala: float,
               pai=None) -> float | None:
    """Pergunta se retoma. Devolve os segundos, 0 para o inicio, None se desistiu.

    So pergunta quando ha ponto guardado. Perguntar sempre transformaria dar
    play em duas decisoes, e a segunda seria quase sempre "sim, do inicio" —
    ruido puro.
    """
    from ui.tela_player import MINIMO_PARA_GUARDAR, posicao_guardada

    ponto = posicao_guardada(con, caminho)
    if ponto <= MINIMO_PARA_GUARDAR:
        return 0.0

    linha = con.execute("SELECT duracao FROM posicoes WHERE caminho = ?",
                        (str(caminho),)).fetchone()
    duracao = float(linha["duracao"] or 0) if linha else 0.0

    dialogo = ContinuarDe(titulo, ponto, duracao, paleta, escala, pai)
    if dialogo.exec() != QDialog.Accepted:
        return None
    return dialogo.ponto
