# -*- coding: utf-8 -*-
"""Mapeia a janela do BRAVOS (programa Windows) para montar o RPA. SO LE.

Abra o BRAVOS na tela que quer mapear (login, menu, Relatorio de Notas
Fiscais, resultado) e rode:  INSPECIONAR.bat
Gera saida/mapa_<hora>.txt com os nomes, tipos e ids de cada campo/botao.
Se a tela de login estiver aberta, os campos aparecem VAZIOS -- nao digite a
senha antes de mapear.
"""
import datetime as dt
import sys
from pathlib import Path

SAIDA = Path(__file__).resolve().parent / "saida"


def main() -> int:
    from pywinauto import Desktop
    SAIDA.mkdir(exist_ok=True)
    arq = SAIDA / f"mapa_{dt.datetime.now():%Y%m%d_%H%M%S}.txt"
    with open(arq, "w", encoding="utf-8") as f:
        for backend in ("uia", "win32"):
            f.write(f"\n##### backend {backend} #####\n")
            janelas = Desktop(backend=backend).windows()
            f.write("Janelas abertas: " + " | ".join(repr(w.window_text()) for w in janelas) + "\n")
            alvo = [w for w in janelas if "bravos" in (w.window_text() or "").lower()] or \
                   [w for w in janelas if w.window_text()]
            for w in alvo[:3]:
                f.write(f"\n=== {w.window_text()!r} (classe {w.class_name()}) ===\n")
                try:
                    for c in w.descendants():
                        try:
                            ei = c.element_info
                            txt = c.window_text()
                            if txt and c.element_info.control_type == "Edit" and "senha" in (ei.name or "").lower():
                                txt = "***"
                            f.write(f"{ei.control_type or ei.class_name!s:18} | nome={ei.name!r:40} | id={getattr(ei, 'automation_id', '')!r} "
                                    f"| classe={ei.class_name!r} | texto={txt[:60]!r}\n")
                        except Exception as e:
                            f.write(f"(erro lendo controle: {e})\n")
                except Exception as e:
                    f.write(f"(erro: {e})\n")
    print(f"Mapa gravado em: {arq}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
