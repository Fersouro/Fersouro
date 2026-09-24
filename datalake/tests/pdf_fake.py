"""Gera PDFs minimos com texto posicionado (sem dependencias) para os testes."""

from __future__ import annotations

from pathlib import Path


def _esc(texto: str) -> bytes:
    b = texto.encode("cp1252")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def gerar_pdf(caminho: Path, paginas: list[list[tuple[float, float, str]]]) -> Path:
    """paginas: [[(x, y, texto), ...], ...] em pontos (A4 = 595 x 842)."""
    objetos: list[bytes] = []
    n_pag = len(paginas)
    # 1 catalogo, 2 paginas, 3 fonte, depois (pagina, conteudo) por pagina
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n_pag))
    objetos.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objetos.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pag} >>".encode())
    objetos.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for i, linhas in enumerate(paginas):
        conteudo = b"".join(
            b"BT /F1 10 Tf %.1f %.1f Td (" % (x, y) + _esc(t) + b") Tj ET\n" for x, y, t in linhas
        )
        objetos.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        objetos.append(b"<< /Length %d >>\nstream\n" % len(conteudo) + conteudo + b"endstream")
    saida = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, obj in enumerate(objetos, start=1):
        offsets.append(len(saida))
        saida += b"%d 0 obj\n" % n + obj + b"\nendobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    for off in offsets:
        saida += b"%010d 00000 n \n" % off
    saida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, xref)
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(bytes(saida))
    return caminho


def pdf_sg(caminho: Path, sg: str, total: str, extra: list[tuple[float, float, str]] | None = None) -> Path:
    """PDF no formato 'uma SG por relatorio', com numeros-isca antes dos campos."""
    linhas = [
        (50, 800, "VOLKSWAGEN DO BRASIL - GARANTIA"),
        (50, 780, "Relatório SAGA2 - VH47        Emissão: 05/09/2025"),
        (50, 760, "DN: 1234   Regional: SUL   Página 1"),
        (50, 730, f"Nº SG: {sg}"),
        (50, 710, "Valor de peças: R$ 700,00"),
        (50, 690, "Valor de mão de obra: R$ 300,00"),
        (50, 660, f"Valor Total da SG: {total}"),
    ]
    return gerar_pdf(caminho, [linhas + (extra or [])])
