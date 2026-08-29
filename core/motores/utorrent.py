"""Motor uTorrent classico, pela WebUI antiga (/gui/?token=...).

Vantagem: muita gente ja tem o uTorrent instalado, entao nao precisa instalar
nada. Limitacoes, ditas de frente:

  - a API nunca foi documentada oficialmente e pode mudar sem aviso;
  - a pasta de destino nao e por torrent: o uTorrent so aceita trocar a pasta
    padrao global, entao o app troca antes de adicionar e devolve depois;
  - nao ha renomear arquivo pela API, entao a organizacao move no disco (o
    proprio uTorrent reencontra o conteudo quando a pasta muda junto).

Precisa da WebUI ligada em Opcoes > Interface Web, com usuario e senha.
"""
from __future__ import annotations

import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from base64 import b64encode
from pathlib import Path

from .base import ErroMotor, Motor, Progresso, Recursos

PORTA_PADRAO = 8080

# Bits do campo "status" na lista do uTorrent.
_INICIADO, _CHECANDO, _INICIA_APOS_CHECAR, _CHECADO = 1, 2, 4, 8
_ERRO, _PAUSADO, _NA_FILA, _CARREGADO = 16, 32, 64, 128

PRIORIDADE_NAO_BAIXAR = 0
PRIORIDADE_NORMAL = 2


def caminho_aceito(caminho) -> bool:
    """True se a Interface Web do uTorrent consegue receber este caminho.

    Ela recusa qualquer caractere fora do ASCII na consulta: em UTF-8 devolve
    HTTP 400, e em cp1252 responde 200 mas ignora o valor — silenciosamente, que
    e pior. Como isso depende so do texto, da para saber antes de tentar.
    """
    return all(ord(c) < 128 for c in str(caminho))


class UTorrent(Motor):
    nome = "uTorrent"
    recursos = Recursos(
        escolher_arquivos=True, injetar_trackers=True,
        renomear=False,          # a WebUI antiga nao tem renameFile
        mover=False,
        sequencial=False,
        semeia_bem=True,
        observacoes=["A pasta de destino é global, não por torrent.",
                     "A organização move os arquivos no disco."])

    def __init__(self, url: str = f"http://127.0.0.1:{PORTA_PADRAO}",
                 usuario: str = "", senha: str = "", tempo_limite: int = 20):
        self.base = url.rstrip("/")
        if not self.base.endswith("/gui"):
            self.base += "/gui"
        self.usuario = usuario
        self.senha = senha
        self.tempo_limite = tempo_limite
        self._token: str | None = None
        # Coisas que deram meio-certo e a tela precisa contar.
        self.avisos: list[str] = []
        self._jar = http.cookiejar.CookieJar()
        self._abridor = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar))

    # ------------------------------------------------------------ transporte

    def _cabecalhos(self) -> dict:
        cab = {"Referer": self.base}
        if self.usuario or self.senha:
            credencial = b64encode(f"{self.usuario}:{self.senha}".encode()).decode()
            cab["Authorization"] = f"Basic {credencial}"
        return cab

    def _pedir(self, caminho: str, dados: bytes | None = None,
               extra: dict | None = None) -> str:
        req = urllib.request.Request(
            f"{self.base}{caminho}", data=dados,
            headers={**self._cabecalhos(), **(extra or {})})
        try:
            with self._abridor.open(req, timeout=self.tempo_limite) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise ErroMotor(
                    "o uTorrent recusou o login (401). Confira usuário e senha "
                    "em Opções → Interface Web.") from e
            raise ErroMotor(f"uTorrent devolveu HTTP {e.code}.") from e
        except urllib.error.URLError as e:
            raise ErroMotor(
                f"não consegui falar com o uTorrent em {self.base} ({e.reason}). "
                "Abra o uTorrent e ligue a Interface Web em Opções → Interface Web."
            ) from e

    def _pegar_token(self) -> str:
        if self._token:
            return self._token
        html = self._pedir("/token.html")
        achado = re.search(r">([^<]+)</div>", html)
        if not achado:
            raise ErroMotor("não consegui ler o token da Interface Web do uTorrent.")
        self._token = achado.group(1).strip()
        return self._token

    def _acao(self, params: dict) -> dict:
        consulta = urllib.parse.urlencode({"token": self._pegar_token(), **params})
        texto = self._pedir(f"/?{consulta}")
        try:
            return json.loads(texto) if texto.strip() else {}
        except json.JSONDecodeError:
            return {}

    # ------------------------------------------------------------- conexao

    def disponivel(self) -> tuple[bool, str]:
        try:
            self._token = None
            self._pegar_token()
            return True, "uTorrent (Interface Web)"
        except ErroMotor as e:
            return False, str(e)

    # ------------------------------------------------------------- consulta

    @staticmethod
    def _estado(status: int, progresso: int) -> str:
        if status & _ERRO:
            return "erro"
        if status & _PAUSADO or not status & _INICIADO:
            return "pausado"
        if progresso >= 1000:
            return "semeando"
        return "baixando"

    def listar(self, infohashes: list[str] | None = None,
               categoria: str | None = None) -> list[Progresso]:
        dados = self._acao({"list": 1})
        alvo = {h.lower() for h in (infohashes or [])}
        saida = []
        for t in dados.get("torrents", []):
            # [hash, status, nome, tamanho, progresso(0-1000), baixado, enviado,
            #  ratio, up, down, eta, rotulo, peers_con, peers, seeds_con, seeds,
            #  disponibilidade, ordem, restante, ...]
            infohash = str(t[0]).lower()
            if alvo and infohash not in alvo:
                continue
            if categoria and len(t) > 11 and t[11] and categoria not in str(t[11]):
                continue
            progresso = int(t[4])
            saida.append(Progresso(
                infohash=infohash, nome=t[2], estado=self._estado(int(t[1]), progresso),
                progresso=progresso / 1000.0, baixado=int(t[5]), tamanho=int(t[3]),
                velocidade=int(t[9]), seeds=int(t[14]), peers=int(t[12]),
                eta=max(0, int(t[10])),
                caminho=str(t[26]) if len(t) > 26 else "",
                ratio=int(t[7]) / 1000.0,
            ))
        return saida

    def torrents(self, categoria: str | None = None,
                 hashes: list[str] | None = None) -> list[Progresso]:
        return self.listar(hashes, categoria)

    def arquivos(self, infohash: str) -> list[dict]:
        dados = self._acao({"action": "getfiles", "hash": infohash})
        bruto = dados.get("files") or []
        if len(bruto) < 2:
            return []
        return [{"indice": i, "nome": f[0], "name": f[0],
                 "tamanho": int(f[1]), "prioridade": int(f[3]) if len(f) > 3 else 2}
                for i, f in enumerate(bruto[1])]

    def propriedades(self, infohash: str) -> dict:
        dados = self._acao({"action": "getprops", "hash": infohash})
        props = (dados.get("props") or [{}])[0]
        return {"share_ratio": None, "addition_date": None, **props}

    # ---------------------------------------------------------------- acoes

    def _ler_config(self, chave: str) -> str | None:
        for s in self._acao({"action": "getsettings"}).get("settings", []):
            if s and s[0] == chave:
                return s[2]
        return None

    def _definir_pasta(self, pasta: Path) -> bool:
        """Tenta apontar a pasta de download. Nunca levanta excecao.

        A Interface Web do uTorrent nao aceita caractere fora do ASCII na
        consulta: um caminho como "C:/Users/Kairós/..." devolve HTTP 400, e em
        cp1252 ele responde 200 mas ignora o valor. Como isso derrubava o
        download inteiro — a pessoa via "uTorrent devolveu HTTP 400" e nada
        acontecia —, aqui a falha vira aviso: o torrent entra assim mesmo, na
        pasta que o proprio uTorrent usa.
        """
        try:
            self._acao({"action": "setsetting", "s": "dir_active_download",
                        "v": str(pasta)})
        except ErroMotor:
            return False
        # Responder 200 nao garante que aplicou; conferir e o unico jeito.
        lido = (self._ler_config("dir_active_download") or "").rstrip("\\/")
        return lido.lower() == str(pasta).rstrip("\\/").lower()

    def pasta_de_download(self) -> str | None:
        """A pasta que o proprio uTorrent usa, quando ele tem uma fixa.

        Serve para o Acervo parar de brigar com o cliente. A Interface Web nao
        deixa definir um caminho com acento, mas o uTorrent aceita esse mesmo
        caminho quando configurado na janela dele — entao, em vez de insistir,
        o app le onde o download vai cair e passa a olhar para la.
        """
        try:
            if (self._ler_config("dir_active_download_flag") or "").lower() in (
                    "true", "1"):
                pasta = (self._ler_config("dir_active_download") or "").strip()
                return pasta or None
        except ErroMotor:
            pass
        return None

    def adicionar(self, caminho_torrent: Path, pasta_destino: Path,
                  categoria: str | None = None, pausado: bool = True) -> None:
        """O uTorrent so tem pasta global: troca, adiciona, e devolve como estava."""
        self.avisos = []
        anterior = self._ler_config("dir_active_download")
        pasta_destino.mkdir(parents=True, exist_ok=True)
        try:
            if not self._definir_pasta(pasta_destino):
                dele = self.pasta_de_download()
                onde = (f"vai para “{dele}”, que é a pasta configurada no "
                        "próprio uTorrent" if dele else
                        "vai para a pasta padrão do uTorrent")
                self.avisos.append(
                    "a Interface Web do uTorrent não aceita acento no caminho, "
                    f"então ela recusou “{pasta_destino}”. O arquivo {onde}.")
            self._enviar_arquivo(caminho_torrent)
        finally:
            if anterior:
                try:
                    self._acao({"action": "setsetting", "s": "dir_active_download",
                                "v": anterior})
                except ErroMotor:
                    pass

        # A WebUI antiga nao adiciona pausado; para quando pedido.
        if pausado:
            from .bencode_infohash import infohash_de
            try:
                self.parar(infohash_de(caminho_torrent))
            except Exception:
                pass
        if categoria:
            try:
                from .bencode_infohash import infohash_de
                self._acao({"action": "setprops", "hash": infohash_de(caminho_torrent),
                            "s": "label", "v": categoria})
            except Exception:
                pass

    def _enviar_arquivo(self, caminho: Path) -> None:
        limite = f"----acervo{uuid.uuid4().hex}"
        corpo = (
            f"--{limite}\r\nContent-Disposition: form-data; name=\"torrent_file\"; "
            f"filename=\"{caminho.name}\"\r\n"
            f"Content-Type: application/x-bittorrent\r\n\r\n".encode()
            + caminho.read_bytes()
            + f"\r\n--{limite}--\r\n".encode())
        consulta = urllib.parse.urlencode({"token": self._pegar_token(),
                                           "action": "add-file"})
        self._pedir(f"/?{consulta}", corpo,
                    {"Content-Type": f"multipart/form-data; boundary={limite}"})

    def adicionar_trackers(self, infohash: str, urls: list[str]) -> None:
        if not urls:
            return
        atuais = ""
        dados = self._acao({"action": "getprops", "hash": infohash})
        props = (dados.get("props") or [{}])[0]
        if isinstance(props, dict):
            atuais = props.get("trackers", "") or ""
        junto = "\r\n".join([atuais.strip(), *urls]).strip()
        self._acao({"action": "setprops", "hash": infohash, "s": "trackers",
                    "v": junto})

    def nao_baixar(self, infohash: str, indices: list[int]) -> None:
        if not indices:
            return
        params = {"action": "setprio", "hash": infohash, "p": PRIORIDADE_NAO_BAIXAR}
        # O uTorrent aceita varios &f=; urlencode com doseq resolve.
        consulta = urllib.parse.urlencode(
            {"token": self._pegar_token(), **params, "f": indices}, doseq=True)
        self._pedir(f"/?{consulta}")

    def iniciar(self, infohash: str) -> None:
        self._acao({"action": "start", "hash": infohash})

    def parar(self, infohash: str) -> None:
        self._acao({"action": "pause", "hash": infohash})

    def remover(self, infohash: str, apagar_arquivos: bool = False) -> None:
        self._acao({"action": "removedata" if apagar_arquivos else "remove",
                    "hash": infohash})
