"""Abre o Acervo numa janela propria, sem cara de navegador.

Usa o modo aplicativo do Edge (`--app=`), que ja vem em todo Windows 10 e 11.
A janela nao tem barra de endereco, nem abas, nem menu: e o app e so o app,
com o proprio icone na barra de tarefas.

Foi a escolha depois de o pywebview (janela nativa via .NET) quebrar no
Python 3.14 - e ela tem uma vantagem: nao acrescenta uma unica dependencia,
entao o executavel continua com 10 MB e nao existe runtime para dar errado
na maquina de quem baixar.

Um perfil separado em dados/janela garante que a janela abra sempre, mesmo
com o navegador do usuario ja aberto, e sem misturar nada com a navegacao dele.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path

# Ordem de preferencia. O Edge esta em qualquer Windows atual.
NAVEGADORES = [
    ("Edge", [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ], "msedge"),
    ("Chrome", [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ], "chrome"),
    ("Brave", [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    ], "brave"),
]


def _achar() -> tuple[str, str] | None:
    """(nome, caminho) do primeiro navegador com modo aplicativo que existir."""
    for nome, caminhos, comando in NAVEGADORES:
        for c in caminhos:
            if c and Path(c).is_file():
                return nome, c
        achado = shutil.which(comando)
        if achado:
            return nome, achado
    return None


def abrir(url: str, perfil: Path, largura: int = 1360, altura: int = 860):
    """Abre a janela do app. Devolve o processo, ou None se caiu no navegador comum.

    Quando devolve um processo, quem chamou pode esperar por ele: fechar a
    janela passa a encerrar o programa, como em qualquer app de desktop.
    """
    achado = _achar()
    if not achado:
        webbrowser.open(url)
        return None

    _nome, executavel = achado
    perfil.mkdir(parents=True, exist_ok=True)

    argumentos = [
        executavel,
        f"--app={url}",
        f"--window-size={largura},{altura}",
        f"--user-data-dir={perfil}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,AutofillServerCommunication",
        # Sem isto o Edge as vezes some com a janela para a instancia ja aberta.
        "--new-window",
    ]
    try:
        return subprocess.Popen(argumentos, close_fds=True)
    except OSError:
        webbrowser.open(url)
        return None


def nome_do_navegador() -> str:
    achado = _achar()
    return achado[0] if achado else "navegador padrão"
