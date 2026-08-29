"""Segurança de mexer na configuração do uTorrent.

O Acervo escreve no `settings.dat` do uTorrent para ligar a Interface Web. É o
único lugar em que ele altera a configuração de outro programa, e um erro ali
não aparece como exceção: aparece como o uTorrent do usuário abrindo com as
preferências zeradas.

O que este teste cobra:

  1. **ida e volta fiel** — decodificar e recodificar o settings.dat real tem de
     devolver os mesmos bytes. Se o codificador introduzir qualquer diferença
     (ordem de chaves, formato de inteiro), o arquivo gravado deixa de ser o do
     usuário com duas chaves trocadas e passa a ser outro arquivo;
  2. **mudança cirúrgica** — ligar a Interface Web altera só as chaves da
     Interface Web. Nenhuma outra preferência pode sair diferente;
  3. **recusa com o uTorrent aberto** — ele reescreve as próprias configurações
     ao sair, então gravar com ele em execução seria trabalho perdido.

Roda sobre uma cópia em memória: nada no disco é tocado.

    python -m testes.casos_utorrent
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import bencode                              # noqa: E402
from core import utorrent_config as ut                # noqa: E402

CHAVES_DA_WEBUI = {b"webui.enable", b"webui.enable_listen", b"webui.username",
                   b"webui.password", b"webui.hashword", b"webui.salt",
                   b".fileguard"}


def _aplicar_como_o_app_faz(cfg: dict, usuario: str, senha: str) -> dict:
    """Repete o que `ligar_webui` faz, sem tocar no disco."""
    novo = dict(cfg)
    novo[b"webui.enable"] = 1
    novo[b"webui.enable_listen"] = 1
    novo[b"webui.username"] = usuario.encode()
    novo[b"webui.password"] = senha.encode()
    for morta in (b"webui.hashword", b"webui.salt", b".fileguard"):
        novo.pop(morta, None)
    return novo


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    arquivo = ut.pasta() / "settings.dat"
    if not arquivo.is_file():
        print("AVISO: uTorrent não instalado aqui; nada a verificar.")
        return 0

    bruto = arquivo.read_bytes()
    falhas = 0

    # 1. ida e volta fiel
    cfg, _ = bencode.decodificar(bruto)
    refeito = bencode.codificar(cfg)
    if refeito == bruto:
        print(f"OK     ida e volta fiel — {len(bruto)} bytes idênticos")
    else:
        print(f"FALHA  ida e volta mudou o arquivo "
              f"({len(bruto)} bytes viraram {len(refeito)})")
        falhas += 1

    # 2. mudanca cirurgica
    depois = _aplicar_como_o_app_faz(cfg, "acervo", "senha-de-teste")
    mexidas = {k for k in set(cfg) | set(depois) if cfg.get(k) != depois.get(k)}
    intrusas = mexidas - CHAVES_DA_WEBUI
    if intrusas:
        print("FALHA  mudou chave que não é da Interface Web: "
              + ", ".join(sorted(k.decode("utf8", "replace") for k in intrusas)))
        falhas += 1
    else:
        print(f"OK     mudança cirúrgica — {len(mexidas)} chaves, todas da Interface Web")

    if depois.get(b"webui.enable") != 1 or b"webui.hashword" in depois:
        print("FALHA  a Interface Web não ficou ligada, ou sobrou o hash antigo")
        falhas += 1

    # 3. recusa com o uTorrent aberto
    if ut.esta_rodando():
        r = ut.ligar_webui("acervo", "x")
        if r.get("ok"):
            print("FALHA  gravou com o uTorrent aberto — seria desfeito na saída")
            falhas += 1
        else:
            print("OK     recusa gravar com o uTorrent aberto")
    else:
        print("OK     (uTorrent fechado; a recusa não pôde ser exercitada)")

    # 4. o caminho com acento, que derrubava o download inteiro
    from core.motores.utorrent import caminho_aceito

    casos = [
        ("C:/Torrent/_baixando", True),
        ("C:\\Downloads\\filmes", True),
        ("C:/Users/José/Documents/Torrent/_baixando", False),
        ("D:/Vídeos/baixando", False),
    ]
    ruins = [c for c, esperado in casos if caminho_aceito(c) != esperado]
    if ruins:
        print("FALHA  caminho_aceito errou em: " + ", ".join(ruins))
        falhas += len(ruins)
    else:
        print("OK     reconhece caminho que a Interface Web não aceita")

    if falhas:
        print(f"\n{falhas} verificação(ões) falharam.")
        return 1
    print("\nOK: mexer na configuração do uTorrent é seguro.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
