"""Motor qBittorrent: Web API v2, so com biblioteca padrao.

O fluxo de adicionar um torrent aqui tem quatro passos que importam:

  1. adiciona pausado, para dar tempo de ajustar antes de comecar a baixar;
  2. injeta trackers publicos - 90% do acervo nao tem tracker nenhum e depende
     so de DHT, o que faz o download levar muito tempo para engatar;
  3. desmarca os arquivos de propaganda (nunca em torrent de jogo, onde toda
     parte .rar e obrigatoria);
  4. so entao inicia.
"""
from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .base import ErroMotor, Motor, Progresso, Recursos

# Trackers publicos conhecidos, usados para dar um empurrao nos torrents sem tracker.
# A lista viva fica em dados/trackers.txt; esta e o ponto de partida embutido.
TRACKERS_PADRAO = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.tracker.cl:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://explodie.org:6969/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://opentracker.i2p.rocks:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://tracker.tiny-vps.com:6969/announce",
    "udp://p4p.arenabg.com:1337/announce",
    "udp://tracker.cyberia.is:6969/announce",
    "http://tracker.openbittorrent.com:80/announce",
]

PRIORIDADE_NAO_BAIXAR = 0
PRIORIDADE_NORMAL = 1


ErroQbit = ErroMotor          # nome antigo, mantido para nao quebrar imports

# Como o qBittorrent nomeia os estados, traduzido para o vocabulario do app.
_ESTADOS = {
    "downloading": "baixando", "metaDL": "baixando", "forcedDL": "baixando",
    "stalledDL": "baixando", "queuedDL": "baixando", "checkingDL": "baixando",
    "allocating": "baixando",
    "pausedDL": "pausado", "stoppedDL": "pausado",
    "uploading": "semeando", "forcedUP": "semeando", "stalledUP": "semeando",
    "queuedUP": "semeando", "checkingUP": "semeando",
    "pausedUP": "concluido", "stoppedUP": "concluido",
    "error": "erro", "missingFiles": "erro",
}


class Qbit(Motor):
    nome = "qBittorrent"
    recursos = Recursos(
        escolher_arquivos=True, injetar_trackers=True, renomear=True,
        mover=True, sequencial=True, semeia_bem=True)

    def __init__(self, url: str = "http://127.0.0.1:8080", usuario: str = "",
                 senha: str = "", tempo_limite: int = 20):
        self.base = url.rstrip("/")
        self.usuario = usuario
        self.senha = senha
        self.tempo_limite = tempo_limite
        self._jar = http.cookiejar.CookieJar()
        self._abridor = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar)
        )
        self._autenticado = False

    # ------------------------------------------------------------- transporte

    def _pedir(self, rota: str, dados: bytes | None = None,
               cabecalhos: dict | None = None) -> str:
        req = urllib.request.Request(
            f"{self.base}/api/v2/{rota}",
            data=dados,
            headers={"Referer": self.base, **(cabecalhos or {})},
        )
        try:
            with self._abridor.open(req, timeout=self.tempo_limite) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            corpo = e.read().decode("utf-8", "replace")[:200]
            if e.code == 403:
                raise ErroQbit("qBittorrent recusou (403). A sessao expirou ou a "
                               "Web UI exige login.") from e
            raise ErroQbit(f"{rota} devolveu HTTP {e.code}: {corpo}") from e
        except urllib.error.URLError as e:
            raise ErroQbit(
                f"nao consegui falar com o qBittorrent em {self.base} ({e.reason}). "
                "Confira se ele esta aberto e com a Web UI ligada em "
                "Ferramentas > Opcoes > Web UI."
            ) from e

    def _post(self, rota: str, campos: dict) -> str:
        corpo = urllib.parse.urlencode(
            {k: v for k, v in campos.items() if v is not None}
        ).encode()
        return self._pedir(rota, corpo,
                           {"Content-Type": "application/x-www-form-urlencoded"})

    def _get(self, rota: str, params: dict | None = None) -> str:
        if params:
            rota += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None})
        return self._pedir(rota)

    def _post_multipart(self, rota: str, campos: dict, arquivo: tuple[str, bytes]) -> str:
        """POST multipart - o unico jeito de enviar os bytes de um .torrent."""
        limite = f"----acervo{uuid.uuid4().hex}"
        partes: list[bytes] = []
        for chave, valor in campos.items():
            if valor is None:
                continue
            partes.append(
                f"--{limite}\r\nContent-Disposition: form-data; name=\"{chave}\"\r\n\r\n"
                f"{valor}\r\n".encode("utf-8")
            )
        nome, dados = arquivo
        partes.append(
            f"--{limite}\r\nContent-Disposition: form-data; name=\"torrents\"; "
            f"filename=\"{nome}\"\r\nContent-Type: application/x-bittorrent\r\n\r\n"
            .encode("utf-8")
        )
        partes.append(dados)
        partes.append(f"\r\n--{limite}--\r\n".encode("utf-8"))
        return self._pedir(rota, b"".join(partes),
                           {"Content-Type": f"multipart/form-data; boundary={limite}"})

    # ------------------------------------------------------------------ sessao

    def entrar(self) -> None:
        if self._autenticado:
            return
        if not self.usuario:
            # Web UI sem autenticacao para o localhost.
            self.versao()
            self._autenticado = True
            return
        resposta = self._post("auth/login",
                              {"username": self.usuario, "password": self.senha})
        if resposta.strip() != "Ok.":
            raise ErroQbit("login recusado pelo qBittorrent: confira usuario e senha "
                           "em Ferramentas > Opcoes > Web UI.")
        self._autenticado = True

    def versao(self) -> str:
        return self._get("app/version").strip()

    def disponivel(self) -> tuple[bool, str]:
        """(esta_no_ar, mensagem). Nunca levanta excecao - serve para a interface."""
        try:
            self.entrar()
            return True, self.versao()
        except ErroQbit as e:
            return False, str(e)

    # ---------------------------------------------------------------- consulta

    def listar(self, infohashes: list[str] | None = None,
               categoria: str | None = None) -> list[Progresso]:
        self.entrar()
        params = {}
        if categoria:
            params["category"] = categoria
        if infohashes:
            params["hashes"] = "|".join(infohashes)
        dados = json.loads(self._get("torrents/info", params) or "[]")
        return [
            Progresso(
                infohash=t.get("hash", ""),
                nome=t.get("name", ""),
                estado=_ESTADOS.get(t.get("state", ""), "baixando"),
                progresso=float(t.get("progress", 0)),
                baixado=int(t.get("completed", 0)),
                tamanho=int(t.get("size", 0)),
                velocidade=int(t.get("dlspeed", 0)),
                seeds=int(t.get("num_seeds", 0)),
                peers=int(t.get("num_leechs", 0)),
                eta=int(t.get("eta", 0)),
                caminho=t.get("content_path") or t.get("save_path", ""),
                ratio=t.get("ratio"),
                adicionado=t.get("added_on"),
            )
            for t in dados
        ]

    # Nome antigo, ainda usado por partes do app.
    def torrents(self, categoria: str | None = None,
                 hashes: list[str] | None = None) -> list[Progresso]:
        return self.listar(hashes, categoria)

    def arquivos(self, infohash: str) -> list[dict]:
        self.entrar()
        bruto = json.loads(self._get("torrents/files", {"hash": infohash}) or "[]")
        return [{"indice": a.get("index", i), "nome": a.get("name", ""),
                 "tamanho": a.get("size", 0), "prioridade": a.get("priority", 1),
                 "name": a.get("name", "")}          # chave antiga, ainda usada
                for i, a in enumerate(bruto)]

    def propriedades(self, infohash: str) -> dict:
        self.entrar()
        return json.loads(self._get("torrents/properties", {"hash": infohash}) or "{}")

    # ------------------------------------------------------------------- acoes

    def criar_categoria(self, nome: str, pasta: str | Path) -> None:
        self.entrar()
        try:
            self._post("torrents/createCategory",
                       {"category": nome, "savePath": str(pasta)})
        except ErroQbit:
            # Ja existe: so garante que a pasta esta certa.
            self._post("torrents/editCategory", {"category": nome, "savePath": str(pasta)})

    def adicionar(self, caminho_torrent: Path, pasta_destino: Path,
                  categoria: str | None = None, etiquetas: str | None = None,
                  pausado: bool = True) -> None:
        self.entrar()
        self._post_multipart(
            "torrents/add",
            {
                "savepath": str(pasta_destino),
                "category": categoria,
                "tags": etiquetas,
                # As duas grafias: mudou de "paused" para "stopped" no qBittorrent 5.
                "paused": "true" if pausado else "false",
                "stopped": "true" if pausado else "false",
                "autoTMM": "false",
            },
            (caminho_torrent.name, caminho_torrent.read_bytes()),
        )

    def adicionar_trackers(self, infohash: str, urls: list[str]) -> None:
        if not urls:
            return
        self.entrar()
        self._post("torrents/addTrackers", {"hash": infohash, "urls": "\n".join(urls)})

    def nao_baixar(self, infohash: str, indices: list[int]) -> None:
        self.prioridade_arquivos(infohash, indices, PRIORIDADE_NAO_BAIXAR)

    def prioridade_arquivos(self, infohash: str, indices: list[int], prioridade: int) -> None:
        if not indices:
            return
        self.entrar()
        self._post("torrents/filePrio", {
            "hash": infohash,
            "id": "|".join(str(i) for i in indices),
            "priority": prioridade,
        })

    def sequencial(self, infohash: str) -> None:
        self.entrar()
        self._post("torrents/toggleSequentialDownload", {"hashes": infohash})

    def iniciar(self, infohash: str) -> None:
        self.entrar()
        try:
            self._post("torrents/start", {"hashes": infohash})   # qBittorrent 5+
        except ErroQbit:
            self._post("torrents/resume", {"hashes": infohash})  # 4.x

    def parar(self, infohash: str) -> None:
        self.entrar()
        try:
            self._post("torrents/stop", {"hashes": infohash})
        except ErroQbit:
            self._post("torrents/pause", {"hashes": infohash})

    def remover(self, infohash: str, apagar_arquivos: bool = False) -> None:
        self.entrar()
        self._post("torrents/delete", {
            "hashes": infohash,
            "deleteFiles": "true" if apagar_arquivos else "false",
        })

    def renomear_arquivo(self, infohash: str, de: str, para: str) -> None:
        self.entrar()
        self._post("torrents/renameFile",
                   {"hash": infohash, "oldPath": de, "newPath": para})

    def renomear_pasta(self, infohash: str, de: str, para: str) -> None:
        self.entrar()
        self._post("torrents/renameFolder",
                   {"hash": infohash, "oldPath": de, "newPath": para})

    def mover(self, infohash: str, destino: str | Path) -> None:
        """Move mantendo o seeding: o qBittorrent passa a apontar para o novo lugar."""
        self.entrar()
        self._post("torrents/setLocation", {"hashes": infohash, "location": str(destino)})


def carregar_trackers(caminho: Path, extras: list[str] | None = None) -> list[str]:
    """Lista de trackers = arquivo do usuario (se houver) + embutidos + extras.

    `extras` costuma vir dos proprios torrents do acervo que ja tem tracker:
    se funcionam para esse conteudo, tendem a funcionar para o resto tambem.
    """
    urls: list[str] = []
    if caminho.is_file():
        urls += [l.strip() for l in caminho.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")]
    urls += TRACKERS_PADRAO
    urls += extras or []

    vistos: set[str] = set()
    unicos = []
    for u in urls:
        if u not in vistos:
            vistos.add(u)
            unicos.append(u)
    return unicos
