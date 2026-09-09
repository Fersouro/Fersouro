# Relatórios em Excel — documentação

Um **relatório** é uma pasta de trabalho `.xlsx` com várias abas, número
formatado como número se lê (R$, %, dd/mm/aaaa), linha de total e destaque no
que precisa de atenção. Cada relatório é um arquivo YAML em
`datalake/conf/reports/`.

> Não confundir com o **export** (`datalake export`): aquele grava um modelo
> gold por arquivo, cru, para quem vai levar o dado para outro lugar. O
> relatório é para ser lido por uma pessoa.

---

## 1. Como rodar

```bash
datalake report                 # todos os relatórios
datalake report -r margem_pecas # só um (pode repetir o -r)
datalake report --list          # o que existe, sem gerar nada
datalake report --out D:\saida  # outra pasta de destino
```

Os arquivos saem em `<lake>/export/relatorios/` — no servidor,
`C:\datalake\export\relatorios\`. Como o servidor da página publica a pasta
`export` inteira, eles já ficam acessíveis na rede em
**`https://192.168.78.6:8443/relatorios/`** — atrás do login do portal (veja
`estoque-minimo.md`, seção 5).

O `datalake run` gera os relatórios sozinho, no fim do pipeline (depois do
export). Ou seja: as 6 cargas diárias já atualizam as planilhas. Para desligar,
`settings.yml`:

```yaml
reports:
  enabled: false
```

---

## 2. Como definir um relatório

Um arquivo por relatório em `conf/reports/`. O prefixo numérico do nome do
arquivo só serve para ordenar a listagem — o nome do relatório é o campo
`name`, e é ele que vira `nome.xlsx`.

```yaml
name: margem_pecas                # vira margem_pecas.xlsx
title: Margem de Peças            # título na capa
description: Venda, custo e lucro por filial, líquidos de devolução.

formats:                          # vale para todas as abas
  lucro_porcentagem: percentual
  venda_total: moeda

sheets:
  - name: Mes atual               # nome da aba (o Excel corta em 31 caracteres)
    description: O que a aba mostra — aparece na capa.
    sql: |
      SELECT filial, venda_total, lucro
        FROM margem_pecas
       WHERE competencia = date_trunc('month', current_date)
       ORDER BY lucro DESC
    totals: [venda_total, lucro]  # linha TOTAL no fim
    formats:                      # só desta aba; vence o de cima
      lucro: moeda
    highlights:
      - when: lucro < 0           # expressão SQL sobre o resultado da aba
        style: vermelho           # vermelho | amarelo | verde | azul
        scope: row                # 'row' (padrão) ou o nome de uma coluna
    limit: 50000                  # opcional

  - name: Detalhe
    model: margem_pecas           # atalho para SELECT * FROM margem_pecas
```

`sql` e `model` são exclusivos: ou um, ou outro.

### O que o SQL enxerga

As mesmas views da camada gold:

- `<fonte>__<tabela>` para toda tabela da silver (ex.: `ccm__pec_item_revenda`);
- `<tabela>` quando o nome não se repete entre as fontes;
- o nome de cada **modelo gold** materializado (ex.: `margem_pecas`).

É SQL do DuckDB, igual ao dos modelos gold — não há linguagem nova.

---

## 3. Parâmetros (o gerador da página)

Um relatório pode declarar campos que quem gera escolhe — é o que transforma a
página num **gerador**, em vez de uma lista de arquivos prontos:

```yaml
parameters:
  - name: data_inicial
    label: Data inicial
    type: data            # mes | data | numero | texto | lista
    default: inicio-do-mes
  - name: revenda
    label: Revenda
    type: lista           # vira um seletor, sem digitar
    default: ""
    optional: true
    options:
      - value: 1
        label: Revenda 1
      - value: 2
        label: Revenda 2
      - value: ""         # vazio = sem filtro
        label: Consolidado (1 e 2)
```

`type: lista` gera um seletor com essas opções e recusa qualquer valor fora
delas. A opção de valor vazio, com `optional: true`, é o "consolidado": não
filtra nada, então **as duas lojas saem, cada uma na sua linha, e a linha TOTAL
soma as duas**. Na capa da planilha aparece o rótulo escolhido
("Consolidado (1 e 2)"), não o valor técnico.

No SQL o valor entra como **parâmetro nomeado do DuckDB**, nunca concatenado —
é isso que impede o formulário da página de injetar SQL:

```sql
SELECT ... FROM faturamento_notas
 WHERE competencia = $competencia
   AND ($departamento IS NULL OR departamento = $departamento)
```

Pela linha de comando:

```bash
datalake report -r faturamento-funilaria --param competencia=2026-08
datalake report -r faturamento-funilaria --param departamento=      # todos
```

`type: mes` aceita `2026-09`, `09/2026`, `2026-09-17` e `atual`. `type: data`
aceita `2026-09-30`, `30/09/2026` e os atalhos `hoje`, `ontem`,
`inicio-do-mes`, `fim-do-mes` — que servem principalmente de `default`: na
página o campo já aparece como seletor de data com o dia certo preenchido. Não informar o
campo usa o `default`; informar **em branco** significa "todos" (só em
`optional: true`) — são coisas diferentes de propósito. A capa da planilha
registra o que foi escolhido, senão duas gerações do mesmo relatório com
filtros diferentes ficam indistinguíveis depois de salvas.

### Pela página, em `/gerar`

A tela inicial (`https://192.168.78.6:8443/`) mostra os relatórios **em lista,
um por linha**: nome e descrição à esquerda, os campos no meio e o botão **Exportar em
Excel** à direita. As datas são escritas como aqui se escreve — `01/08/2026` a
`30/08/2026` —, já preenchidas com o primeiro e o último dia do mês. Clicar no
botão baixa o `.xlsx` direto (vai como anexo, não abre numa aba) e a página
continua onde estava, pronta para a próxima consulta. O servidor não gera dentro do próprio processo: ele chama o
`datalake report` do projeto, com o Python do venv dele — o mesmo código da
carga, sem exigir duckdb/openpyxl no Python do serviço.

- O arquivo sai em `export/relatorios/gerados/<relatorio>_<data-hora>.xlsx`, com
  carimbo no nome: duas gerações do mesmo relatório com filtros diferentes não
  se sobrescrevem, e a planilha da carga automática não é tocada.
- Uma geração por vez (as consultas varrem o lake); pedidos simultâneos recebem
  "já existe uma geração em andamento".
- Arquivos gerados sob demanda com mais de 7 dias são apagados sozinhos.
- Só entram nomes de relatório que existem em `conf/reports/` — o que vem do
  formulário nunca vira caminho nem argumento solto.

## 4. Formatos

Formato nomeado ou máscara do Excel crua (`'#,##0.000'` etc.).

| Nome | Mostra | Quando usar |
|---|---|---|
| `moeda` | `R$ 1.234,56` | valor em dinheiro |
| `numero` | `1.234,56` | quantidade fracionária |
| `inteiro` | `1.234` | contagem |
| `percentual` | `12,50%` | valor **já** multiplicado por 100 (o que a gold entrega) |
| `fracao` | `12,5%` | valor entre 0 e 1 (o Excel multiplica) |
| `data` | `13/08/2026` | data |
| `data_hora` | `13/08/2026 09:30` | data com hora |
| `mes` | `08/2026` | competência |
| `texto` | como está | código que não pode virar número |

Sem declaração, o formato é **inferido** pelo nome e pelo tipo da coluna:
`*_porcentagem` → percentual; `valor_*`, `vlr_*`, `preco`, `custo`, `lucro`,
`venda`, `desconto`, `frete` → moeda; inteiro → inteiro; data → data;
`competencia` → mês. Texto fica sem formato.

Duas armadilhas que a inferência já evita:

- **`revenda` não é dinheiro.** Contém "venda", mas é o número da loja — inteiro
  vem antes de moeda na ordem de decisão.
- **Porcentagem não é multiplicada duas vezes.** A gold entrega `12.5` para
  12,5%; o formato `%` nativo do Excel mostraria 1250%. Por isso `percentual`
  usa o `%` como literal.

Quando a inferência errar, declare em `formats` — o declarado sempre vence.

---

## 5. Totais e destaques

**Totais** usam `=SUBTOTAL(109;...)`, não `SOMA`: com o filtro da planilha
ligado, o total passa a ser o do que está sendo mostrado — que é o número que a
pessoa está olhando. A linha de total fica **fora** da faixa do filtro.

**Destaques** são condição SQL avaliada pelo próprio DuckDB sobre o resultado da
aba, então vale qualquer expressão que o SQL entenda:

```yaml
highlights:
  - when: disponivel <= 0 AND reservado > 0
    style: vermelho
  - when: desconto_porcentagem > 10
    style: amarelo
    scope: desconto_porcentagem     # pinta só a célula, não a linha
```

---

## 6. A capa

A primeira aba é sempre a **Capa**: título, descrição, data/hora da geração e
uma linha por aba com o que ela mostra e quantas linhas tem. É o que responde
"de quando é essa planilha?" para quem recebe o arquivo por e-mail ou pela rede.

---

## 7. Relatórios que já existem

| Arquivo | Relatório | Campos |
|---|---|---|
| `10_faturamento_funilaria.yml` | Faturamento - Funilaria | Data inicial, Data final, Revenda |
| `20_veiculos_novos_custeio.yml` | Veiculos-Novos-Custeio | Data inicial, Data final, Revenda |
| `30_veiculos_usados_custeio.yml` | Veiculos-Usados-Custeio | Data inicial, Data final, Revenda |
| `40_venda_direta_custeio.yml` | Venda-Direta-Custeio | Data inicial, Data final, Revenda |
| `50_balcao_pecas_faturamento.yml` | Balcao-Pecas-Faturamento | Data inicial, Data final, Revenda |

Em todos, o período é a **data de aprovação do financeiro** (nos de custeio) ou
a **data de entrada/saída** (nos de faturamento), e Revenda oferece 1, 2 ou
consolidado.

É o único no ar. Os demais estão em **`conf/reports/exemplos/`**, que a página
não lê — ficam como referência de escrita (resumo por período, detalhe linha a
linha, filtro opcional, destaque, pivô de série, consulta ao histórico diário).
Para colocar um deles no ar, mova o arquivo uma pasta acima:

```bash
git mv conf/reports/exemplos/20_oficina_producao.yml conf/reports/
```

**Uma consulta, um relatório, uma aba.** Cada linha da tela responde a uma
pergunta só; o detalhe de um resumo é outro relatório, não uma aba extra.

---

## 8. Faturamento - Funilaria: o que mudou da consulta original

O modelo `sql/gold/40_faturamento_notas.sql` traduz a consulta do Apollo com o
grão na **nota**, não no total por filial — assim a fórmula do líquido fica num
lugar só e o relatório agrega como precisar. Diferenças propositais:

1. **O período virou campo.** O original filtrava
   `BETWEEN TRUNC(SYSDATE,'MM') AND LAST_DAY(SYSDATE)` — sempre o mês corrente.
   Agora são dois campos de data na tela, já preenchidos com o primeiro e o
   último dia do mês: gerar sem mexer em nada dá o mesmo número da consulta.
2. **A loja virou seletor**: Revenda 1, Revenda 2 ou Consolidado. Empresa (`1`)
   e departamento (`410`) seguem fixos no SQL — este relatório é o da funilaria,
   e um campo que ninguém muda só ocupa a tela.
3. **Séries 03 e 08 viram uma coluna `serie`** no modelo; o relatório pivota de
   volta para as duas colunas do original.

**Uma consulta, um relatório, uma aba.** O detalhe nota a nota é um relatório
separado (`Funilaria - Notas do período`), não uma aba extra — assim cada item
da tela corresponde a uma pergunta só.
4. **Fora o `LEFT JOIN FAT_NOTAS_VENDEDOR`.** Ele não contribui com nenhuma
   coluna do `SELECT` nem do `GROUP BY` e, havendo mais de um vendedor na mesma
   nota, multiplicaria a linha e inflaria a soma.
5. **`GER_REVENDA` ligada por empresa E revenda.** O original ligava só por
   revenda, o que bastava com `EMPRESA = 1` fixo; sem esse filtro, ligar só pela
   revenda repetiria a nota uma vez por empresa.

> **Ponto em aberto:** na fórmula original, a subtração do ICMS desonerado
> aparece **duas vezes** (o primeiro e o quarto `CASE` são idênticos). Parece
> engano de cópia, mas mexer nisso mudaria o número que a empresa usa hoje —
> então foi mantida, com o bloco marcado no SQL. Para cobrar uma vez só, apague
> o bloco entre os comentários `>>> bloco repetido do original <<<`.

## 9. Custeio de veículos: o que mudou das consultas originais

Os três relatórios de custeio saem de dois modelos: `veiculos_custeio` (grão de
proposta × linha de fórmula) e `veiculos_custeio_nota`, que acrescenta a nota
fiscal. O **pivô** — uma coluna por linha de fórmula — fica no relatório, não no
modelo: cada consulta pivota a sua lista, e a lista muda com o tempo.

1. **Sem intervalo fixo**: a data de aprovação virou campo na tela.
2. **Vendedor por `LEFT JOIN`.** No original era `INNER`: proposta cujo vendedor
   não estivesse no cadastro sumia da consulta inteira — junto com o dinheiro
   dela. Com `LEFT`, a linha aparece e só o nome fica vazio.
3. **A capa da nota é ligada também por empresa e revenda**, não só pelo número.
   Número de nota se repete entre filiais e séries; ligando só pelo número, a
   consulta podia pegar a nota de outra loja — e com ela um `STATUS` que não era
   o daquela venda.
4. **`FAT_VENDEDOR` ligado por empresa, revenda e vendedor** (a consulta de
   venda direta já fazia assim; as de novos e usados ligavam só pelo código).

> **Duas colunas que nunca teriam valor.** Na consulta de veículos novos, o
> `WHERE` filtra `'Bonus Interno'` e `'Bonus Troca'` **sem acento**, enquanto o
> `PIVOT` procura `'Bônus Interno'` e `'Bônus Troca'` **com acento** — nenhuma
> linha satisfaz as duas coisas, então essas colunas sairiam sempre vazias.
> Aqui as duas grafias caem na mesma coluna. Se no ERP só existir uma delas, o
> resultado é o mesmo; se existirem as duas, agora somam na coluna certa.

## 10. Solução de problemas

| Sintoma | Causa | O que fazer |
|---|---|---|
| Relatório sai como `skipped` | cita um modelo que ainda não existe na gold | rode a carga; confira `datalake query "SELECT * FROM gold.<modelo> LIMIT 1"` |
| `coluna de total inexistente` | nome em `totals` não está no SELECT da aba | use o **alias** da coluna, como ela aparece no cabeçalho |
| Coluna aparece como texto no Excel | valor não numérico vindo da gold | acerte o `CAST` no modelo gold; formato não converte texto em número |
| `R$` numa coluna que é código | o nome bateu com uma pista de dinheiro | declare `formats: {coluna: inteiro}` (ou `texto`) |
| Porcentagem 100× maior | valor entre 0 e 1 com formato `percentual` | use `fracao` |
| Muitas linhas | limite físico do xlsx (1.048.575 por aba) | agregue na aba, use `limit`, ou leve o detalhe pelo `datalake export -f csv` |
| Página `/gerar` diz que não achou o projeto | o servidor não encontrou o `pyproject.toml` sob `C:\datalake\app` | suba o serviço com `--projeto <caminho da pasta datalake>` |
| "Já existe uma geração em andamento" | outra pessoa está gerando | espere terminar; é uma de cada vez, de propósito |
| Parâmetro recusado | formato do valor | a mensagem diz o formato esperado (ex.: `AAAA-MM`) |

---

## 11. Onde está o código

- `src/datalake/report.py` — leitura do YAML, parâmetros, execução, escrita do xlsx.
- `sql/gold/60_margem_pecas.sql` — grão de **dia** (era mês), para o filtro de
  período funcionar de verdade. Somar os dias de um mês dá exatamente o total
  mensal de antes; as porcentagens saem do relatório, sobre a soma do período.
- `scripts/servir_pagina.py` — a tela inicial e a chamada do `datalake report`.
  Os campos de cada relatório vêm de `datalake report --list --json`: o formato
  fica definido num lugar só, e um tipo novo de campo aparece na tela sem mexer
  no servidor.
- `conf/reports/*.yml` — as definições.
- `tests/test_report.py` — testes (inferência de formato, capa, totais, destaque).
