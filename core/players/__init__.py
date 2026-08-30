"""Escolha do motor de video.

Mesmo desenho de `core/motores/`: o app fala com `base.Player` e nunca com um
motor especifico. `detectar()` conta o que existe na maquina, `escolher()`
devolve o melhor disponivel.

A ordem nao e arbitraria. O VLC vem primeiro porque, quando ja esta instalado,
nao custa nada e toca tudo. O libmpv vem depois porque o app precisa baixa-lo
antes. E o programa padrao do sistema fecha a fila, sempre disponivel: assim o
botao Reproduzir nunca fica morto, mesmo sem nenhum motor embutido — e o
comportamento nesse caso e exatamente o que existia antes deste modulo.
"""
from __future__ import annotations

from .base import ErroPlayer, Faixa, Player, Recursos
from .mpv import PlayerMPV, procurar_libmpv
from .sistema import PlayerSistema
from .vlc import PlayerVLC, pasta_do_vlc

__all__ = ["ErroPlayer", "Faixa", "Player", "PlayerMPV", "PlayerSistema",
           "PlayerVLC", "Recursos", "ORDEM", "ROTULOS", "criar", "detectar",
           "escolher", "pasta_do_vlc", "procurar_libmpv"]

ORDEM = ("vlc", "mpv", "sistema")
ROTULOS = {"vlc": "VLC", "mpv": "libmpv", "sistema": "Programa padrão do Windows",
           "auto": "Escolher automaticamente"}


def criar(tipo: str, cfg=None) -> Player:
    opcoes = (cfg.bruto.get("reproducao") if cfg else None) or {}
    if tipo == "vlc":
        return PlayerVLC(opcoes.get("vlc_caminho") or None)
    if tipo == "mpv":
        return PlayerMPV(opcoes.get("mpv_caminho") or None)
    if tipo == "sistema":
        return PlayerSistema()
    raise ValueError(f"motor de vídeo desconhecido: {tipo}")


def detectar(cfg=None) -> list[dict]:
    """Testa cada motor e relata. Nao levanta excecao."""
    saida = []
    for tipo in ORDEM:
        try:
            motor = criar(tipo, cfg)
            no_ar, mensagem = motor.disponivel()
        except Exception as e:                        # noqa: BLE001
            saida.append({"tipo": tipo, "nome": ROTULOS[tipo], "disponivel": False,
                          "mensagem": str(e), "recursos": Recursos()})
            continue
        saida.append({"tipo": tipo, "nome": motor.nome, "disponivel": no_ar,
                      "mensagem": mensagem, "recursos": motor.recursos})
    return saida


def escolher(cfg=None) -> tuple[Player, str]:
    """O motor a usar agora. Sempre devolve um — no pior caso, o do sistema."""
    opcoes = (cfg.bruto.get("reproducao") if cfg else None) or {}

    if not opcoes.get("embutido", True):
        motor = PlayerSistema()
        return motor, "player embutido desligado nas Configurações"

    preferido = (opcoes.get("motor") or "auto").lower()
    if preferido != "auto":
        try:
            motor = criar(preferido, cfg)
            no_ar, mensagem = motor.disponivel()
            if no_ar:
                return motor, mensagem
        except (ValueError, Exception):               # noqa: BLE001
            pass

    for tipo in ORDEM:
        try:
            motor = criar(tipo, cfg)
            no_ar, mensagem = motor.disponivel()
        except Exception:                             # noqa: BLE001
            continue
        if no_ar:
            return motor, mensagem
    return PlayerSistema(), "abre no programa padrão do sistema"
