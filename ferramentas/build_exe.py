"""Gera o Acervo.exe — o aplicativo de desktop.

    python -m ferramentas.build_exe

Precisa do PyInstaller (so para construir):
    python -m pip install pyinstaller

O resultado sai em dist/Acervo.exe: arquivo unico, sem console, com icone
proprio. O config.toml e a pasta dados/ ficam AO LADO do .exe, para o usuario
achar e para sobreviverem entre aberturas.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
NOME = "Acervo"

# O Qt traz muita coisa que este app nao usa. Tirar corta dezenas de MB e
# encurta o tempo de abertura.
QT_FORA = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.Qt3DCore",
    "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSerialPort", "PySide6.QtSensors", "PySide6.QtSpatialAudio",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtHttpServer",
    "PySide6.QtNetworkAuth", "PySide6.QtWebSockets", "PySide6.QtGraphs",
    # shiboken6 NAO entra aqui: e o nucleo do PySide6. Excluir faz o app nem abrir.
]
OUTROS_FORA = ["tkinter", "unittest", "pydoc", "test", "distutils", "setuptools",
               "pip", "PIL", "numpy", "pandas"]


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller nao encontrado. Instale com:\n"
              "    python -m pip install pyinstaller")
        return 1
    try:
        import PySide6  # noqa: F401
    except ImportError:
        print("PySide6 nao encontrado. Instale com:\n"
              "    python -m pip install PySide6-Essentials")
        return 1

    icone = RAIZ / "recursos" / "acervo.ico"
    if not icone.is_file():
        print("Icone ausente - gerando primeiro...")
        subprocess.run([sys.executable, "-m", "ferramentas.gerar_icone"],
                       cwd=RAIZ, check=True)

    # `build/` e descartavel: e so cache do PyInstaller.
    if (RAIZ / "build").exists():
        shutil.rmtree(RAIZ / "build")

    # `dist/` NAO e descartavel. Quando o app roda empacotado, e ali que ficam o
    # config.toml do usuario, o banco, as capas baixadas e o aria2c.exe — apagar
    # a pasta inteira a cada build significa reinstalar o app do zero em cima de
    # quem ja o estava usando. Aqui so o executavel e substituido.
    dist = RAIZ / "dist"
    dist.mkdir(exist_ok=True)
    antigo_exe = dist / f"{NOME}.exe"
    if antigo_exe.exists():
        try:
            antigo_exe.unlink()
        except OSError:
            print(f"Feche o {NOME} antes de reconstruir: o .exe esta em uso.")
            return 1

    comando = [
        sys.executable, "-m", "PyInstaller",
        "--name", NOME,
        "--onefile",
        "--windowed",                     # sem janela de console atras do app
        "--icon", str(icone),
        "--distpath", str(RAIZ / "dist"),
        "--workpath", str(RAIZ / "build"),
        "--specpath", str(RAIZ / "build"),
        "--noconfirm",
        "--add-data", f"{RAIZ / 'recursos'}{';' if sys.platform == 'win32' else ':'}recursos",
        # A GPL exige que a licenca acompanhe o binario distribuido.
        "--add-data", f"{RAIZ / 'LICENSE'}{';' if sys.platform == 'win32' else ':'}.",
    ]
    for modulo in QT_FORA + OUTROS_FORA:
        comando += ["--exclude-module", modulo]
    comando.append(str(RAIZ / "acervo.py"))

    print("Construindo... (2 a 4 minutos)\n")
    if subprocess.run(comando, cwd=RAIZ).returncode != 0:
        print("\nA construcao falhou. A saida do PyInstaller esta acima.")
        return 1

    exe = RAIZ / "dist" / f"{NOME}.exe"
    if not exe.is_file():
        print("\nO PyInstaller terminou mas o .exe nao apareceu em dist/.")
        return 1

    exemplo = RAIZ / "config.exemplo.toml"
    if exemplo.is_file():
        shutil.copy2(exemplo, exe.parent / "config.exemplo.toml")

    (exe.parent / "LEIA-ME.txt").write_text(
        "Acervo\n"
        "======\n\n"
        "Dê dois cliques em Acervo.exe.\n\n"
        "Na primeira vez o app pergunta onde ficam seus arquivos .torrent.\n"
        "Todo o resto (qBittorrent, capas, travas de segurança) se configura\n"
        "dentro do próprio app, em Configurações.\n\n"
        "Estes arquivos aparecem aqui depois da primeira abertura:\n"
        "  config.toml   suas configurações (contém suas chaves de API)\n"
        "  dados/        banco do catálogo e as capas baixadas\n\n"
        "Para desinstalar, apague esta pasta. Nada é escrito no Registro do\n"
        "Windows e nada vai para a pasta de sistema.\n",
        encoding="utf-8")

    print(f"\n  Pronto: {exe}")
    print(f"  Tamanho: {exe.stat().st_size / 1024 / 1024:.1f} MB")
    print("\n  A pasta dist/ inteira é o que você distribui.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
