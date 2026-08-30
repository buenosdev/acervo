"""Ultimo recurso: entrega o arquivo ao programa padrao do Windows.

Nao e um player embutido — a janela do Acervo nao desenha nada e nao controla
nada. Existe para que o botao Reproduzir nunca fique morto: sem VLC e sem
libmpv, ele volta a ser exatamente o que era antes de haver player embutido.
"""
from __future__ import annotations

import os
from pathlib import Path

from .base import ErroPlayer, Player, Recursos


class PlayerSistema(Player):
    nome = "programa padrão do Windows"
    recursos = Recursos(
        embutido=False, faixas=False, posicao=False,
        observacoes=["Abre fora do Acervo, no programa que o Windows usa."])

    def disponivel(self) -> tuple[bool, str]:
        return True, "abre no programa padrão do sistema"

    def abrir(self, caminho: Path, janela: int | None = None) -> None:
        try:
            os.startfile(str(caminho))
        except OSError as e:
            raise ErroPlayer(f"não consegui abrir: {e}") from e

    def tocar(self) -> None:
        pass

    def pausar(self) -> None:
        pass

    def tocando(self) -> bool:
        return False

    def posicao(self) -> float:
        return 0.0

    def ir_para(self, segundos: float) -> None:
        pass

    def duracao(self) -> float:
        return 0.0

    def volume(self) -> int:
        return 100

    def definir_volume(self, valor: int) -> None:
        pass

    def mudo(self, ligado: bool) -> None:
        pass
