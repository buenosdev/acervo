"""Motor aria2: o app inicia o proprio processo e fala com ele por JSON-RPC.

E o unico motor que nao depende de nenhum programa instalado pelo usuario -
basta o `aria2c.exe`, um binario de ~5 MB que fica ao lado do Acervo.

Limitacao que precisa ficar clara: o aria2 baixa bem, mas nao e um cliente de
biblioteca. Ele semeia so enquanto o app estiver aberto e ate o tempo de seed
configurado. Como este projeto inteiro depende de haver quem semeie, ele e a
escolha de ultimo recurso, nao a preferida.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from base64 import b64encode
from pathlib import Path

from .base import ErroMotor, Motor, Progresso, Recursos

PORTA_PADRAO = 6810
# Se a porta estiver ocupada, o app tenta as seguintes em vez de desistir.
FAIXA_PORTAS = 10
NOME_BINARIO = "aria2c.exe" if os.name == "nt" else "aria2c"

# Pagina oficial do projeto, para o app oferecer o download com a origem a vista.
ORIGEM_OFICIAL = "https://github.com/aria2/aria2/releases"


def segredo_rpc(pasta_dados_cfg: Path | None = None) -> str:
    """Segredo do RPC, estavel entre instancias e entre aberturas do app.

    Era sorteado no construtor. Como o app cria um motor novo a cada consulta —
    inclusive no relogio de 3 segundos — o segundo motor nao conseguia falar com
    o aria2 que o primeiro tinha subido: o daemon respondia "Unauthorized", o app
    concluia que nao havia motor e tentava subir outro processo na mesma porta.
    A cada 3 segundos. Guardado em arquivo, qualquer instancia (inclusive de uma
    execucao anterior) fala com o daemon que ja estiver de pe.
    """
    from ..local import pasta_dados

    # A pasta de dados da configuracao, quando houver: e ela que o usuario
    # escolheu, e e la que o daemon de qualquer instancia deve procurar. Usar a
    # pasta de instalacao fazia o app rodando do codigo-fonte e o .exe gravarem
    # segredos diferentes — e entao um nao conseguia falar com o aria2 do outro.
    base = Path(pasta_dados_cfg) if pasta_dados_cfg else pasta_dados() / "dados"
    arquivo = base / "aria2-rpc.txt"
    try:
        if arquivo.is_file():
            guardado = arquivo.read_text(encoding="utf-8").strip()
            if guardado:
                return guardado
    except OSError:
        pass

    novo = uuid.uuid4().hex
    try:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(novo, encoding="utf-8")
    except OSError:
        pass          # sem poder gravar, ao menos esta execucao fica coerente
    return novo


def porta_ocupada(porta: int) -> bool:
    """True se ja ha alguem escutando ali. Evita subir um segundo daemon."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", porta)) == 0


def procurar_binario(pastas_extras: list[Path] | None = None) -> Path | None:
    """Procura o aria2c ao lado do app, nos dados, e no PATH."""
    from ..local import pasta_dados, pasta_recursos

    candidatos: list[Path] = []
    for base in (pasta_dados(), pasta_recursos(), *(pastas_extras or [])):
        candidatos += [base / NOME_BINARIO, base / "aria2" / NOME_BINARIO]
    for c in candidatos:
        if c.is_file():
            return c
    achado = shutil.which("aria2c")
    return Path(achado) if achado else None


class Aria2(Motor):
    nome = "aria2"
    recursos = Recursos(
        escolher_arquivos=True, injetar_trackers=True,
        renomear=False, mover=False, sequencial=False,
        semeia_bem=False,
        observacoes=["Semeia apenas enquanto o Acervo estiver aberto.",
                     "A organização move os arquivos no disco."])

    def __init__(self, binario: Path | None = None, porta: int = PORTA_PADRAO,
                 pasta_padrao: Path | None = None, tempo_semeando: int = 60,
                 pasta_dados: Path | None = None):
        self.binario = Path(binario) if binario else procurar_binario()
        self.porta = porta
        self.pasta_padrao = Path(pasta_padrao) if pasta_padrao else Path.cwd()
        self.tempo_semeando = tempo_semeando
        self.segredo = segredo_rpc(pasta_dados)
        self.processo: subprocess.Popen | None = None
        self._gid_por_hash: dict[str, str] = {}

    # ---------------------------------------------------------- processo

    def _no_ar(self) -> bool:
        try:
            self._chamar("aria2.getVersion", tempo_limite=3)
            return True
        except Exception:
            return False

    def garantir_ligado(self) -> None:
        """Sobe o aria2c se ainda nao estiver de pe. Idempotente."""
        if self._no_ar():
            return

        # A porta pode estar ocupada por um aria2 de outra origem — inclusive um
        # que este mesmo app deixou para tras antes de aprender a encerrar. Em
        # vez de mandar o usuario abrir o Gerenciador de Tarefas, procuramos uma
        # porta nossa: primeiro alguma onde ja exista um aria2 que aceite nosso
        # segredo (e reaproveitamos), depois a primeira livre.
        if not self._adotar_existente():
            livre = self._porta_livre()
            if livre is None:
                raise ErroMotor(
                    f"as portas {PORTA_PADRAO} a {PORTA_PADRAO + FAIXA_PORTAS - 1} "
                    "estão todas ocupadas. Feche o que estiver usando essa faixa "
                    "e tente de novo.")
            self.porta = livre
        else:
            return

        if not self.binario or not self.binario.is_file():
            raise ErroMotor(
                "o aria2c não foi encontrado. Em Configurações → Torrent há um "
                "botão para baixá-lo, ou aponte um aria2c.exe que você já tenha.")

        self.pasta_padrao.mkdir(parents=True, exist_ok=True)
        argumentos = [
            str(self.binario),
            "--enable-rpc", "--rpc-listen-all=false",
            f"--rpc-listen-port={self.porta}", f"--rpc-secret={self.segredo}",
            f"--dir={self.pasta_padrao}",
            "--continue=true", "--check-integrity=true",
            "--bt-enable-lpd=true", "--enable-dht=true", "--enable-peer-exchange=true",
            f"--seed-time={self.tempo_semeando}",
            "--follow-torrent=mem", "--pause-metadata=false",
            "--max-concurrent-downloads=4", "--summary-interval=0", "--quiet=true",
        ]
        try:
            # `stdin` precisa ser explicito: empacotado sem console, o app nao
            # tem entrada padrao valida, e o Popen falha com "identificador
            # invalido" antes de o aria2 sequer comecar. No .exe isso deixava o
            # download morto sem nenhuma mensagem — funcionava so no ambiente de
            # desenvolvimento, que tem console.
            self.processo = subprocess.Popen(
                argumentos, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            raise ErroMotor(f"não consegui iniciar o aria2c: {e}") from e

        fim = time.monotonic() + 12
        while time.monotonic() < fim:
            if self._no_ar():
                return
            time.sleep(0.3)
        raise ErroMotor("o aria2c iniciou mas não respondeu ao RPC.")

    def _adotar_existente(self) -> bool:
        """Reaproveita um aria2 nosso que ja esteja de pe em alguma das portas."""
        original = self.porta
        for p in range(PORTA_PADRAO, PORTA_PADRAO + FAIXA_PORTAS):
            if not porta_ocupada(p):
                continue
            self.porta = p
            if self._no_ar():
                return True             # e o nosso: fala com ele e pronto
        self.porta = original
        return False

    def _porta_livre(self) -> int | None:
        for p in range(PORTA_PADRAO, PORTA_PADRAO + FAIXA_PORTAS):
            if not porta_ocupada(p):
                return p
        return None

    def encerrar(self) -> None:
        """Derruba o daemon. Funciona mesmo sem termos sido nos a subi-lo.

        A versao anterior saia na primeira linha quando `self.processo` era None
        — e era sempre None, porque quem chamava recebia uma instancia recem
        criada. Resultado: o aria2 sobrevivia ao fechamento do app.
        """
        try:
            self._chamar("aria2.shutdown", tempo_limite=3)
        except Exception:                                  # noqa: BLE001
            if self.processo is not None:
                self.processo.terminate()
        self.processo = None

    # --------------------------------------------------------------- rpc

    def _chamar(self, metodo: str, *params, tempo_limite: int = 20):
        corpo = json.dumps({
            "jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": metodo,
            "params": [f"token:{self.segredo}", *params],
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.porta}/jsonrpc", corpo,
            {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=tempo_limite) as r:
                resposta = json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise ErroMotor(f"o aria2 não respondeu ({e.reason}).") from e
        if "error" in resposta:
            raise ErroMotor(f"aria2: {resposta['error'].get('message', 'erro')}")
        return resposta.get("result")

    # ------------------------------------------------------------- conexao

    def disponivel(self) -> tuple[bool, str]:
        try:
            self.garantir_ligado()
            versao = self._chamar("aria2.getVersion")
            return True, f"aria2 {versao.get('version', '')}"
        except ErroMotor as e:
            return False, str(e)

    # ------------------------------------------------------------- consulta

    _ESTADOS = {"active": "baixando", "waiting": "baixando", "paused": "pausado",
                "complete": "concluido", "error": "erro", "removed": "erro"}

    def _todos(self) -> list[dict]:
        ativos = self._chamar("aria2.tellActive") or []
        esperando = self._chamar("aria2.tellWaiting", 0, 200) or []
        prontos = self._chamar("aria2.tellStopped", 0, 200) or []
        return [*ativos, *esperando, *prontos]

    def _para_progresso(self, t: dict) -> Progresso:
        total = int(t.get("totalLength", 0) or 0)
        feito = int(t.get("completedLength", 0) or 0)
        velocidade = int(t.get("downloadSpeed", 0) or 0)
        infohash = (t.get("infoHash") or "").lower()
        if infohash:
            self._gid_por_hash[infohash] = t.get("gid", "")
        nome = ""
        bt = t.get("bittorrent") or {}
        if isinstance(bt.get("info"), dict):
            nome = bt["info"].get("name", "")
        if not nome and t.get("files"):
            nome = Path(t["files"][0].get("path", "")).name
        restante = max(0, total - feito)
        return Progresso(
            infohash=infohash, nome=nome,
            estado=self._ESTADOS.get(t.get("status", ""), "baixando"),
            progresso=(feito / total) if total else 0.0,
            baixado=feito, tamanho=total, velocidade=velocidade,
            seeds=int(t.get("numSeeders", 0) or 0),
            peers=int(t.get("connections", 0) or 0),
            eta=int(restante / velocidade) if velocidade else 0,
            caminho=t.get("dir", ""),
            ratio=None,
        )

    def listar(self, infohashes: list[str] | None = None,
               categoria: str | None = None) -> list[Progresso]:
        alvo = {h.lower() for h in (infohashes or [])}
        saida = [self._para_progresso(t) for t in self._todos()]
        return [p for p in saida if not alvo or p.infohash in alvo]

    def torrents(self, categoria: str | None = None,
                 hashes: list[str] | None = None) -> list[Progresso]:
        return self.listar(hashes, categoria)

    def _gid(self, infohash: str) -> str:
        gid = self._gid_por_hash.get(infohash.lower())
        if gid:
            return gid
        self.listar()                                # refaz o mapa
        gid = self._gid_por_hash.get(infohash.lower())
        if not gid:
            raise ErroMotor("esse torrent não está no aria2.")
        return gid

    def arquivos(self, infohash: str) -> list[dict]:
        itens = self._chamar("aria2.getFiles", self._gid(infohash)) or []
        return [{"indice": int(a.get("index", i + 1)) - 1,
                 "nome": a.get("path", ""), "name": a.get("path", ""),
                 "tamanho": int(a.get("length", 0)),
                 "prioridade": 1 if a.get("selected") == "true" else 0}
                for i, a in enumerate(itens)]

    def propriedades(self, infohash: str) -> dict:
        return {"share_ratio": None, "addition_date": None}

    # ---------------------------------------------------------------- acoes

    def adicionar(self, caminho_torrent: Path, pasta_destino: Path,
                  categoria: str | None = None, pausado: bool = True) -> None:
        self.garantir_ligado()
        pasta_destino.mkdir(parents=True, exist_ok=True)
        opcoes = {"dir": str(pasta_destino), "pause": "true" if pausado else "false"}
        conteudo = b64encode(caminho_torrent.read_bytes()).decode()
        gid = self._chamar("aria2.addTorrent", conteudo, [], opcoes)
        try:
            estado = self._chamar("aria2.tellStatus", gid, ["infoHash"])
            if estado.get("infoHash"):
                self._gid_por_hash[estado["infoHash"].lower()] = gid
        except ErroMotor:
            pass

    def adicionar_trackers(self, infohash: str, urls: list[str]) -> None:
        if not urls:
            return
        # O aria2 aceita trackers extras por opcao global, aplicada aos torrents.
        self._chamar("aria2.changeGlobalOption",
                     {"bt-tracker": ",".join(urls[:60])})

    def nao_baixar(self, infohash: str, indices: list[int]) -> None:
        """O aria2 escolhe pelo que MANTER, entao inverte-se a lista."""
        todos = self.arquivos(infohash)
        if not todos:
            return
        manter = [str(a["indice"] + 1) for a in todos if a["indice"] not in indices]
        if not manter:
            return
        self._chamar("aria2.changeOption", self._gid(infohash),
                     {"select-file": ",".join(manter)})

    def iniciar(self, infohash: str) -> None:
        self._chamar("aria2.unpause", self._gid(infohash))

    def parar(self, infohash: str) -> None:
        self._chamar("aria2.pause", self._gid(infohash))

    def remover(self, infohash: str, apagar_arquivos: bool = False) -> None:
        gid = self._gid(infohash)
        try:
            self._chamar("aria2.remove", gid)
        except ErroMotor:
            self._chamar("aria2.removeDownloadResult", gid)
        if apagar_arquivos:
            for a in self.arquivos(infohash):
                try:
                    Path(a["nome"]).unlink(missing_ok=True)
                except OSError:
                    pass


# ------------------------------------------------------------------ instalar

VERSAO_ARIA2 = "1.37.0"
URL_ARIA2 = (f"https://github.com/aria2/aria2/releases/download/"
             f"release-{VERSAO_ARIA2}/aria2-{VERSAO_ARIA2}-win-64bit-build1.zip")
TAMANHO_APROXIMADO_MB = 5


def baixar_binario(destino: Path, ao_progredir=None) -> Path:
    """Baixa o aria2 oficial e extrai so o aria2c.exe.

    Nao e chamado sozinho em lugar nenhum: a interface pergunta antes, mostrando
    origem e tamanho, porque baixar um executavel de terceiros e decisao do
    usuario, nao do app.
    """
    import io
    import zipfile

    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    alvo = destino / NOME_BINARIO

    req = urllib.request.Request(URL_ARIA2, headers={"User-Agent": "Acervo/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            total = int(r.headers.get("Content-Length") or 0)
            pedacos, lidos = [], 0
            while True:
                pedaco = r.read(65536)
                if not pedaco:
                    break
                pedacos.append(pedaco)
                lidos += len(pedaco)
                if ao_progredir and total:
                    ao_progredir(lidos / total)
            dados = b"".join(pedacos)
    except urllib.error.URLError as e:
        raise ErroMotor(f"não consegui baixar o aria2 ({e.reason}).") from e

    try:
        with zipfile.ZipFile(io.BytesIO(dados)) as z:
            nome = next((n for n in z.namelist()
                         if n.endswith(NOME_BINARIO)), None)
            if not nome:
                raise ErroMotor("o pacote baixado não continha o aria2c.exe.")
            alvo.write_bytes(z.read(nome))
    except zipfile.BadZipFile as e:
        raise ErroMotor("o download veio corrompido; tente de novo.") from e

    return alvo
