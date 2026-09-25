"""Troca o nome do pet pela marca BageVet no cabo do 22_scoop.

    openscad -o logo22.stl logo_cabo_22.scad
    python3 trocar_nome_22.py 22_scoop.3mf

Este modelo e diferente do Paw Scoop: e um solido so, e as duas cores vem de
pintura por face (nao de pecas separadas). O nome do pet tambem nao e so
relevo - as letras sao prismas de 0,8 mm sobre um plinto de mais 0,8 mm, e o
miolo de cada letra e cortado atraves do plinto ate o cabo. Entao:

 1. a silhueta cheia do nome e tirada do proprio modelo (tudo que sobe acima
    do cabo, que e plano em z = -8,2);
 2. um booleano corta fora tudo que esta acima do cabo dentro dessa silhueta,
    deixando a tira lisa de novo;
 3. o booleano refaz a triangulacao, entao a pintura e reposta copiando a cor
    da face mais proxima na malha original - as pastilhas da concha continuam
    brancas e o cabo volta a ser todo da cor do corpo;
 4. a marca entra como uma SEGUNDA PARTE do mesmo objeto, no extrusor 2. E
    assim que as duas cores continuam separadas para o AMS.

A geometria base e de terceiros (Parametric Paw Pet Food Scoop, GreedyDog,
MakerWorld), entao o 3MF de entrada nao esta no repositorio.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import trimesh
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

warnings.filterwarnings('ignore')

NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
Z_CABO = -8.2      # o cabo e plano nesta cota, no sistema do objeto
MARCA_CY = -28.27  # centro do nome original ao longo do cabo
MARCA_Z = -8.22    # 0,02 mm enterrada, para a marca prevalecer sobre o cabo


def ler_malha(pasta):
    raiz = ET.parse(f"{pasta}/3D/Objects/object_1.model").getroot()
    obj = next(o for o in raiz.iter(NS + "object") if o.get("id") == "1")
    malha = obj.find(NS + "mesh")
    v = np.array([[float(x.get("x")), float(x.get("y")), float(x.get("z"))]
                  for x in malha.find(NS + "vertices")])
    tris = list(malha.find(NS + "triangles"))
    f = np.array([[int(t.get("v1")), int(t.get("v2")), int(t.get("v3"))] for t in tris])
    pc = np.array([t.get("paint_color") or "" for t in tris])
    return v, f, pc


def silhueta_do_nome(m):
    """Contorno cheio de tudo que sobe acima do cabo, na projecao XY."""
    cy = m.triangles[:, :, 1].mean(axis=1)
    topo = ((m.face_normals[:, 2] > 0.99)
            & (m.triangles[:, :, 2].mean(axis=1) > Z_CABO + 0.1)
            & (cy < 0))
    polis = [Polygon(t[:, :2]) for t in m.triangles[topo]]
    uni = unary_union([p for p in polis if p.is_valid and p.area > 1e-9])
    uni = uni.buffer(0.05).buffer(-0.05)
    partes = list(uni.geoms) if isinstance(uni, MultiPolygon) else [uni]
    return [Polygon(p.exterior).simplify(0.01) for p in partes]


def limpar_cabo(m, polis, tmp):
    """Corta fora o nome com um booleano e devolve a malha limpa."""
    m.export(f"{tmp}/corpo.stl")
    contornos = "\n".join(
        "  polygon(points=[%s]);" % ", ".join(
            "[%.4f,%.4f]" % (x, y)
            for x, y in np.array(p.buffer(0.15, join_style=1).simplify(0.02)
                                 .exterior.coords)[:-1])
        for p in polis)
    open(f"{tmp}/limpar.scad", "w").write(f"""
module silhueta() {{
{contornos}
}}
difference() {{
    import("{tmp}/corpo.stl", convexity = 12);
    translate([0, 0, {Z_CABO}]) linear_extrude(30) silhueta();
}}
""")
    r = subprocess.run(["openscad", "-o", f"{tmp}/limpo.stl", f"{tmp}/limpar.scad"],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[-800:])
    return trimesh.load(f"{tmp}/limpo.stl")


def malha_xml(v, f, pc, oid):
    vs = "\n".join('     <vertex x="%.6f" y="%.6f" z="%.6f"/>' % tuple(p) for p in v)
    ts = "\n".join(
        '     <triangle v1="%d" v2="%d" v3="%d"%s/>'
        % (a, b, c, (' paint_color="%s"' % pc[i]) if pc is not None and pc[i] else "")
        for i, (a, b, c) in enumerate(f))
    return (f'  <object id="{oid}" type="model">\n   <mesh>\n    <vertices>\n'
            + vs + '\n    </vertices>\n    <triangles>\n' + ts
            + '\n    </triangles>\n   </mesh>\n  </object>')


def main(entrada, logo_stl="logo22.stl", saida="saida22"):
    tmp = tempfile.mkdtemp()
    pasta = f"{tmp}/pkg"
    with zipfile.ZipFile(entrada) as z:
        z.extractall(pasta)

    v, f, pc = ler_malha(pasta)
    m = trimesh.Trimesh(vertices=v, faces=f, process=False)
    print(f"original: {len(f)} faces, {m.volume/1000:.3f} cm3, "
          f"fechada={m.is_watertight}, pintadas {(pc != '').sum()}")

    polis = silhueta_do_nome(m)
    novo = limpar_cabo(m, polis, tmp)
    print(f"cabo limpo: {len(novo.faces)} faces, {novo.volume/1000:.3f} cm3, "
          f"fechada={novo.is_watertight}, normais_ok={novo.is_winding_consistent}")

    # repoe a pintura pela face mais proxima da malha original
    _, _, viz = trimesh.proximity.ProximityQuery(m).on_surface(novo.triangles.mean(axis=1))
    pc_novo = pc[viz]
    cy = novo.triangles[:, :, 1].mean(axis=1)
    pc_novo[cy < 0] = '4'          # o cabo nao tem nada branco depois de tirar o nome
    a0 = trimesh.Trimesh(vertices=v, faces=f[(pc == '8') & (m.triangles[:, :, 1].mean(axis=1) >= 0)],
                         process=False).area
    a1 = trimesh.Trimesh(vertices=novo.vertices, faces=novo.faces[pc_novo == '8'],
                         process=False).area
    print(f"pastilhas brancas: {a0:.1f} mm2 antes, {a1:.1f} mm2 depois")

    logo = trimesh.load(logo_stl)
    logo.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [0, 0, 1]))
    logo.apply_translation([0, MARCA_CY, MARCA_Z])
    print(f"marca: {len(logo.faces)} faces, {logo.volume/1000:.3f} cm3, "
          f"fechada={logo.is_watertight}, ilhas={len(logo.split(only_watertight=False))}, "
          f"x {logo.bounds[0][0]:.2f}..{logo.bounds[1][0]:.2f} "
          f"y {logo.bounds[0][1]:.2f}..{logo.bounds[1][1]:.2f}")

    # --- reescreve o pacote --------------------------------------------------
    alvo = f"{pasta}/3D/Objects/object_1.model"
    texto = open(alvo, encoding="utf-8").read()
    ini = texto.index('  <object id="1"')
    fim = texto.index('</object>', ini) + len('</object>')
    texto = (texto[:ini]
             + malha_xml(novo.vertices, novo.faces, pc_novo, 1) + "\n"
             + malha_xml(logo.vertices, logo.faces, None, 2)
             + texto[fim:])
    open(alvo, "w", encoding="utf-8").write(texto)

    # o objeto passa a ter duas pecas: corpo e marca
    alvo = f"{pasta}/3D/3dmodel.model"
    s = open(alvo, encoding="utf-8").read()
    comp = ('    <component p:path="/3D/Objects/object_1.model" objectid="2" '
            'p:UUID="00010001-b206-40ff-9872-83e8017abed1" '
            'transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n   </components>')
    s = s.replace("   </components>", comp, 1)
    open(alvo, "w", encoding="utf-8").write(s)

    alvo = f"{pasta}/Metadata/model_settings.config"
    s = open(alvo, encoding="utf-8").read()
    matriz = s.split('<metadata key="matrix" value="')[1].split('"')[0]
    peca = (f'    <part id="2" subtype="normal_part">\n'
            f'      <metadata key="name" value="Logo BageVet"/>\n'
            f'      <metadata key="matrix" value="{matriz}"/>\n'
            f'      <metadata key="extruder" value="2"/>\n'
            f'      <mesh_stat face_count="{len(logo.faces)}" edges_fixed="0" '
            f'degenerate_facets="0" facets_removed="0" facets_reversed="0" '
            f'backwards_edges="0"/>\n    </part>\n  </object>')
    s = s.replace("    </part>\n  </object>", "    </part>\n" + peca, 1)
    s = s.replace(f'<metadata face_count="{len(f)}"/>',
                  f'<metadata face_count="{len(novo.faces) + len(logo.faces)}"/>')
    open(alvo, "w", encoding="utf-8").write(s)

    os.makedirs(saida, exist_ok=True)
    destino = f"{saida}/scoop22_bagevet.3mf"
    if os.path.exists(destino):
        os.remove(destino)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(f"{pasta}/[Content_Types].xml", "[Content_Types].xml")
        for raiz, _, arquivos in os.walk(pasta):
            for a in sorted(arquivos):
                rel = os.path.relpath(os.path.join(raiz, a), pasta).replace(os.sep, "/")
                if rel != "[Content_Types].xml":
                    z.write(os.path.join(raiz, a), rel)

    # STLs: corpo e marca, no mesmo sistema de coordenadas
    novo.export(f"{saida}/scoop22_bagevet_corpo.stl")
    logo.export(f"{saida}/scoop22_bagevet_marca.stl")
    trimesh.util.concatenate([novo, logo]).export(f"{saida}/scoop22_bagevet_colorido.stl")
    shutil.rmtree(tmp)

    print("\narquivos gerados:")
    for a in sorted(os.listdir(saida)):
        print(f"  {a:40s} {os.path.getsize(f'{saida}/{a}')/1024:8.0f} kB")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(*sys.argv[1:])
