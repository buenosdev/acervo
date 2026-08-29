"""Trabalho demorado fora da linha da interface.

Varrer 250 torrents, checar seeders e buscar capas levam segundos ou minutos.
Na linha principal isso congelaria a janela, entao cada tarefa vai para uma
linha propria e devolve o resultado por sinal.

Cuidado que custou um crash para aprender: um `QRunnable` e destruido pelo pool
assim que `run()` termina. Se o objeto que emite o sinal viver dentro dele, a
entrega — que acontece depois, ja na linha principal — encontra memoria
liberada, e o app morre com violacao de acesso, sem mensagem nenhuma. Por isso
`setAutoDelete(False)` e a tarefa fica guardada ate o callback rodar.

Cada tarefa abre a propria conexao SQLite: o modulo sqlite3 nao permite usar a
mesma conexao em linhas diferentes.
"""
from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


def vivo(objeto) -> bool:
    """True se o objeto Qt ainda existe do lado C++.

    Widgets sao destruidos quando a tela e remontada; um callback que chega
    atrasado nao pode tocar neles.
    """
    if objeto is None:
        return False
    try:
        from shiboken6 import isValid
        return bool(isValid(objeto))
    except Exception:
        return True


class _Sinais(QObject):
    concluido = Signal(object)
    falhou = Signal(str)


class Tarefa(QRunnable):
    def __init__(self, funcao: Callable[[], object]):
        super().__init__()
        self.funcao = funcao
        self.sinais = _Sinais()
        # O pool nao pode apagar isto: quem apaga e o Executor, depois da entrega.
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:
        try:
            resultado = self.funcao()
        except Exception as erro:                 # a janela mostra, nunca quebra
            self._emitir(self.sinais.falhou, str(erro) or type(erro).__name__)
            return
        self._emitir(self.sinais.concluido, resultado)

    @staticmethod
    def _emitir(sinal, valor) -> None:
        try:
            sinal.emit(valor)
        except RuntimeError:
            pass                                  # a janela ja fechou


class Executor:
    """Fila de tarefas, uma por nome, com as pendentes mantidas vivas."""

    def __init__(self) -> None:
        self.pool = QThreadPool.globalInstance()
        self._rodando: set[str] = set()
        self._pendentes: dict[str, Tarefa] = {}
        self._trava = threading.Lock()
        self._encerrando = False

    def rodando(self, nome: str) -> bool:
        return nome in self._rodando

    def rodar(self, nome: str, funcao: Callable[[], object],
              ao_terminar: Callable[[object], None],
              ao_falhar: Callable[[str], None] | None = None) -> bool:
        """Dispara `funcao` numa linha separada. False se ja estava rodando."""
        with self._trava:
            if self._encerrando or nome in self._rodando:
                return False
            self._rodando.add(nome)

        tarefa = Tarefa(funcao)

        def soltar() -> None:
            with self._trava:
                self._rodando.discard(nome)
                self._pendentes.pop(nome, None)

        def terminou(resultado):
            soltar()
            if not self._encerrando:
                ao_terminar(resultado)

        def falhou(mensagem):
            soltar()
            if not self._encerrando and ao_falhar:
                ao_falhar(mensagem)

        tarefa.sinais.concluido.connect(terminou)
        tarefa.sinais.falhou.connect(falhou)

        with self._trava:
            self._pendentes[nome] = tarefa        # segura ate a entrega
        self.pool.start(tarefa)
        return True

    def aguardar(self, ms: int = 3000) -> None:
        """Chamado ao fechar: para de aceitar tarefas e espera as em voo."""
        self._encerrando = True
        self.pool.waitForDone(ms)
        with self._trava:
            self._pendentes.clear()
