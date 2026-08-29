"""Descobre e configura a Interface Web do uTorrent sozinho, ate onde da.

O que da para automatizar:

  * achar o uTorrent instalado e saber se esta aberto;
  * ler o `settings.dat` dele e saber se a Interface Web esta ligada;
  * descobrir em qual porta ela responde, testando as candidatas;
  * preencher o usuario (o uTorrent usa "admin" por padrao);
  * quando a interface esta desligada e o programa fechado, ligar sozinho.

O que nao da, e vale dizer por que: a senha e guardada como hash com sal
(`webui.hashword` + `webui.salt`), justamente para nao poder ser lida de volta.
Nenhum programa consegue recuperar dali a senha que voce digitou — nem este. Por
isso, quando a interface ja esta ligada, o app pede a senha e mais nada: tudo o
que podia ser descoberto, ele descobre.

Outro detalhe que muda o que e possivel: o uTorrent so grava o `settings.dat` ao
fechar. Mexer no arquivo com ele aberto nao adianta — o proprio uTorrent
sobrescreve tudo na saida. Por isso ligar a interface exige o programa fechado.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from base64 import b64encode
from dataclasses import dataclass, field
from pathlib import Path

from . import bencode

USUARIO_PADRAO = "admin"

# Portas onde a Interface Web costuma estar, na ordem em que vale testar.
PORTAS_CANDIDATAS = (8080, 8081, 10000, 8112, 9090)


@dataclass
class Estado:
    instalado: bool = False
    rodando: bool = False
    webui_ligada: bool | None = None      # None = nao deu para saber
    porta: int | None = None
    exige_senha: bool = False
    executavel: Path | None = None
    arquivo_config: Path | None = None
    avisos: list[str] = field(default_factory=list)


def pasta() -> Path:
    return Path(os.path.expandvars("%APPDATA%")) / "uTorrent"


def executavel() -> Path | None:
    for caminho in (pasta() / "uTorrent.exe",
                    Path(os.path.expandvars("%LOCALAPPDATA%")) / "uTorrent" / "uTorrent.exe",
                    Path(r"C:/Program Files (x86)/uTorrent/uTorrent.exe")):
        try:
            if caminho.is_file():
                return caminho
        except OSError:
            continue
    return None


def esta_rodando() -> bool:
    """True se ha um processo uTorrent. Sem dependencia externa."""
    import subprocess

    try:
        saida = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq uTorrent.exe", "/NH"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "utorrent.exe" in saida.lower()


def ler_config() -> dict | None:
    """Le o settings.dat. `None` quando nao da para ler."""
    arquivo = pasta() / "settings.dat"
    try:
        dados, _ = bencode.decodificar(arquivo.read_bytes())
    except (OSError, ValueError, IndexError):
        return None
    return dados if isinstance(dados, dict) else None


def _responde_webui(porta: int, tempo: float = 2.0) -> str | None:
    """'aberta', 'protegida' ou None. So um GET; nao envia credencial."""
    url = f"http://127.0.0.1:{porta}/gui/token.html"
    try:
        with urllib.request.urlopen(url, timeout=tempo):
            return "aberta"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "protegida"
        return None
    except (urllib.error.URLError, OSError):
        return None


def descobrir_porta(extra: int | None = None) -> tuple[int | None, bool]:
    """Acha a porta da Interface Web. Devolve (porta, exige_senha)."""
    candidatas: list[int] = []
    if extra:
        candidatas.append(int(extra))
    candidatas += [p for p in PORTAS_CANDIDATAS if p != extra]

    for porta in candidatas:
        resposta = _responde_webui(porta)
        if resposta:
            return porta, resposta == "protegida"
    return None, False


def estado(porta_configurada: int | None = None) -> Estado:
    """Retrato do uTorrent nesta maquina, sem alterar nada."""
    e = Estado()
    e.executavel = executavel()
    e.instalado = e.executavel is not None
    if not e.instalado:
        return e

    e.arquivo_config = pasta() / "settings.dat"
    e.rodando = esta_rodando()

    cfg = ler_config()
    if cfg is not None:
        ligada = cfg.get(b"webui.enable")
        e.webui_ligada = bool(ligada) if ligada is not None else False
        if e.rodando:
            # O arquivo so e gravado na saida: com o programa aberto, ele conta
            # o passado. Quem manda e a porta respondendo agora.
            e.avisos.append("o uTorrent está aberto — o settings.dat no disco "
                            "pode estar desatualizado")

    e.porta, e.exige_senha = descobrir_porta(porta_configurada)
    if e.porta:
        e.webui_ligada = True            # respondendo e prova melhor que arquivo
    return e


# --------------------------------------------------------------- ligar a webui

def ligar_webui(usuario: str, senha: str) -> dict:
    """Liga a Interface Web escrevendo no settings.dat. Exige o uTorrent fechado.

    Guarda uma copia antes de mexer. Remove o `.fileguard` de proposito: ele e a
    soma de verificacao que o uTorrent usa para notar adulteracao, e nao ha como
    recalcula-la de fora; sem a chave, o uTorrent trata o arquivo como de uma
    versao anterior e o aceita, em vez de reclamar que esta corrompido.
    """
    if esta_rodando():
        return {"ok": False,
                "erro": "feche o uTorrent primeiro. Ele reescreve as próprias "
                        "configurações ao sair, então qualquer mudança feita "
                        "com ele aberto seria desfeita."}

    arquivo = pasta() / "settings.dat"
    if not arquivo.is_file():
        return {"ok": False, "erro": f"não achei {arquivo}."}

    cfg = ler_config()
    if cfg is None:
        return {"ok": False, "erro": "não consegui ler o settings.dat do uTorrent."}

    copia = arquivo.with_suffix(".dat.acervo-backup")
    try:
        copia.write_bytes(arquivo.read_bytes())
    except OSError as e:
        return {"ok": False, "erro": f"não consegui guardar uma cópia: {e}"}

    cfg[b"webui.enable"] = 1
    cfg[b"webui.enable_listen"] = 1
    cfg[b"webui.username"] = usuario.encode("utf-8")
    # Em texto: o uTorrent aceita `webui.password` e converte para hash com sal
    # na primeira vez que sobe. As chaves de hash antigas precisam sair, senao
    # ele ignora a senha nova e continua pedindo a anterior.
    cfg[b"webui.password"] = senha.encode("utf-8")
    for morta in (b"webui.hashword", b"webui.salt"):
        cfg.pop(morta, None)
    cfg.pop(b".fileguard", None)

    try:
        arquivo.write_bytes(bencode.codificar(cfg))
    except (OSError, ValueError) as e:
        try:
            arquivo.write_bytes(copia.read_bytes())    # desfaz
        except OSError:
            pass
        return {"ok": False, "erro": f"não consegui gravar: {e}"}

    return {"ok": True, "backup": str(copia),
            "mensagem": "Interface Web ligada no uTorrent.",
            "detalhe": "Abra o uTorrent para ele aplicar a mudança. "
                       f"A configuração anterior ficou guardada em {copia.name}."}


def abrir_utorrent() -> bool:
    """Inicia o uTorrent. Devolve False se nao achou o executavel."""
    import subprocess

    exe = executavel()
    if exe is None:
        return False
    try:
        subprocess.Popen([str(exe)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        return False
    return True


def credencial_basica(usuario: str, senha: str) -> str:
    return "Basic " + b64encode(f"{usuario}:{senha}".encode()).decode()
