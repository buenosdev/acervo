"""Motor de video usando o libmpv, que o app pode baixar sozinho.

Existe para quem nao tem VLC instalado. Segue o mesmo caminho do aria2: o
binario nao e redistribuido junto com o Acervo — o app oferece baixar do
projeto oficial, mostrando origem e tamanho, e so depois de voce confirmar.

Como o VLC, o mpv traz os proprios decodificadores, entao toca x265, DTS e MKV
sem depender de codec instalado no Windows.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import c_char_p, c_double, c_int, c_int64, c_void_p
from pathlib import Path

from .base import ErroPlayer, Faixa, Player, Recursos

NOME_BIBLIOTECA = "libmpv-2.dll"
ORIGEM_OFICIAL = "https://mpv.io/installation/"
# Compilacoes oficiais para Windows, publicadas pelo projeto. O nome do pacote
# traz data e hash do commit, entao nao da para montar o link fixo: ele e
# resolvido na hora, pela API de releases.
API_RELEASES = ("https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/"
                "releases/latest")
PREFIXO_PACOTE = "mpv-dev-x86_64-"
TAMANHO_APROXIMADO_MB = 29


def endereco_do_pacote() -> tuple[str, int]:
    """(url, bytes) do pacote mais recente. Levanta ErroPlayer se nao achar."""
    import json
    import urllib.request

    req = urllib.request.Request(API_RELEASES, headers={
        "User-Agent": "Acervo/1.0", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            dados = json.loads(r.read().decode("utf-8"))
    except Exception as e:                             # noqa: BLE001
        raise ErroPlayer(f"não consegui consultar as versões do mpv: {e}") from e

    for a in dados.get("assets") or []:
        nome = a.get("name") or ""
        # "-dev-" e o pacote com a biblioteca; o outro so tem o mpv.exe.
        if nome.startswith(PREFIXO_PACOTE) and nome.endswith(".7z"):
            return a.get("browser_download_url"), int(a.get("size") or 0)
    raise ErroPlayer("a versão mais recente do mpv não trouxe o pacote esperado.")


def procurar_libmpv(pastas_extras: list[Path] | None = None) -> Path | None:
    """Procura o libmpv ao lado do app, nos dados e no PATH."""
    import shutil

    from ..local import pasta_dados, pasta_recursos

    candidatos: list[Path] = []
    for base in (pasta_dados(), pasta_dados() / "dados", pasta_recursos(),
                 *(pastas_extras or [])):
        candidatos += [base / NOME_BIBLIOTECA, base / "mpv" / NOME_BIBLIOTECA]
    for c in candidatos:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    achado = shutil.which(NOME_BIBLIOTECA)
    return Path(achado) if achado else None


class PlayerMPV(Player):
    nome = "mpv"
    recursos = Recursos(
        embutido=True, faixas=True, posicao=True,
        observacoes=["Motor baixado pelo app; não exige nada instalado."])

    def __init__(self, biblioteca: Path | None = None):
        self.biblioteca = Path(biblioteca) if biblioteca else procurar_libmpv()
        self._lib = None
        self._ctx = None

    # ------------------------------------------------------------- carga

    def _carregar(self):
        if self._lib is not None:
            return self._lib
        if not self.biblioteca or not self.biblioteca.is_file():
            raise ErroPlayer(
                "o libmpv não está aqui. Em Configurações → Reprodução há um "
                "botão para baixá-lo.")
        try:
            os.add_dll_directory(str(self.biblioteca.parent))
            lib = ctypes.CDLL(str(self.biblioteca))
        except OSError as e:
            raise ErroPlayer(f"não consegui carregar o libmpv: {e}") from e

        assinaturas = {
            "mpv_create": ([], c_void_p),
            "mpv_initialize": ([c_void_p], c_int),
            "mpv_terminate_destroy": ([c_void_p], None),
            "mpv_command": ([c_void_p, ctypes.POINTER(c_char_p)], c_int),
            "mpv_set_option_string": ([c_void_p, c_char_p, c_char_p], c_int),
            "mpv_set_property_string": ([c_void_p, c_char_p, c_char_p], c_int),
            "mpv_get_property": ([c_void_p, c_char_p, c_int, c_void_p], c_int),
            "mpv_set_property": ([c_void_p, c_char_p, c_int, c_void_p], c_int),
        }
        for nome, (args, saida) in assinaturas.items():
            fn = getattr(lib, nome, None)
            if fn is None:
                raise ErroPlayer(f"este libmpv não tem {nome}.")
            fn.argtypes = args
            fn.restype = saida
        self._lib = lib
        return lib

    # ------------------------------------------------------- propriedades

    _FORMATO_DOUBLE = 5
    _FORMATO_INT64 = 4
    _FORMATO_FLAG = 3

    def _get_double(self, nome: str) -> float:
        if not self._ctx:
            return 0.0
        valor = c_double(0)
        if self._lib.mpv_get_property(self._ctx, nome.encode(), self._FORMATO_DOUBLE,
                                      ctypes.byref(valor)) < 0:
            return 0.0
        return float(valor.value)

    def _get_int(self, nome: str) -> int:
        if not self._ctx:
            return 0
        valor = c_int64(0)
        if self._lib.mpv_get_property(self._ctx, nome.encode(), self._FORMATO_INT64,
                                      ctypes.byref(valor)) < 0:
            return 0
        return int(valor.value)

    def _set_flag(self, nome: str, ligado: bool) -> None:
        if self._ctx:
            valor = c_int(1 if ligado else 0)
            self._lib.mpv_set_property(self._ctx, nome.encode(), self._FORMATO_FLAG,
                                       ctypes.byref(valor))

    def _comando(self, *partes: str) -> None:
        if not self._ctx:
            return
        vetor = (c_char_p * (len(partes) + 1))(
            *[p.encode("utf-8") for p in partes], None)
        self._lib.mpv_command(self._ctx, vetor)

    # ---------------------------------------------------------- disponivel

    def disponivel(self) -> tuple[bool, str]:
        try:
            self._carregar()
        except ErroPlayer as e:
            return False, str(e)
        return True, f"libmpv ({self.biblioteca})"

    # --------------------------------------------------------------- abrir

    def abrir(self, caminho: Path, janela: int | None = None) -> None:
        lib = self._carregar()
        self.encerrar()
        self._ctx = lib.mpv_create()
        if not self._ctx:
            raise ErroPlayer("o libmpv não iniciou.")
        if janela:
            lib.mpv_set_option_string(self._ctx, b"wid", str(int(janela)).encode())
        for chave, valor in ((b"osc", b"no"), (b"input-default-bindings", b"no"),
                             (b"terminal", b"no"), (b"force-window", b"yes")):
            lib.mpv_set_option_string(self._ctx, chave, valor)
        if lib.mpv_initialize(self._ctx) < 0:
            raise ErroPlayer("o libmpv não inicializou.")
        self._comando("loadfile", str(caminho))

    def encerrar(self) -> None:
        if self._ctx and self._lib:
            self._lib.mpv_terminate_destroy(self._ctx)
        self._ctx = None

    # --------------------------------------------------------------- tocar

    def tocar(self) -> None:
        self._set_flag("pause", False)

    def pausar(self) -> None:
        self._set_flag("pause", True)

    def tocando(self) -> bool:
        if not self._ctx:
            return False
        valor = c_int(0)
        if self._lib.mpv_get_property(self._ctx, b"pause", self._FORMATO_FLAG,
                                      ctypes.byref(valor)) < 0:
            return False
        return valor.value == 0

    def terminou(self) -> bool:
        if not self._ctx:
            return False
        valor = c_int(0)
        if self._lib.mpv_get_property(self._ctx, b"eof-reached", self._FORMATO_FLAG,
                                      ctypes.byref(valor)) < 0:
            return False
        return bool(valor.value)

    # ------------------------------------------------------------- posicao

    def posicao(self) -> float:
        return self._get_double("time-pos")

    def ir_para(self, segundos: float) -> None:
        self._comando("seek", str(max(0, segundos)), "absolute")

    def duracao(self) -> float:
        return self._get_double("duration")

    # ----------------------------------------------------------------- som

    def volume(self) -> int:
        return int(self._get_double("volume"))

    def definir_volume(self, valor: int) -> None:
        if self._ctx:
            self._lib.mpv_set_property_string(
                self._ctx, b"volume", str(int(max(0, min(150, valor)))).encode())

    def mudo(self, ligado: bool) -> None:
        self._set_flag("mute", ligado)

    # -------------------------------------------------------------- faixas

    def _faixas(self, tipo: str) -> list[Faixa]:
        if not self._ctx:
            return []
        saida: list[Faixa] = []
        for i in range(self._get_int("track-list/count")):
            if self._texto(f"track-list/{i}/type") != tipo:
                continue
            ident = self._get_int(f"track-list/{i}/id")
            titulo = self._texto(f"track-list/{i}/title")
            idioma = self._texto(f"track-list/{i}/lang")
            nome = " · ".join(x for x in (titulo, idioma) if x) or f"Faixa {ident}"
            saida.append(Faixa(id=ident, nome=nome))
        return saida

    def _texto(self, nome: str) -> str:
        if not self._ctx:
            return ""
        ponteiro = c_char_p()
        # 1 = MPV_FORMAT_STRING
        if self._lib.mpv_get_property(self._ctx, nome.encode(), 1,
                                      ctypes.byref(ponteiro)) < 0:
            return ""
        return (ponteiro.value or b"").decode("utf-8", "replace")

    def faixas_audio(self) -> list[Faixa]:
        return self._faixas("audio")

    def definir_audio(self, faixa_id: int) -> None:
        if self._ctx:
            self._lib.mpv_set_property_string(self._ctx, b"aid",
                                              str(int(faixa_id)).encode())

    def audio_atual(self) -> int:
        return self._get_int("aid")

    def faixas_legenda(self) -> list[Faixa]:
        return self._faixas("sub")

    def definir_legenda(self, faixa_id: int) -> None:
        if self._ctx:
            valor = b"no" if int(faixa_id) < 0 else str(int(faixa_id)).encode()
            self._lib.mpv_set_property_string(self._ctx, b"sid", valor)

    def legenda_atual(self) -> int:
        return self._get_int("sid")

    def carregar_legenda(self, caminho: Path) -> bool:
        self._comando("sub-add", str(caminho))
        return True


# ------------------------------------------------------------------ instalar

def baixar_biblioteca(destino: Path, ao_progredir=None) -> Path:
    """Baixa o libmpv oficial e extrai so o que o app usa.

    Nao e chamado sozinho: a interface pergunta antes, mostrando origem e
    tamanho, porque baixar um binario de terceiros e decisao do usuario e nao do
    app. Mesmo caminho do aria2.

    O pacote do mpv vem em `.7z`. A extracao usa o `tar.exe` do proprio Windows,
    que desde a versao 1803 e o bsdtar com libarchive e le esse formato. Quando
    nao der, o erro diz o que fazer a mao em vez de falhar calado.
    """
    import subprocess
    import tempfile
    import urllib.request

    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    alvo = destino / NOME_BIBLIOTECA

    url, _ = endereco_do_pacote()
    req = urllib.request.Request(url, headers={"User-Agent": "Acervo/1.0"})
    pacote = Path(tempfile.gettempdir()) / "acervo-libmpv.7z"
    try:
        with urllib.request.urlopen(req, timeout=180) as r, pacote.open("wb") as saida:
            total = int(r.headers.get("Content-Length") or 0)
            lidos = 0
            while True:
                pedaco = r.read(262144)
                if not pedaco:
                    break
                saida.write(pedaco)
                lidos += len(pedaco)
                if ao_progredir and total:
                    ao_progredir(lidos / total)
    except Exception as e:                             # noqa: BLE001
        raise ErroPlayer(f"não consegui baixar o libmpv: {e}") from e

    extraido = Path(tempfile.gettempdir()) / "acervo-libmpv"
    try:
        import shutil

        shutil.rmtree(extraido, ignore_errors=True)
        extraido.mkdir(parents=True, exist_ok=True)
        tar = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "tar.exe"
        resultado = subprocess.run(
            [str(tar), "-xf", str(pacote)], cwd=str(extraido),
            capture_output=True, text=True, timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if resultado.returncode != 0:
            raise ErroPlayer(
                "baixei o pacote, mas não consegui abri-lo aqui. Ele está em "
                f"{pacote} — extraia o {NOME_BIBLIOTECA} e aponte o caminho em "
                "Configurações → Reprodução.")

        achados = list(extraido.rglob(NOME_BIBLIOTECA))
        if not achados:
            raise ErroPlayer(f"o pacote não trouxe o {NOME_BIBLIOTECA}.")
        shutil.copy2(achados[0], alvo)
    finally:
        pacote.unlink(missing_ok=True)

    if not alvo.is_file():
        raise ErroPlayer("a cópia do libmpv não ficou no lugar.")
    return alvo
