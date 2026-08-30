"""O que um motor de video precisa saber fazer.

Mesmo desenho de `core/motores/base.py`: o app conversa com esta interface e
nunca com um player especifico. Assim trocar de motor — VLC instalado, libmpv
baixado pelo app, ou o programa padrao do sistema — nao mexe na tela.

Por que nao o QtMultimedia, que ja vem com o Qt: ele usa o Windows Media
Foundation, que nao toca x265 sem a extensao HEVC da Microsoft (paga, e ausente
na maioria das maquinas) e nao toca audio DTS. Num acervo de filme baixado, que
e quase todo MKV com x264/x265 e faixa dupla, isso reprovaria boa parte dos
arquivos — e o pior tipo de falha: a que so aparece no arquivo que a pessoa quer
ver agora.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ErroPlayer(Exception):
    """Falha ao preparar ou tocar um video."""


@dataclass
class Faixa:
    """Uma faixa de audio ou legenda. `id` e o que o motor entende."""

    id: int
    nome: str


@dataclass
class Recursos:
    embutido: bool = True          # desenha dentro da janela do app
    faixas: bool = True            # deixa escolher audio e legenda
    posicao: bool = True           # da e aceita a posicao em segundos
    observacoes: list[str] | None = None


class Player:
    """Interface comum. Tempo sempre em segundos, nunca em milissegundos."""

    nome = "player"
    recursos = Recursos()

    # ------------------------------------------------------------ ciclo

    def disponivel(self) -> tuple[bool, str]:
        """(esta utilizavel, explicacao curta)."""
        raise NotImplementedError

    def abrir(self, caminho: Path, janela: int | None = None) -> None:
        """Carrega o arquivo. `janela` e o identificador nativo onde desenhar."""
        raise NotImplementedError

    def encerrar(self) -> None:
        """Solta tudo. Chamado ao sair da tela e ao fechar o app."""

    # ------------------------------------------------------------ tocar

    def tocar(self) -> None:
        raise NotImplementedError

    def pausar(self) -> None:
        raise NotImplementedError

    def tocando(self) -> bool:
        raise NotImplementedError

    def terminou(self) -> bool:
        return False

    # ---------------------------------------------------------- posicao

    def posicao(self) -> float:
        """Segundos desde o inicio."""
        raise NotImplementedError

    def ir_para(self, segundos: float) -> None:
        raise NotImplementedError

    def duracao(self) -> float:
        """Segundos no total. 0 enquanto o motor ainda nao sabe."""
        raise NotImplementedError

    # ------------------------------------------------------------ som

    def volume(self) -> int:
        raise NotImplementedError

    def definir_volume(self, valor: int) -> None:
        raise NotImplementedError

    def mudo(self, ligado: bool) -> None:
        raise NotImplementedError

    # ---------------------------------------------------------- faixas

    def faixas_audio(self) -> list[Faixa]:
        return []

    def definir_audio(self, faixa_id: int) -> None:
        pass

    def audio_atual(self) -> int:
        return -1

    def faixas_legenda(self) -> list[Faixa]:
        return []

    def definir_legenda(self, faixa_id: int) -> None:
        pass

    def legenda_atual(self) -> int:
        return -1

    def carregar_legenda(self, caminho: Path) -> bool:
        """Adiciona um .srt de fora do arquivo. False se o motor nao souber."""
        return False

    # Motores que sabem detectar preenchem isto; os outros deixam False.
    audio_falhou = False
