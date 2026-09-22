# Chaveiro BageVet — tag circular para impressão 3D

Tag circular personalizável, pronta para impressão 3D, em duas versões:

- **Duas cores** (como a referência): disco verde com a coroa de patinhas e a
  marca em branco na frente; verso branco com o nome do pet em verde.
- **Uma cor**: a mesma peça num arquivo só.

O nome do verso é trocado a cada chaveiro — por linha de comando, um a um ou em
lote a partir de uma lista de pets.

| Frente | Verso |
| --- | --- |
| ![frente](stl/preview_BOLINHA_frente.png) | ![verso](stl/preview_BOLINHA_verso.png) |

## Arquivos

| Arquivo | Descrição |
| --- | --- |
| `chaveiro_bagevet.scad` | modelo paramétrico (fonte editável, OpenSCAD) |
| `gerar_chaveiro.py` | gera os STLs de cada pet, ajusta o texto e valida as malhas |
| `pets.txt` | exemplo de lista para geração em lote |
| `stl/chaveiro_bagevet_BOLINHA_cor1-corpo.stl` | **2 cores** — corpo (cor 1, verde) |
| `stl/chaveiro_bagevet_BOLINHA_cor1-nome.stl` | **2 cores** — nome do pet (cor 1, verde) |
| `stl/chaveiro_bagevet_BOLINHA_cor2-casca.stl` | **2 cores** — face do verso (cor 2, branco) |
| `stl/chaveiro_bagevet_BOLINHA_cor2-logo.stl` | **2 cores** — marca da frente (cor 2, branco) |
| `stl/chaveiro_bagevet_LUNA_*.stl` | segundo exemplo, mesmo conjunto |
| `stl/chaveiro_bagevet_BOLINHA.stl` | **1 cor** — peça única, alto-relevo nos dois lados |
| `stl/chaveiro_bagevet_BOLINHA_verso_baixo.stl` | **1 cor** — verso gravado, imprime deitado sem suporte |

## Trocar o nome do pet

```bash
python3 gerar_chaveiro.py --nome LUNA --cores 2              # um pet, 2 cores
python3 gerar_chaveiro.py --nomes "THOR,MEL,FRED" --cores 2  # vários de uma vez
python3 gerar_chaveiro.py --lista pets.txt --cores 2         # lista (um nome por linha)
python3 gerar_chaveiro.py --nome BOLINHA                     # peça única, 1 cor
python3 gerar_chaveiro.py --nome NINA --cores 2 --preview    # + PNG das duas faces
```

Cada pet sai com o seu conjunto de arquivos, nomeado pelo pet. Acentos podem ser
usados (`--nome "Júlio"`): vão gravados na peça e saem do nome do arquivo.

O script mede a fonte, mantém a altura das letras em **8 mm** e, se o nome for
longo, aplica só a condensação horizontal necessária para não encostar na borda
(`BOLINHA` sai com fator 0,852; `LUNA`, `THOR` e `FRED` saem naturais). Ele avisa
e interrompe se o nome exigir condensar demais. Depois de exportar, valida cada
malha (fechada, normais consistentes, volume positivo).

Sem Python dá para editar direto o `.scad`: a primeira linha do bloco
`[Personalizacao]` é `nome = "BOLINHA";`. Nesse caminho, confira nomes longos —
o ajuste automático de largura é feito pelo script.

Requisitos: `openscad` e `python3 -m pip install fonttools trimesh`
(`trimesh` só na validação; `xvfb` só para gerar os PNGs num servidor).

## Imprimir em duas cores

As quatro partes ficam no mesmo sistema de coordenadas e se encaixam sem folga
nem sobreposição (conferido: a soma dos volumes bate exatamente com a peça
montada). Carregue as quatro como **um objeto com várias partes**:

- **Bambu Studio / Orca**: importe os 4 STLs de uma vez e responda **Sim** em
  "carregar como objeto único com várias partes"; depois atribua o filamento de
  cada parte na lista de objetos.
- **PrusaSlicer**: carregue `cor1-corpo`, clique com o direito no objeto →
  *Adicionar parte → Carregar parte* para os outros três; atribua a extrusora de
  cada um.

Cor 1 (verde): `cor1-corpo` + `cor1-nome`. Cor 2 (branco): `cor2-casca` + `cor2-logo`.

Sem impressora multimaterial dá para usar os mesmos arquivos com **troca manual
de filamento**: a casca do verso e o nome ocupam os 0,6 mm iniciais e a marca da
frente começa em 3,5 mm de altura.

## Impressão

- **Orientação**: deitado, com a frente para cima e o furo apontando para trás
  (`+Y`). Nessa posição o conjunto de duas cores **não precisa de suporte**.
- **Camada**: 0,15–0,20 mm. O relevo da frente (1,0 mm) dá 5 a 7 camadas e a
  casca do verso (0,6 mm) dá 3 a 4.
- **Parede/preenchimento**: 3 perímetros, 20–30 %.
- **Bico**: 0,4 mm. Medidas críticas do desenho: o traço mais fino é o do
  subtítulo `MEDICINA ANIMAL`, com 0,48 mm (já engrossado no modelo); a menor
  folga entre os dedinhos das patinhas da coroa é 0,46 mm e cada dedinho tem
  0,88 mm. As letras do nome têm 1,43 mm de traço e as de `BageVet`, 0,84 mm.
- **Argola**: o furo de 5 mm aceita argola de 20–25 mm.

### Uma cor

`chaveiro_bagevet_BOLINHA.stl` segue a especificação original: alto-relevo de
1 mm nas duas faces, 5,5 mm de espessura total. Deitada, a peça apoia sobre as
letras do verso, então o slicer vai pedir suporte nessa face. A alternativa é
`..._verso_baixo.stl` (gerado com `--verso baixo`), com o verso **gravado** 1 mm:
imprime deitado sem nenhum suporte, com 4,5 mm de espessura total.

## Medidas (conferidas na malha exportada)

| Item | Valor |
| --- | --- |
| Diâmetro externo | 50,00 mm |
| Espessura do disco | 3,50 mm |
| Arredondamento da borda externa | raio 1,0 mm (toda a volta) |
| Furo da argola | Ø 5,00 mm, centro a 16,5 mm do centro |
| Borda do furo → borda externa | 6,00 mm |
| Logo da frente | Ø 34,0 mm, centralizada, relevo 1,0 mm |
| Nome do verso | letras de 8,0 mm de altura |
| Patinha do verso | 8,0 mm de largura, acima do nome |
| Casca colorida do verso (2 cores) | 0,60 mm |
| Espessura total | 4,50 mm (2 cores) · 5,50 mm (1 cor, relevo nos dois lados) |
| Malhas | todas fechadas (manifold), com volume positivo |

## Ajustes rápidos no `.scad`

| Parâmetro | Efeito |
| --- | --- |
| `nome` | nome do pet no verso |
| `texto_logo`, `texto_subtitulo` | textos da frente |
| `diametro`, `espessura`, `raio_borda` | geometria do disco |
| `relevo` | altura do relevo (mínimo recomendado 0,8 mm) |
| `furo_diametro`, `furo_margem` | furo da argola |
| `logo_diametro`, `n_patas`, `pata_coroa` | coroa de patinhas da frente |
| `altura_nome`, `nome_y`, `pata_verso` | composição do verso |
| `fonte` | fonte do texto (`"Liberation Sans:style=Bold"` por padrão) |
| `casca_verso` | espessura da casca de outra cor no verso (0 = peça de uma cor) |
| `modo_verso` | `"relevo"` ou `"baixo"` (quando não há casca) |
| `parte` | `"completo"`, `"corpo"`, `"casca"`, `"logo"` ou `"nome"` |

Para manter a peça com 3,5 mm de espessura **total** (como na referência
impressa), use `espessura = 1.5` com `relevo = 1.0`.
