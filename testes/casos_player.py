"""Regras do player embutido.

Duas coisas que só aparecem em uso e são chatas de descobrir tarde:

  1. **a escolha do motor.** Ela precisa terminar sempre em algo que funcione.
     Sem VLC e sem libmpv, o botão Reproduzir não pode ficar morto — cai no
     programa padrão do sistema, que é o comportamento que existia antes de
     haver player embutido. E com o player desligado nas Configurações, o
     embutido não pode ser escolhido de jeito nenhum;

  2. **quando guardar a posição.** Guardar sempre é pior que não guardar:
     oferecer "retomar de 0:08" logo depois de abrir, ou "retomar de 1:58 de
     2:00" num filme já assistido, é ruído. A regra tem margem nas duas pontas.

    python -m testes.casos_player
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, players                          # noqa: E402
from ui.tela_player import (MINIMO_PARA_GUARDAR, guardar_posicao,  # noqa: E402
                            posicao_guardada)


class _Config:
    """Config mínima, para não depender do config.toml da máquina."""

    def __init__(self, **reproducao):
        self.bruto = {"reproducao": reproducao}


def _escolha(**reproducao) -> tuple[str, bool]:
    motor, _ = players.escolher(_Config(**reproducao))
    return motor.nome, motor.recursos.embutido


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    falhas = 0

    # --- 1. escolha do motor -------------------------------------------------
    tem_vlc = players.pasta_do_vlc() is not None
    nome, embutido = _escolha(embutido=True, motor="auto")
    if tem_vlc and not embutido:
        print(f"FALHA  há VLC nesta máquina, mas escolheu {nome}")
        falhas += 1
    else:
        print(f"OK     com VLC={tem_vlc}: escolheu {nome} (embutido={embutido})")

    # Player desligado nas Configurações: nunca pode devolver motor embutido.
    nome, embutido = _escolha(embutido=False)
    if embutido:
        print(f"FALHA  player desligado e ainda assim escolheu {nome} embutido")
        falhas += 1
    else:
        print("OK     desligado nas Configurações cai no programa do sistema")

    # Sem nenhum motor: apontando caminhos que não existem, tem de sobrar o
    # do sistema — o botão Reproduzir nunca fica morto.
    nome, embutido = _escolha(embutido=True, motor="auto",
                              vlc_caminho="Z:/nao/existe",
                              mpv_caminho="Z:/nao/existe/libmpv-2.dll")
    if embutido:
        print(f"FALHA  sem motor instalado, escolheu {nome} como embutido")
        falhas += 1
    else:
        print("OK     sem VLC e sem libmpv, sobra o programa do sistema")

    # --- 2. quando guardar a posição ----------------------------------------
    pasta = Path(tempfile.mkdtemp(prefix="acervo-player-"))
    con = db.conectar(pasta / "teste.db")
    filme = Path("C:/filmes/exemplo.mkv")
    duracao = 5400.0                       # 1h30

    casos = [
        ("logo no começo", 8.0, False),
        ("no limite de baixo", MINIMO_PARA_GUARDAR - 1, False),
        ("no meio", 1800.0, True),
        ("quase no fim", duracao * 0.97, False),
    ]
    for rotulo, segundos, esperado in casos:
        guardou = guardar_posicao(con, filme, segundos, duracao)
        if guardou != esperado:
            print(f"FALHA  {rotulo}: guardou={guardou}, esperado={esperado}")
            falhas += 1
    else:
        print("OK     guarda no meio; ignora o começo e o fim")

    # Chegar ao fim precisa apagar o que havia, senão o filme fica oferecendo
    # "retomar" para sempre depois de assistido.
    guardar_posicao(con, filme, 1800.0, duracao)
    guardar_posicao(con, filme, duracao * 0.99, duracao)
    if posicao_guardada(con, filme) != 0.0:
        print("FALHA  assistir até o fim não limpou a posição guardada")
        falhas += 1
    else:
        print("OK     assistir até o fim limpa a posição")

    # --- 3. a pergunta "onde assistir" ---------------------------------------
    from ui.escolher_player import AQUI, FORA, perguntar

    class _Cfg(_Config):
        pass

    # Quem ja pediu para nao ser perguntado nao ve dialogo nenhum: a resposta
    # sai direto do que ficou guardado.
    escolha, lembrar = perguntar(_Cfg(perguntar=False, embutido=True), "x", None, 1.0)
    if escolha != AQUI or lembrar:
        print(f"FALHA  com perguntar=False e embutido=True, devia devolver {AQUI}")
        falhas += 1
    escolha, _ = perguntar(_Cfg(perguntar=False, embutido=False), "x", None, 1.0)
    if escolha != FORA:
        print(f"FALHA  com embutido=False, devia devolver {FORA}")
        falhas += 1
    else:
        print("OK     não pergunta quando a pessoa já decidiu")

    # Sem motor embutido utilizavel, perguntar seria oferecer o que nao existe.
    escolha, _ = perguntar(_Cfg(perguntar=True, embutido=True,
                                vlc_caminho="Z:/nao/existe",
                                mpv_caminho="Z:/nao/existe/libmpv-2.dll"),
                           "x", None, 1.0)
    if escolha != FORA:
        print("FALHA  sem motor embutido, não devia oferecer a opção de assistir aqui")
        falhas += 1
    else:
        print("OK     sem motor embutido, vai direto para o programa do sistema")

    con.close()
    import shutil
    shutil.rmtree(pasta, ignore_errors=True)

    if falhas:
        print(f"\n{falhas} falha(s).")
        return 1
    print("\nOK: o player escolhe um motor utilizável e guarda posição com juízo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
