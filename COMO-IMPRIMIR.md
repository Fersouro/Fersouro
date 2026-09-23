# Brindes BageVet em 3D — como imprimir

Dois brindes personalizados, prontos para a Bambu Lab A1 com bico de 0,4 mm.
Todos os arquivos já saem apoiados na mesa, na posição certa, e foram
conferidos fatiando de verdade: **nenhum aviso, nenhum suporte**.

---

## 1. Chaveiro (o do jeito das fotos)

São duas peças que se encaixam:

| Arquivo | O que é | Cor |
| --- | --- | --- |
| `<NOME>_corpo.stl` | disco Ø50 × 3,6 mm, com a cava na frente e o nome do pet + patinha no verso | branco + a cor do nome |
| `placa-patinhas.stl` | placa Ø34,5 × 0,8 mm com 8 patinhas, encaixa na cava | verde + branco |

### Corpo — duas cores por **partes**

1. Arraste o `<NOME>_corpo.stl` para o Bambu Studio.
2. Ele pergunta se deve carregar como **um objeto com várias partes** →
   responda **Sim**.
3. Na lista do objeto aparecem 10 partes (12 no caso de nomes maiores): a
   **primeira é o corpo branco**, as demais são as letras e a patinha.
4. Clique na segunda, **shift + clique na última** e escolha o filamento da cor
   do nome.

O nome ocupa os 0,6 mm iniciais, rente à face — não há vão nem relevo pendurado,
por isso a peça apoia inteira na mesa.

### Placa — duas cores por **troca de filamento**

1. Arraste a `placa-patinhas.stl` (peça única).
2. Clique com o direito na régua de camadas, em **z = 0,80 mm**, →
   *Adicionar troca de filamento*. Verde embaixo, branco nas patinhas.

### Montagem

A placa entra na cava com **0,15 mm de folga por lado** e **0,20 mm no fundo**
(espaço para a cola). Montada, fica rente à face e as patinhas sobressaem 1,0 mm.
Cola de cianoacrilato (super bonder) ou epóxi.

### Tempos (bico 0,4 mm, camada 0,2 mm, 3 paredes, 20 %)

| Peça | Camadas | Material | Tempo |
| --- | --- | --- | --- |
| corpo | 18 | 3,78 cm³ | ~28 min |
| placa | 9 | 0,86 cm³ | ~10 min |

### Outro pet

```bash
cd chaveiro-3d
python3 gerar_chaveiro.py --aplicado --nome "Thor"
python3 gerar_chaveiro.py --aplicado --nomes "MEL,FRED,NINA"
```

Só o corpo muda — a placa é sempre a mesma. Acentos funcionam
(`--nome "Júlio"`).

---

## 2. Pegador de ração

| Arquivo | Quando usar |
| --- | --- |
| `pegador_bagevet_colorido.3mf` | **AMS**: abre com as três partes e as cores já atribuídas |
| `pegador_bagevet.stl` | uma cor só |
| `pegador_bagevet_corpo/painel/logo.stl` | multipartes, se preferir montar à mão |

Imprime deitado, boca da concha para cima, **sem suporte**: 190 camadas,
50,5 cm³, ~4 h 36 min. Para contato com ração, prefira PETG.

Medidas: 190 × 85 × 38 mm, parede 2,5 mm, fundo 3 mm, capacidade útil medida em
**112 cm³ (~45 g de ração seca)**.

---

## 3. Outras montagens do chaveiro (na pasta `outras-montagens/`)

- `<NOME>_colorido.3mf` — o chaveiro inteiro em 4 partes coloridas numa
  impressão só, sem cava e sem cola (é o que mais se parece com a arte
  original: patinhas brancas sobre a face verde).
- `<NOME>.stl` — peça única, uma cor, relevo nos dois lados.
- `cor1-*.stl` / `cor2-*.stl` — as mesmas 4 partes em arquivos separados.

---

## 4. Gerar do zero / mudar medidas

Na pasta `fontes/`: os modelos em OpenSCAD (`.scad`) e os geradores em Python.
Requisitos: `openscad` e `python3 -m pip install fonttools trimesh`.
O `PROMPT.md` guarda a especificação e as decisões de projeto.

Observação sobre a fonte: o nome sai na cursiva `Z003`, a mais próxima da arte
entre as disponíveis. Para usar outra, instale a fonte e troque `fonte_nome` no
`.scad`.
