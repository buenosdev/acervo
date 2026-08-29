"""Gera o icone do aplicativo (.ico) sem depender de nada externo.

    python -m ferramentas.gerar_icone

Desenha em memoria com 4x de supersampling (para dar antialiasing), codifica
PNG com zlib e monta o container ICO com todos os tamanhos que o Windows usa.
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TAMANHOS = (16, 24, 32, 48, 64, 128, 256)
SUPER = 4  # amostras por eixo

FUNDO_TOPO = (23, 24, 32)
FUNDO_BASE = (10, 10, 14)
BORDA = (44, 46, 60)
LETRA = (232, 232, 236)
SETA = (77, 144, 255)


def _mistura(base, cor, alfa):
    return tuple(round(b + (c - b) * alfa) for b, c in zip(base, cor))


def _dentro_do_arredondado(x, y, lado, raio):
    if raio <= 0:
        return 0 <= x < lado and 0 <= y < lado
    cx = min(max(x, raio), lado - raio)
    cy = min(max(y, raio), lado - raio)
    return (x - cx) ** 2 + (y - cy) ** 2 <= raio * raio


def _dist_segmento(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return ((px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2) ** 0.5


def desenhar(lado: int) -> bytearray:
    """Devolve RGBA de `lado` x `lado`, renderizado com supersampling."""
    g = lado * SUPER
    u = g / 32.0                      # unidade: o desenho e pensado num grid 32x32
    raio = 7 * u

    # "A" do Acervo
    a_esq = (7.0 * u, 24.0 * u)
    a_topo = (13.2 * u, 8.0 * u)
    a_dir = (19.4 * u, 24.0 * u)
    a_barra_y = 19.0 * u
    a_barra = (9.9 * u, a_barra_y, 16.5 * u, a_barra_y)
    esp_letra = 1.45 * u

    # Seta de download
    seta_x = 24.2 * u
    circ_y, circ_r = 11.4 * u, 2.7 * u
    haste = (seta_x, 15.6 * u, seta_x, 22.4 * u)
    asa_e = (seta_x - 3.0 * u, 19.4 * u, seta_x, 22.4 * u)
    asa_d = (seta_x + 3.0 * u, 19.4 * u, seta_x, 22.4 * u)
    esp_seta = 1.15 * u

    acumulado = [[[0, 0, 0, 0] for _ in range(lado)] for _ in range(lado)]

    for sy in range(g):
        for sx in range(g):
            px, py = sx + 0.5, sy + 0.5
            if not _dentro_do_arredondado(px, py, g, raio):
                continue

            # Fundo em degrade vertical.
            t = py / g
            cor = list(_mistura(FUNDO_TOPO, FUNDO_BASE, t))
            alfa = 255

            # Borda interna sutil.
            if not _dentro_do_arredondado(px, py, g, raio) or \
               not _dentro_do_arredondado(px - 1.1 * u, py, g - 2.2 * u, raio):
                pass
            borda_d = min(px, py, g - px, g - py)
            if borda_d < 1.0 * u:
                cor = list(_mistura(cor, BORDA, 0.85))

            d_letra = min(
                _dist_segmento(px, py, *a_esq, *a_topo),
                _dist_segmento(px, py, *a_topo, *a_dir),
                _dist_segmento(px, py, *a_barra),
            )
            if d_letra < esp_letra:
                cor = list(LETRA)
            elif d_letra < esp_letra + 0.7 * u:
                cor = list(_mistura(cor, LETRA,
                                    1 - (d_letra - esp_letra) / (0.7 * u)))

            d_circ = abs(((px - seta_x) ** 2 + (py - circ_y) ** 2) ** 0.5)
            d_seta = min(
                _dist_segmento(px, py, *haste),
                _dist_segmento(px, py, *asa_e),
                _dist_segmento(px, py, *asa_d),
            )
            if d_circ < circ_r or d_seta < esp_seta:
                cor = list(SETA)
            elif d_circ < circ_r + 0.6 * u:
                cor = list(_mistura(cor, SETA, 1 - (d_circ - circ_r) / (0.6 * u)))
            elif d_seta < esp_seta + 0.6 * u:
                cor = list(_mistura(cor, SETA, 1 - (d_seta - esp_seta) / (0.6 * u)))

            alvo = acumulado[sy // SUPER][sx // SUPER]
            alvo[0] += cor[0]; alvo[1] += cor[1]; alvo[2] += cor[2]; alvo[3] += alfa

    total = SUPER * SUPER
    saida = bytearray()
    for linha in acumulado:
        for r, gg, b, a in linha:
            saida += bytes((r // total, gg // total, b // total, a // total))
    return saida


def png(rgba: bytes, lado: int) -> bytes:
    cru = bytearray()
    largura = lado * 4
    for y in range(lado):
        cru.append(0)  # filtro "none"
        cru += rgba[y * largura:(y + 1) * largura]

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        c = tipo + dados
        return struct.pack(">I", len(dados)) + c + struct.pack(">I", zlib.crc32(c))

    return (b"\x89PNG\r\n\x1a\n"
            + bloco(b"IHDR", struct.pack(">IIBBBBB", lado, lado, 8, 6, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(bytes(cru), 9))
            + bloco(b"IEND", b""))


def ico(imagens: list[tuple[int, bytes]]) -> bytes:
    cabecalho = struct.pack("<HHH", 0, 1, len(imagens))
    entradas, corpo = b"", b""
    deslocamento = 6 + 16 * len(imagens)
    for lado, dados in imagens:
        entradas += struct.pack(
            "<BBBBHHII",
            0 if lado >= 256 else lado, 0 if lado >= 256 else lado,
            0, 0, 1, 32, len(dados), deslocamento)
        corpo += dados
        deslocamento += len(dados)
    return cabecalho + entradas + corpo


def main() -> int:
    destino = Path(__file__).resolve().parent.parent / "recursos" / "acervo.ico"
    imagens = []
    for lado in TAMANHOS:
        print(f"  desenhando {lado}x{lado}...", flush=True)
        imagens.append((lado, png(bytes(desenhar(lado)), lado)))
    destino.write_bytes(ico(imagens))
    print(f"\nIcone gravado: {destino} ({destino.stat().st_size / 1024:.1f} KiB, "
          f"{len(TAMANHOS)} tamanhos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
