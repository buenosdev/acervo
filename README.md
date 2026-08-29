# Acervo

[![Licença: GPL-3.0](https://img.shields.io/badge/licen%C3%A7a-GPL--3.0--or--later-blue)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![Qt: PySide6](https://img.shields.io/badge/interface-PySide6%20(Qt)-41cd52)](https://doc.qt.io/qtforpython/)

**Software livre**, sob a [GPL-3.0-or-later](LICENSE). O código é aberto, pode
ser usado, estudado, modificado e redistribuído — e quem distribuir uma versão
modificada precisa abrir o código dela também. Contribuições são bem-vindas:
veja [Como contribuir](#como-contribuir).

Aplicativo de desktop para Windows que transforma seus arquivos `.torrent` num
catálogo com capas. O `.torrent` é a biblioteca permanente; o arquivo de vídeo é
cache que você baixa quando quer e devolve quando terminar.

No acervo em que foi desenvolvido: **1,24 TiB de conteúdo indexado por 14,4 MiB
de `.torrent`** — proporção de 1 : 90.000. O disco tinha 1,22 TiB livres, ou
seja, a biblioteca inteira não caberia. É essa a ideia.

## Como abrir

Dê dois cliques em **`Acervo.exe`**.

É um programa de verdade: janela nativa em Qt, sem servidor, sem porta de rede,
sem navegador envolvido. Fechar a janela encerra o programa.

Na primeira vez ele pergunta onde ficam seus arquivos `.torrent` e já lê o
índice ao salvar. Todo o resto — qBittorrent, chaves de capas, travas de
segurança — se configura dentro do app, em **Configurações**.

Rodando pelo código-fonte:

```bash
python acervo.py
```

## O que ele faz

**Catálogo.** Lê seus `.torrent`, entende o nome do release (título, ano,
temporada, episódio, qualidade, idioma) e monta a grade com capas do TMDB.

**Sabe o que está no disco.** Cruza o índice com a pasta da mídia e marca cada
obra como *no disco*, *pela metade* ou *só no índice*. Também aponta as pastas
**órfãs** — mídia sem nenhum `.torrent` apontando para ela, as únicas onde
apagar é irreversível.

**Baixa organizando.** Ao clicar em Baixar, o app:

1. adiciona o torrent **pausado**, para ajustar antes de começar;
2. **injeta trackers públicos** — 90% dos torrents de acervos antigos não têm
   tracker nenhum e dependem só de DHT, e é isso que faz o download demorar a
   engatar. Nunca em torrent privado;
3. **desmarca a propaganda** — os `.url`, os `ACESSE O OFICIAL....mp4` e os PNGs
   de anúncio que os sites embutem. Em jogo nada é desmarcado: toda parte `.rar`
   é obrigatória;
4. inicia.

**Devolve o espaço.** Depois de assistir, um botão apaga a mídia e mantém o
`.torrent`. A biblioteca continua inteira no catálogo, ocupando kilobytes.

## Capas

Toda obra tem capa — a grade nunca fica com buraco.

1. **Automática.** TMDB para filmes e séries, SteamGridDB para jogos. Quando o
   nome do arquivo não bate com o oficial, o app tenta variações sozinho: sem o
   subtítulo depois do traço, sem o número no fim, sem o artigo inicial. Se o
   tipo tiver sido adivinhado errado, tenta o outro lado.
2. **Gerada.** O que sobrar ganha uma capa com o título, em cor derivada do
   próprio nome — a mesma obra tem sempre a mesma cor.
3. **Manual.** Abra a obra, seção **Capa**: procure por outro nome e clique na
   miniatura certa, ou escolha uma imagem do seu computador.

## Duplicatas

Repetição aparece em três níveis, e cada um é tratado conforme a certeza:

| Nível | O que é | O que o app faz |
|---|---|---|
| Mesmo infohash | o mesmo arquivo em pastas diferentes | junta sozinho, sem perguntar |
| Mesmo `tmdb_id` | títulos diferentes, obra confirmada igual | **Juntar as confirmadas**, um clique |
| Títulos parecidos | só um palpite | sugestão; você escolhe qual fica |

Em **Configurações → Duplicatas**. Juntar nunca apaga `.torrent` nem mídia: move
os releases para uma obra só e fica com o melhor de cada uma (capa real ganha de
capa gerada, sinopse preenchida ganha de vazia).

Se as duas obras já foram identificadas no TMDB e deram IDs diferentes, o app
não as sugere — é o que separa "Todo Mundo em Pânico" de "Todo Mundo em
Pânico 2".

## A trava que importa

Apagar a mídia e guardar só o `.torrent` só é reversível **enquanto houver
seeders**. Por isso **Liberar espaço** não é um botão comum: ele só funciona se
a checagem de seeders tiver passado, for recente (14 dias por padrão) e o item
não estiver protegido. Sem isso ele recusa — mesmo com confirmação.

A checagem usa scrape UDP nos trackers e, opcionalmente, o DHT do próprio
qBittorrent para os torrents sem tracker.

## Acessibilidade

- **Teclado em tudo.** `Tab` navega, `Enter` abre, `Esc` fecha. Atalhos:
  `Ctrl+L` ou `/` para a busca, `F5` relê o índice, `Ctrl+,` abre configurações,
  `Ctrl+Q` sai.
- **Leitores de tela.** Qt expõe a árvore de acessibilidade nativa do Windows
  (UI Automation). Cada capa é um botão com nome e descrição — o Narrador
  anuncia "A Casa do Dragão, Série, 2022, só no índice, 7.7 GB".
- **Três temas**: escuro, claro e alto contraste.
- **Três tamanhos de texto**: normal, +15% e +32%, aplicados à interface inteira.
- **Nada depende só de cor**: todo indicador colorido vem com texto junto.
- Todo contraste de texto passa em WCAG AA. O tom de cinza do mock original
  (#3f3f46 sobre fundo escuro) dá 1,9:1, muito abaixo do mínimo de 4,5:1 — aqui
  ele ficou só para bordas, e o texto usa um tom que mede 5,4:1.
- **Nada trava a janela**: varredura, checagem de seeders e busca de capas
  rodam fora da linha da interface.

## Motor de download

O catálogo, as capas, as duplicatas, a organização e o liberar espaço funcionam
**sem nenhum cliente instalado**. Só o botão *Baixar* precisa de um motor — e há
três, com detecção automática em **Configurações → Torrent**.

| Motor | Instalar? | Semeia depois de concluir | Renomeia sem quebrar o seeding |
|---|---|---|---|
| **qBittorrent** | sim | sim | sim |
| **uTorrent** | provavelmente já tem | sim | não — a organização move no disco |
| **aria2** | não, o app baixa | só enquanto o app estiver aberto | não |

A ordem de preferência não é arbitrária: o qBittorrent vem primeiro porque é o
único que semeia direito depois de concluir — e este projeto inteiro depende de
haver quem semeie, senão apagar a mídia deixa de ser reversível.

**qBittorrent** — Ferramentas → Opções → Web UI: marque “Servidor Web UI”,
porta `8080`, e “Ignorar autenticação para clientes no localhost”.

**uTorrent** — Opções → Preferências → Interface Web: marque “Ativar Interface
Web” e defina usuário e senha (o uTorrent exige os dois). A API dele nunca foi
documentada oficialmente, então pode mudar sem aviso — o app avisa em vez de
falhar calado.

**aria2** — clique em **Baixar o aria2** na mesma tela. São ~5 MB do projeto
oficial no GitHub; o app mostra origem e destino antes de baixar e guarda o
`aria2c.exe` ao lado dos dados. Não precisa instalar nada.

O passo a passo também está dentro do app, e o botão **Testar** diagnostica os
três de uma vez.

## Chaves de API (opcionais e gratuitas)

| Serviço | Para quê | Onde pegar |
|---|---|---|
| TMDB | capa, sinopse em português e nota de filmes e séries | themoviedb.org → Configurações → API → **Developer** → copie a **“API Key (v3 auth)”**, a curta de 32 caracteres |
| SteamGridDB | capa de jogos | steamgriddb.com (login pela Steam) → Preferences → API |

Cole em **Configurações → Capas**, teste ali mesmo e clique em **Buscar capas
que faltam**. As imagens ficam em `dados/posters/`, então depois funciona
offline.

O SteamGridDB fica atrás do Cloudflare, que recusa o `User-Agent` padrão do
Python com erro 1010 — o app manda um cabeçalho normal. Se aparecer 403, é isso
e não a chave: costuma passar em alguns minutos.

## Como contribuir

O projeto é aberto e as contribuições passam pelo GitHub:

1. abra uma *issue* descrevendo o problema ou a ideia — inclusive "não entendi
   isto aqui", que costuma apontar um defeito de interface;
2. para mudar código, faça um *fork*, trabalhe num ramo e abra um *pull
   request* descrevendo **o problema que a mudança resolve**, não só o que ela
   faz;
3. rode a bateria antes de enviar (veja
   [Ferramentas de linha de comando](#ferramentas-de-linha-de-comando)). Um
   *pull request* que quebra um teste existente precisa explicar por quê;
4. defeito com causa identificada vira teste. Boa parte da suíte nasceu assim —
   `casos_pintura` existe porque a rolagem engasgava, `casos_utorrent` porque
   escrever na configuração de outro programa é arriscado.

Ao contribuir, você concorda em licenciar sua contribuição sob a GPL-3.0-or-later,
como o resto do projeto.

## Licença

Copyright (C) 2026 Davi Bueno (buenosdev)

Este programa é software livre: você pode redistribuí-lo e/ou modificá-lo sob os
termos da **Licença Pública Geral GNU**, versão 3 ou (a seu critério) qualquer
versão posterior. Ele é distribuído na esperança de ser útil, mas **sem nenhuma
garantia**. O texto completo está em [LICENSE](LICENSE).

Em resumo, sem valor jurídico: use, estude, modifique e compartilhe à vontade;
se distribuir uma versão modificada, distribua também o código dela.

### Software de terceiros

| Projeto | Licença | Como é usado |
|---|---|---|
| [PySide6 / Qt](https://doc.qt.io/qtforpython/) | LGPL-3.0 | Interface. Vinculado dinamicamente; o executável é gerado a partir deste código-fonte, que fica disponível aqui — o que satisfaz o direito de relinkar. |
| [aria2](https://aria2.github.io/) | GPL-2.0-or-later | Motor de download padrão. **Não é redistribuído**: o app baixa o binário oficial do GitHub do projeto, com sua confirmação. |
| [TMDB](https://www.themoviedb.org/) | API, termos próprios | Capas, sinopses e notas de filmes e séries. |
| [SteamGridDB](https://www.steamgriddb.com/) | API, termos próprios | Capas de jogos. |

> Este produto usa a API do TMDB, mas **não é endossado nem certificado pelo
> TMDB**. *This product uses the TMDB API but is not endorsed or certified by
> TMDB.*

## O que fica fora do repositório

O `.gitignore` já mantém fora do repositório:

- **`config.toml`** — suas chaves de API e os caminhos da sua máquina;
- **`dados/`** — banco e capas baixadas;
- **`dist/`, `build/`** — o executável;
- **`_web_antigo/`** — a interface web anterior, guardada fora do caminho;
- **`config.toml.bak`** e **`aria2-rpc.txt`** — a cópia de segurança da
  configuração (com as mesmas chaves) e o segredo do RPC do aria2.

Quem clonar recebe `config.exemplo.toml`, com caminhos genéricos e chaves
vazias — e configura tudo pelo próprio app na primeira abertura.

## Gerando o executável

```bash
python -m pip install PySide6-Essentials pyinstaller
```
```bash
python -m ferramentas.build_exe
```

Sai em `dist/Acervo.exe` — arquivo único de ~40 MB, sem console, com ícone
próprio. O ícone é gerado por código, sem editor de imagem:

```bash
python -m ferramentas.gerar_icone
```

## Ferramentas de linha de comando

Tudo isto existe na interface, mas os relatórios completos saem melhor no
terminal.

```bash
python -m ferramentas.varredura      # relê os .torrent do índice
```
```bash
python -m ferramentas.biblioteca     # cruza o índice com o que está no disco
```
```bash
python -m ferramentas.faxina         # duplicatas, corrompidos e órfãos
```
```bash
python -m ferramentas.saude          # quantos seeders cada torrent ainda tem
```
```bash
python -m ferramentas.organizar      # prévia da renomeação padrão Jellyfin
```
```bash
python -m ferramentas.metadados      # busca capas e sinopses
```
```bash
python -m testes.casos_release       # 46 testes do parser de nomes
python -m testes.casos_layout        # cartão estável em 4 tamanhos x 5 janelas
python -m testes.casos_pintura       # orçamento de pintura da grade (1 quadro)
python -m testes.casos_guia          # guia: cartão cabe e não cobre o alvo
python -m testes.casos_utorrent      # mexer no settings.dat do uTorrent é seguro
python -m testes.casos_estresse      # 400 tarefas em rajada + navegação rápida
```

Nenhuma delas apaga arquivo. As duas que mexem no disco — `faxina --resgatar` e
`organizar --aplicar` — só movem, e pedem confirmação antes.

## Organização da biblioteca

Nomes no padrão que Jellyfin, Plex e Kodi leem sem configuração:

```
Filmes/Sisu (2022)/Sisu (2022) [1080P DUAL].mkv
Series/The Boys/Season 04/The Boys - S04E01 [1080P DUAL].mkv
Jogos/Hollow Knight/
```

Para o que o qBittorrent baixou, a organização é feita pela API dele
(`renameFile` / `setLocation`), não movendo arquivo por fora — assim o seeding
continua, não há cópia duplicada ocupando disco, e apagar devolve o espaço na
hora.

## Estrutura

```
acervo.py             ponto de entrada do aplicativo

ui/janela.py          janela principal: lateral, topo, grade
ui/painel_item.py     detalhes da obra: releases, capa, ações
ui/dialogo_config.py  configurações em seis abas
ui/widgets.py         cartão de capa, etiquetas, avisos
ui/tema.py            paletas e folha de estilo
ui/tarefas.py         trabalho pesado fora da linha da interface

core/bencode.py       lê .torrent, calcula infohash
core/release.py       parser de nome de release, afinado para releases BR
core/scanner.py       varre o índice e popula o banco
core/library.py       reconcilia índice x disco
core/consultas.py     consultas do catálogo
core/motores/         qBittorrent, uTorrent e aria2 atrás de uma interface só
core/downloads.py     o fluxo de baixar (trackers, propaganda, início)
core/importar.py      adicionar .torrent, recusando duplicata na entrada
core/health.py        seeders: scrape UDP e DHT
core/espaco.py        apaga mídia mantendo o .torrent
core/organizer.py     nomes padrão Jellyfin
core/metadata.py      TMDB e SteamGridDB
core/capas.py         capa gerada, troca manual
core/duplicatas.py    encontra e junta obras repetidas
core/config.py        lê e grava o config.toml
core/ajustes.py       configuração pela interface: validar, testar, salvar
core/db.py            schema SQLite
```

Única dependência em tempo de execução: **PySide6** (Qt). Todo o resto é
biblioteca padrão do Python. Empacotado no `.exe`, o usuário final não instala
nada.
