"""Leitura e gravacao do config.toml.

`tomllib` (biblioteca padrao) so le. A gravacao e feita por um gerador proprio:
a estrutura do arquivo e fixa e conhecida, entao nao vale uma dependencia nova
so para isso - e assim os comentarios explicativos sobrevivem a cada salvamento.
"""
from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .local import pasta_dados

RAIZ_APP = pasta_dados()
ARQUIVO_PADRAO = RAIZ_APP / "config.toml"
ARQUIVO_EXEMPLO = RAIZ_APP / "config.exemplo.toml"

PADROES = {
    "caminhos": {
        "indice": "",
        "biblioteca": "",
        "staging": "",
        "dados": str(RAIZ_APP / "dados"),
        "ignorar": ["_baixando"],
        # Terminou de baixar, vai para a biblioteca sozinho. Desligue
        # aqui quem preferir conferir a previa antes de mover.
        "organizar_ao_concluir": True,
    },
    "motor": {
        # aria2 e o padrao: e o unico que nao exige nada instalado nem
        # configurado. Os outros continuam existindo, atras de "Avancado".
        "tipo": "aria2",
        "qbittorrent_url": "http://127.0.0.1:8080",
        "utorrent_url": "http://127.0.0.1:8080",
        "aria2_caminho": "",
        "aria2_seed_min": 60,
        "usuario": "",
        "senha": "",
        "prefixo_categoria": "acervo",
        "injetar_trackers": True,
        "pular_lixo": True,
        "download_sequencial": False,
    },
    "metadados": {
        "tmdb_api_key": "",
        "tmdb_idioma": "pt-BR",
        "steamgriddb_api_key": "",
    },
    "seguranca": {
        "minimo_seeders": 1,
        "validade_saude_dias": 14,
        "pastas_protegidas": [],
    },
    "reproducao": {
        # Player embutido ligado de fabrica; desligado, "Reproduzir" volta a
        # abrir no programa padrao do Windows.
        "embutido": True,
        # Pergunta onde assistir antes de reproduzir. Some assim que a pessoa
        # marcar "nao perguntar de novo" — e ai vale o que ela escolheu.
        "perguntar": True,
        "motor": "auto",          # auto | vlc | mpv | sistema
        "vlc_caminho": "",
        "mpv_caminho": "",
        "volume": 90,
    },
    "aparencia": {
        "tema": "escuro",
        "fonte": "normal",
        "tamanho_grade": "medio",
        "modo": "grade",
        # Como o cartao reage ao mouse. `python -m ferramentas.hovers` abre uma
        # bancada para experimentar todos com o catalogo de verdade.
        "hover": "revelar",
        # O guia so aparece sozinho uma vez. Depois disso fica em
        # Configuracoes -> Aparencia, para quem quiser rever.
        "guia_visto": False,
    },
}


@dataclass
class Config:
    indice: Path
    biblioteca: Path
    staging: Path
    dados: Path
    ignorar: list[str]
    motor: dict
    metadados: dict
    seguranca: dict
    arquivo: Path = ARQUIVO_PADRAO
    bruto: dict = field(default_factory=dict)

    @property
    def qbittorrent(self) -> dict:
        """Nome antigo da secao, mantido para nao quebrar chamadas existentes."""
        return self.motor

    @property
    def banco(self) -> Path:
        return self.dados / "acervo.db"

    @property
    def posters(self) -> Path:
        return self.dados / "posters"

    def _preenchido(self, chave: str) -> bool:
        """Path("") vira Path(".") no Python, e "." e sempre um diretorio valido.

        Sem esta checagem no texto cru, um caminho em branco passaria por
        "configurado" e o app varreria a pasta de onde foi aberto.
        """
        bruto = (self.bruto.get("caminhos") or {}).get(chave) or ""
        return bool(str(bruto).strip())

    @property
    def configurado(self) -> bool:
        """Ha o minimo para o app funcionar: uma pasta de indice que existe."""
        return self._preenchido("indice") and self.indice.is_dir()

    def pendencias(self) -> list[str]:
        """O que ainda falta para o app fazer tudo. Alimenta o assistente inicial."""
        faltando = []
        if not self.configurado:
            faltando.append("indice")
        if not self._preenchido("biblioteca") or not self.biblioteca.is_dir():
            faltando.append("biblioteca")
        if not (self.metadados.get("tmdb_api_key") or "").strip():
            faltando.append("tmdb")
        return faltando


def _mesclar(padrao: dict, lido: dict) -> dict:
    """Preenche o que faltar no arquivo do usuario com os padroes."""
    saida = {}
    for secao, valores in padrao.items():
        atual = lido.get(secao) or {}
        saida[secao] = {**valores, **{k: v for k, v in atual.items() if v is not None}}
    for secao, valores in lido.items():
        if secao not in saida:
            saida[secao] = valores
    return saida


def carregar(caminho: str | Path | None = None) -> Config:
    caminho = Path(caminho) if caminho else ARQUIVO_PADRAO
    lido: dict = {}
    if caminho.is_file():
        lido = tomllib.loads(caminho.read_text(encoding="utf-8"))
    dados = _mesclar(PADROES, lido)

    c = dados["caminhos"]
    dados_dir = Path(c.get("dados") or (RAIZ_APP / "dados"))
    return Config(
        indice=Path(c.get("indice") or ""),
        biblioteca=Path(c.get("biblioteca") or ""),
        staging=Path(c.get("staging") or (dados_dir.parent / "_baixando")),
        dados=dados_dir,
        ignorar=c.get("ignorar") or [],
        motor=dados["motor"],
        metadados=dados["metadados"],
        seguranca=dados["seguranca"],
        arquivo=caminho,
        bruto=dados,
    )


# ------------------------------------------------------------------- gravacao

def _valor_toml(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_valor_toml(x) for x in v) + "]"
    texto = str(v).replace("\\", "/").replace('"', '\\"')
    return f'"{texto}"'


COMENTARIOS = {
    ("caminhos", "indice"): "Pasta com os arquivos .torrent - o indice permanente da biblioteca.",
    ("caminhos", "biblioteca"): "Raiz da midia. Filmes/, Series/ e Jogos/ ficam aqui dentro.",
    ("caminhos", "staging"): "Onde o qBittorrent baixa antes de organizar.",
    ("caminhos", "dados"): "Banco e cache de posteres.",
    ("caminhos", "ignorar"): "Pastas que a varredura de disco deve pular.",
    ("motor", "tipo"): "auto | qbittorrent | utorrent | aria2",
    ("motor", "qbittorrent_url"): "Endereco da Web UI do qBittorrent.",
    ("motor", "utorrent_url"): "Endereco da Interface Web do uTorrent.",
    ("motor", "aria2_caminho"): "Caminho do aria2c.exe (vazio = procura sozinho).",
    ("motor", "aria2_seed_min"): "Minutos semeando depois de concluir, no aria2.",
    ("motor", "usuario"): "Deixe vazio se o cliente ignora autenticacao no localhost.",
    ("motor", "injetar_trackers"):
        "Injetar trackers publicos ao adicionar (nunca em torrent privado).",
    ("motor", "pular_lixo"): "Nao baixar arquivos de propaganda dos sites.",
    ("motor", "download_sequencial"): "Baixar em ordem, para assistir enquanto baixa.",
    ("metadados", "tmdb_api_key"): "Chave v3 gratuita: themoviedb.org/settings/api",
    ("metadados", "steamgriddb_api_key"):
        "Chave gratuita: steamgriddb.com/profile/preferences/api",
    ("seguranca", "minimo_seeders"): "Nao oferecer 'liberar espaco' abaixo deste numero.",
    ("seguranca", "validade_saude_dias"): "Depois disso a checagem de seeders vence.",
    ("seguranca", "pastas_protegidas"): "Pastas cujo conteudo o app nunca pode apagar.",
    ("aparencia", "tema"): "escuro | claro | contraste",
    ("aparencia", "fonte"): "normal | grande | maior",
    ("aparencia", "tamanho_grade"): "pequeno | medio | grande | enorme",
    ("aparencia", "modo"): "grade | lista",
}

TITULOS = {
    "caminhos": "Onde estao as coisas",
    "motor": "Motor de download",
    "metadados": "Capas e sinopses",
    "seguranca": "Travas de seguranca",
    "aparencia": "Aparencia da janela",
}


def gerar_toml(dados: dict) -> str:
    linhas = ["# Configuracao do Acervo.",
              "# Gerado pelo proprio app (Configuracoes) - pode editar a mao tambem.",
              "# Caminhos podem usar barra normal (/) mesmo no Windows.",
              ""]
    for secao in ("caminhos", "motor", "metadados", "seguranca", "aparencia"):
        valores = dados.get(secao) or {}
        linhas.append(f"# --- {TITULOS.get(secao, secao)} ---")
        linhas.append(f"[{secao}]")
        for chave, valor in valores.items():
            comentario = COMENTARIOS.get((secao, chave))
            if comentario:
                linhas.append(f"# {comentario}")
            linhas.append(f"{chave} = {_valor_toml(valor)}")
        linhas.append("")
    return "\n".join(linhas)


def salvar(dados: dict, caminho: str | Path | None = None) -> Path:
    """Grava o config.toml, guardando uma copia do anterior."""
    caminho = Path(caminho) if caminho else ARQUIVO_PADRAO
    completo = _mesclar(PADROES, dados)
    if caminho.is_file():
        shutil.copy2(caminho, caminho.with_suffix(".toml.bak"))
    caminho.write_text(gerar_toml(completo), encoding="utf-8")
    return caminho


def aplicar(alteracoes: dict, caminho: str | Path | None = None) -> Config:
    """Mescla alteracoes vindas da interface no arquivo e devolve a config nova."""
    atual = carregar(caminho).bruto
    for secao, valores in (alteracoes or {}).items():
        if secao not in atual:
            atual[secao] = {}
        for chave, valor in (valores or {}).items():
            atual[secao][chave] = valor
    salvar(atual, caminho)
    return carregar(caminho)
