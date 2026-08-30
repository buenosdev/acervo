"""Achar no disco o arquivo que o app mesmo renomeou.

Este engano ja apareceu quatro vezes, sempre igual: alguma parte do app procura
o arquivo pelo nome que consta no `.torrent`, e depois da organizacao esse nome
nao existe mais em lugar nenhum.

  1. a conciliacao do disco — a obra inteira virava "órfã";
  2. o plano de organizacao — todo movimento saia como "PULADO (sumiu)";
  3. o botao de reproduzir um episodio — "Não achei ... no disco";
  4. apagar — o cliente apagava a pasta antiga, vazia, e o filme ficava.

Todas as quatro passam por `library.mapear_arquivos`. Este teste cobra as
propriedades que ela precisa ter, com nomes de release de verdade.

    python -m testes.casos_achar
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import library                                # noqa: E402

MARCADOR = re.compile(r"[Ss](\d{1,2})[ ._-]?[Ee](\d{1,3})")


def _episodio(nome: str):
    m = MARCADOR.search(nome)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _montar(pasta: Path, arquivos: dict[str, int]) -> None:
    for nome, tamanho in arquivos.items():
        alvo = pasta / nome
        alvo.parent.mkdir(parents=True, exist_ok=True)
        with alvo.open("wb") as f:
            f.write(b"\0" * tamanho)


def _linhas(nomes_e_tamanhos: dict[str, int]) -> list[dict]:
    return [{"caminho": n, "tamanho": t, "tipo": "midia"}
            for n, t in nomes_e_tamanhos.items()]


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    falhas = 0
    raiz = Path(tempfile.mkdtemp(prefix="acervo-achar-"))

    # 1. nome intacto: o caminho mais simples continua funcionando.
    a = raiz / "intacto"
    no_torrent = {"Filme.2024.1080p.WEB-DL.mkv": 4096}
    _montar(a, no_torrent)
    mapa = library.mapear_arquivos(a, _linhas(no_torrent))
    if len(mapa) == 1:
        print("OK     nome igual ao do torrent")
    else:
        print("FALHA  não achou o arquivo com o nome original")
        falhas += 1

    # 2. renomeado pela organizacao: so o tamanho sobrevive.
    b = raiz / "renomeado"
    _montar(b, {"Filme (2024) [1080P DUAL].mkv": 4096})
    mapa = library.mapear_arquivos(b, _linhas(no_torrent))
    if len(mapa) == 1:
        print("OK     renomeado — casou pelo tamanho")
    else:
        print("FALHA  arquivo renomeado ficou invisível")
        falhas += 1

    # 3. serie renomeada com episodios DO MESMO TAMANHO. So o tamanho nao
    #    resolve, e casar errado aqui faz o app abrir o episodio errado calado.
    c = raiz / "serie"
    do_torrent = {f"Serie.S01E{n:02d}.1080p.WEB-DL.mkv": 8192 for n in range(1, 6)}
    _montar(c, {f"Serie - S01E{n:02d} [1080P].mkv": 8192 for n in range(1, 6)})
    mapa = library.mapear_arquivos(c, _linhas(do_torrent))
    trocados = [k for k, v in mapa.items() if _episodio(k) != _episodio(v.name)]
    if len(mapa) == 5 and not trocados:
        print("OK     série renomeada, 5 episódios do mesmo tamanho, sem troca")
    else:
        print(f"FALHA  {len(mapa)}/5 casados, {len(trocados)} episódio(s) trocados "
              f"— o app abriria o episódio errado")
        falhas += 1

    # 4. arquivo que nao esta no disco nao pode ser inventado.
    d = raiz / "faltando"
    _montar(d, {"Serie - S01E01 [1080P].mkv": 8192})
    mapa = library.mapear_arquivos(d, _linhas(do_torrent))
    if len(mapa) == 1:
        print("OK     só casa o que existe; não inventa o que falta")
    else:
        print(f"FALHA  casou {len(mapa)} com só 1 arquivo no disco")
        falhas += 1

    import shutil
    shutil.rmtree(raiz, ignore_errors=True)

    if falhas:
        print(f"\n{falhas} falha(s).")
        return 1
    print("\nOK: o app acha o arquivo mesmo depois de renomear.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
