# Prompt e especificação do chaveiro BageVet

Arquivo de referência para gerar novos chaveiros (outros nomes de pet) sem
precisar redescobrir as medidas e as decisões já tomadas.

## Jeito rápido (não precisa de prompt nenhum)

O modelo já está pronto: só rodar o gerador com o nome desejado.

```bash
cd chaveiro-3d
python3 gerar_chaveiro.py --cava                        # corpo-base com cava + medalha da logo
python3 gerar_chaveiro.py --nome REX --cores 2          # 2 cores (4 partes)
python3 gerar_chaveiro.py --nome REX                    # peça única, 1 cor
python3 gerar_chaveiro.py --nomes "REX,MIA,TOBIAS" --cores 2
python3 gerar_chaveiro.py --lista pets.txt --cores 2    # um nome por linha
python3 gerar_chaveiro.py --nome REX --cores 2 --preview  # + PNG das 2 faces
```

Requisitos: `openscad` e `python3 -m pip install fonttools trimesh`.

## Especificação da peça (briefing original)

- Chaveiro redondo, tag circular, pronto para impressão 3D, em STL.
- Disco de **50 mm** de diâmetro e **3,5 mm** de espessura, bordas externas
  levemente arredondadas (chanfro de ~1 mm) para acabamento confortável.
- Furo para argola de **5 mm** de diâmetro, na parte superior do disco, com a
  **borda do furo a 6 mm da borda externa** da peça.
- **Frente (lado A)**: relevo positivo da logo — círculo de patinhas (disposição
  circular de pequenas patas) com o texto "BageVet" e o subtítulo
  "MEDICINA ANIMAL" abaixo. Logo com **34 mm** de diâmetro, centralizada,
  relevo de **1 mm**.
- **Verso (lado B)**: relevo positivo do nome do pet centralizado, com um ícone
  de patinha acima. Fonte legível, altura de letra **8 mm**, relevo de **1 mm**.
  A área do nome é um espaço reservado editável (paramétrico).
- **Fabricação**: relevo mínimo de 0,8 mm para legibilidade; sem suportes;
  superfície lisa e fechada (manifold); impressão deitada com o furo para cima.
- **Cores**: frente em duas cores como a arte de referência — disco verde com a
  coroa de patinhas e a marca em branco; verso branco com o nome em verde.

## Decisões tomadas (e o porquê)

| Decisão | Motivo |
| --- | --- |
| Texto da marca como `BageVet` | grafia da arte de referência (o briefing trazia "BAGeVET") — muda em uma linha no `.scad` (`texto_logo`) |
| Espessura total 5,5 mm na peça de 1 cor | disco de 3,5 mm + 1 mm de relevo em cada face, conforme o briefing. Para 3,5 mm totais, use `espessura = 1.5` |
| No conjunto de 2 cores o nome é embutido rente à face | é o que permite imprimir deitado **sem suporte nenhum**; alto-relevo nas duas faces obrigaria a apoiar a peça sobre as letras |
| Altura do nome fixa em 8 mm, condensando a largura | mantém a medida pedida; nomes longos (ex.: `BOLINHA`, fator 0,852) só ficam um pouco mais estreitos |
| Patinha reproporcionada | nas proporções iniciais a folga entre os dedinhos da coroa ficava em 0,25 mm e borraria num bico de 0,4 mm; hoje são 0,46 mm |
| Subtítulo engrossado em 0,06 mm | leva o traço mais fino da peça de 0,36 mm para 0,48 mm, acima do que um bico de 0,4 mm resolve |
| Cava da logo como peça única (medalha) | a logo é feita de ~30 sólidos soltos (8 patinhas e as letras); cavas com a silhueta exata deixariam paredes de 0,16 mm no corpo e peças soltas para encaixar uma a uma |
| Verso espelhado no eixo vertical | virando o chaveiro pendurado, o furo continua em cima e o nome fica na leitura correta |

## Limites conhecidos

- Nome até ~8 caracteres largos sai bem; acima disso o gerador condensa mais e
  avisa. Abaixo de fator 0,55 ele recusa e pede um nome mais curto.
- Acentos funcionam (`--nome "Júlio"`): vão gravados na peça e saem do nome do
  arquivo.
- Em lote, o relevo da frente é igual para todos os pets e é reaproveitado.

## Prompt pronto para colar (se for refazer do zero noutra sessão)

> Gere um modelo 3D paramétrico em OpenSCAD, exportado em STL, de um chaveiro
> circular: disco de 50 mm de diâmetro e 3,5 mm de espessura, bordas externas
> arredondadas com raio de 1 mm; furo de 5 mm de diâmetro na parte superior, com
> a borda do furo a 6 mm da borda externa. Na frente, relevo positivo de 1 mm com
> a logo em 34 mm de diâmetro: coroa de 8 patinhas em disposição circular, o
> texto "BageVet" e o subtítulo "MEDICINA ANIMAL" abaixo. No verso, relevo
> positivo de 1 mm com o nome do pet (parâmetro editável, letras de 8 mm de
> altura) e uma patinha acima. A peça deve sair em duas cores: corpo verde com a
> marca em branco na frente, e verso branco com o nome em verde — exporte as
> partes separadas por cor, no mesmo sistema de coordenadas e encaixadas sem
> folga, de modo que imprima deitada, com o furo para cima, sem suportes.
> Garanta malha fechada (manifold), relevo mínimo de 0,8 mm, traço mínimo e
> folgas acima de 0,4 mm (bico de 0,4 mm), e um script que gere o STL de vários
> nomes de pet em lote, validando cada malha.
