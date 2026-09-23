#!/usr/bin/env python3
"""Gera os arquivos do pegador de racao BageVet.

Saidas:
  - pegador_bagevet.stl           peca unica (uma cor)
  - pegador_bagevet_corpo.stl     \
  - pegador_bagevet_painel.stl     > multipartes para AMS/MMU
  - pegador_bagevet_logo.stl      /
  - pegador_bagevet_colorido.3mf  as tres partes num arquivo so, ja coloridas

STL nao guarda cor nem nada de fatiamento - e so geometria. Para imprimir
colorido na AMS use o 3MF (ou carregue os tres STLs como um objeto com varias
partes). O bico e a altura de camada sao escolhidos no fatiador; a opcao
--fatiar confere aqui mesmo que a peca fatia limpa com bico de 0,4 mm.
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
SCAD = AQUI / "pegador_bagevet.scad"

# (parte, arquivo, cor sugerida no 3MF)
PARTES = [
    ("corpo",  "corpo",  "#12695CFF"),
    ("painel", "painel", "#F4F1E8FF"),
    ("logo",   "logo",   "#12695CFF"),
]


def executavel(nome: str) -> str:
    exe = shutil.which(nome)
    if not exe:
        raise SystemExit(f"[erro] {nome} nao encontrado no PATH.")
    return exe


def rodar_openscad(saida: Path, parte: str) -> None:
    cmd = [executavel("openscad"), "-o", str(saida), "--export-format=binstl",
           "-D", f'parte="{parte}"', str(SCAD)]
    saida.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"[erro] OpenSCAD falhou em {saida.name}")


def validar(stl: Path):
    import trimesh
    m = trimesh.load(stl)
    x, y, z = m.extents
    ok = m.is_watertight and m.is_winding_consistent and m.volume > 0
    print(f"   {stl.name}: {len(m.faces)} faces | {x:.2f} x {y:.2f} x {z:.2f} mm | "
          f"{m.volume/1000:.2f} cm3 | {'malha fechada OK' if ok else 'PROBLEMA NA MALHA'}")
    if not ok:
        raise SystemExit(f"[erro] malha nao-manifold em {stl.name}")
    return m


# --------------------------------------------------------------------------- #
#  3MF: zip com o modelo em XML, uma cor por objeto
# --------------------------------------------------------------------------- #
CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>
"""

RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


def escrever_3mf(destino: Path, pecas: list[tuple[str, str, object]], desloc) -> None:
    """pecas = [(nome, cor, malha trimesh)] - todas no mesmo referencial."""
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<model unit="millimeter" xml:lang="en-US" '
              'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">',
              ' <resources>',
              '  <basematerials id="1">']
    for nome, cor, _ in pecas:
        linhas.append(f'   <base name="{nome}" displaycolor="{cor}"/>')
    linhas.append('  </basematerials>')

    for i, (nome, _cor, malha) in enumerate(pecas):
        oid = i + 2
        linhas.append(f'  <object id="{oid}" type="model" pid="1" pindex="{i}" name="{nome}">')
        linhas.append('   <mesh>')
        linhas.append('    <vertices>')
        for v in malha.vertices + desloc:
            linhas.append(f'     <vertex x="{v[0]:.6f}" y="{v[1]:.6f}" z="{v[2]:.6f}"/>')
        linhas.append('    </vertices>')
        linhas.append('    <triangles>')
        for t in malha.faces:
            linhas.append(f'     <triangle v1="{t[0]}" v2="{t[1]}" v3="{t[2]}"/>')
        linhas.append('    </triangles>')
        linhas.append('   </mesh>')
        linhas.append('  </object>')

    # objeto montado: as partes entram como componentes de um unico objeto, entao
    # o fatiador abre como "um objeto com varias partes" (cada uma com sua cor)
    conjunto = len(pecas) + 2
    linhas.append(f'  <object id="{conjunto}" type="model" name="montado">')
    linhas.append('   <components>')
    for i in range(len(pecas)):
        linhas.append(f'    <component objectid="{i + 2}"/>')
    linhas.append('   </components>')
    linhas.append('  </object>')
    linhas.append(' </resources>')
    linhas.append(' <build>')
    linhas.append(f'  <item objectid="{conjunto}"/>')
    linhas.append(' </build>')
    linhas.append('</model>')

    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("3D/3dmodel.model", "\n".join(linhas))


def fatiar(stl: Path, bico: float, camada: float) -> None:
    exe = shutil.which("prusa-slicer")
    if not exe:
        print("   (prusa-slicer ausente: fatiamento de conferencia pulado)")
        return
    gcode = stl.with_suffix(".gcode")
    cmd = [exe, "--export-gcode", "--nozzle-diameter", str(bico),
           "--layer-height", str(camada), "--first-layer-height", str(camada),
           "--perimeters", "3", "--fill-density", "20%", "--skirts", "1",
           "--filament-diameter", "1.75", "--thin-walls",
           "-o", str(gcode), str(stl)]
    if not shutil.which("xvfb-run") is None:
        cmd = ["xvfb-run", "-a"] + cmd
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"   {stl.name}: fatiador retornou erro ({proc.stderr.strip().splitlines()[-1:]})")
        return
    texto = gcode.read_text(errors="ignore")
    camadas = texto.count(";LAYER_CHANGE")
    tempo = next((l.split("= ")[1] for l in texto.splitlines()
                  if l.startswith("; estimated printing time (normal mode)")), "?")
    material = next((l.split("= ")[1] for l in texto.splitlines()
                     if l.startswith("; filament used [cm3]")), "?")
    gcode.unlink()
    print(f"   {stl.name}: bico {bico} mm, camada {camada} mm -> "
          f"{camadas} camadas, {material} cm3, {tempo}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Gera os arquivos do pegador BageVet.")
    ap.add_argument("--saida", default=str(AQUI / "stl"))
    ap.add_argument("--fatiar", action="store_true",
                    help="confere o fatiamento (bico 0,4 mm) de cada arquivo")
    ap.add_argument("--bico", type=float, default=0.4)
    ap.add_argument("--camada", type=float, default=0.2)
    args = ap.parse_args()

    destino = Path(args.saida)
    import trimesh

    print("Peca unica (uma cor):")
    unica = destino / "pegador_bagevet.stl"
    rodar_openscad(unica, "completo")
    validar(unica)

    print("\nMultipartes (AMS/MMU):")
    malhas = []
    for parte, sufixo, cor in PARTES:
        caminho = destino / f"pegador_bagevet_{sufixo}.stl"
        rodar_openscad(caminho, parte)
        malhas.append((sufixo, cor, validar(caminho)))

    print("\n3MF colorido:")
    juntas = trimesh.util.concatenate([m for _, _, m in malhas])
    desloc = -juntas.bounds[0]          # 3MF no primeiro octante
    tres = destino / "pegador_bagevet_colorido.3mf"
    escrever_3mf(tres, malhas, desloc)
    print(f"   {tres.name}: {len(malhas)} objetos coloridos, "
          f"{tres.stat().st_size/1024:.0f} KB")

    if args.fatiar:
        print(f"\nConferencia de fatiamento (bico {args.bico} mm):")
        for stl in [unica] + [destino / f"pegador_bagevet_{s}.stl" for _, s, _ in PARTES]:
            fatiar(stl, args.bico, args.camada)

    print("\nConcluido.")


if __name__ == "__main__":
    main()
