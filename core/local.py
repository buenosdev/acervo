"""Onde as coisas ficam, rodando pelo Python ou empacotado como .exe.

Quando vira executavel, o PyInstaller descompacta os arquivos embutidos (a pasta
web/) numa pasta temporaria, que some ao fechar. Ja o config.toml e o banco
precisam sobreviver e ficar visiveis para o usuario, entao vao ao lado do .exe.
Confundir os dois faz o app perder a configuracao a cada abertura.
"""
from __future__ import annotations

import sys
from pathlib import Path


def empacotado() -> bool:
    return bool(getattr(sys, "frozen", False))


def pasta_recursos() -> Path:
    """Arquivos embutidos e somente leitura (web/, icone)."""
    if empacotado():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def pasta_dados() -> Path:
    """Onde ficam config.toml, dados/ e as capas. Persiste entre aberturas."""
    if empacotado():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def avisar(titulo: str, mensagem: str) -> None:
    """Mostra um aviso na tela. Sem console (modo .exe), print nao aparece."""
    if not empacotado():
        print(f"{titulo}: {mensagem}")
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, mensagem, titulo, 0x40)
    except Exception:
        pass
