# Pegador de ração BageVet (a partir do Paw Scoop)

Troca o nome do pet gravado no cabo do modelo *Paw Scoop* pela marca BageVet,
sem mexer em mais nada da peça.

## O que tem aqui

| Arquivo | O que faz |
| --- | --- |
| `logo_cabo.scad` | desenha a marca: coroa de patinhas + "BageVet" + "MEDICINA ANIMAL", 53,75 × 15,30 × 1,00 mm. Reaproveita `pata2d()` e `texto_fit()` de `../chaveiro-3d/chaveiro_bagevet.scad`, para o desenho ser o mesmo do chaveiro |
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

- `pegador_bagevet_colorido.stl` — um arquivo, 68 sólidos. O slicer abre como
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
  1,03 mm até a borda (o nome original deixava 0,77 mm);
- relevo de 0,985 mm acima do piso do painel, igual ao do nome original.

Medido no desenho da marca: traço mínimo 0,56 mm e vão mínimo 0,46 mm, os dois
acima do que um bico de 0,4 mm resolve. Fatiado no PrusaSlicer com bico 0,4 mm e
camada 0,2 mm: 200 camadas, sem nenhum aviso e sem suporte.

## Para mudar a marca

Tudo em `logo_cabo.scad`: altura das letras, espacejamento, tamanho da coroa,
quantidade de patinhas. Mexendo no tamanho do bloco de texto, atualize também
`texto_larg`, `texto_cx` e `texto_cy` — são as medidas do próprio desenho, e é
com elas que a composição fica centrada. A posição no cabo é o `MARCA_CX` do
script Python.
