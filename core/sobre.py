"""Identidade do projeto: versao, licenca e de quem sao os dados de terceiros.

Fica num modulo proprio, e nao no `acervo.py`, porque a tela de Configuracoes
tambem precisa disso — e importar do ponto de entrada quebraria quando o app
roda empacotado, alem de criar dependencia circular.

O conteudo daqui nao e enfeite. A GPL pede que um programa interativo diga sob
que licenca roda, e os termos da API do TMDB exigem a atribuicao onde os dados
deles aparecem; ambas as coisas sao mostradas na aba "Sobre".
"""
from __future__ import annotations

NOME = "Acervo"
VERSAO = "0.2.0"
DESCRICAO = "Gerenciador local de biblioteca de torrents."

AUTOR = "Davi Bueno (buenosdev)"
ANO = 2026
LICENCA = "GPL-3.0-or-later"
REPOSITORIO = "https://github.com/buenosdev/acervo"
URL_LICENCA = "https://www.gnu.org/licenses/gpl-3.0.html"

COPYRIGHT = f"Copyright (C) {ANO} {AUTOR}"

# Atribuicao exigida pelos termos da API do TMDB, nas duas linguas.
CREDITO_TMDB = (
    "Este produto usa a API do TMDB, mas não é endossado nem certificado "
    "pelo TMDB.\n"
    "This product uses the TMDB API but is not endorsed or certified by TMDB.")

TERCEIROS = [
    ("PySide6 / Qt", "LGPL-3.0",
     "Interface. Vinculado dinamicamente; o código-fonte deste app é aberto, "
     "o que preserva o direito de relinkar."),
    ("aria2", "GPL-2.0 ou posterior",
     "Motor de download padrão. Não é redistribuído: o app baixa o binário "
     "oficial do projeto, com a sua confirmação."),
    ("TMDB", "API, termos próprios",
     "Capas, sinopses e notas de filmes e séries."),
    ("SteamGridDB", "API, termos próprios", "Capas de jogos."),
]

AVISO_GPL = (
    "Este programa é software livre: você pode redistribuí-lo e/ou modificá-lo "
    "sob os termos da Licença Pública Geral GNU, versão 3 ou (a seu critério) "
    "qualquer versão posterior.\n\n"
    "Se distribuir uma versão modificada, precisa distribuir o código dela "
    "também.\n\n"
    "Ele vem SEM NENHUMA GARANTIA, na medida permitida por lei.")
