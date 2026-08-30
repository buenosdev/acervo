"""Motor de video usando o libvlc de um VLC instalado na maquina.

O binding e escrito a mao, com ctypes, porque sao quinze funcoes. Somar o pacote
`python-vlc` — 400 KB de binding gerado, cobrindo a API inteira — ao executavel
por causa disso seria caro para o que se usa.

O VLC foi escolhido por um motivo concreto e nao por gosto: ele traz os proprios
decodificadores. Toca x265, DTS e MKV sem depender de codec instalado no
Windows, que e exatamente onde o player nativo falha num acervo de filme baixado.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import c_char_p, c_int, c_int64, c_uint, c_void_p
from pathlib import Path

from .base import ErroPlayer, Faixa, Player, Recursos

# Onde o instalador do VLC costuma deixar as coisas no Windows.
LOCAIS = (
    r"C:/Program Files/VideoLAN/VLC",
    r"C:/Program Files (x86)/VideoLAN/VLC",
)
ORIGEM_OFICIAL = "https://www.videolan.org/vlc/"


class _Descricao(ctypes.Structure):
    """libvlc_track_description_t — lista ligada de faixas."""


_Descricao._fields_ = [
    ("id", c_int),
    ("nome", c_char_p),
    ("proximo", ctypes.POINTER(_Descricao)),
]


def pasta_do_vlc() -> Path | None:
    """Onde esta o VLC, se estiver. Le o registro antes de chutar caminhos."""
    try:
        import winreg

        for raiz in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(raiz, r"SOFTWARE\VideoLAN\VLC") as chave:
                    caminho = Path(winreg.QueryValueEx(chave, "InstallDir")[0])
                    if (caminho / "libvlc.dll").is_file():
                        return caminho
            except OSError:
                continue
    except ImportError:
        pass

    for local in LOCAIS:
        caminho = Path(local)
        if (caminho / "libvlc.dll").is_file():
            return caminho
    return None


class PlayerVLC(Player):
    nome = "VLC"
    recursos = Recursos(
        embutido=True, faixas=True, posicao=True,
        observacoes=["Usa os decodificadores do VLC instalado."])

    # Assinatura do callback de log do libvlc.
    _TIPO_LOG = ctypes.CFUNCTYPE(None, c_void_p, c_int, c_void_p, c_char_p, c_void_p)

    def __init__(self, pasta: Path | None = None):
        self.pasta = Path(pasta) if pasta else pasta_do_vlc()
        self._lib = None
        self._instancia = None
        self._player = None
        self._midia = None
        # Fica ligado enquanto o ponteiro do callback existir; guardar numa
        # variavel de instancia impede o coletor de lixo de recolhe-lo enquanto
        # o VLC ainda chama.
        self._log = None
        self.audio_falhou = False

    def _ligar_log(self) -> None:
        """Escuta o log do VLC so para saber se a saida de audio abriu.

        Nao ha API para perguntar "tem som?". Sem isto, uma faixa que o VLC nao
        consegue abrir — acontece com certos 5.1 — resulta em filme rodando em
        silencio absoluto, sem nada na tela explicando. Com isto, o app percebe
        e troca de faixa.
        """
        def receber(_dados, nivel, _ctx, formato, _args):
            try:
                if nivel < 4 or not formato:
                    return
                texto = formato.decode("utf-8", "replace").lower()
                if "audio output" in texto or "audio sample frequency" in texto:
                    self.audio_falhou = True
            except Exception:                          # noqa: BLE001
                pass

        self._log = self._TIPO_LOG(receber)
        try:
            self._lib.libvlc_log_set.argtypes = [c_void_p, self._TIPO_LOG, c_void_p]
            self._lib.libvlc_log_set(self._instancia, self._log, None)
        except Exception:                              # noqa: BLE001
            self._log = None

    # ------------------------------------------------------------- carga

    def _carregar(self):
        if self._lib is not None:
            return self._lib
        if not self.pasta or not (self.pasta / "libvlc.dll").is_file():
            raise ErroPlayer(
                "o VLC não está instalado. Em Configurações → Reprodução dá "
                "para baixar um motor de vídeo, ou o app abre no programa "
                "padrão do Windows.")
        try:
            # O libvlc carrega os plugins a partir daqui; sem isto ele sobe mas
            # nao decodifica nada, o que da uma tela preta silenciosa.
            os.environ.setdefault("VLC_PLUGIN_PATH", str(self.pasta / "plugins"))
            os.add_dll_directory(str(self.pasta))
            lib = ctypes.CDLL(str(self.pasta / "libvlc.dll"))
        except OSError as e:
            raise ErroPlayer(f"não consegui carregar o VLC: {e}") from e

        assinaturas = {
            "libvlc_new": ([c_int, ctypes.POINTER(c_char_p)], c_void_p),
            "libvlc_release": ([c_void_p], None),
            "libvlc_get_version": ([], c_char_p),
            "libvlc_media_new_path": ([c_void_p, c_char_p], c_void_p),
            "libvlc_media_release": ([c_void_p], None),
            "libvlc_media_player_new_from_media": ([c_void_p], c_void_p),
            "libvlc_media_player_release": ([c_void_p], None),
            "libvlc_media_player_set_hwnd": ([c_void_p, c_void_p], None),
            "libvlc_media_player_play": ([c_void_p], c_int),
            "libvlc_media_player_set_pause": ([c_void_p, c_int], None),
            "libvlc_media_player_stop": ([c_void_p], None),
            "libvlc_media_player_is_playing": ([c_void_p], c_int),
            "libvlc_media_player_get_time": ([c_void_p], c_int64),
            "libvlc_media_player_set_time": ([c_void_p, c_int64], None),
            "libvlc_media_player_get_length": ([c_void_p], c_int64),
            "libvlc_media_player_get_state": ([c_void_p], c_int),
            "libvlc_audio_set_volume": ([c_void_p, c_int], c_int),
            "libvlc_audio_get_volume": ([c_void_p], c_int),
            "libvlc_audio_set_mute": ([c_void_p, c_int], None),
            "libvlc_audio_get_track_description":
                ([c_void_p], ctypes.POINTER(_Descricao)),
            "libvlc_audio_set_track": ([c_void_p, c_int], c_int),
            "libvlc_audio_get_track": ([c_void_p], c_int),
            "libvlc_video_get_spu_description":
                ([c_void_p], ctypes.POINTER(_Descricao)),
            "libvlc_video_set_spu": ([c_void_p, c_int], c_int),
            "libvlc_video_get_spu": ([c_void_p], c_int),
            "libvlc_track_description_list_release":
                ([ctypes.POINTER(_Descricao)], None),
            "libvlc_media_player_add_slave":
                ([c_void_p, c_uint, c_char_p, c_int], c_int),
        }
        for nome, (args, saida) in assinaturas.items():
            fn = getattr(lib, nome, None)
            if fn is None:
                continue          # funcao ausente nesta versao; tratada no uso
            fn.argtypes = args
            fn.restype = saida
        self._lib = lib
        return lib

    # ---------------------------------------------------------- disponivel

    def disponivel(self) -> tuple[bool, str]:
        try:
            lib = self._carregar()
        except ErroPlayer as e:
            return False, str(e)
        versao = lib.libvlc_get_version()
        return True, f"VLC {versao.decode('utf-8', 'replace').split()[0]}"

    # --------------------------------------------------------------- abrir

    def abrir(self, caminho: Path, janela: int | None = None) -> None:
        lib = self._carregar()
        self.encerrar()

        opcoes = [b"--no-video-title-show", b"--quiet", b"--intf=dummy"]
        vetor = (c_char_p * len(opcoes))(*opcoes)
        self._instancia = lib.libvlc_new(len(opcoes), vetor)
        if not self._instancia:
            raise ErroPlayer("o VLC não conseguiu iniciar.")

        self._midia = lib.libvlc_media_new_path(
            self._instancia, str(caminho).encode("utf-8"))
        if not self._midia:
            raise ErroPlayer(f"o VLC não abriu {caminho.name}.")

        self._player = lib.libvlc_media_player_new_from_media(self._midia)
        if not self._player:
            raise ErroPlayer("o VLC não criou o reprodutor.")
        self.audio_falhou = False
        self._ligar_log()
        if janela:
            lib.libvlc_media_player_set_hwnd(self._player, c_void_p(int(janela)))

    def encerrar(self) -> None:
        lib = self._lib
        if lib is None:
            return
        if self._player:
            lib.libvlc_media_player_stop(self._player)
            lib.libvlc_media_player_release(self._player)
            self._player = None
        if self._midia:
            lib.libvlc_media_release(self._midia)
            self._midia = None
        if self._instancia:
            lib.libvlc_release(self._instancia)
            self._instancia = None
        self._log = None

    # --------------------------------------------------------------- tocar

    def tocar(self) -> None:
        if self._player:
            self._lib.libvlc_media_player_play(self._player)

    def pausar(self) -> None:
        if self._player:
            self._lib.libvlc_media_player_set_pause(self._player, 1)

    def tocando(self) -> bool:
        return bool(self._player
                    and self._lib.libvlc_media_player_is_playing(self._player))

    def terminou(self) -> bool:
        # 6 = Ended, 7 = Error, na enum libvlc_state_t.
        return bool(self._player
                    and self._lib.libvlc_media_player_get_state(self._player) == 6)

    # ------------------------------------------------------------- posicao

    def posicao(self) -> float:
        if not self._player:
            return 0.0
        ms = self._lib.libvlc_media_player_get_time(self._player)
        return max(0.0, ms / 1000.0)

    def ir_para(self, segundos: float) -> None:
        if self._player:
            self._lib.libvlc_media_player_set_time(
                self._player, c_int64(int(max(0, segundos) * 1000)))

    def duracao(self) -> float:
        if not self._player:
            return 0.0
        ms = self._lib.libvlc_media_player_get_length(self._player)
        return max(0.0, ms / 1000.0)

    # ----------------------------------------------------------------- som

    def volume(self) -> int:
        return self._lib.libvlc_audio_get_volume(self._player) if self._player else 0

    def definir_volume(self, valor: int) -> None:
        if self._player:
            self._lib.libvlc_audio_set_volume(self._player, int(max(0, min(150, valor))))

    def mudo(self, ligado: bool) -> None:
        if self._player:
            self._lib.libvlc_audio_set_mute(self._player, 1 if ligado else 0)

    # -------------------------------------------------------------- faixas

    def _listar(self, funcao) -> list[Faixa]:
        if not self._player:
            return []
        cabeca = funcao(self._player)
        saida: list[Faixa] = []
        atual = cabeca
        while atual:
            item = atual.contents
            nome = (item.nome or b"").decode("utf-8", "replace")
            saida.append(Faixa(id=item.id, nome=nome or f"Faixa {item.id}"))
            atual = item.proximo
        if cabeca:
            self._lib.libvlc_track_description_list_release(cabeca)
        return saida

    def faixas_audio(self) -> list[Faixa]:
        return self._listar(self._lib.libvlc_audio_get_track_description)

    def definir_audio(self, faixa_id: int) -> None:
        if self._player:
            self.audio_falhou = False     # a faixa nova merece um veredito novo
            self._lib.libvlc_audio_set_track(self._player, int(faixa_id))

    def audio_atual(self) -> int:
        return self._lib.libvlc_audio_get_track(self._player) if self._player else -1

    def faixas_legenda(self) -> list[Faixa]:
        return self._listar(self._lib.libvlc_video_get_spu_description)

    def definir_legenda(self, faixa_id: int) -> None:
        if self._player:
            self._lib.libvlc_video_set_spu(self._player, int(faixa_id))

    def legenda_atual(self) -> int:
        return self._lib.libvlc_video_get_spu(self._player) if self._player else -1

    def carregar_legenda(self, caminho: Path) -> bool:
        """Anexa um .srt externo. 0 = slave de legenda, na enum do libvlc."""
        if not self._player or not hasattr(self._lib, "libvlc_media_player_add_slave"):
            return False
        uri = caminho.absolute().as_uri().encode("utf-8")
        return self._lib.libvlc_media_player_add_slave(self._player, 0, uri, 1) == 0
