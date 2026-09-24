"""Troca o nome do pet pela marca BageVet no cabo do Paw Scoop.

Gera as duas versoes em STL (colorida numa impressao so e multipartes) e o
proprio 3MF de entrada com a malha do texto substituida pela da marca.

    openscad -o logo.stl logo_cabo.scad
    python3 trocar_nome_por_logo.py Paw_Scoop2.3mf

O 3MF de entrada nao esta neste repositorio: a geometria base e de terceiros
(Personalized Paw & Bone Pet Food Scoop, 3D CRAFT HUB, MakerWorld, sob Standard
Digital File License). Guarde o arquivo original ao lado do script.

O modelo ja vem separado em sete solidos - o corpo e seis insertos que o autor
pintou na cor clara. E isso que permite reproduzir as duas cores em STL sem
depender da pintura por face, que o STL nao carrega.
"""
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import trimesh
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"

# Transformacoes que o proprio 3MF descreve, do sistema do objeto para a mesa.
T_CORPO = np.array([[1, 0, 0, 128.0], [0, 0, -1, 128.0], [0, 1, 0, 20.0], [0, 0, 0, 1.0]])
T_TEXTO = np.array([[0.994566541234451, -0.104102810033834, 0.0, 163.912403106689],
                    [0.104102810033834,  0.994566541234451, 0.0, 131.140731811523],
                    [0.0, 0.0, 1.0, 9.5],
                    [0.0, 0.0, 0.0, 1.0]])

# A marca ocupa a mesma area que o nome do pet ocupava: mesmo centro no cabo,
# mesmo relevo e mesmo sentido de leitura, com a coroa do lado da concha.
MARCA_CX = 164.4    # centro do nome original no eixo do cabo
PAINEL_Y = 128.0    # o cabo e simetrico em torno desta linha
Z_BASE   = 9.485    # mesma cota em que o texto original comecava
Z_PAINEL = 9.5      # piso do painel rebaixado

# Os insertos claros encostam no corpo com as faces exatamente coincidentes. Num
# STL isso faz o leitor do slicer soldar os vertices e as partes deixam de se
# separar, entao no arquivo colorido cada inserto cresce um tiquinho para as
# pecas se sobreporem em vez de se tocarem. 0,01 mm e um vigesimo de um traco de
# bico 0,4: o fatiador nem enxerga.
FOLGA = 0.01


def ler_corpo(pasta):
    """Malha do objeto 1 (a peca inteira) ja na pose da mesa."""
    raiz = ET.parse(f"{pasta}/3D/Objects/object_1.model").getroot()
    obj = next(o for o in raiz.iter(NS + "object") if o.get("id") == "1")
    malha = obj.find(NS + "mesh")
    v = np.array([[float(x.get("x")), float(x.get("y")), float(x.get("z"))]
                  for x in malha.find(NS + "vertices")])
    f = np.array([[int(t.get("v1")), int(t.get("v2")), int(t.get("v3"))]
                  for t in malha.find(NS + "triangles")])
    m = trimesh.Trimesh(vertices=v, faces=f, process=False)
    m.apply_transform(T_CORPO)
    return m, f


def separar(m, f):
    """Corpo principal e os insertos claros, do maior para o menor."""
    grupos = trimesh.graph.connected_components(m.face_adjacency,
                                                nodes=np.arange(len(f)))
    pecas = [trimesh.Trimesh(vertices=m.vertices, faces=f[g], process=True)
             for g in grupos]
    pecas.sort(key=lambda p: -p.volume)
    return pecas[0], pecas[1:]


def contorno(malha, z):
    """Contorno 2D das faces horizontais da malha na cota z."""
    tri = malha.triangles
    sel = ((malha.face_normals[:, 2] > 0.99)
           & (np.abs(tri[:, :, 2].mean(axis=1) - z) < 0.02))
    polis = [Polygon(t[:, :2]) for t in tri[sel]]
    uni = unary_union([p for p in polis if p.is_valid and p.area > 1e-9])
    uni = uni.buffer(0.02).buffer(-0.02)
    partes = list(uni.geoms) if isinstance(uni, MultiPolygon) else [uni]
    return max(partes, key=lambda p: p.area)


def sombra(malha):
    polis = [Polygon(t[:, :2]) for t in malha.triangles]
    uni = unary_union([p for p in polis if p.is_valid and p.area > 1e-9])
    return uni.buffer(0.01).buffer(-0.01)


def engordar(malha, d=FOLGA):
    g = malha.copy()
    g.vertices = g.vertices + g.vertex_normals * d
    return g


def gravar_3mf(pasta, local, n_faces_total, destino):
    """Reescreve o pacote trocando so a malha do objeto 2 (o texto)."""
    caminho = f"{pasta}/3D/Objects/object_1.model"
    texto = open(caminho, encoding="utf-8").read()
    vs = "\n".join('     <vertex x="%.6f" y="%.6f" z="%.6f"/>' % tuple(p)
                   for p in local.vertices)
    ts = "\n".join('     <triangle v1="%d" v2="%d" v3="%d"/>' % tuple(t)
                   for t in local.faces)
    nova = ('  <object id="2" p:UUID="00010001-81cb-4c03-9d28-80fed5dfa1dc" type="model">\n'
            '   <mesh>\n    <vertices>\n' + vs + '\n    </vertices>\n'
            '    <triangles>\n' + ts + '\n    </triangles>\n   </mesh>\n  </object>')
    ini = texto.index('  <object id="2"')
    fim = texto.index('</object>', ini) + len('</object>')
    open(caminho, "w", encoding="utf-8").write(texto[:ini] + nova + texto[fim:])

    # nome da parte e contagem de faces; tira o <text_info> para o Bambu Studio
    # nao tentar redesenhar o texto por cima da marca
    cfg = f"{pasta}/Metadata/model_settings.config"
    s = open(cfg, encoding="utf-8").read()
    s = s.replace('<metadata key="name" value="text_shape"/>',
                  '<metadata key="name" value="Logo BageVet"/>')
    s = re.sub(r'\s*<text_info[^>]*/>', '', s)
    s = re.sub(r'<mesh_stat face_count="3476"',
               '<mesh_stat face_count="%d"' % len(local.faces), s)
    s = re.sub(r'<metadata face_count="\d+"/>',
               '<metadata face_count="%d"/>' % n_faces_total, s)
    open(cfg, "w", encoding="utf-8").write(s)

    if os.path.exists(destino):
        os.remove(destino)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        # o [Content_Types].xml precisa ser a primeira entrada do pacote
        z.write(f"{pasta}/[Content_Types].xml", "[Content_Types].xml")
        for raiz, _, arquivos in os.walk(pasta):
            for a in sorted(arquivos):
                rel = os.path.relpath(os.path.join(raiz, a), pasta).replace(os.sep, "/")
                if rel != "[Content_Types].xml":
                    z.write(os.path.join(raiz, a), rel)


def main(entrada, logo_stl="logo.stl", saida="saida"):
    pasta = tempfile.mkdtemp()
    with zipfile.ZipFile(entrada) as z:
        z.extractall(pasta)

    corpo, faces = ler_corpo(pasta)
    principal, claros = separar(corpo, faces)
    logo = trimesh.load(logo_stl)
    logo.apply_translation([MARCA_CX, PAINEL_Y, Z_BASE])

    print(f"corpo principal : {len(principal.faces):6d} faces  "
          f"{principal.volume/1000:7.2f} cm3  fechado={principal.is_watertight}")
    for i, p in enumerate(claros, 1):
        print(f"inserto claro {i} : {len(p.faces):6d} faces  "
              f"{p.volume/1000:7.2f} cm3  fechado={p.is_watertight}")
    print(f"marca BageVet   : {len(logo.faces):6d} faces  {logo.volume/1000:7.2f} cm3"
          f"  fechado={logo.is_watertight}  ilhas={len(logo.split(only_watertight=False))}")

    # a marca tem de caber inteira dentro do painel rebaixado do cabo
    painel = contorno(max(claros, key=lambda p: p.bounds[1][2]), Z_PAINEL)
    marca = sombra(logo)
    dentro = painel.contains(marca)
    folga = marca.distance(painel.exterior) if dentro else float("nan")
    print(f"\nmarca dentro do painel: {dentro}   "
          f"folga minima ate a borda: {folga:.2f} mm")
    if not dentro:
        sys.exit("a marca passou da borda do painel - ajuste MARCA_CX ou o logo_cabo.scad")

    os.makedirs(f"{saida}/multipartes", exist_ok=True)

    # 1. colorido: um arquivo, varios solidos. A ordem vira a numeracao das
    #    partes no slicer: 1 = corpo, 2 a 7 = as pecas claras, 8+ = a marca.
    trimesh.util.concatenate(
        [principal] + [engordar(c) for c in claros] + [logo]
    ).export(f"{saida}/pegador_bagevet_colorido.stl")

    # 2. multipartes: um arquivo por cor, com a geometria exata do original
    principal.export(f"{saida}/multipartes/pegador_bagevet_corpo.stl")
    trimesh.util.concatenate(claros).export(
        f"{saida}/multipartes/pegador_bagevet_detalhes-claros.stl")
    logo.export(f"{saida}/multipartes/pegador_bagevet_marca.stl")

    # 3. o 3MF de entrada, so com a malha do texto trocada
    local = logo.copy()
    local.apply_transform(np.linalg.inv(T_TEXTO))
    n = len(principal.faces) + sum(len(c.faces) for c in claros) + len(local.faces)
    gravar_3mf(pasta, local, n, f"{saida}/pegador_bagevet.3mf")
    shutil.rmtree(pasta)

    print("\narquivos gerados:")
    for raiz, _, arquivos in os.walk(saida):
        for a in sorted(arquivos):
            c = os.path.join(raiz, a)
            print(f"  {os.path.relpath(c, saida):46s} {os.path.getsize(c)/1024:8.0f} kB")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(*sys.argv[1:])
