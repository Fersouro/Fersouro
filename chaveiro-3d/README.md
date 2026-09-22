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
| `PROMPT.md` | especificação, decisões tomadas e o prompt guardado para novos nomes |
| `gerar_chaveiro.py` | gera os STLs de cada pet, ajusta o texto e valida as malhas |
| `pets.txt` | exemplo de lista para geração em lote |
| `stl/chaveiro_bagevet_BOLINHA_cor1-corpo.stl` | **2 cores** — corpo (cor 1, verde) |
| `stl/chaveiro_bagevet_BOLINHA_cor1-nome.stl` | **2 cores** — nome do pet (cor 1, verde) |
| `stl/chaveiro_bagevet_BOLINHA_cor2-casca.stl` | **2 cores** — face do verso (cor 2, branco) |
| `stl/chaveiro_bagevet_BOLINHA_cor2-logo.stl` | **2 cores** — marca da frente (cor 2, branco) |
| `stl/chaveiro_bagevet_LUNA_*.stl` | segundo exemplo, mesmo conjunto |
| `stl/chaveiro_bagevet_BOLINHA.stl` | **1 cor** — peça única, alto-relevo nos dois lados |
| `stl/chaveiro_bagevet_LUNA.stl` | **1 cor** — peça única, alto-relevo nos dois lados |
| `stl/chaveiro_bagevet_BOLINHA_verso_baixo.stl` | **1 cor** — verso gravado, imprime deitado sem suporte |
| `stl/chaveiro_bagevet_corpo-base-2cavas.stl` | **peças aplicadas** — corpo universal, cava nos dois lados |
| `stl/chaveiro_bagevet_medalha-logo.stl` | **peças aplicadas** — a logo completa, impressa em separado |
| `stl/chaveiro_bagevet_BOLINHA_plaquinha.stl` | **peças aplicadas** — plaquinha do nome (uma por pet) |
| `stl/chaveiro_bagevet_LUNA_plaquinha.stl` | idem, segundo exemplo |
| `stl/chaveiro_bagevet_corpo-base-cava.stl` | variante com cava só na frente e verso liso |

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

## Peças aplicadas (cava nos dois lados)

O corpo vira uma peça universal, impressa uma vez e usada sempre; a logo e o
nome são peças aplicadas, impressas em separado e coladas nas cavas.

```bash
python3 gerar_chaveiro.py --cava-verso --nomes "BOLINHA,LUNA"   # corpo + medalha + 1 plaquinha por pet
python3 gerar_chaveiro.py --cava-verso --lista pets.txt         # em lote
python3 gerar_chaveiro.py --cava                                # só a cava da frente, verso liso
```

| Peça | Medidas | Quantas |
| --- | --- | --- |
| `corpo-base-2cavas` | Ø50 × 3,5 mm, cava de 1,0 mm na frente e de 0,8 mm no verso | uma para sempre |
| `medalha-logo` | Ø34,5 × 1,9 mm (0,9 mm na cava + 1,0 mm de relevo) | uma por chaveiro, sempre igual |
| `<NOME>_plaquinha` | Ø45,0 × 1,7 mm (0,7 mm na cava + 1,0 mm de relevo) | uma por pet |

Encaixe conferido na malha: **0,15 mm de folga lateral** e **0,1 mm no fundo** em
cada cava. As duas cavas e as duas peças têm um recorte em volta do furo da
argola, deixando 1,05 mm de material maciço ao redor dele. Montado, o conjunto
fica com 5,50 mm de espessura.

Dois pontos que vale saber antes de imprimir:

- **Núcleo do corpo**: com cava nos dois lados sobram 1,7 mm de material entre
  elas. Depois de coladas as duas peças o conjunto volta a ser um sanduíche
  maciço de 3,5 mm, mas o corpo sozinho é mais flexível. Para mais margem, use
  `espessura = 4.0` no `.scad` (núcleo de 2,2 mm).
- **Suporte no corpo**: imprima o corpo com a **frente para cima**. A cava do
  verso fica virada para baixo e o slicer vai pedir um suporte rasteiro de
  0,8 mm ali — sai com a unha e a marca fica escondida embaixo da plaquinha.
  As duas peças aplicadas imprimem deitadas, relevo para cima, sem suporte
  nenhum.

Com a cava do verso, o nome passa a ter de caber dentro da plaquinha de Ø45, e
não no disco inteiro: `BOLINHA` sai com condensação 0,791 (antes 0,852) e nomes
de até 5 ou 6 letras continuam saindo naturais.

Uma observação sobre o visual: as peças aplicadas são chapas inteiras, então a
área da logo e a do nome ficam todas na cor delas, com um anel na cor do corpo.
Não é o mesmo efeito da arte de referência, onde só as patinhas e as letras são
brancas sobre a face verde — esse efeito só sai imprimindo as duas cores juntas
(o conjunto de 4 partes acima). Abrir cavas com a silhueta exata da logo não é
viável nesta escala: as paredes entre as cavas dos dedinhos ficariam com
0,16 mm, e as letras soltas teriam de ser encaixadas uma a uma.

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
| Cava da logo (logo aplicada) | Ø 34,80 mm, 1,00 mm de profundidade |
| Medalha da logo | Ø 34,50 mm, 1,90 mm de altura (0,90 mm na cava + 1,00 mm de relevo) |
| Cava do verso | Ø 45,30 mm, 0,80 mm de profundidade |
| Plaquinha do nome | Ø 45,00 mm, 1,70 mm de altura (0,70 mm na cava + 1,00 mm de relevo) |
| Núcleo do corpo entre as duas cavas | 1,70 mm |
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
| `modo_verso` | `"relevo"`, `"baixo"` ou `"liso"` (quando não há casca) |
| `cava_logo` | `true` abre a cava na frente e transforma a logo em medalha |
| `cava_verso`, `cava_verso_prof`, `plaquinha_diam` | cava do verso e a plaquinha do nome |
| `cava_profundidade`, `cava_folga`, `cava_folga_z` | profundidade e folgas do encaixe |
| `medalha_margem`, `medalha_parede` | sobra da chapa e material junto ao furo |
| `parte` | `"completo"`, `"corpo"`, `"casca"`, `"logo"`, `"nome"`, `"medalha"` ou `"plaquinha"` |

Para manter a peça com 3,5 mm de espessura **total** (como na referência
impressa), use `espessura = 1.5` com `relevo = 1.0`.
