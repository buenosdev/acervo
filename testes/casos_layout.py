"""Regressao de layout.

O cartao ja colapsou para 100x30 em certas janelas, virando uma faixa fina que
engolia capa e titulo. Este teste mede a celula em varias larguras de janela e
em todos os tamanhos de capa: se voltar a depender do contexto, quebra aqui.

    python -m testes.casos_layout
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor            # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import config, consultas, db      # noqa: E402
from ui import tema                         # noqa: E402
from ui.grade import GradeObras             # noqa: E402
from ui.widgets import PROPORCAO_CAPA, TAMANHOS_CARTAO  # noqa: E402

JANELAS = [(1320, 840), (1366, 740), (980, 640), (1920, 1080), (1100, 700)]


def _luminancia(c: QColor) -> float:
    def canal(v: int) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return (0.2126 * canal(c.red()) + 0.7152 * canal(c.green())
            + 0.0722 * canal(c.blue()))


def _contraste(a: QColor, b: QColor) -> float:
    menor, maior = sorted((_luminancia(a), _luminancia(b)))
    return (maior + 0.05) / (menor + 0.05)


def _conferir_dialogos(app, cfg) -> int:
    """Os dialogos precisam ter o fundo do tema.

    A folha de estilo so pintava `QWidget#raiz`, entao todo QDialog ficava com o
    cinza padrao do Windows enquanto o texto seguia a cor do tema. No tema
    escuro isso dava claro sobre claro: o titulo media 1,1:1 de contraste, ou
    seja, invisivel. Aqui cada dialogo e desenhado nos tres temas e medido.
    """
    from core import players
    from ui.escolher_player import ContinuarDe, EscolherPlayer

    motor, _ = players.escolher(cfg)
    falhas = 0
    for nome, pal in (("escuro", tema.ESCURO), ("claro", tema.CLARO),
                      ("contraste", tema.CONTRASTE)):
        app.setStyleSheet(tema.folha(pal, 1.0))
        for rotulo, dialogo in (
                ("escolher player", EscolherPlayer("Obra", motor.nome, pal, 1.0)),
                ("continuar de", ContinuarDe("Obra", 754.0, 2600.0, pal, 1.0))):
            dialogo.adjustSize()
            dialogo.show()
            app.processEvents()
            img = dialogo.grab().toImage()
            fundo = QColor(img.pixel(4, 4))
            esperado = QColor(pal.fundo)
            faixa = [QColor(img.pixel(x, y)) for y in range(24, 46)
                     for x in range(22, min(img.width() - 2, 420), 3)]
            titulo = max(faixa, key=lambda c: _contraste(c, fundo))
            razao = _contraste(titulo, fundo)
            if fundo != esperado:
                print(f"FALHA  {rotulo} no tema {nome}: fundo {fundo.name()}, "
                      f"o tema pede {esperado.name()}")
                falhas += 1
            elif razao < 4.5:
                print(f"FALHA  {rotulo} no tema {nome}: título a {razao:.1f}:1 "
                      f"de contraste (mínimo 4,5:1)")
                falhas += 1
            else:
                print(f"OK     {rotulo:16} tema {nome:9} fundo do tema, "
                      f"título a {razao:4.1f}:1")
            dialogo.close()
            app.processEvents()
    return falhas


def _conferir_contadores(con, cfg) -> int:
    """A barra lateral promete um numero; a grade precisa entregar aquele numero.

    Os filtros de cima contam obras (tabela `itens`) e os de baixo contavam
    torrents (tabela `disco`), que sao unidades diferentes: "So no indice"
    dizia 203 e a grade abria com 138. Aqui cada contador e comparado com o
    tamanho da lista que o clique dele produz.
    """
    r = consultas.resumo(con, cfg)
    falhas = 0
    for estado, rotulo in (("completo", "No disco"), ("parcial", "Baixando"),
                           ("indice", "Só no índice")):
        promete = r["estados"].get(estado, {}).get("obras", 0)
        entrega = len(consultas.listar(con, estado=estado))
        if promete != entrega:
            print(f"FALHA  contador “{rotulo}” diz {promete}, a grade mostra "
                  f"{entrega}")
            falhas += 1
        else:
            print(f"OK     contador {rotulo:14} {promete:>4} = o que a grade mostra")

    soma_tipos = sum(r["por_tipo"].get(t, 0) for t in ("filme", "serie", "jogo"))
    if soma_tipos != r["itens"]:
        print(f"FALHA  filmes+séries+jogos = {soma_tipos}, mas “Tudo” diz "
              f"{r['itens']}")
        falhas += 1
    else:
        print(f"OK     contador {'Tudo':14} {r['itens']:>4} = filmes+séries+jogos")
    return falhas


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    app = QApplication.instance() or QApplication([])
    cfg = config.carregar()
    con = db.conectar(cfg.banco)
    obras = consultas.listar(con)[:40]
    if not obras:
        print("Catálogo vazio; rode a varredura antes.")
        return 1

    falhas = 0
    for tamanho, largura in TAMANHOS_CARTAO.items():
        g = GradeObras(cfg.posters, tema.ESCURO, 1.0, tamanho)
        g.definir_obras(obras)
        alturas = set()
        for larg, alt in JANELAS:
            g.resize(larg, alt)
            g.show()
            app.processEvents()
            tam = g.delegate.sizeHint(None, None)
            alturas.add((tam.width(), tam.height()))
        g.hide()

        esperado = (largura, int(largura * PROPORCAO_CAPA) + g.delegate.altura_texto)
        if len(alturas) != 1 or alturas.pop() != esperado:
            print(f"FALHA  tamanho {tamanho}: célula variou com a janela "
                  f"({alturas}), esperado {esperado}")
            falhas += 1
        else:
            print(f"OK     {tamanho:8} {esperado[0]}x{esperado[1]} "
                  f"— igual nas {len(JANELAS)} janelas")

    g = GradeObras(cfg.posters, tema.ESCURO, 1.0, "medio", "lista")
    g.definir_obras(obras)
    g.resize(900, 600)
    g.show()
    app.processEvents()
    altura_lista = g.delegate.sizeHint(None, None).height()
    g.hide()
    if altura_lista != g.delegate.altura_linha:
        print(f"FALHA  modo lista: altura {altura_lista}")
        falhas += 1
    else:
        print(f"OK     lista    altura fixa {altura_lista}")

    # A area de acao da tela da obra e remontada a cada tique do relogio. A
    # limpeza anterior descia um nivel so nos layouts aninhados, e os widgets
    # dois niveis abaixo — a barra de progresso, a porcentagem, a velocidade —
    # sobreviviam: ficavam desenhados no mesmo lugar, com os novos por cima.
    # Era o texto embaralhado e o botao Pausar sobre a barra.
    from PySide6.QtWidgets import QProgressBar, QPushButton    # noqa: PLC0415

    from ui.janela import Janela                               # noqa: PLC0415

    janela = Janela(cfg)
    janela.resize(1200, 860)
    janela.show()
    app.processEvents()
    janela.abrir_item(obras[0]["id"])
    app.processEvents()

    tela = janela.tela_item
    for i in range(6):
        tela.ativo = {"progresso": 0.1 + i * 0.1, "velocidade": 5_000_000,
                      "baixado": 10 ** 9, "tamanho": 10 ** 10, "eta": 600,
                      "pausado": False}
        tela._montar_acao()
        app.processEvents()

    barras = len(tela.caixa_acao.findChildren(QProgressBar))
    botoes = len(tela.caixa_acao.findChildren(QPushButton))
    if barras != 1 or botoes != 1:
        print(f"FALHA  ação remontada 6x deixou {barras} barras e {botoes} botões "
              f"vivos — eles se sobrepõem na tela")
        falhas += 1
    else:
        print("OK     ação  remontar 6x deixa 1 barra e 1 botão")
    janela.close()
    app.processEvents()

    falhas += _conferir_dialogos(app, cfg)
    falhas += _conferir_contadores(con, cfg)

    con.close()
    if falhas:
        print(f"\n{falhas} falha(s).")
        return 1
    print(f"\nOK: célula estável em {len(TAMANHOS_CARTAO)} tamanhos "
          f"x {len(JANELAS)} janelas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
