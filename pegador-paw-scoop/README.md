# Pegador de ração BageVet (a partir do Paw Scoop)

Troca o nome do pet gravado no cabo do modelo *Paw Scoop* pela marca BageVet,
sem mexer em mais nada da peça.

## O que tem aqui

| Arquivo | O que faz |
| --- | --- |
| `logo_cabo.scad` | desenha a marca conforme a arte atual: coroa de seis patinhas + "bagévet" com a cruz + "medicina animal" alinhado à direita, 56,90 × 15,25 × 1,00 mm. Reaproveita `pata2d()` de `../chaveiro-3d/chaveiro_bagevet.scad` |
| `trocar_nome_por_logo.py` | abre o 3MF, separa os sólidos, põe a marca no lugar do nome e exporta os arquivos prontos |

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
  da marca e nada mais, mantendo perfis, pintura por face e posição na mesa.

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
