"""Orquestra o download: liga o indice do Acervo ao motor escolhido.

Aqui mora a regra de negocio que faz o download comecar rapido e ocupar menos
espaco: trackers injetados e propaganda desmarcada antes de iniciar.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .motores import ErroMotor, escolher
from .motores.qbittorrent import carregar_trackers

TEMPO_ESPERA_ADICAO = 15  # segundos ate o cliente registrar o torrent


# Motor em uso, guardado entre chamadas.
#
# `cliente()` e chamado pelo relogio de 3 segundos da janela. Criando um motor
# novo a cada vez, o app refazia duas sondagens HTTP por ciclo e — no caso do
# aria2 — perdia o proprio daemon de vista, porque cada instancia trazia um
# segredo RPC diferente. Guardar a instancia conserta as duas coisas, e ainda
# faz `encerrar()` funcionar: quem fecha o app recebe o motor que subiu o
# processo, nao um estranho com `self.processo = None`.
_motor = None
_assinatura = None


def _assinar(cfg) -> tuple:
    """O que, se mudar, obriga a escolher o motor de novo."""
    o = cfg.bruto.get("motor") or {}
    return (o.get("tipo"), o.get("qbittorrent_url"), o.get("utorrent_url"),
            o.get("aria2_caminho"), o.get("usuario"), o.get("senha"),
            str(cfg.staging))


def esquecer_motor() -> None:
    """Descarta o motor guardado. Chamado quando as configuracoes mudam."""
    global _motor, _assinatura
    _motor, _assinatura = None, None


def cliente(cfg):
    """O motor a usar agora. `None` quando nenhum cliente esta disponivel."""
    global _motor, _assinatura

    assinatura = _assinar(cfg)
    if _motor is not None and _assinatura == assinatura:
        return _motor

    motor, _ = escolher(cfg)
    _motor, _assinatura = motor, assinatura
    return motor


def cliente_ou_erro(cfg):
    motor, explicacao = escolher(cfg)
    if motor is None:
        raise ErroMotor(explicacao)
    return motor


def _trackers_do_acervo(con: sqlite3.Connection, limite: int = 40) -> list[str]:
    """Trackers que ja aparecem nos proprios .torrent do usuario, mais usados primeiro."""
    contagem: dict[str, int] = {}
    for linha in con.execute("SELECT trackers FROM torrents WHERE trackers IS NOT NULL"):
        for url in (linha["trackers"] or "").splitlines():
            url = url.strip()
            if url:
                contagem[url] = contagem.get(url, 0) + 1
    ordenados = sorted(contagem.items(), key=lambda kv: -kv[1])
    return [u for u, _ in ordenados[:limite]]


def _esperar_registro(q, infohash: str) -> bool:
    fim = time.monotonic() + TEMPO_ESPERA_ADICAO
    while time.monotonic() < fim:
        if q.listar([infohash]):
            return True
        time.sleep(0.4)
    return False


def baixar(con: sqlite3.Connection, cfg, caminho_torrent: str,
           pular: list[int] | None = None) -> dict:
    """Adiciona um torrent ao motor ativo, ajustado e ja iniciado.

    `pular` sao indices de arquivos que o usuario escolheu nao baixar — e o que
    permite trazer um episodio so de uma temporada inteira. Vao pelo mesmo
    caminho da propaganda: desmarcados no cliente antes de iniciar.
    """
    t = con.execute(
        "SELECT t.*, i.tipo AS tipo_item, COALESCE(NULLIF(i.titulo_corrigido,''), i.titulo) "
        "AS titulo FROM torrents t LEFT JOIN itens i ON i.id = t.item_id "
        "WHERE t.caminho = ?", (caminho_torrent,)
    ).fetchone()
    if not t:
        return {"ok": False, "erro": "torrent nao encontrado no indice"}
    if t["corrompido"]:
        return {"ok": False, "erro": "este .torrent esta corrompido e nao pode ser lido"}

    arquivo = Path(cfg.indice) / caminho_torrent
    if not arquivo.is_file():
        return {"ok": False, "erro": f"arquivo sumiu do indice: {caminho_torrent}"}

    infohash = t["infohash"]
    tipo = t["tipo_item"] or "filme"
    opcoes = cfg.bruto.get("motor") or {}
    prefixo = opcoes.get("prefixo_categoria", "acervo")
    categoria = f"{prefixo}-{tipo}"

    # `escolher` ja testa quem esta no ar; repetir `disponivel()` aqui so
    # gastaria mais uma viagem de rede antes de o download comecar.
    q, explicacao = escolher(cfg)
    if q is None:
        return {"ok": False, "erro": explicacao, "sem_motor": True}

    passos: list[str] = []
    staging = Path(cfg.staging)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        # So o qBittorrent tem categorias; nos outros isso simplesmente nao existe.
        if hasattr(q, "criar_categoria"):
            q.criar_categoria(categoria, staging)

        if q.listar([infohash]):
            passos.append(f"ja estava no {q.nome} - so reiniciando")
        else:
            q.adicionar(arquivo, staging, categoria=categoria, pausado=True)
            if not _esperar_registro(q, infohash):
                return {"ok": False,
                        "erro": f"o {q.nome} aceitou o arquivo mas o torrent nao "
                                "apareceu na lista a tempo"}
            # O motor pode ter conseguido adicionar mas nao respeitar a pasta;
            # dizer isso e melhor que deixar a pessoa procurar o arquivo depois.
            for aviso in getattr(q, "avisos", []) or []:
                passos.append(aviso)
            passos.append(f"adicionado em {staging}"
                          if not getattr(q, "avisos", None)
                          else f"adicionado ({q.nome} escolheu a pasta)")

        # Trackers: nunca em torrent privado - adicionar tracker publico ali
        # quebra a regra do tracker fechado e pode custar a conta do usuario.
        if (opcoes.get("injetar_trackers", True) and not t["privado"]
                and q.recursos.injetar_trackers):
            urls = carregar_trackers(Path(cfg.dados) / "trackers.txt",
                                     _trackers_do_acervo(con))
            q.adicionar_trackers(infohash, urls)
            passos.append(f"{len(urls)} trackers injetados"
                          + (" (o torrent nao tinha nenhum)" if not t["n_trackers"] else ""))

        # Propaganda e escolha do usuario saem numa chamada so. Em jogo nada
        # e desmarcado: faltando uma parte, o jogo nao roda.
        #
        # Uma chamada, e nao duas, por causa do aria2: `select-file` diz o que
        # MANTER, entao cada chamada recalcula a selecao inteira e a ultima
        # apagava a anterior. Na pratica, escolher episodios reativava a
        # propaganda — e escolher nada desativava a filtragem de propaganda.
        if tipo != "jogo" and q.recursos.escolher_arquivos:
            fora: list[int] = []
            motivos: list[str] = []

            if opcoes.get("pular_lixo", True):
                lixo = [l["indice"] for l in con.execute(
                    "SELECT indice FROM torrent_files "
                    "WHERE caminho_torrent = ? AND tipo = 'lixo'", (caminho_torrent,))]
                if lixo:
                    fora += lixo
                    motivos.append(f"{len(lixo)} de propaganda")

            escolhidos = [int(i) for i in (pular or [])]
            if escolhidos:
                novos = [i for i in escolhidos if i not in fora]
                fora += novos
                motivos.append(f"{len(escolhidos)} que você não quis")

            if fora:
                q.nao_baixar(infohash, sorted(set(fora)))
                marcas = ",".join("?" * len(fora))
                poupado = con.execute(
                    f"SELECT COALESCE(SUM(tamanho),0) b FROM torrent_files "
                    f"WHERE caminho_torrent = ? AND indice IN ({marcas})",
                    (caminho_torrent, *sorted(set(fora)))).fetchone()["b"]
                passos.append(
                    f"{len(set(fora))} arquivo(s) fora do download — "
                    + ", ".join(motivos)
                    + f" ({poupado / 1024 / 1024 / 1024:.2f} GiB a menos)")

        if opcoes.get("download_sequencial", False) and q.recursos.sequencial:
            q.sequencial(infohash)
            passos.append("download sequencial ligado")

        q.iniciar(infohash)
        passos.append("iniciado")

        con.execute(
            "INSERT INTO disco (caminho_local, infohash, caminho_torrent, estado, "
            "bytes_presentes, bytes_esperados, gerenciado, visto_em) "
            "VALUES (?, ?, ?, 'parcial', 0, ?, 1, datetime('now')) "
            "ON CONFLICT(caminho_local) DO UPDATE SET gerenciado = 1, "
            "  infohash = excluded.infohash, caminho_torrent = excluded.caminho_torrent",
            (str(staging / t["nome"]), infohash, caminho_torrent, t["tamanho_total"]),
        )
        con.commit()

    except ErroMotor as e:
        return {"ok": False, "erro": str(e), "passos": passos}

    return {"ok": True, "infohash": infohash, "titulo": t["titulo"] or t["nome"],
            "motor": q.nome, "versao": explicacao, "passos": passos}


def _agir(cfg, infohash: str, acao: str, **extras) -> dict:
    """Pausar, retomar ou remover um torrent. Usado pelos botoes da tela da obra."""
    q = cliente(cfg)
    if q is None:
        return {"ok": False, "erro": escolher(cfg)[1]}
    no_ar, mensagem = q.disponivel()
    if not no_ar:
        esquecer_motor()      # caiu: a proxima chamada redetecta
        return {"ok": False, "erro": mensagem}
    try:
        if acao == "pausar":
            q.parar(infohash)
        elif acao == "retomar":
            q.iniciar(infohash)
        elif acao == "remover":
            q.remover(infohash, apagar_arquivos=bool(extras.get("apagar_arquivos")))
        else:
            return {"ok": False, "erro": f"ação desconhecida: {acao}"}
    except ErroMotor as e:
        return {"ok": False, "erro": str(e)}
    return {"ok": True}


def pausar(cfg, infohash: str) -> dict:
    return _agir(cfg, infohash, "pausar")


def retomar(cfg, infohash: str) -> dict:
    return _agir(cfg, infohash, "retomar")


def remover(cfg, infohash: str, apagar_arquivos: bool = False) -> dict:
    return _agir(cfg, infohash, "remover", apagar_arquivos=apagar_arquivos)


def detalhes_do_torrent(cfg, infohash: str) -> dict:
    """Ratio, data de adicao e demais numeros que a ficha da obra mostra."""
    q = cliente(cfg)
    if q is None:
        return {}
    no_ar, _ = q.disponivel()
    if not no_ar:
        esquecer_motor()
        return {}
    try:
        lista = q.listar([infohash])
        if not lista:
            return {}
        props = q.propriedades(infohash) if hasattr(q, 'propriedades') else {}
        p = lista[0]
        return {
            "estado": p.estado, "progresso": p.progresso, "seeds": p.seeds,
            "peers": p.peers, "velocidade": p.velocidade, "eta": p.eta,
            "baixado": p.baixado, "tamanho": p.tamanho, "caminho": p.caminho,
            "ratio": props.get("share_ratio", p.ratio),
            "adicionado": props.get("addition_date"),
            "pausado": p.pausado,
        }
    except ErroMotor:
        return {}


def progresso(con: sqlite3.Connection, cfg) -> dict:
    """Downloads em andamento, com o titulo bonito do catalogo."""
    q = cliente(cfg)
    if q is None:
        return {"disponivel": False, "erro": escolher(cfg)[1], "downloads": []}
    no_ar, versao = q.disponivel()
    if not no_ar:
        esquecer_motor()
        return {"disponivel": False, "erro": versao, "downloads": []}

    prefixo = cfg.qbittorrent.get("prefixo_categoria", "acervo")
    vistos: dict[str, dict] = {}
    for tipo in ("filme", "serie", "jogo"):
        for p in q.listar(categoria=f"{prefixo}-{tipo}"):
            linha = con.execute(
                "SELECT COALESCE(NULLIF(i.titulo_corrigido,''), i.titulo) titulo "
                "FROM torrents t JOIN itens i ON i.id = t.item_id "
                "WHERE t.infohash = ? LIMIT 1", (p.infohash,)
            ).fetchone()
            vistos[p.infohash] = {
                "infohash": p.infohash,
                "titulo": (linha["titulo"] if linha else None) or p.nome,
                "nome": p.nome,
                "tipo": tipo,
                "estado": p.estado,
                "terminou": p.terminou,
                "progresso": round(p.progresso, 4),
                "baixado": p.baixado,
                "tamanho": p.tamanho,
                "velocidade": p.velocidade,
                "seeds": p.seeds,
                "peers": p.peers,
                "eta": p.eta,
                "caminho": p.caminho,
            }
    return {"disponivel": True, "versao": versao,
            "downloads": sorted(vistos.values(), key=lambda d: d["progresso"])}
