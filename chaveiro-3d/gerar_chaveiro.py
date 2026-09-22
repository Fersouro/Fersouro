#!/usr/bin/env python3
"""Gera o STL do chaveiro BageVet com o nome do pet desejado.

Mede a fonte com fontTools para descobrir a largura real do texto, calcula
(quando necessario) uma condensacao horizontal que mantem o nome dentro do
disco sem alterar a altura das letras, chama o OpenSCAD e valida a malha.

Exemplos:
    python3 gerar_chaveiro.py --nome LUNA
    python3 gerar_chaveiro.py --nome BOLINHA --modo-verso baixo
    python3 gerar_chaveiro.py --nome THOR --multicor
"""

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

from fontTools.ttLib import TTFont

AQUI = Path(__file__).resolve().parent
SCAD = AQUI / "chaveiro_bagevet.scad"
FONTE_TTF = Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")
# Folga entre qualquer relevo e a borda externa do disco.
MARGEM_BORDA = 2.5
# Folga entre o texto da marca e a coroa de patinhas.
MARGEM_COROA = 0.5


# --------------------------------------------------------------------------- #
#  Leitura dos parametros do .scad (fonte unica de verdade da geometria)
# --------------------------------------------------------------------------- #
def ler_parametros(scad: Path) -> dict[str, float]:
    par: dict[str, float] = {}
    for linha in scad.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?\d+(?:\.\d+)?)\s*;", linha)
        if m:
            par.setdefault(m.group(1), float(m.group(2)))
    return par


# --------------------------------------------------------------------------- #
#  Metrica de texto
# --------------------------------------------------------------------------- #
class Fonte:
    def __init__(self, ttf: Path):
        self.tt = TTFont(str(ttf))
        self.upm = self.tt["head"].unitsPerEm
        self.cmap = self.tt.getBestCmap()
        self.glyphs = self.tt.getGlyphSet()
        self.hmtx = self.tt["hmtx"]
        self.glyf = self.tt["glyf"] if "glyf" in self.tt else None

    def _nome_glifo(self, ch: str) -> str:
        cp = ord(ch)
        if cp in self.cmap:
            return self.cmap[cp]
        # fallback: tenta a forma sem acento (ex.: Julio no lugar de Julio)
        base = unicodedata.normalize("NFD", ch)[0]
        return self.cmap.get(ord(base), ".notdef")

    def caixa(self, texto: str, espacamento: float = 1.0):
        """Caixa da mancha grafica em em, ja centrada como no halign="center"."""
        pen = 0.0
        x0 = y0 = math.inf
        x1 = y1 = -math.inf
        for ch in texto:
            g = self._nome_glifo(ch)
            avanco = self.hmtx[g][0]
            gl = self.glyf[g] if self.glyf else None
            if gl is not None and gl.numberOfContours != 0:
                x0 = min(x0, pen + gl.xMin)
                x1 = max(x1, pen + gl.xMax)
                y0 = min(y0, gl.yMin)
                y1 = max(y1, gl.yMax)
            pen += avanco * espacamento
        if x0 is math.inf:
            raise ValueError("texto sem glifos visiveis")
        centro = pen / 2          # halign="center" usa a largura de avanco
        return ((x0 - centro) / self.upm, y0 / self.upm,
                (x1 - centro) / self.upm, y1 / self.upm)


def ajustar(fonte: Fonte, texto: str, altura: float, base_y: float,
            raio_max: float, espacamento: float = 1.0, engrossa: float = 0.0,
            escala_min: float = 0.55):
    """Devolve (escala_x, largura_mm, y_min, y_max) cabendo em raio_max."""
    x0, y0, x1, y1 = fonte.caixa(texto, espacamento)
    s = altura / (y1 - y0)                       # resize([0, altura], auto=true)
    bx0, bx1 = x0 * s - engrossa, x1 * s + engrossa
    by0, by1 = y0 * s + base_y - engrossa, y1 * s + base_y + engrossa

    escala = 1.0
    for x in (bx0, bx1):
        for y in (by0, by1):
            if math.hypot(x * escala, y) <= raio_max or x == 0:
                continue
            limite = raio_max * raio_max - y * y
            if limite <= 0:
                raise SystemExit(
                    f"[erro] '{texto}' nao cabe na altura de {altura} mm "
                    f"nesta posicao (y = {y:.1f} mm)."
                )
            escala = min(escala, math.sqrt(limite) / abs(x))
    if escala < 1.0:                      # margem de seguranca so quando condensa
        escala = math.floor(escala * 0.995 * 1000) / 1000
    if escala < escala_min:
        raise SystemExit(
            f"[erro] '{texto}' exigiria condensar para {escala:.2f} "
            f"(minimo {escala_min}). Use um nome mais curto."
        )
    return escala, (bx1 - bx0) * escala, by0, by1


# --------------------------------------------------------------------------- #
#  OpenSCAD + validacao
# --------------------------------------------------------------------------- #
def rodar_openscad(saida: Path, defs: dict[str, object],
                   extras: list[str] | None = None) -> None:
    exe = shutil.which("openscad") or shutil.which("openscad-nogui")
    if not exe:
        raise SystemExit("[erro] OpenSCAD nao encontrado no PATH.")
    cmd = [exe, "-o", str(saida)] + (extras or [])
    if saida.suffix.lower() == ".stl":
        cmd.append("--export-format=binstl")   # STL binario: arquivo menor
    # renderizar PNG exige contexto grafico; em servidor usa Xvfb se preciso
    if saida.suffix.lower() == ".png" and not os.environ.get("DISPLAY"):
        xvfb = shutil.which("xvfb-run")
        if xvfb:
            cmd = [xvfb, "-a", "-s", "-screen 0 1024x1024x24"] + cmd
    for chave, valor in defs.items():
        literal = f'"{valor}"' if isinstance(valor, str) else valor
        cmd += ["-D", f"{chave}={literal}"]
    cmd.append(str(SCAD))
    saida.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"[erro] OpenSCAD falhou ao gerar {saida.name}")
    for linha in proc.stderr.splitlines():
        if "WARNING" in linha or "ERROR" in linha:
            print("   openscad:", linha.strip())


def validar(stl: Path) -> None:
    try:
        import trimesh
    except ImportError:
        print(f"   {stl.name}: validacao pulada (trimesh ausente)")
        return
    malha = trimesh.load(stl)
    x, y, z = malha.extents
    print(f"   {stl.name}: {len(malha.faces)} faces | "
          f"caixa {x:.2f} x {y:.2f} x {z:.2f} mm | "
          f"volume {malha.volume / 1000:.2f} cm3 | "
          f"fechada={malha.is_watertight} winding_ok={malha.is_winding_consistent} "
          f"volume_positivo={malha.volume > 0}")
    if not (malha.is_watertight and malha.is_winding_consistent):
        raise SystemExit(f"[erro] malha nao-manifold em {stl.name}")


def limpar(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", sem_acento).strip("_").upper() or "PET"


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Gera o STL do chaveiro BageVet.")
    ap.add_argument("--nome", default="BOLINHA", help="nome do pet (verso)")
    ap.add_argument("--saida", default=str(AQUI / "stl"), help="pasta de saida")
    ap.add_argument("--modo-verso", choices=["relevo", "baixo"], default="relevo",
                    help="relevo = alto-relevo nos dois lados; "
                         "baixo = verso gravado (imprime deitado sem suporte)")
    ap.add_argument("--multicor", action="store_true",
                    help="tambem exporta corpo + detalhe separados (2 cores/MMU)")
    ap.add_argument("--preview", action="store_true", help="tambem gera PNG das duas faces")
    args = ap.parse_args()

    p = ler_parametros(SCAD)
    fonte = Fonte(FONTE_TTF)
    raio_util = p["diametro"] / 2 - MARGEM_BORDA
    raio_logo = p["logo_diametro"] / 2 - p["pata_coroa"] * 0.95 - MARGEM_COROA

    esc_nome, larg_nome, ny0, ny1 = ajustar(
        fonte, args.nome, p["altura_nome"], p["nome_y"], raio_util)
    esc_logo, larg_logo, *_ = ajustar(
        fonte, "BageVet", p["altura_logo"], p["logo_y"], raio_logo)
    esc_sub, larg_sub, *_ = ajustar(
        fonte, "MEDICINA ANIMAL", p["altura_sub"], p["sub_y"], raio_logo,
        espacamento=p["espacamento_sub"], engrossa=p["engrossar_sub"])

    total = p["espessura"] + p["relevo"] * (1 if args.modo_verso == "baixo" else 2)
    print(f"Nome: '{args.nome}'")
    print(f"   letras {p['altura_nome']:.1f} mm de altura, "
          f"largura {larg_nome:.1f} mm, condensacao {esc_nome:.3f}"
          f"{'  (natural)' if esc_nome == 1 else '  (ajustada ao disco)'}")
    print(f"   marca: 'BageVet' {larg_logo:.1f} mm (x{esc_logo:.3f}) | "
          f"subtitulo {larg_sub:.1f} mm (x{esc_sub:.3f})")
    print(f"   espessura total com relevo: {total:.1f} mm")

    base = {
        "nome": args.nome,
        "escala_x_nome": esc_nome,
        "escala_x_logo": esc_logo,
        "escala_x_sub": esc_sub,
        "modo_verso": args.modo_verso,
    }
    destino = Path(args.saida)
    slug = limpar(args.nome)
    sufixo = "" if args.modo_verso == "relevo" else "_verso_baixo"

    alvos = [(destino / f"chaveiro_bagevet_{slug}{sufixo}.stl", "completo")]
    if args.multicor:
        alvos += [(destino / f"chaveiro_bagevet_{slug}_corpo.stl", "corpo"),
                  (destino / f"chaveiro_bagevet_{slug}_detalhe.stl", "detalhe")]

    for caminho, parte in alvos:
        rodar_openscad(caminho, {**base, "parte": parte})
        validar(caminho)

    if args.preview:
        for lado, camera in (("frente", "0,0,0,62,0,18,150"),
                             ("verso", "0,0,0,62,180,-18,150")):
            png = destino / f"preview_{slug}_{lado}.png"
            rodar_openscad(png, {**base, "parte": "completo"},
                           ["--camera", camera, "--imgsize", "1000,1000",
                            "--projection", "p", "--colorscheme", "Tomorrow",
                            "--render"])
            print(f"   {png.name} gerado")

    print("Concluido.")


if __name__ == "__main__":
    main()
