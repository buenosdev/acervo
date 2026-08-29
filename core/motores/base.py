"""O contrato que todo motor de download precisa cumprir.

O resto do app (downloads.py, health.py, organizer.py) fala so com esta
interface, nunca com um cliente especifico. Assim trocar de motor nao espalha
mudanca pelo codigo, e cada motor pode declarar honestamente o que nao sabe
fazer em vez de fingir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class ErroMotor(RuntimeError):
    """Falha ao falar com o cliente (fora do ar, senha errada, versao antiga)."""


@dataclass
class Progresso:
    infohash: str
    nome: str
    estado: str                # baixando | pausado | semeando | concluido | erro
    progresso: float           # 0.0 a 1.0
    baixado: int
    tamanho: int
    velocidade: int            # bytes/s
    seeds: int
    peers: int
    eta: int                   # segundos; 0 quando desconhecido
    caminho: str
    ratio: float | None = None
    adicionado: int | None = None   # timestamp

    @property
    def terminou(self) -> bool:
        return self.estado in ("concluido", "semeando")

    @property
    def pausado(self) -> bool:
        return self.estado == "pausado"


@dataclass
class Recursos:
    """O que este motor sabe fazer. A interface esconde o que ele nao sabe."""
    escolher_arquivos: bool = True     # baixar so parte do torrent
    injetar_trackers: bool = True
    renomear: bool = False             # renomear sem quebrar o seeding
    mover: bool = False                # trocar a pasta pela API
    sequencial: bool = False
    semeia_bem: bool = True            # continua semeando depois de concluir
    observacoes: list[str] = field(default_factory=list)


class Motor:
    """Base dos motores. Os metodos que nao se aplicam podem nao fazer nada."""

    nome = "?"
    recursos = Recursos()

    # ------------------------------------------------------------- conexao

    def disponivel(self) -> tuple[bool, str]:
        """(esta_no_ar, versao_ou_mensagem_de_erro). Nunca levanta excecao."""
        raise NotImplementedError

    # ------------------------------------------------------------- consulta

    def listar(self, infohashes: list[str] | None = None) -> list[Progresso]:
        raise NotImplementedError

    def arquivos(self, infohash: str) -> list[dict]:
        """[{indice, nome, tamanho, prioridade}] — nomes relativos ao torrent."""
        return []

    # ---------------------------------------------------------------- acoes

    def adicionar(self, caminho_torrent: Path, pasta_destino: Path,
                  categoria: str | None = None, pausado: bool = True) -> None:
        raise NotImplementedError

    def adicionar_trackers(self, infohash: str, urls: list[str]) -> None:
        return None

    def nao_baixar(self, infohash: str, indices: list[int]) -> None:
        """Marca arquivos para nao serem baixados (a propaganda dos sites)."""
        return None

    def sequencial(self, infohash: str) -> None:
        return None

    def iniciar(self, infohash: str) -> None:
        raise NotImplementedError

    def parar(self, infohash: str) -> None:
        raise NotImplementedError

    def remover(self, infohash: str, apagar_arquivos: bool = False) -> None:
        raise NotImplementedError

    # ------------------------------------------------------- organizacao

    def renomear_arquivo(self, infohash: str, de: str, para: str) -> None:
        raise ErroMotor(f"{self.nome} não sabe renomear arquivos pela API.")

    def mover(self, infohash: str, destino: str | Path) -> None:
        raise ErroMotor(f"{self.nome} não sabe mover o torrent pela API.")

    # ------------------------------------------------------------ encerrar

    def encerrar(self) -> None:
        """Chamado ao fechar o app. So importa para motor que o app iniciou."""
        return None
