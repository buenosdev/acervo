"""Cores, fontes e folha de estilo do aplicativo.

Os tokens sao os mesmos do layout no Figma. Onde ha divergencia e por
acessibilidade: o cinza do mock para texto secundario (#3f3f46 sobre #0f0f14)
da 1,9:1 de contraste, muito abaixo dos 4,5:1 da WCAG AA. Aqui esse tom ficou
so para bordas e divisorias, e o texto usa TENUE, que mede 5,4:1.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Paleta:
    nome: str
    fundo: str
    lateral: str
    linha: str
    cartao: str
    cartao_bd: str
    ativo: str
    campo_bd: str
    elevado: str
    texto: str
    forte: str
    fraco: str
    tenue: str
    borda_txt: str
    azul: str
    verde: str
    roxo: str
    ambar: str
    vermelho: str
    azul_fundo: str
    verde_fundo: str
    vermelho_fundo: str
    ambar_fundo: str
    contraste_botao: str      # texto sobre o azul cheio


ESCURO = Paleta(
    nome="escuro",
    fundo="#0d0d0f", lateral="#090910", linha="#141420", cartao="#0f0f14",
    cartao_bd="#1a1a22", ativo="#131319", campo_bd="#262630", elevado="#1a1a22",
    texto="#d4d4d8", forte="#e8e8ec", fraco="#a1a1aa", tenue="#8a8a96",
    borda_txt="#3f3f46",
    azul="#4d90ff", verde="#34d17f", roxo="#a78bfa", ambar="#f0ad2e",
    vermelho="#f56565",
    azul_fundo="#10203a", verde_fundo="#0e2a1c", vermelho_fundo="#2c1416",
    ambar_fundo="#2a2010", contraste_botao="#04101f",
)

CLARO = Paleta(
    nome="claro",
    fundo="#f4f4f6", lateral="#ffffff", linha="#e0e0e6", cartao="#ffffff",
    cartao_bd="#dcdce4", ativo="#ececf2", campo_bd="#c9c9d4", elevado="#f0f0f4",
    texto="#26262e", forte="#101014", fraco="#55555f", tenue="#63636e",
    borda_txt="#b4b4c0",
    azul="#1f5fd0", verde="#12794a", roxo="#6d3fd4", ambar="#8a5a05",
    vermelho="#c0342f",
    azul_fundo="#e3edff", verde_fundo="#dff5e8", vermelho_fundo="#fde5e4",
    ambar_fundo="#fbeeda", contraste_botao="#ffffff",
)

CONTRASTE = Paleta(
    nome="contraste",
    fundo="#000000", lateral="#000000", linha="#6a6a78", cartao="#000000",
    cartao_bd="#7a7a88", ativo="#1c1c28", campo_bd="#9a9aa8", elevado="#0c0c14",
    texto="#ffffff", forte="#ffffff", fraco="#e6e6ee", tenue="#dcdce6",
    borda_txt="#9a9aa8",
    azul="#7ab4ff", verde="#5ef0a0", roxo="#c9b0ff", ambar="#ffc44d",
    vermelho="#ff8a8a",
    azul_fundo="#001636", verde_fundo="#002616", vermelho_fundo="#340d0d",
    ambar_fundo="#2e2200", contraste_botao="#000000",
)

PALETAS = {"escuro": ESCURO, "claro": CLARO, "contraste": CONTRASTE}
ESCALAS = {"normal": 1.0, "grande": 1.15, "maior": 1.32}

CORES_ESTADO = {
    "completo": ("verde", "NO DISCO"),
    "baixando": ("azul", "BAIXANDO"),
    "pausado": ("ambar", "PAUSADO"),
    "parcial": ("azul", "METADE"),
    "indice": ("tenue", "ÍNDICE"),
    "orfao": ("ambar", "ÓRFÃO"),
}


def fonte_mono() -> str:
    return '"JetBrains Mono", "Cascadia Mono", Consolas, monospace'


def fonte_texto() -> str:
    return '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif'


def px(base: int, escala: float) -> int:
    return max(1, round(base * escala))


def folha(p: Paleta, escala: float = 1.0) -> str:
    """Folha de estilo Qt do aplicativo inteiro."""
    f = lambda n: px(n, escala)  # noqa: E731
    return f"""
* {{
    font-family: {fonte_texto()};
    font-size: {f(13)}px;
    outline: none;
}}

QWidget#raiz, QWidget#areaCentral {{ background: {p.fundo}; }}
QWidget {{ color: {p.texto}; }}

/* ------------------------------------------------------------- lateral */
QWidget#lateral {{
    background: {p.lateral};
    border-right: 1px solid {p.linha};
}}
QLabel#marca {{
    font-family: {fonte_mono()};
    font-size: {f(15)}px; font-weight: 700; color: {p.forte};
}}
QLabel#marcaSub {{
    font-family: {fonte_mono()};
    font-size: {f(10)}px; color: {p.tenue};
}}
QLabel#tituloSecao {{
    font-family: {fonte_mono()};
    font-size: {f(10)}px; font-weight: 600; color: {p.tenue};
    padding: 0 8px;
}}

QPushButton#itemNav {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: {f(7)}px {f(10)}px;
    text-align: left;
    color: {p.fraco};
    font-size: {f(13)}px;
    font-weight: 500;
}}
QPushButton#itemNav:hover {{ background: {p.ativo}; color: {p.texto}; }}
QPushButton#itemNav:checked {{
    background: {p.ativo}; color: {p.forte}; border-color: {p.cartao_bd};
}}
QPushButton#itemNav:focus {{ border-color: {p.azul}; }}

QLabel#numeroNav {{
    font-family: {fonte_mono()};
    font-size: {f(11)}px; color: {p.tenue};
}}

/* ---------------------------------------------------------- topo/campos */
QWidget#topo {{
    background: {p.lateral};
    border-bottom: 1px solid {p.linha};
}}
QLabel#tituloTopo {{
    font-size: {f(14)}px; font-weight: 600; color: {p.texto};
}}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
    background: {p.ativo};
    border: 1px solid {p.campo_bd};
    border-radius: 4px;
    padding: {f(6)}px {f(9)}px;
    color: {p.texto};
    selection-background-color: {p.azul};
    selection-color: {p.contraste_botao};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
    border-color: {p.azul};
}}
QLineEdit[mono="true"] {{ font-family: {fonte_mono()}; }}
QComboBox::drop-down {{ border: none; width: {f(18)}px; }}
QComboBox QAbstractItemView {{
    background: {p.ativo}; color: {p.texto};
    border: 1px solid {p.campo_bd};
    selection-background-color: {p.azul};
    selection-color: {p.contraste_botao};
}}

QPushButton {{
    background: {p.ativo};
    color: {p.fraco};
    border: 1px solid {p.campo_bd};
    border-radius: 4px;
    padding: {f(6)}px {f(12)}px;
    font-size: {f(12)}px;
}}
QPushButton:hover {{ color: {p.forte}; border-color: {p.borda_txt}; }}
QPushButton:focus {{ border-color: {p.azul}; }}
QPushButton:disabled {{ color: {p.tenue}; border-color: {p.linha}; }}

QPushButton[destaque="true"] {{
    background: {p.azul}; border-color: {p.azul};
    color: {p.contraste_botao}; font-weight: 600;
}}
QPushButton[destaque="true"]:hover {{ background: {p.azul}; color: {p.contraste_botao}; }}
QPushButton[destaque="true"]:disabled {{ background: {p.elevado}; border-color: {p.campo_bd}; }}

QPushButton[perigo="true"] {{ color: {p.vermelho}; border-color: {p.vermelho}; }}

/* ------------------------------------------------------------- cartoes */
QFrame#cartao {{
    background: {p.cartao};
    border: 1px solid {p.cartao_bd};
    border-radius: 6px;
}}
QFrame#cartao:hover {{ border-color: {p.borda_txt}; }}
QFrame#cartao[selecionado="true"] {{ border-color: {p.azul}; }}
QLabel#tituloCartao {{
    font-size: {f(13)}px; font-weight: 600; color: {p.forte};
}}
QLabel#metaCartao {{
    font-family: {fonte_mono()};
    font-size: {f(11)}px; color: {p.tenue};
}}

/* ------------------------------------------------------------- paineis */
QLabel#tituloPainel {{ font-size: {f(18)}px; font-weight: 650; color: {p.forte}; }}
QLabel#subPainel {{
    font-family: {fonte_mono()};
    font-size: {f(11)}px; color: {p.tenue};
}}
QLabel#ajuda {{ font-size: {f(11)}px; color: {p.tenue}; }}
QLabel#rotulo {{ font-size: {f(12)}px; font-weight: 600; color: {p.texto}; }}

QFrame#release, QFrame#caixa {{
    background: {p.cartao};
    border: 1px solid {p.cartao_bd};
    border-radius: 6px;
}}

QLabel[etiqueta="true"] {{
    background: {p.elevado}; color: {p.fraco};
    border-radius: 3px; padding: {f(2)}px {f(7)}px;
    font-family: {fonte_mono()}; font-size: {f(10)}px;
}}
QLabel[etiqueta="ok"] {{ background: {p.verde_fundo}; color: {p.verde}; }}
QLabel[etiqueta="aviso"] {{ background: {p.ambar_fundo}; color: {p.ambar}; }}
QLabel[etiqueta="erro"] {{ background: {p.vermelho_fundo}; color: {p.vermelho}; }}
QLabel[etiqueta="info"] {{ background: {p.azul_fundo}; color: {p.azul}; }}

QLabel#retorno {{
    border-radius: 4px; padding: {f(8)}px {f(11)}px; font-size: {f(12)}px;
}}
QLabel#retorno[nivel="ok"] {{ background: {p.verde_fundo}; color: {p.verde}; }}
QLabel#retorno[nivel="erro"] {{ background: {p.vermelho_fundo}; color: {p.vermelho}; }}
QLabel#retorno[nivel="info"] {{ background: {p.azul_fundo}; color: {p.azul}; }}
QLabel#retorno[nivel="aviso"] {{ background: {p.ambar_fundo}; color: {p.ambar}; }}

/* --------------------------------------------------------------- abas */
QTabWidget::pane {{ border: none; border-top: 1px solid {p.linha}; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {p.fraco};
    border: 1px solid transparent; border-radius: 4px;
    padding: {f(6)}px {f(12)}px; margin-right: 3px;
    font-size: {f(12)}px;
}}
QTabBar::tab:hover {{ background: {p.ativo}; color: {p.texto}; }}
QTabBar::tab:selected {{
    background: {p.ativo}; color: {p.forte};
    border-color: {p.cartao_bd}; font-weight: 600;
}}
QTabBar::tab:focus {{ border-color: {p.azul}; }}

/* ------------------------------------------------------------ diversos */
QGroupBox {{
    border: 1px solid {p.cartao_bd}; border-radius: 6px;
    margin-top: {f(12)}px; padding: {f(14)}px {f(12)}px {f(10)}px;
    font-size: {f(12)}px; font-weight: 600; color: {p.texto};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: {f(10)}px; padding: 0 {f(5)}px; }}

QCheckBox, QRadioButton {{ font-size: {f(12)}px; color: {p.texto}; spacing: {f(8)}px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: {f(15)}px; height: {f(15)}px;
    border: 1px solid {p.campo_bd}; background: {p.ativo};
}}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: {f(8)}px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {p.azul}; border-color: {p.azul};
}}
QCheckBox:focus, QRadioButton:focus {{ color: {p.forte}; }}

QProgressBar {{
    background: {p.elevado}; border: none; border-radius: 2px;
    height: {f(5)}px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {p.azul}; border-radius: 2px; }}

QScrollBar:vertical {{ background: transparent; width: {f(10)}px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {p.campo_bd}; border-radius: {f(5)}px; min-height: {f(30)}px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.borda_txt}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QToolTip {{
    background: {p.elevado}; color: {p.texto};
    border: 1px solid {p.campo_bd}; padding: {f(5)}px {f(8)}px;
}}

QMenu {{ background: {p.lateral}; border: 1px solid {p.campo_bd}; padding: {f(4)}px; }}
QMenu::item {{ padding: {f(6)}px {f(20)}px; border-radius: 3px; }}
QMenu::item:selected {{ background: {p.ativo}; color: {p.forte}; }}

QSplitter::handle {{ background: {p.linha}; }}

/* ---------------------------------------------------- tela da obra */
QLabel#tituloGrande {{
    font-size: {f(40)}px; font-weight: 800; color: #ffffff;
    letter-spacing: -0.02em;
}}
QLabel#statusObra {{
    font-family: {fonte_mono()};
    font-size: {f(11)}px; font-weight: 700; letter-spacing: 0.06em;
}}
QLabel#sinopse {{
    font-size: {f(13)}px; color: {p.fraco}; line-height: 150%;
}}
QLabel#tituloSecaoGrande {{
    font-size: {f(15)}px; font-weight: 700; color: {p.forte};
}}
QLabel#rotuloFicha {{
    font-family: {fonte_mono()};
    font-size: {f(10)}px; color: {p.tenue}; letter-spacing: 0.09em;
}}
QLabel#valorFicha {{
    font-family: {fonte_mono()};
    font-size: {f(11)}px; color: {p.texto};
}}
QLabel#hash {{
    font-family: {fonte_mono()};
    font-size: {f(10)}px; color: {p.tenue};
    background: {p.elevado}; border-radius: 4px; padding: {f(8)}px;
}}
QLabel#monoTexto {{
    font-family: {fonte_mono()}; font-size: {f(11.5)}px; color: {p.texto};
}}
QLabel#nomeEpisodio {{ font-size: {f(13)}px; font-weight: 600; color: {p.forte}; }}
QLabel#nomeEpisodioPendente {{ font-size: {f(13)}px; font-weight: 600; color: {p.fraco}; }}
/* O nome cru do release fica de legenda: pequeno, apagado e em fonte mono, so
   para conferir de qual arquivo se trata. O `tenue` de cada paleta ja respeita
   o contraste minimo, entao no tema de alto contraste isto nao some. */
QLabel#nomeArquivoBruto {{
    font-family: {fonte_mono()}; font-size: {f(10)}px; color: {p.tenue};
}}

QFrame#linhaArquivo {{
    background: {p.cartao}; border: 1px solid {p.cartao_bd}; border-radius: 5px;
}}

QPushButton#botaoGrande {{
    padding: {f(11)}px {f(24)}px;
    font-size: {f(13)}px; font-weight: 600;
    border-radius: 5px;
}}
QPushButton#botaoEpisodio {{
    border-radius: {f(14)}px; padding: 0;
    background: {p.elevado}; color: {p.texto};
    font-size: {f(11)}px;
}}
QPushButton#botaoEpisodio:disabled {{ color: {p.tenue}; background: transparent;
                                      border-color: {p.cartao_bd}; }}
QPushButton#botaoEpisodio:hover:!disabled {{ background: {p.azul};
                                             color: {p.contraste_botao}; }}

/* ------------------------------------------------------------ topo */
QPushButton#voltar {{
    padding: {f(7)}px {f(14)}px; font-size: {f(12.5)}px;
    background: {p.elevado}; color: {p.forte};
}}
QPushButton#alternador {{
    padding: {f(5)}px {f(8)}px; min-width: {f(26)}px;
}}
QPushButton#alternador:checked {{
    background: {p.ativo}; color: {p.forte}; border-color: {p.azul};
}}

/* Rolagem sem moldura em toda a aplicacao. */
QScrollArea, QScrollArea > QWidget, QListView {{
    background: transparent; border: none;
}}
QListView {{ outline: none; }}
QListView::item:selected {{ background: transparent; }}
"""
