# Pegador de ração BageVet (a partir do Paw Scoop)

Troca o nome do pet gravado no cabo do modelo *Paw Scoop* pela marca BageVet,
sem mexer em mais nada da peça.

Duas bases diferentes usam a mesma marca: o *Paw Scoop* e o *22_scoop*. Cada
uma tem o seu par de arquivos, porque a estrutura dos dois modelos e diferente.

## O que tem aqui

| Arquivo | O que faz |
| --- | --- |
| `logo_cabo.scad` | desenha a marca conforme a arte atual: coroa de seis patinhas + "bagévet" com a cruz + "medicina animal" alinhado à direita, 56,90 × 15,25 × 1,00 mm. Reaproveita `pata2d()` de `../chaveiro-3d/chaveiro_bagevet.scad` |
| `trocar_nome_por_logo.py` | Paw Scoop: abre o 3MF, separa os sólidos, põe a marca no lugar do nome e exporta os arquivos prontos |
| `logo_cabo_22.scad` | a mesma marca dimensionada para o cabo do *22_scoop* (tira plana de 18 mm): coroa Ø 13,40 mm, "bagévet" de 8,40 mm com a cruz e "medicina animal" alinhado à direita, 49,61 × 13,36 × 0,80 mm |
| `trocar_nome_22.py` | 22_scoop: tira o nome com um booleano, repõe a pintura por face e entrega a marca como segunda peça no extrusor 2 |

**A geometria do pegador não está no repositório.** A base é de terceiros
(*Personalized Paw & Bone Pet Food Scoop*, 3D CRAFT HUB, MakerWorld, sob
Standard Digital File License), que não permite redistribuição. Guarde o 3MF
original numa pasta sua e aponte o script para ele.

## Como usar

```sh
openscad -o logo.stl logo_cabo.scad
python3 trocar_nome_por_logo.py Paw_Scoop2.3mf
```

Sai uma pasta `saida/` com:

- `pegador_bagevet_colorido.stl` — um arquivo, 63 sólidos. O slicer abre como
  um objeto com várias partes: a 1 é o corpo, as 2 a 7 são as peças claras
  (é só nelas que se troca o filamento) e da 8 em diante são as ilhas da marca;
- `multipartes/` — corpo, peças claras e marca em arquivos separados, com a
  geometria exata do original;
- `pegador_bagevet.3mf` — o arquivo de entrada com a malha do texto trocada pela
  da marca e nada mais, mantendo perfis, pintura por face e posição na mesa;
- `pegador_bagevet_leve.3mf` — o mesmo arquivo com o perfil de impressão leve já
  gravado (ver abaixo). A malha é bit a bit igual à do anterior.

## O 22_scoop é outro caso

Este segundo modelo é um sólido só, e as duas cores vêm de **pintura por face**,
não de peças separadas. O nome também não era só relevo: as letras eram prismas
de 0,8 mm sobre um plinto de mais 0,8 mm, com o miolo de cada letra cortado
através do plinto até o cabo.

Então `trocar_nome_22.py` faz outro caminho:

1. tira do próprio modelo a silhueta cheia do nome (tudo que sobe acima do cabo,
   que é plano em z = −8,2);
2. corta fora esse volume com um booleano no OpenSCAD, deixando a tira lisa;
3. o booleano refaz a triangulação, então a pintura é reposta copiando a cor da
   face mais próxima na malha original — as pastilhas da concha continuam
   brancas (2601,8 mm² antes e depois) e o cabo volta a ser todo da cor do corpo;
4. a marca entra como **segunda peça do mesmo objeto, no extrusor 2**, com um
   degrau de 0,8 mm — o mesmo relevo das pastilhas. Repetir o plinto de dois
   degraus engordaria o desenho em 0,45 mm por lado e fecharia os vãos entre os
   dedinhos e entre as letras.

Aqui só o 3MF carrega o resultado completo: as pastilhas são pintura, e STL não
carrega pintura.

## Por que dá para colorir em STL

O modelo original já vem separado em sete sólidos: o corpo e seis insertos que
o autor pintou na cor clara. A cor, no 3MF, vem dessa pintura por face — que o
STL não carrega. Como os insertos são sólidos de verdade, o script os exporta
separados e a cor volta a ser geometria.

Os insertos encostam no corpo com as faces exatamente coincidentes. Num STL
isso faz o leitor do slicer soldar os vértices e as partes deixam de se separar,
então **no arquivo colorido** cada inserto cresce 0,01 mm, para se sobrepor ao
corpo em vez de tocá-lo. É um vigésimo de um traço de bico 0,4 — não muda nada
no que sai impresso. Nos arquivos de `multipartes/` a geometria é a original.

## O perfil leve

O 3MF de origem vem com o perfil **"0.20mm Strength"**: 6 paredes e 25 % de
preenchimento em grade. Numa concha de ração isso é perfil de peça estrutural —
sai em **90 g e 2 h 50** na X1C.

O peso não está na geometria. Nesta peça cada parede custa cerca de **13 g**,
porque o contorno da pata, o da concha e o do cabo se repetem por 200 camadas;
o preenchimento, esse, quase não pesa (entre 0 % e 10 % de relâmpago a diferença
é menor que 2 g). Então `PERFIL_LEVE` corta parede e troca a grade por
relâmpago, que só levanta coluna onde há superfície de topo para apoiar:

| | antes | depois |
| --- | --- | --- |
| paredes | 6 | 2 |
| preenchimento | 25 % grade | 5 % relâmpago |
| camadas de topo | 5 | 4 |
| PLA | 90,5 g | **48,6 g** |
| tempo na X1C | 2 h 50 | **~1 h 50** |

Abaixo de ~46 g o perfil não tem mais o que cortar: a peça fica com 39 cm³ de
material para 93 cm³ de volume, ou seja, já é 58 % ar, e o que sobra é parede,
primeira camada e topo. Daí em diante só reduzindo a peça.

## Conferências que o script faz

- todos os sólidos fechados (manifold), normais consistentes, volume positivo;
- a marca tem de caber inteira dentro do painel rebaixado do cabo — hoje sobra
  1,04 mm até a borda (o nome original deixava 0,77 mm);
- relevo de 0,985 mm acima do piso do painel, igual ao do nome original.

Medido no desenho da marca: traço mínimo 0,48 mm e menor vão entre formas
0,40 mm. Fatiado no PrusaSlicer com bico 0,4 mm e camada 0,2 mm: 200 camadas,
sem nenhum aviso e sem suporte.

Três pontos em que a marca se afasta da arte, e o motivo: o subtítulo saiu em
2,60 mm em vez dos 1,72 mm proporcionais (nessa altura o traço ficaria em
0,25 mm, abaixo do que o bico deposita); a silhueta da patinha é a versão
geométrica do chaveiro, porque redesenhá-la encorpada como na arte derruba a
folga entre a pastilha e os dedinhos para 0,33 mm; e o relevo sai todo numa cor
só, então o verde da coroa e da cruz contra o preto do texto não aparece. Com o
vetor da marca (SVG, AI, PDF ou EPS) dá para usar o contorno exato.

## Para mudar a marca

Tudo em `logo_cabo.scad`: altura das letras, espacejamento, tamanho da coroa,
quantidade de patinhas, tamanho da cruz. As cotas marcadas "(arte)" saem da
medição da própria imagem da marca. Mexendo no tamanho do texto, atualize também
`marca_larg` e `centro_dx` — são medidas do próprio desenho, e é com elas que a
composição fecha e fica centrada. A posição no cabo é o `MARCA_CX` do script
Python.
