"""Lancamento na planilha Excel JA EXISTENTE, com a SG como chave (upsert).

Regras (docs/saga-vh47.md):
  * nunca cria planilha nova, nunca apaga linha nem celula;
  * a SG (coluna "O.S.") e a chave: SG nova -> linha nova no fim dos dados;
    SG existente -> so preenche celulas VAZIAS dos campos extraidos; valor
    diferente do que ja esta la e "divergente": registrado no log e mantido
    (ou sobrescrito, se ``ao_divergir: atualizar``);
  * campos sem valor na fonte (NF, data, mao de obra...) ficam como estao;
  * dinheiro vai como NUMERO (formato #,##0.00), nunca como texto "R$ ...";
  * antes da primeira gravacao do dia de trabalho, copia de seguranca em
    ``backup/``; a gravacao e atomica (arquivo temporario + troca), e com a
    planilha aberta no Excel a gravacao para com mensagem clara.

Colunas sao achadas pelo TEXTO do cabecalho (sem acento, maiuscula ou
pontuacao), em qualquer aba e em qualquer linha das 30 primeiras -- nao por
posicao. Campo novo = mais um apelido em ``colunas`` no YAML.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .valores import chave_numerica, normalizar_texto, parse_brl, ValorInvalido

log = logging.getLogger("rpa.planilha")

FORMATO_DINHEIRO = "#,##0.00"
FORMATO_DATA = "dd/mm/yyyy"
LINHAS_PROCURA_CABECALHO = 30

# Partes do .xlsx que o openpyxl NAO preserva ao regravar.
_OBJETOS_PERDIDOS = ("xl/charts/", "xl/drawings/", "xl/activeX/", "xl/ctrlProps/", "xl/slicers/")


class ErroPlanilha(Exception):
    """Planilha ausente, sem a estrutura esperada, em uso ou arriscada de gravar."""


def _compacto(texto: Any) -> str:
    """'O.S.' -> 'os'; 'NF de mão de obra (serviço)' -> 'nfdemaodeobraservico'."""
    return re.sub(r"[^a-z0-9]", "", normalizar_texto(str(texto or "")))


@dataclass
class Acao:
    chave: str
    acao: str  # inserida | atualizada | sem_mudanca | divergente
    linha: int
    detalhe: str = ""
    dados: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfigPlanilha:
    caminho: Path
    colunas: dict[str, list[str]]
    chave: str = "sg"
    tipos: dict[str, str] = field(default_factory=dict)  # campo -> dinheiro | data | documento | texto
    aba: str | None = None
    ao_divergir: str = "manter"
    chave_como: str = "auto"  # auto | numero | texto
    copiar_formulas: bool = True
    backup_dir: Path | None = None
    backups_manter: int = 30
    permitir_perda_de_objetos: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any], tipos: dict[str, str], base: Path) -> "ConfigPlanilha":
        caminho = str(d.get("caminho") or "").strip()
        if not caminho or "${" in caminho:
            raise ErroPlanilha(
                "Caminho da planilha nao configurado: defina SAGA_PLANILHA no .env "
                "(ex.: SAGA_PLANILHA=C:\\datalake\\planilhas\\garantia.xlsx)"
            )
        colunas = {k: ([v] if isinstance(v, str) else list(v)) for k, v in (d.get("colunas") or {}).items()}
        chave = d.get("chave", "sg")
        if chave not in colunas:
            raise ErroPlanilha(f"planilha.colunas precisa ter o campo chave '{chave}'")
        ao_divergir = d.get("ao_divergir", "manter")
        if ao_divergir not in ("manter", "atualizar"):
            raise ErroPlanilha("planilha.ao_divergir: use 'manter' ou 'atualizar'")
        backup = d.get("backup_dir")
        return cls(
            caminho=Path(caminho),
            colunas=colunas,
            chave=chave,
            tipos=tipos,
            aba=d.get("aba") or None,
            ao_divergir=ao_divergir,
            chave_como=d.get("chave_como", "auto"),
            copiar_formulas=bool(d.get("copiar_formulas", True)),
            backup_dir=Path(backup) if backup else base / "backup_planilha",
            backups_manter=int(d.get("backups_manter", 30)),
            permitir_perda_de_objetos=bool(d.get("permitir_perda_de_objetos", False)),
        )


class Planilha:
    """Uma sessao de escrita: abre, faz upserts e grava (atomico)."""

    def __init__(self, cfg: ConfigPlanilha):
        self.cfg = cfg
        self._fez_backup = False

    # --------------------------------------------------------------- checagens
    def checar_pode_gravar(self) -> None:
        caminho = self.cfg.caminho
        if not caminho.is_file():
            raise ErroPlanilha(f"Planilha nao encontrada: {caminho} (a RPA nao cria planilha nova)")
        if caminho.suffix.lower() not in (".xlsx", ".xlsm"):
            raise ErroPlanilha(f"{caminho.name}: so .xlsx/.xlsm (salve como .xlsx no Excel)")
        trava = caminho.with_name("~$" + caminho.name)
        if trava.exists():
            raise ErroPlanilha(f"A planilha esta aberta no Excel ({trava.name}). Feche e rode de novo.")
        if not self.cfg.permitir_perda_de_objetos:
            with zipfile.ZipFile(caminho) as z:
                perdidos = sorted({p for n in z.namelist() for p in _OBJETOS_PERDIDOS if n.startswith(p)})
            if perdidos:
                raise ErroPlanilha(
                    f"{caminho.name} tem graficos/imagens/controles ({', '.join(perdidos)}) que se perderiam "
                    "ao regravar. Tire-os para outra planilha ou, ciente disso, use "
                    "planilha.permitir_perda_de_objetos: true"
                )

    # -------------------------------------------------------------- estrutura
    def _abrir(self):
        from openpyxl import load_workbook

        keep_vba = self.cfg.caminho.suffix.lower() == ".xlsm"
        try:
            return load_workbook(self.cfg.caminho, keep_vba=keep_vba)
        except Exception as exc:  # noqa: BLE001
            raise ErroPlanilha(f"Nao consegui abrir {self.cfg.caminho.name}: {exc}") from exc

    def _achar_cabecalho(self, wb) -> tuple[Any, int, dict[str, int]]:
        """(aba, linha do cabecalho, campo -> numero da coluna)."""
        abas = [wb[self.cfg.aba]] if self.cfg.aba else list(wb.worksheets)
        if self.cfg.aba and self.cfg.aba not in wb.sheetnames:
            raise ErroPlanilha(f"Aba '{self.cfg.aba}' nao existe (abas: {', '.join(wb.sheetnames)})")
        apelidos = {campo: {_compacto(a) for a in lista} for campo, lista in self.cfg.colunas.items()}
        melhor: tuple[int, Any, int, dict[str, int]] | None = None
        for ws in abas:
            for linha in ws.iter_rows(min_row=1, max_row=LINHAS_PROCURA_CABECALHO):
                achadas: dict[str, int] = {}
                for cel in linha:
                    txt = _compacto(cel.value)
                    if not txt:
                        continue
                    for campo, nomes in apelidos.items():
                        if txt in nomes and campo not in achadas:
                            achadas[campo] = cel.column
                if self.cfg.chave in achadas and (melhor is None or len(achadas) > melhor[0]):
                    melhor = (len(achadas), ws, linha[0].row, achadas)
        if melhor is None:
            nomes = " / ".join(self.cfg.colunas[self.cfg.chave])
            raise ErroPlanilha(f"Nao achei o cabecalho da coluna-chave ({nomes}) em {self.cfg.caminho.name}")
        _, ws, linha, colunas = melhor
        faltando = [c for c in self.cfg.colunas if c not in colunas]
        if faltando:
            log.warning("Colunas nao encontradas na aba '%s' (ficam de fora): %s", ws.title, ", ".join(faltando))
        return ws, linha, colunas

    @staticmethod
    def _ultima_linha(ws, linha_cab: int) -> int:
        """Ultima linha com algum valor (max_row engana: formatacao conta como uso)."""
        for r in range(ws.max_row, linha_cab, -1):
            if any(c.value not in (None, "") for c in ws[r]):
                return r
        return linha_cab

    # ----------------------------------------------------------------- escrita
    def _valor_para_celula(self, campo: str, valor: Any, chave_numero: bool) -> Any:
        tipo = self.cfg.tipos.get(campo, "texto")
        if valor is None:
            return None
        if tipo == "dinheiro":
            return float(Decimal(str(valor)).quantize(Decimal("0.01")))
        if campo == self.cfg.chave or tipo == "documento":
            texto = str(valor)
            if chave_numero and texto.isdigit() and len(texto) <= 15:
                return int(texto)
            return texto
        return valor

    def _iguais(self, campo: str, atual: Any, novo: Any) -> bool:
        tipo = self.cfg.tipos.get(campo, "texto")
        if tipo == "dinheiro":
            try:
                return parse_brl(atual) == parse_brl(novo)
            except ValorInvalido:
                return False
        if campo == self.cfg.chave or tipo == "documento":
            return chave_numerica(atual) == chave_numerica(novo)
        if isinstance(atual, dt.datetime) and isinstance(novo, dt.date):
            return atual.date() == novo
        return normalizar_texto(str(atual)) == normalizar_texto(str(novo))

    def _formatar(self, cel, campo: str) -> None:
        tipo = self.cfg.tipos.get(campo)
        if tipo == "dinheiro" and cel.number_format in ("General", "@"):
            cel.number_format = FORMATO_DINHEIRO
        elif tipo == "data" and cel.number_format in ("General", "@"):
            cel.number_format = FORMATO_DATA
        elif tipo in ("documento",) or campo == self.cfg.chave:
            if isinstance(cel.value, int) and cel.number_format == "@":
                cel.number_format = "0"

    def _nova_linha(self, ws, modelo: int, destino: int, linha_cab: int, preencher: set[int]) -> None:
        """Copia estilo (e formulas, ajustadas) da ultima linha de dados."""
        from copy import copy

        from openpyxl.formula.translate import Translator

        if modelo <= linha_cab:
            return
        for cel in ws[modelo]:
            alvo = ws.cell(row=destino, column=cel.column)
            if cel.has_style:
                alvo._style = copy(cel._style)
            if (self.cfg.copiar_formulas and cel.column not in preencher
                    and isinstance(cel.value, str) and cel.value.startswith("=")):
                alvo.value = Translator(cel.value, origin=cel.coordinate).translate_formula(alvo.coordinate)
        if ws.row_dimensions[modelo].height:
            ws.row_dimensions[destino].height = ws.row_dimensions[modelo].height

    @staticmethod
    def _estender_tabela(ws, ultima: int, nova: int, linha_cab: int) -> None:
        """Se os dados estao numa Tabela do Excel, a tabela passa a incluir a linha nova."""
        from openpyxl.worksheet.cell_range import CellRange

        for tabela in ws.tables.values():
            faixa = CellRange(tabela.ref)
            if faixa.min_row == linha_cab and faixa.max_row in (ultima, linha_cab + 1) and nova > faixa.max_row:
                faixa.expand(down=nova - faixa.max_row)
                tabela.ref = faixa.coord
                if tabela.autoFilter is not None:
                    tabela.autoFilter.ref = faixa.coord

    def upsert(self, registros: list[dict[str, Any]]) -> list[Acao]:
        """Lanca os registros e grava. Devolve o que foi feito com cada SG."""
        self.checar_pode_gravar()
        wb = self._abrir()
        ws, linha_cab, colunas = self._achar_cabecalho(wb)
        col_chave = colunas[self.cfg.chave]

        # SGs ja presentes
        indice: dict[str, int] = {}
        numericos = textos = 0
        ultima = self._ultima_linha(ws, linha_cab)
        for r in range(linha_cab + 1, ultima + 1):
            v = ws.cell(row=r, column=col_chave).value
            if v in (None, ""):
                continue
            if isinstance(v, (int, float)):
                numericos += 1
            else:
                textos += 1
            k = chave_numerica(v)
            if k in indice:
                log.warning("A planilha ja tem a %s %s repetida (linhas %d e %d); uso a primeira.",
                            self.cfg.chave.upper(), k, indice[k], r)
                continue
            indice[k] = r
        chave_numero = {"numero": True, "texto": False}.get(self.cfg.chave_como, numericos >= textos)
        # Modelo de estilo/formula = ultima linha COM SG (nao uma linha de TOTAL embaixo).
        modelo = max(indice.values(), default=ultima)
        if ultima > modelo:
            log.warning("Ha linha(s) sem %s abaixo dos dados (linha %d -- total?). SG nova entra "
                        "depois dela; confira se alguma soma precisa ser estendida.",
                        self.cfg.chave.upper(), ultima)

        acoes: list[Acao] = []
        mudou = False
        for reg in registros:
            chave = chave_numerica(reg.get(self.cfg.chave))
            if not chave:
                raise ErroPlanilha(f"registro sem {self.cfg.chave}: {reg}")
            valores = {c: v for c, v in reg.items() if v is not None and c in colunas}

            if chave not in indice:
                destino = ultima + 1
                self._nova_linha(ws, modelo, destino, linha_cab, {colunas[c] for c in valores})
                for campo, valor in valores.items():
                    cel = ws.cell(row=destino, column=colunas[campo])
                    cel.value = self._valor_para_celula(campo, valor, chave_numero)
                    self._formatar(cel, campo)
                self._estender_tabela(ws, ultima, destino, linha_cab)
                indice[chave] = destino
                ultima = modelo = destino
                mudou = True
                acoes.append(Acao(chave, "inserida", destino, dados=valores))
                continue

            linha = indice[chave]
            preenchidos, divergentes = [], []
            for campo, valor in valores.items():
                if campo == self.cfg.chave:
                    continue
                cel = ws.cell(row=linha, column=colunas[campo])
                if cel.value in (None, ""):
                    cel.value = self._valor_para_celula(campo, valor, chave_numero)
                    self._formatar(cel, campo)
                    preenchidos.append(campo)
                elif not self._iguais(campo, cel.value, valor):
                    divergentes.append(f"{campo}: planilha={cel.value!r} pdf={valor}")
                    if self.cfg.ao_divergir == "atualizar":
                        cel.value = self._valor_para_celula(campo, valor, chave_numero)
                        self._formatar(cel, campo)
                        preenchidos.append(campo)
            if preenchidos:
                mudou = True
            if divergentes:
                acao = "atualizada" if self.cfg.ao_divergir == "atualizar" else "divergente"
                acoes.append(Acao(chave, acao, linha, "; ".join(divergentes), valores))
            elif preenchidos:
                acoes.append(Acao(chave, "atualizada", linha, "preencheu " + ", ".join(preenchidos), valores))
            else:
                acoes.append(Acao(chave, "sem_mudanca", linha, dados=valores))

        if mudou:
            self._gravar(wb)
        return acoes

    # --------------------------------------------------------------- gravacao
    def _backup(self) -> None:
        if self._fez_backup:
            return
        pasta = self.cfg.backup_dir
        pasta.mkdir(parents=True, exist_ok=True)
        carimbo = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        destino = pasta / f"{self.cfg.caminho.stem}_{carimbo}{self.cfg.caminho.suffix}"
        shutil.copy2(self.cfg.caminho, destino)
        log.info("Copia de seguranca da planilha: %s", destino)
        antigos = sorted(pasta.glob(f"{self.cfg.caminho.stem}_*{self.cfg.caminho.suffix}"))
        for velho in antigos[: max(0, len(antigos) - self.cfg.backups_manter)]:
            velho.unlink(missing_ok=True)
        self._fez_backup = True

    def _gravar(self, wb) -> None:
        self._backup()
        tmp = self.cfg.caminho.with_name(f".~rpa_{self.cfg.caminho.name}")
        try:
            wb.save(tmp)
            os.replace(tmp, self.cfg.caminho)
        except PermissionError as exc:
            tmp.unlink(missing_ok=True)
            raise ErroPlanilha(
                f"Sem permissao para gravar {self.cfg.caminho.name} -- esta aberta no Excel? ({exc})"
            ) from exc
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
