"""Escolha do motor de download.

O app fala com `Motor` (base.py) e nunca com um cliente especifico. Este modulo
descobre qual esta disponivel e devolve o melhor.

A ordem de preferencia nao e arbitraria: o qBittorrent vem primeiro porque e o
unico dos tres que semeia direito depois de concluir — e este projeto inteiro
depende de haver quem semeie, senao apagar a midia deixa de ser reversivel. O
uTorrent vem em seguida por ser comum e ja estar instalado em muita maquina. O
aria2 e o ultimo: baixa bem, mas so semeia enquanto o app estiver aberto.
"""
from __future__ import annotations

from pathlib import Path

from .aria2 import Aria2, procurar_binario as procurar_aria2
from .base import ErroMotor, Motor, Progresso, Recursos
from .qbittorrent import Qbit
from .utorrent import UTorrent

__all__ = ["Aria2", "ErroMotor", "Motor", "Progresso", "Qbit", "Recursos",
           "UTorrent", "como_ligar", "criar", "detectar", "escolher",
           "instalados", "ORDEM", "ROTULOS"]

ORDEM = ("qbittorrent", "utorrent", "aria2")
ROTULOS = {"qbittorrent": "qBittorrent", "utorrent": "uTorrent", "aria2": "aria2",
           "auto": "Detectar automaticamente"}

# Enderecos padrao de cada um, usados quando a configuracao nao diz outra coisa.
PADRAO_URL = {"qbittorrent": "http://127.0.0.1:8080",
              "utorrent": "http://127.0.0.1:8080"}


def criar(tipo: str, cfg) -> Motor:
    """Instancia um motor pelo nome, com o que estiver na configuracao."""
    opcoes = cfg.bruto.get("motor") or {}
    if tipo == "qbittorrent":
        return Qbit(opcoes.get("qbittorrent_url") or PADRAO_URL["qbittorrent"],
                    opcoes.get("usuario", ""), opcoes.get("senha", ""))
    if tipo == "utorrent":
        return UTorrent(opcoes.get("utorrent_url") or PADRAO_URL["utorrent"],
                        opcoes.get("usuario", ""), opcoes.get("senha", ""))
    if tipo == "aria2":
        binario = opcoes.get("aria2_caminho") or None
        return Aria2(Path(binario) if binario else None,
                     pasta_padrao=Path(cfg.staging),
                     tempo_semeando=int(opcoes.get("aria2_seed_min", 60)),
                     pasta_dados=Path(getattr(cfg, "dados", "") or "") or None)
    raise ValueError(f"motor desconhecido: {tipo}")


def detectar(cfg, incluir_aria2: bool = True) -> list[dict]:
    """Testa cada motor e relata o que achou. Nao levanta excecao.

    Devolve [{tipo, nome, disponivel, mensagem, recursos}] na ordem de
    preferencia — serve tanto para escolher sozinho quanto para a tela mostrar
    o estado de cada um.
    """
    saida = []
    for tipo in ORDEM:
        if tipo == "aria2" and not incluir_aria2:
            continue
        try:
            motor = criar(tipo, cfg)
        except Exception as e:                        # noqa: BLE001
            saida.append({"tipo": tipo, "nome": ROTULOS[tipo], "disponivel": False,
                          "mensagem": str(e), "recursos": Recursos()})
            continue

        # O aria2 so conta como disponivel se o binario existir; iniciar o
        # processo aqui, so para testar, seria intrusivo demais.
        if tipo == "aria2":
            binario = motor.binario
            existe = bool(binario and Path(binario).is_file())
            saida.append({
                "tipo": tipo, "nome": motor.nome, "disponivel": existe,
                "mensagem": (f"pronto ({binario})" if existe else
                             "o aria2c.exe não está aqui — dá para baixar em "
                             "Configurações → Torrent"),
                "recursos": motor.recursos})
            continue

        no_ar, mensagem = motor.disponivel()
        saida.append({"tipo": tipo, "nome": motor.nome, "disponivel": no_ar,
                      "mensagem": mensagem, "recursos": motor.recursos})
    return saida


def escolher(cfg) -> tuple[Motor | None, str]:
    """O motor a usar agora. Devolve (motor, explicacao)."""
    opcoes = cfg.bruto.get("motor") or {}
    preferido = (opcoes.get("tipo") or "auto").lower()

    if preferido != "auto":
        try:
            motor = criar(preferido, cfg)
        except ValueError as e:
            return None, str(e)
        no_ar, mensagem = motor.disponivel()
        if no_ar:
            return motor, f"{motor.nome}: {mensagem}"
        return None, mensagem

    for achado in detectar(cfg):
        if not achado["disponivel"]:
            continue
        motor = criar(achado["tipo"], cfg)
        if achado["tipo"] == "aria2":
            no_ar, mensagem = motor.disponivel()   # so aqui o processo sobe
            if not no_ar:
                continue
            return motor, f"{motor.nome}: {mensagem}"
        return motor, f"{motor.nome}: {achado['mensagem']}"

    return None, _porque_nenhum()


# Onde cada cliente costuma se instalar no Windows. Barra normal de proposito:
# o Path converte, e assim nao ha sequencia de escape para dar errado.
LOCAIS = {
    "utorrent": ("%APPDATA%/uTorrent/uTorrent.exe",
                 "%LOCALAPPDATA%/uTorrent/uTorrent.exe",
                 "C:/Program Files (x86)/uTorrent/uTorrent.exe"),
    "qbittorrent": ("C:/Program Files/qBittorrent/qbittorrent.exe",
                    "C:/Program Files (x86)/qBittorrent/qbittorrent.exe"),
}


def _instalado(tipo: str) -> Path | None:
    """Procura o executavel do cliente no disco, sem executar nada."""
    import os

    for modelo in LOCAIS.get(tipo, ()):
        caminho = Path(os.path.expandvars(modelo))
        try:
            if caminho.is_file():
                return caminho
        except OSError:
            continue
    return None


def instalados() -> list[str]:
    """Clientes que existem no disco, mesmo que a interface web esteja desligada."""
    return [t for t in ORDEM if t in LOCAIS and _instalado(t)]


def como_ligar(tipo: str) -> str:
    """Onde ficam as opcoes da interface web de cada cliente."""
    if tipo == "qbittorrent":
        return ("Ferramentas → Opções → Web UI: marque “Servidor Web UI”, deixe a "
                "porta 8080 e marque “Ignorar autenticação para clientes no "
                "localhost”.")
    return ("Opções → Preferências → Interface Web: marque “Ativar Interface "
            "Web” e defina usuário e senha — o uTorrent exige os dois. Depois "
            "escreva os mesmos aqui nos campos Usuário e Senha.")


def _porque_nenhum() -> str:
    """Explica a falta de motor com o que existe nesta maquina.

    A mensagem generica mandava procurar em Configuracoes sem dizer o que estava
    errado. Quando o cliente esta instalado e so a interface web esta desligada,
    isso e uma frase de diferenca — e a diferenca entre resolver em trinta
    segundos e achar que o app esta quebrado.
    """
    achados = [t for t in ORDEM if t in LOCAIS and _instalado(t)]
    if achados:
        nomes = " e ".join(ROTULOS[t] for t in achados)
        primeiro = achados[0]
        passo = ("Ferramentas → Opções → Web UI" if primeiro == "qbittorrent"
                 else "Opções → Preferências → Interface Web")
        return (f"O {nomes} está instalado, mas a interface web dele está "
                f"desligada — é por ela que o Acervo conversa com o cliente."
                + "\n" +
                f"Abra o {ROTULOS[primeiro]} em {passo}, ative, e deixe o "
                f"programa aberto. Depois use “Testar” em Configurações → Torrent."
                + "\n" +
                "Se preferir não mexer nele, o botão “Baixar o aria2” resolve "
                "sem instalar nada.")
    return ("Nenhum cliente de torrent instalado. Em Configurações → Torrent, o "
            "botão “Baixar o aria2” resolve sem instalar nada (~2 MB, o próprio "
            "app cuida). Se preferir, instale o qBittorrent — ele semeia melhor "
            "depois que o download termina.")
