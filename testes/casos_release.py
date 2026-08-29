"""Casos de regressao do parser, todos tirados de nomes reais do acervo.

    python -m testes.casos_release

Cada caso que quebrar imprime o esperado e o obtido. Ao adicionar uma regra nova
em core/release.py, adicione aqui o nome que motivou a regra.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.release import (FILME, JOGO, SERIE, analisar, classificar_arquivo,  # noqa: E402
                          maior_e_video)

# (nome_do_arquivo, dica_de_tipo, {campo: valor_esperado})
CASOS = [
    # ---------------------------------------------------------------- filmes
    ("Sisu 2022 1080p BluRay DUAL 5.1.1.torrent", FILME,
     dict(titulo="Sisu", ano=2022, qualidade="1080P", fonte="BluRay", idioma="DUAL")),
    # O "4" faz parte do titulo; a versao de jogo nao pode comer "4.2024".
    ("Meu.Malvado.Favorito.4.2024.1080p.WEB-DL.DUAL.5.1.1.torrent", FILME,
     dict(titulo="Meu Malvado Favorito 4", ano=2024)),
    # "2.0" e titulo, nao layout de audio.
    ("M3GAN.2.0.2025.WEB-DL.FULLHD.1080p.x264.DUAL.5.1-SF.1.torrent", FILME,
     dict(titulo="M3GAN 2.0", ano=2025)),
    ("Sonic 3 - O Filme 2024 WEB-DL 2160p x265 DV HDR DUAL 5.1.1.torrent", FILME,
     dict(titulo="Sonic 3 - O Filme", ano=2024, qualidade="2160P", hdr=["DV", "HDR"])),
    # Sem nenhum marcador tecnico: o titulo e o nome inteiro.
    ("Efeito Borboleta - Trilogia.1.torrent", FILME,
     dict(titulo="Efeito Borboleta - Trilogia", ano=None)),
    ("[ACESSE COMANDOTORRENTS.COM] Todo Dia (2018) [BluRay] [1080p] [DUAL].1.torrent", FILME,
     dict(titulo="Todo Dia", ano=2018)),
    ("Gênio Indomável [1997]-BluRay 720p Dual Áudio.1.torrent", FILME,
     dict(titulo="Gênio Indomável", ano=1997)),
    ("Questao de Tempo (2013) - wolverdonfilmes.com.1.torrent", FILME,
     dict(titulo="Questao de Tempo", ano=2013)),
    ("COMANDO.TO - A Serie Divergente 2014-2015-2016 [1080p] [DUAL].1.torrent", FILME,
     dict(titulo="A Serie Divergente", ano=2014)),
    ("The.Legend.of.Hei.II.2025.1080p.USA.BluRay.REMUX.DTS-HD.MA.5.1.AVC-ZigZag.mkv.1.torrent",
     FILME, dict(titulo="The Legend of Hei II", ano=2025, fonte="BluRay")),
    ("Boa.Sorte.Divirta-se.Não.Morra.2025.WEB-DL.1080p.x264.DUAL.5.1-STARCKFILMES.1.torrent",
     FILME, dict(titulo="Boa Sorte Divirta-se Não Morra", ano=2025)),
    ("Todo Mundo Em Panico 5 DVDRip Rmvb Dublado.rmvb.1.torrent", FILME,
     dict(titulo="Todo Mundo Em Panico 5", ano=None, fonte="DVDRip")),

    # ---------------------------------------------------------------- series
    ("Gen.V.S01E01-03.1080p.WEB-DL.DUAL.5.1.1.torrent", SERIE,
     dict(titulo="Gen V", temporada=1, episodios=[1, 2, 3])),
    ("Gen.V.S02E01-02-03.WEB-DL.1080p.x264.DUAL.5.1-SF.1.torrent", SERIE,
     dict(titulo="Gen V", temporada=2, episodios=[1, 2, 3])),
    # O ano solto depois do episodio nao pode virar episodio 202.
    ("The Boys S03E06 2022 WEB-DL 1080p DUAL 5.1.1.torrent", SERIE,
     dict(titulo="The Boys", temporada=3, episodios=[6], ano=2022)),
    ("The.Boys.S02.1080p.AMZN.WEB-DL.DDP5.1.H.264-PiA.1.torrent", SERIE,
     dict(titulo="The Boys", temporada=2, episodios=[], temporada_completa=True)),
    ("Marvel's.Agent.Carter.1ªTemporada.720p.WEB-DL.x.264.Dual-BLUDV.1.torrent", SERIE,
     dict(titulo="Marvel's Agent Carter", temporada=1, temporada_completa=True)),
    ("Agente Carter da Marvel 2016 – 2ª Temporada Completa (1080p) WWW.BLUDV.COM.1.torrent",
     SERIE, dict(titulo="Agente Carter da Marvel", temporada=2, ano=2016,
                 temporada_completa=True)),
    ("Heroes 1º à 4º temporada dual audio pt-BR en-US (Com Legendas SRT pt-BR)", SERIE,
     dict(titulo="Heroes", temporada=1, temporada_completa=True)),
    ("Rick.e.Morty.S09E10.WEB-DL.1080p.x264.DUAL.5.1-STARCKFILMES.1.torrent", SERIE,
     dict(titulo="Rick e Morty", temporada=9, episodios=[10])),
    ("Knuckles S01 2024 WEB-DL 1080p x264 DUAL 2.0.torrent", SERIE,
     dict(titulo="Knuckles", temporada=1, ano=2024, temporada_completa=True)),
    ("[Avalon] Steins;Gate (BDRip 1080p 10bit x264 FLAC) [rich_jc].1.torrent", SERIE,
     dict(titulo="Steins;Gate", fonte="BDRip")),
    ("Z.Nation.1ª.Temporada.2015.720p.Dublado-WOLVERDONFILMES.COM.torrent", SERIE,
     dict(titulo="Z Nation", temporada=1, idioma="DUBLADO")),

    # ----------------------------------------------------------------- jogos
    ("Legend of Zelda, The - Breath of the Wild (World) (En,Ja,Fr,De,Es,It,Nl,Ru) (Rev 3).torrent",
     JOGO, dict(titulo="The Legend of Zelda - Breath of the Wild")),
    # "-Villains" e parte do titulo; "-EMPRESS" e grupo.
    ("LEGO DC Super-Villains [FitGirl Repack].1.torrent", JOGO,
     dict(titulo="LEGO DC Super-Villains")),
    ("Watchs.Dogs.Legion-EMPRESS.1.torrent", JOGO, dict(titulo="Watchs Dogs Legion")),
    # ".16" no fim e parte da versao, nao o sufixo ".1" de copia do navegador.
    ("Project.Zomboid.v41.78.16.rar.torrent", JOGO, dict(titulo="Project Zomboid")),
    ("Gang.Beasts.v1.21.922.rar.torrent", JOGO, dict(titulo="Gang Beasts")),
    ("Among.Us.v2020.9.9s.rar.1.torrent", JOGO, dict(titulo="Among Us")),
    ("[R.G. Mechanics] Legendary.torrent", JOGO, dict(titulo="Legendary")),
    ("need-for-speed-underground.torrent", JOGO, dict(titulo="Need For Speed Underground")),
    ("Bomb_rush_cyberfunk_1.0.20385_(70384)_win_gog.1.torrent", JOGO,
     dict(titulo="Bomb rush cyberfunk")),
    ("Nidhogg.v1.004-ALiAS.torrent", JOGO, dict(titulo="Nidhogg")),
    ("FIFA 19 [FitGirl Repack].torrent", JOGO, dict(titulo="FIFA 19")),
    ("Need for Speed Underground (2003) PC [РУС] Repack by MOP030B.torrent", JOGO,
     dict(titulo="Need for Speed Underground", ano=2003)),
    # "2.0.2025" tem tres componentes e passava por numero de versao de jogo: o
    # filme ia para a estante de jogos e nunca achava capa, porque capa de jogo
    # e procurada em outra base. Numero terminado em ano e ano, nao versao.
    ("M3GAN.2.0.2025.WEB-DL.1080p.x264.DUAL.5.1-SF.torrent", FILME,
     dict(titulo="M3GAN 2.0", ano=2025)),
    # Versao de verdade continua sendo versao.
    ("The.Sims.4.v1.105.332.1030.torrent", JOGO, dict(titulo="The Sims 4")),
]

# (arquivos_do_torrent, o_maior_e_video?) — a pista que decide jogo x filme.
CASOS_CONTEUDO = [
    ([("M3GAN.2.0.2025.WEB-DL.mkv", 2_720_624_041), ("GRUPO TELEGRAM.url", 115)], True),
    ([("setup.part1.rar", 3_000_000_000), ("leiame.txt", 400)], False),
    ([("jogo.iso", 8_000_000_000)], False),
    ([("S01E01.mkv", 900_000_000), ("S01E02.mkv", 910_000_000)], True),
]

# (caminho_dentro_do_torrent, tipo_do_item, tamanho, classificacao_esperada)
CASOS_ARQUIVO = [
    ("Sisu 2022 1080p BluRay DUAL 5.1.mkv", FILME, 2_635_463_086, "midia"),
    # O filme de verdade carrega o nome do site: NAO pode virar lixo.
    ("A.Presenca.2021.1080p.BluRay.DUAL.COMANDO.TO.mkv", FILME, 2_000_000_000, "midia"),
    ("Heroes.Reborn.S01E01.WEB-RMZ.720p.DUAL.DUBLASERIES.TV.mkv", SERIE, 900_000_000, "midia"),
    ("ACESSE O OFICIAL - TorrentDosFilmes.SE.mp4", FILME, 2_400_740, "lixo"),
    ("BAIXAR OUTROS FILMES.url", FILME, 210, "lixo"),
    ("[-LEIA-ME-].txt", SERIE, 900, "lixo"),
    ("Acesse -StarckFilmes.png", FILME, 1_772_000, "lixo"),
    # Propaganda disfarcada de episodio: so o tamanho denuncia.
    ("Gen.V.S01E00.1080p.WEB-DL.DUAL.5.1.mp4", SERIE, 2_400_000, "lixo"),
    ("Sisu.pt-BR.srt", FILME, 52_000, "legenda"),
    # Em jogo nada e descartado: partes .rar sao todas obrigatorias.
    ("Dishonored/setup-1.bin", JOGO, 4_000_000_000, "arquivo_jogo"),
    ("Blasphemous/leia-me.txt", JOGO, 500, "arquivo_jogo"),
]


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    falhas = 0
    for nome, dica, esperado in CASOS:
        r = analisar(nome, dica)
        for campo, valor in esperado.items():
            obtido = getattr(r, campo)
            if obtido != valor:
                falhas += 1
                print(f"FALHA  {nome}\n       campo '{campo}': esperado {valor!r}, "
                      f"obtido {obtido!r}")

    for caminho, tipo, tamanho, esperado in CASOS_ARQUIVO:
        obtido = classificar_arquivo(caminho, tipo, tamanho)
        if obtido != esperado:
            falhas += 1
            print(f"FALHA  {caminho}\n       esperado {esperado!r}, obtido {obtido!r}")

    for arquivos, esperado in CASOS_CONTEUDO:
        obtido = maior_e_video(arquivos)
        if obtido != esperado:
            maior = max(arquivos, key=lambda a: a[1])[0]
            print(f"FALHA conteudo: maior arquivo {maior} -> "
                  f"video={obtido}, esperado {esperado}")
            falhas += 1

    total = len(CASOS) + len(CASOS_ARQUIVO) + len(CASOS_CONTEUDO)
    if falhas:
        print(f"\n{falhas} verificacao(oes) falharam em {total} casos.")
        return 1
    print(f"OK: {total} casos ({len(CASOS)} nomes + {len(CASOS_ARQUIVO)} arquivos"
          f" + {len(CASOS_CONTEUDO)} de conteudo).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
