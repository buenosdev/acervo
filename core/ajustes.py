"""Configuracao pela interface: ler, validar, testar e salvar.

O objetivo e que ninguem precise abrir o config.toml na mao nem sair do app para
ligar o qBittorrent. Cada teste devolve uma mensagem que explica o que fazer
quando da errado, nao so "falhou".
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import config

# Campos que a interface pode gravar. Qualquer outra coisa e ignorada: assim a
# tela nao consegue escrever lixo no arquivo.
CAMPOS = {
    "caminhos": {"indice", "biblioteca", "staging", "dados", "ignorar"},
    "motor": {"tipo", "qbittorrent_url", "utorrent_url", "aria2_caminho",
              "aria2_seed_min", "usuario", "senha", "prefixo_categoria",
              "injetar_trackers", "pular_lixo", "download_sequencial"},
    "metadados": {"tmdb_api_key", "tmdb_idioma", "steamgriddb_api_key"},
    "seguranca": {"minimo_seeders", "validade_saude_dias", "pastas_protegidas"},
    "aparencia": {"tema", "fonte", "tamanho_grade", "modo"},
}
SEGREDOS = {("metadados", "tmdb_api_key"), ("metadados", "steamgriddb_api_key"),
            ("motor", "senha")}


def _mascarar(valor: str) -> str:
    """Mostra so o fim da chave, o bastante para o usuario reconhecer qual e."""
    valor = str(valor or "")
    return f"{'•' * 8}{valor[-4:]}" if len(valor) > 6 else ("" if not valor else "••••")


def ler(cfg) -> dict:
    """Config atual para a tela. Segredos vao mascarados, nunca em claro."""
    saida: dict = {}
    for secao, permitidos in CAMPOS.items():
        valores = dict(cfg.bruto.get(secao) or {})
        saida[secao] = {}
        for chave in permitidos:
            valor = valores.get(chave)
            if (secao, chave) in SEGREDOS:
                saida[secao][chave] = _mascarar(valor)
                saida[secao][f"{chave}_definida"] = bool(str(valor or "").strip())
            else:
                saida[secao][chave] = valor
    saida["arquivo"] = str(cfg.arquivo)
    saida["pendencias"] = cfg.pendencias()
    saida["configurado"] = cfg.configurado
    return saida


def _limpar(alteracoes: dict, cfg) -> dict:
    """Descarta campos desconhecidos e ignora segredo que voltou mascarado."""
    limpo: dict = {}
    for secao, valores in (alteracoes or {}).items():
        permitidos = CAMPOS.get(secao)
        if not permitidos:
            continue
        limpo[secao] = {}
        for chave, valor in (valores or {}).items():
            if chave not in permitidos:
                continue
            if (secao, chave) in SEGREDOS:
                texto = str(valor or "")
                # A tela devolve "••••abcd" quando o usuario nao mexeu no campo.
                if not texto.strip() or "•" in texto:
                    continue
                limpo[secao][chave] = texto.strip()
            elif chave in ("minimo_seeders", "validade_saude_dias", "aria2_seed_min"):
                try:
                    limpo[secao][chave] = max(0, int(valor))
                except (TypeError, ValueError):
                    continue
            elif chave in ("ignorar", "pastas_protegidas"):
                if isinstance(valor, str):
                    valor = [x.strip() for x in valor.split(",") if x.strip()]
                limpo[secao][chave] = list(valor or [])
            elif isinstance(valor, bool):
                limpo[secao][chave] = valor
            else:
                limpo[secao][chave] = str(valor or "").strip()
        if not limpo[secao]:
            del limpo[secao]
    return limpo


def validar(alteracoes: dict) -> list[str]:
    """Avisos sobre o que foi digitado - nao impede salvar, so alerta."""
    avisos = []
    caminhos = (alteracoes or {}).get("caminhos") or {}
    for chave, rotulo in (("indice", "pasta do índice"),
                          ("biblioteca", "pasta da biblioteca")):
        valor = str(caminhos.get(chave) or "").strip()
        if valor and not Path(valor).is_dir():
            avisos.append(f"A {rotulo} não existe: {valor}")
    for chave in ("qbittorrent_url", "utorrent_url"):
        url = ((alteracoes or {}).get("motor") or {}).get(chave)
        if url and not str(url).startswith(("http://", "https://")):
            avisos.append(f"O endereço em {chave} precisa começar com http:// ou https://")
    return avisos


def salvar(alteracoes: dict, cfg):
    """Grava e devolve (config_nova, avisos)."""
    limpo = _limpar(alteracoes, cfg)

    # Ninguém deveria precisar inventar a pasta de download: se ficou em branco,
    # ela nasce dentro da biblioteca.
    caminhos = limpo.get("caminhos") or {}
    if "staging" in caminhos and not str(caminhos["staging"]).strip():
        biblioteca = caminhos.get("biblioteca") or str(cfg.biblioteca)
        if str(biblioteca).strip():
            caminhos["staging"] = str(Path(biblioteca) / "_baixando").replace("\\", "/")
            limpo["caminhos"] = caminhos

    avisos = validar(limpo)
    nova = config.aplicar(limpo, cfg.arquivo)
    return nova, avisos


def precisa_varrer(cfg_antiga, cfg_nova, con) -> bool:
    """True se o catalogo ficaria vazio ou desatualizado depois de salvar.

    Sem isto, quem configura pela tela salva, fecha e encontra um catalogo
    vazio: a varredura so acontecia na abertura do programa. Como o app ja
    se considera configurado, o assistente some e o usuario fica sem saida.
    """
    if not cfg_nova.configurado:
        return False
    if str(cfg_antiga.indice) != str(cfg_nova.indice):
        return True
    return not con.execute("SELECT 1 FROM torrents LIMIT 1").fetchone()


# --------------------------------------------------------------------- testes

SUGESTAO_STAGING = "C:/Acervo/_baixando"


def config_de_teste(dados: dict, cfg):
    """Config temporaria com o que esta na tela. Nada e gravado por causa dela."""
    atual = cfg.bruto.get("motor") or {}
    senha = str(dados.get("senha") or "")
    if not senha.strip() or "•" in senha:
        senha = atual.get("senha", "")
    return type("C", (), {
        "bruto": {"motor": {**atual, **{k: v for k, v in dados.items()
                                        if v not in (None, "")}, "senha": senha}},
        "staging": cfg.staging})()


def testar_motor(dados: dict, cfg) -> dict:
    """Testa o motor escolhido com o que esta na tela, sem precisar salvar antes."""
    from .motores import ROTULOS, criar

    atual = cfg.bruto.get("motor") or {}
    tipo = (dados.get("tipo") or atual.get("tipo") or "auto").lower()

    # A config temporaria e montada ANTES do desvio para "auto". Antes ela so
    # existia no ramo dos motores nomeados, e o modo automatico — que e o padrao
    # — testava a config salva, ignorando o usuario e a senha recem digitados.
    # Quem digitava a senha certa e clicava em Testar continuava vendo 401.
    temporaria = config_de_teste(dados, cfg)

    if tipo == "auto":
        return testar_auto(temporaria)
    try:
        q = criar(tipo, temporaria)
    except ValueError as e:
        return {"ok": False, "mensagem": str(e), "detalhe": ""}

    no_ar, mensagem = q.disponivel()
    if no_ar:
        avisos = " ".join(q.recursos.observacoes)
        return {"ok": True,
                "mensagem": f"Conectado: {mensagem}.",
                "detalhe": ("O botão Baixar já funciona. " + avisos).strip()}

    # A mensagem do Windows para "conexão recusada" contém a palavra "recusou",
    # então a dica de login precisa olhar o código HTTP, não o texto.
    autenticacao = "403" in mensagem or "login" in mensagem.lower()
    dica = ("O endereço respondeu, mas recusou o login. Confira usuário e senha "
            "da Web UI — ou marque “Ignorar autenticação para clientes no "
            "localhost” e deixe os dois campos vazios aqui.") if autenticacao else (
        "Abra o qBittorrent e vá em Ferramentas → Opções → Web UI. Marque "
        "“Servidor Web UI (Controle Remoto)”, confira se a porta é a mesma "
        "digitada acima e marque “Ignorar autenticação para clientes no "
        "localhost”. Se o qBittorrent nem estiver instalado, baixe em "
        "qbittorrent.org — sem ele o catálogo funciona, só não dá para baixar.")
    return {"ok": False, "mensagem": mensagem, "detalhe": dica}


def configurar_download(dados: dict, cfg) -> dict:
    """Descobre sozinho o que falta para o botao Baixar funcionar.

    Existe porque "configure a interface web do seu cliente" nao e instrucao
    para quem nunca ouviu falar de interface web. O app olha a maquina e resolve
    tudo o que pode resolver sozinho, deixando so o que depende de voce.

    Devolve {ok, mensagem, detalhe, precisa_aria2, precisa_senha,
             pode_ligar_webui, ajustes}.
    """
    from . import utorrent_config as ut
    from .motores import ROTULOS, como_ligar, detectar, instalados

    temporaria = config_de_teste(dados, cfg)
    achados = detectar(temporaria)
    linhas = [f"{'OK' if a['disponivel'] else '--'} {a['nome']}: {a['mensagem']}"
              for a in achados]
    relato = "\n".join(linhas)
    prontos = [a for a in achados if a["disponivel"]]

    # O uTorrent merece um olhar proprio: e o cliente que ja esta na maquina, e
    # quase tudo nele da para descobrir sem perguntar nada.
    e = ut.estado(_porta_de(dados, cfg))
    # `exige_senha` so diz que a Interface Web pede login — ela sempre pede. O
    # que importa e se as credenciais que temos ja funcionam: se o uTorrent
    # entrou na lista dos disponiveis, nao ha nada a perguntar.
    utorrent_ok = any(a["tipo"] == "utorrent" and a["disponivel"] for a in achados)
    falta_so_a_senha = (not utorrent_ok and e.instalado
                        and bool(e.porta) and e.exige_senha)

    if prontos and not falta_so_a_senha:
        r = {"ok": True, "precisa_aria2": False,
             "mensagem": f"Tudo certo — o Acervo vai usar o {prontos[0]['nome']}.",
             "detalhe": "O botão Baixar já funciona.\n\n" + relato}
        r.update(_conferir_pasta_do_utorrent(prontos[0]["tipo"], cfg))
        return r

    if falta_so_a_senha:
        usuario = (dados.get("usuario") or "").strip() or ut.USUARIO_PADRAO
        ja_da = (f"O {prontos[0]['nome']} já dá conta de baixar, mas o uTorrent "
                 "continua semeando depois que termina — e é isso que deixa "
                 "apagar um filme sem perdê-lo para sempre.\n\n"
                 if prontos else "")
        return {
            "ok": bool(prontos), "precisa_aria2": False, "precisa_senha": True,
            "mensagem": f"Achei a Interface Web do uTorrent na porta {e.porta}.",
            "detalhe": (ja_da +
                        "Já preenchi o endereço e o usuário. Falta só a senha "
                        "que você definiu no uTorrent — ele a guarda embaralhada, "
                        "então nem ele consegue devolvê-la a outro programa."
                        "\n\nEscreva a senha ao lado e clique aqui de novo."),
            "ajustes": {"utorrent_url": f"http://127.0.0.1:{e.porta}",
                        "usuario": usuario, "tipo": "auto"}}

    if e.instalado:
        if e.webui_ligada is False and not e.rodando:
            return {
                "ok": False, "precisa_aria2": False, "pode_ligar_webui": True,
                "mensagem": "O uTorrent está instalado com a Interface Web desligada.",
                "detalhe": ("Como ele está fechado, dá para eu ligar sozinho: "
                            "escrevo a configuração dele, guardo uma cópia da "
                            "anterior e escolho um usuário e senha só para o "
                            "Acervo.\n\n" + relato)}

        if e.webui_ligada is False and e.rodando:
            return {
                "ok": False, "precisa_aria2": True,
                "mensagem": "O uTorrent está aberto e sem a Interface Web.",
                "detalhe": ("Feche o uTorrent e clique aqui de novo — aí eu ligo "
                            "sozinho. Ele reescreve as próprias configurações ao "
                            "sair, então mudar com ele aberto não adiantaria."
                            "\n\nOu, sem mexer nele: " + como_ligar("utorrent")
                            + "\n\n" + relato)}

    tem = instalados()
    if tem:
        nomes = " e ".join(ROTULOS[t] for t in tem)
        return {"ok": False, "precisa_aria2": True,
                "mensagem": f"O {nomes} está instalado, mas desligado para o app.",
                "detalhe": (f"No {ROTULOS[tem[0]]}: {como_ligar(tem[0])}\n\n"
                            "Se preferir não mexer nele, dá para baixar o aria2 "
                            "agora — são ~2 MB, o app cuida sozinho e nada é "
                            "instalado no sistema.\n\n" + relato)}

    return {"ok": False, "precisa_aria2": True,
            "mensagem": "Nenhum cliente de torrent nesta máquina.",
            "detalhe": ("O aria2 resolve sem instalar nada — ~2 MB, baixados e "
                        "guardados ao lado do app.\n\n" + relato)}


def _conferir_pasta_do_utorrent(tipo: str, cfg) -> dict:
    """Alinha a pasta de download do app com a que o uTorrent realmente usa.

    A Interface Web do uTorrent recusa acento no caminho, entao o app nao
    consegue mandar nele a pasta que quer. Insistir seria brigar com o cliente.
    O caminho curto e o contrario: perguntar ao uTorrent onde ele ja salva e
    passar a olhar para la — inclusive porque quem configurou aquilo na janela
    dele provavelmente escolheu de proposito.
    """
    from .motores import criar
    from .motores.utorrent import caminho_aceito

    if tipo != "utorrent" or caminho_aceito(cfg.staging):
        return {}

    try:
        dele = criar("utorrent", cfg).pasta_de_download()
    except Exception:                                  # noqa: BLE001
        dele = None

    if dele:
        if str(dele).rstrip("/" + chr(92)).lower() == str(cfg.staging).rstrip(
                "/" + chr(92)).lower():
            return {}                                  # ja estao alinhados
        return {
            "staging_sugerido": dele,
            "mensagem": "O uTorrent salva numa pasta diferente da configurada aqui.",
            "detalhe": (f"Ele baixa em “{dele}” — foi o que você definiu na "
                        f"janela dele. O Acervo está esperando em “{cfg.staging}”, "
                        "e a Interface Web não deixa mudar isso de fora porque o "
                        "caminho tem acento.\n\nPosso passar a olhar para a pasta "
                        "do uTorrent, e aí o app encontra o que você baixar.")}

    return {
        "staging_sugerido": SUGESTAO_STAGING,
        "mensagem": "O uTorrent baixa, mas não vai usar a sua pasta de download.",
        "detalhe": ("A Interface Web dele recusa acentos no caminho, e "
                    f"“{cfg.staging}” tem um. Sem isso o arquivo cai na pasta "
                    "padrão do uTorrent e o Acervo não acha o que baixou."
                    f"\n\nDá para eu usar “{SUGESTAO_STAGING}” — sem acento, ele "
                    "aceita. Ou escolha uma pasta na janela do próprio uTorrent, "
                    "que aí ele aceita acento e o app se alinha sozinho.")}


def _porta_de(dados: dict, cfg) -> int | None:
    """A porta que ja esta configurada, para ser a primeira testada."""
    url = (dados.get("utorrent_url")
           or (cfg.bruto.get("motor") or {}).get("utorrent_url") or "")
    if ":" in url:
        pedaco = url.rstrip("/").rsplit(":", 1)[-1].split("/")[0]
        if pedaco.isdigit():
            return int(pedaco)
    return None


def ligar_webui_utorrent(cfg) -> dict:
    """Liga a Interface Web do uTorrent e devolve as credenciais escolhidas."""
    import secrets

    from . import utorrent_config as ut

    usuario = "acervo"
    senha = secrets.token_urlsafe(9)
    r = ut.ligar_webui(usuario, senha)
    if not r.get("ok"):
        return r
    r["ajustes"] = {"tipo": "auto", "usuario": usuario, "senha": senha,
                    "utorrent_url": "http://127.0.0.1:8080"}
    return r


def testar_auto(cfg) -> dict:
    """Detecta todos e conta o que achou, na ordem de preferencia."""
    from .motores import detectar

    achados = detectar(cfg)
    prontos = [a for a in achados if a["disponivel"]]
    linhas = [f"{'OK' if a['disponivel'] else '--'} {a['nome']}: {a['mensagem']}"
              for a in achados]
    if prontos:
        return {"ok": True,
                "mensagem": f"Vai usar: {prontos[0]['nome']}.",
                "detalhe": "\n".join(linhas)}
    return {"ok": False,
            "mensagem": "Nenhum cliente de torrent disponível.",
            "detalhe": "\n".join(linhas)}


# Nome antigo, ainda chamado pela tela.
def testar_qbittorrent(dados: dict, cfg) -> dict:
    return testar_motor(dados, cfg)


def testar_tmdb(chave: str, cfg) -> dict:
    from .metadata import CABECALHOS

    chave = str(chave or "")
    if not chave.strip() or "•" in chave:
        chave = cfg.metadados.get("tmdb_api_key", "")
    if not chave.strip():
        return {"ok": False, "mensagem": "Nenhuma chave informada.",
                "detalhe": "Pegue uma grátis em themoviedb.org/settings/api."}
    url = (f"https://api.themoviedb.org/3/search/movie?"
           + urllib.parse.urlencode({"api_key": chave, "query": "Matrix"}))
    try:
        req = urllib.request.Request(url, headers=CABECALHOS)
        with urllib.request.urlopen(req, timeout=15) as r:
            dados = json.loads(r.read().decode("utf-8"))
        return {"ok": True, "mensagem": "Chave do TMDB válida.",
                "detalhe": f"{dados.get('total_results', 0)} resultados no teste."}
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"ok": False, "mensagem": "O TMDB recusou a chave (401).",
                    "detalhe": "Use a “API Key (v3 auth)”, a curta de 32 caracteres — "
                               "não o “API Read Access Token”."}
        return {"ok": False, "mensagem": f"O TMDB respondeu HTTP {e.code}.", "detalhe": ""}
    except urllib.error.URLError as e:
        return {"ok": False, "mensagem": f"Sem resposta do TMDB ({e.reason}).",
                "detalhe": "Confira a conexão com a internet."}


def testar_steamgriddb(chave: str, cfg) -> dict:
    from .metadata import CABECALHOS

    chave = str(chave or "")
    if not chave.strip() or "•" in chave:
        chave = cfg.metadados.get("steamgriddb_api_key", "")
    if not chave.strip():
        return {"ok": False, "mensagem": "Nenhuma chave informada.",
                "detalhe": "É opcional: sem ela os jogos ficam com capa gerada."}
    try:
        req = urllib.request.Request(
            "https://www.steamgriddb.com/api/v2/search/autocomplete/Hollow%20Knight",
            headers={**CABECALHOS, "Authorization": f"Bearer {chave}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            dados = json.loads(r.read().decode("utf-8"))
        n = len(dados.get("data") or [])
        return {"ok": True, "mensagem": "Chave do SteamGridDB válida.",
                "detalhe": f"{n} resultados no teste."}
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"ok": False, "mensagem": "O SteamGridDB recusou a chave (401).",
                    "detalhe": "Gere outra em steamgriddb.com/profile/preferences/api."}
        if e.code == 403:
            return {"ok": False, "mensagem": "Bloqueado pelo Cloudflare (403).",
                    "detalhe": "Costuma ser temporário e não tem a ver com a chave. "
                               "Tente de novo em alguns minutos."}
        return {"ok": False, "mensagem": f"HTTP {e.code}.", "detalhe": ""}
    except urllib.error.URLError as e:
        return {"ok": False, "mensagem": f"Sem resposta ({e.reason}).", "detalhe": ""}


def testar_pasta(caminho: str) -> dict:
    """Confere uma pasta e conta o que ha nela - ajuda a saber se e a certa."""
    caminho = str(caminho or "").strip()
    if not caminho:
        return {"ok": False, "mensagem": "Nenhum caminho informado.", "detalhe": ""}
    p = Path(caminho)
    if not p.exists():
        return {"ok": False, "mensagem": "Essa pasta não existe.",
                "detalhe": "Confira o caminho — copie da barra de endereço do Explorer."}
    if not p.is_dir():
        return {"ok": False, "mensagem": "Isso é um arquivo, não uma pasta.", "detalhe": ""}
    try:
        torrents = sum(1 for _ in p.rglob("*.torrent"))
    except (PermissionError, OSError) as e:
        return {"ok": False, "mensagem": "Sem permissão para ler a pasta.",
                "detalhe": str(e)}
    return {"ok": True, "mensagem": f"Pasta encontrada com {torrents} arquivo(s) .torrent.",
            "detalhe": "" if torrents else
                       "Nenhum .torrent aqui dentro — confira se é mesmo a pasta certa."}


def aplicar_reproducao(cfg, **mudancas):
    """Grava ajustes de reproducao e devolve a config nova.

    Existe para a escolha feita no dialogo "onde assistir" ser exatamente a
    mesma coisa que a chave em Configuracoes -> Reproducao, e nao um ajuste
    paralelo que depois contradiz o outro.
    """
    from . import config

    return config.aplicar({"reproducao": mudancas})
