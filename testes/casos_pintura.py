"""Orcamento de pintura da grade.

A rolagem pulava quadros porque o delegate reconstruia QFont, QFontMetrics e
QPainterPath a cada celula, a cada repintura, e ainda refazia a quebra de linha
do titulo. Com 155 obras na tela isso estourava o tempo de um quadro.

Agora fonte e medida nascem uma vez, o titulo quebrado fica guardado, e o
cartao inteiro e cacheado como pixmap: repintar so recoloca a imagem pronta.

Este teste fixa o orcamento. Se voltar a passar disso, a rolagem voltou a pular.

    python -m testes.casos_pintura
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect                      # noqa: E402
from PySide6.QtGui import QPainter, QPixmap           # noqa: E402
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem  # noqa: E402

from core import config, consultas, db                # noqa: E402
from ui import widgets                                # noqa: E402
from ui import tema                                   # noqa: E402
from ui.grade import DelegateCartao, ModeloObras      # noqa: E402

# Um quadro a 60 Hz tem 16,6 ms. Uma tela cheia mostra ~40 cartoes, entao o
# custo de pintar 40 precisa caber com folga nesse orcamento.
CARTOES_POR_TELA = 40
ORCAMENTO_MS = 16.0
REPINTURAS = 12


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    app = QApplication.instance() or QApplication([])
    cfg = config.carregar()
    con = db.conectar(cfg.banco)
    obras = consultas.listar(con)
    if not obras:
        print("AVISO: catálogo vazio, nada a medir.")
        return 0

    modelo = ModeloObras()
    modelo.definir(obras)
    delegate = DelegateCartao(Path(cfg.posters), tema.ESCURO, 1.0, 158, "grade")

    tela = QPixmap(1280, 800)
    opcao = QStyleOptionViewItem()

    def uma_tela() -> None:
        p = QPainter(tela)
        for i in range(min(CARTOES_POR_TELA, modelo.rowCount())):
            opcao.rect = QRect((i % 7) * 165, (i // 7) * 315, 158,
                               delegate.sizeHint(opcao, modelo.index(i, 0)).height())
            delegate.paint(p, opcao, modelo.index(i, 0))
        p.end()

    # A primeira passada pede as capas; a leitura acontece em segundo plano.
    # Esperar por ela mede o estado normal de uso, com a grade ja formada.
    uma_tela()
    widgets.carregador.esperar(8000)
    widgets.converter_prontas(limite=10_000)   # como a grade faz, fora da pintura
    uma_tela()                                 # enche o cache de cartoes

    inicio = time.perf_counter()
    for _ in range(REPINTURAS):
        uma_tela()
    media = (time.perf_counter() - inicio) * 1000 / REPINTURAS

    # Rolar e diferente de repintar: cada fila nova traz cartoes que nunca
    # foram desenhados. Era aqui que estava o engasgo de verdade — a capa era
    # lida e redimensionada dentro do `paint`, e uma fila nova custava ~63 ms,
    # quatro quadros. O teste anterior nao via isso porque media sempre os
    # mesmos cartoes, ja em cache.
    delegate._cache_cartao.clear()
    widgets.carregador.esperar(8000)
    widgets.converter_prontas(limite=10_000)
    por_fila = []
    for fila in range(min(20, (modelo.rowCount() + 6) // 7)):
        p = QPainter(tela)
        inicio = time.perf_counter()
        for i in range(fila * 7, min(fila * 7 + 7, modelo.rowCount())):
            opcao.rect = QRect((i % 7) * 165, 0, 158, 308)
            delegate.paint(p, opcao, modelo.index(i, 0))
        por_fila.append((time.perf_counter() - inicio) * 1000)
        p.end()
    por_fila.sort()
    mediana = por_fila[len(por_fila) // 2]
    pior_fila = por_fila[-1]
    print(f"rolar até uma fila nova: mediana {mediana:.2f} ms, "
          f"pior {pior_fila:.2f} ms")

    # A mediana e o que decide se a rolagem parece fluida: e o custo da fila
    # tipica. A pior fila ganha folga de proposito — sempre ha uma que paga o
    # aquecimento de fonte ou uma leva de conversoes — mas continua limitada,
    # senao o teste deixaria passar justamente o defeito que ele nasceu para
    # pegar: quando a capa era lida dentro da pintura, a MEDIA era 63 ms.
    if mediana > ORCAMENTO_MS:
        print("FALHA: a fila típica não cabe num quadro — o scroll vai engasgar.")
        print("       (a capa voltou a ser lida dentro da pintura?)")
        return 1
    if pior_fila > ORCAMENTO_MS * 2:
        print(f"FALHA: a pior fila levou {pior_fila:.0f} ms, mais que dois quadros.")
        return 1

    print(f"{len(obras)} obras no catálogo")
    print(f"repintar {CARTOES_POR_TELA} cartões: {media:.2f} ms "
          f"(orçamento {ORCAMENTO_MS:.0f} ms por quadro)")

    if media > ORCAMENTO_MS:
        print("FALHA: a pintura não cabe num quadro — a rolagem vai pular.")
        return 1

    # O cache não pode ficar mostrando a capa antiga: trocar uma capa precisa
    # aparecer na grade. É o outro lado da mesma moeda — sem isto, o ganho de
    # velocidade viraria o bug de "apliquei a capa e não mudou nada".
    obra = modelo.obra_em(modelo.index(0, 0))
    antes = delegate._cartao_estatico(obra)
    reusado = delegate._cartao_estatico(obra)
    widgets.limpar_cache_capas()
    depois = delegate._cartao_estatico(obra)

    if reusado is not antes:
        print("FALHA: o cartão não está sendo reaproveitado entre quadros.")
        return 1
    if depois is antes:
        print("FALHA: trocar a capa não invalidou o cartão em cache.")
        return 1
    print("cache: reaproveita entre quadros e invalida ao trocar a capa")
    print(f"\nOK: sobra {ORCAMENTO_MS - media:.1f} ms por quadro.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
