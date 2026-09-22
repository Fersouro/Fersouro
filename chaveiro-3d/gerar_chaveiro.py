#!/usr/bin/env python3
"""Gera os STLs do chaveiro BageVet com o nome de cada pet.

Mede a fonte com fontTools para descobrir a largura real do texto, calcula
(quando necessario) uma condensacao horizontal que mantem o nome dentro do
disco sem alterar a altura das letras, chama o OpenSCAD e valida a malha.

Exemplos:
    python3 gerar_chaveiro.py --nome LUNA
    python3 gerar_chaveiro.py --nomes "THOR,MEL,FRED,NINA,Julio"
    python3 gerar_chaveiro.py --lista pets.txt --cores 2 --preview
    python3 gerar_chaveiro.py --nome BOLINHA --verso baixo
"""

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
# Cores usadas so na imagem de preview (a peca sai na cor do filamento).
COR1 = "#12695c"   # verde BageVet  -> corpo e nome
COR2 = "#f4f1e8"   # off-white      -> casca do verso e logo da frente

# Partes do conjunto de duas cores: (parte, cor, sufixo do arquivo)
PARTES_2CORES = [
    ("corpo", 1, "cor1-corpo"),
    ("nome",  1, "cor1-nome"),
    ("casca", 2, "cor2-casca"),
    ("logo",  2, "cor2-logo"),
]


# Reaproveitamento do relevo da frente entre pets de um mesmo lote.
_CACHE_LOGO: dict[str, Path] = {}


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
        self.hmtx = self.tt["hmtx"]
        self.glyf = self.tt["glyf"] if "glyf" in self.tt else None

    def _nome_glifo(self, ch: str) -> str:
        cp = ord(ch)
        if cp in self.cmap:
            return self.cmap[cp]
        # fallback: tenta a forma sem acento
        base = unicodedata.normalize("NFD", ch)[0]
        if ord(base) in self.cmap:
            return self.cmap[ord(base)]
        raise SystemExit(f"[erro] a fonte nao tem o caractere '{ch}'.")

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
            raise SystemExit("[erro] o nome nao tem nenhum caractere visivel.")
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
            if x == 0 or math.hypot(x, y) <= raio_max:
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
def executavel() -> str:
    exe = shutil.which("openscad") or shutil.which("openscad-nogui")
    if not exe:
        raise SystemExit("[erro] OpenSCAD nao encontrado no PATH.")
    return exe


def rodar_openscad(saida: Path, fonte_scad: Path, defs: dict[str, object],
                   extras: list[str] | None = None) -> None:
    cmd = [executavel(), "-o", str(saida)] + (extras or [])
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
    cmd.append(str(fonte_scad))
    saida.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"[erro] OpenSCAD falhou ao gerar {saida.name}")


def validar(stl: Path, rotulo: str = "") -> None:
    if stl.stat().st_size < 200:
        raise SystemExit(f"[erro] {stl.name} saiu vazio.")
    try:
        import trimesh
    except ImportError:
        print(f"   {stl.name}: gerado (validacao pulada, trimesh ausente)")
        return
    malha = trimesh.load(stl)
    x, y, z = malha.extents
    ok = malha.is_watertight and malha.is_winding_consistent and malha.volume > 0
    print(f"   {stl.name}{rotulo}: {len(malha.faces)} faces | "
          f"{x:.2f} x {y:.2f} x {z:.2f} mm | {malha.volume/1000:.2f} cm3 | "
          f"{'malha fechada OK' if ok else 'PROBLEMA NA MALHA'}")
    if not ok:
        raise SystemExit(f"[erro] malha nao-manifold em {stl.name}")


def limpar(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", sem_acento).strip("_").upper() or "PET"


# --------------------------------------------------------------------------- #
#  Preview colorido: monta um .scad temporario que inclui o modelo
# --------------------------------------------------------------------------- #
def preview(destino: Path, slug: str, defs: dict[str, object],
            duas_cores: bool, pecas_cava: bool = False) -> None:
    # render() por parte: sem ele o preview do OpenSCAD pinta tudo de uma cor so
    if pecas_cava:
        pecas = (f'color("{COR1}") render() parte_corpo();\n'
                 f'color("{COR2}") render() parte_medalha();')
    elif duas_cores:
        pecas = "\n".join(
            f'color("{COR1 if cor == 1 else COR2}") render() parte_{p}();'
            for p, cor, _ in PARTES_2CORES)
    else:
        pecas = f'color("{COR1}") render() parte_completa();'
    def literal(v):
        return '"%s"' % v if isinstance(v, str) else v
    atribs = "\n".join(f"{k} = {literal(v)};" for k, v in defs.items())
    wrapper = (f'include <{SCAD}>\nrenderizar_peca = false;\n{atribs}\n{pecas}\n')
    with tempfile.NamedTemporaryFile("w", suffix=".scad", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(wrapper)
        temp = Path(fh.name)
    try:
        for lado, camera in (("frente", "0,0,0,62,0,18,150"),
                             ("verso", "0,0,0,62,180,-18,150")):
            png = destino / f"preview_{slug}_{lado}.png"
            rodar_openscad(png, temp, {},
                           ["--camera", camera, "--imgsize", "1000,1000",
                            "--projection", "p", "--colorscheme", "Tomorrow"])
            print(f"   {png.name} gerado")
    finally:
        temp.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
def gerar(nome: str, args, par: dict[str, float], fonte: Fonte, destino: Path) -> None:
    raio_util = par["diametro"] / 2 - MARGEM_BORDA
    raio_logo = par["logo_diametro"] / 2 - par["pata_coroa"] * 0.95 - MARGEM_COROA

    if nome is None:                       # corpo-base sem nome no verso
        esc_nome, larg_nome = 1.0, 0.0
    else:
        esc_nome, larg_nome, *_ = ajustar(
            fonte, nome, par["altura_nome"], par["nome_y"], raio_util)
    esc_logo, larg_logo, *_ = ajustar(
        fonte, "BageVet", par["altura_logo"], par["logo_y"], raio_logo)
    esc_sub, larg_sub, *_ = ajustar(
        fonte, "MEDICINA ANIMAL", par["altura_sub"], par["sub_y"], raio_logo,
        espacamento=par["espacamento_sub"], engrossa=par["engrossar_sub"])

    duas_cores = args.cores == 2
    casca = args.casca if duas_cores else 0.0
    if args.cava:
        casca = 0.0
    base: dict[str, object] = {
        "nome": nome or "",
        "escala_x_nome": esc_nome,
        "escala_x_logo": esc_logo,
        "escala_x_sub": esc_sub,
        "casca_verso": casca,
        "modo_verso": "liso" if nome is None else args.verso,
        "cava_logo": "true" if args.cava else "false",
    }

    if nome is None:
        print("\ncorpo-base (verso liso, serve a qualquer nome)")
    else:
        total = par["espessura"] + par["relevo"] * (
            1 if (casca > 0 or args.verso == "baixo" or args.cava) else 2)
        print(f"\n'{nome}'  ->  letras de {par['altura_nome']:.1f} mm, "
              f"{larg_nome:.1f} mm de largura, condensacao {esc_nome:.3f}"
              f"{' (natural)' if esc_nome == 1 else ' (ajustada ao disco)'}"
              f" | espessura total {total:.1f} mm")

    slug = limpar(nome) if nome else "BASE"
    if args.cava:
        alvo = (destino / "chaveiro_bagevet_corpo-base-cava.stl" if nome is None
                else destino / f"chaveiro_bagevet_{slug}_corpo-cava.stl")
        rodar_openscad(alvo, SCAD, {**base, "parte": "corpo"})
        validar(alvo)
        medalha = destino / "chaveiro_bagevet_medalha-logo.stl"
        if not medalha.exists() or not _CACHE_LOGO.get("medalha"):
            rodar_openscad(medalha, SCAD, {**base, "parte": "medalha"})
            validar(medalha)
            _CACHE_LOGO["medalha"] = medalha
        else:
            print(f"   {medalha.name}: ja gerada (a logo nao muda)")
    elif duas_cores:
        for parte, _cor, sufixo in PARTES_2CORES:
            caminho = destino / f"chaveiro_bagevet_{slug}_{sufixo}.stl"
            # o relevo da frente e igual em todo pet: gera uma vez e copia
            if parte == "logo" and _CACHE_LOGO.get("arquivo"):
                shutil.copyfile(_CACHE_LOGO["arquivo"], caminho)
                print(f"   {caminho.name}: copiado do primeiro (a frente nao muda)")
                continue
            rodar_openscad(caminho, SCAD, {**base, "parte": parte})
            validar(caminho)
            if parte == "logo":
                _CACHE_LOGO["arquivo"] = caminho
    else:
        sufixo = "" if args.verso == "relevo" else "_verso_baixo"
        caminho = destino / f"chaveiro_bagevet_{slug}{sufixo}.stl"
        rodar_openscad(caminho, SCAD, {**base, "parte": "completo"})
        validar(caminho)

    if args.preview:
        preview(destino, slug, base, duas_cores, args.cava)


def main() -> None:
    ap = argparse.ArgumentParser(description="Gera os STLs do chaveiro BageVet.")
    ap.add_argument("--nome", action="append", default=[],
                    help="nome do pet (pode repetir a opcao)")
    ap.add_argument("--nomes", help="varios nomes separados por virgula")
    ap.add_argument("--lista", help="arquivo texto com um nome por linha")
    ap.add_argument("--cava", action="store_true",
                    help="corpo-base com cava na frente + medalha da logo "
                         "impressa em separado (verso liso, serve a qualquer nome)")
    ap.add_argument("--cores", type=int, choices=[1, 2], default=1,
                    help="1 = peca unica; 2 = conjunto de partes para MMU/AMS")
    ap.add_argument("--casca", type=float, default=0.6,
                    help="espessura da casca colorida do verso (com --cores 2)")
    ap.add_argument("--verso", choices=["relevo", "baixo"], default="relevo",
                    help="verso em alto-relevo ou gravado (ignorado com --cores 2)")
    ap.add_argument("--saida", default=str(AQUI / "stl"), help="pasta de saida")
    ap.add_argument("--preview", action="store_true", help="gera PNG das duas faces")
    args = ap.parse_args()

    nomes = list(args.nome)
    if args.nomes:
        nomes += [n.strip() for n in args.nomes.split(",")]
    if args.lista:
        nomes += [l.strip() for l in Path(args.lista).read_text(encoding="utf-8").splitlines()]
    nomes = [n for n in nomes if n]
    if not nomes:
        # com --cava e sem nome, gera o corpo-base liso (serve a qualquer pet)
        nomes = [None] if args.cava else ["BOLINHA"]

    par = ler_parametros(SCAD)
    fonte = Fonte(FONTE_TTF)
    destino = Path(args.saida)
    for nome in nomes:
        gerar(nome, args, par, fonte, destino)
    print(f"\nConcluido: {len(nomes)} chaveiro(s) em {destino}")


if __name__ == "__main__":
    main()
