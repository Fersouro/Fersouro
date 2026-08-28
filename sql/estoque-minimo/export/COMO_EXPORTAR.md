# Como gerar o CSV e me devolver

O gerador da planilha espera **exatamente** este formato:

```
codigo_peca;descricao_peca;estoque_atual;estoque_minimo
5Z0820411E;Filtro de ar condicionado;0;2
05E145933;;8;15
```

Separador `;` · codificação **UTF-8** · cabeçalho na primeira linha · sem aspas ·
descrição pode vir vazia (o gerador marca a peça, não quebra).

---

## Opção 1 — SSMS (SQL Server), a mais simples

1. Abra `export_csv_sqlserver.sql` e troque as 4 linhas `-- <<< ADAPTAR` pelos
   nomes reais das suas tabelas e colunas.
2. Execute.
3. Clique com o botão direito na grade → **Save Results As…** → salve como `.csv`.
4. Antes, garanta o separador `;`:
   `Tools → Options → Query Results → SQL Server → Results to Text → Custom delimiter: ;`
   (ou salve com vírgula e me avise — eu ajusto o gerador).

## Opção 2 — sqlcmd (linha de comando, já sai pronto)

```cmd
sqlcmd -S SEU_SERVIDOR -d SUA_BASE -E -f 65001 -s";" -W -h-1 ^
       -i export_csv_sqlserver.sql -o estoque_revenda1.csv
```

- `-f 65001` = UTF-8, senão acentuação vira lixo
- `-s";"` = separador ponto-e-vírgula
- `-W` = tira o preenchimento de espaços à direita
- `-h-1` = suprime o cabeçalho automático — **acrescente a primeira linha
  `codigo_peca;descricao_peca;estoque_atual;estoque_minimo` à mão**, ou tire o
  `-h-1` e apague a linha de tracinhos que o sqlcmd insere abaixo do cabeçalho.

## Opção 3 — Firebird

Use `export_csv_firebird.sql` no IBExpert, FlameRobin ou DBeaver e exporte o
resultado como CSV, marcando separador `;` e codificação UTF-8.

Via `isql`, o mais prático é exportar pelo DBeaver — o `isql` formata em colunas
fixas e daria trabalho para limpar.

## Opção 4 — Power BI

Se a consulta já existe num relatório: selecione a tabela → **Exportar dados** →
`.csv`. Confira depois se o separador saiu `;` (padrão no Windows em pt-BR) e se
a codificação é UTF-8.

---

## O que fazer com o arquivo

Me mande de uma destas formas:

- **anexe o `.csv`** aqui na conversa; ou
- **cole o conteúdo** direto no chat (até algumas centenas de linhas é tranquilo); ou
- se for grande, **suba no Google Drive** e me passe o link — eu tenho acesso ao
  seu Drive e leio de lá.

Aí eu rodo:

```bash
python gerar_xls_estoque_minimo.py <seu_arquivo>.csv Estoque_Minimo_Revenda1.xlsx \
       --revenda 1 --fator 1.0
```

e devolvo a planilha com **saldo real**, déficit verdadeiro, as rupturas no topo
em vermelho e a descrição vinda do seu cadastro — e mando por e-mail se você quiser.

## Antes de rodar, decida uma coisa

O filtro `estoque_atual <= estoque_minimo` vem **ligado** nas duas queries: traz só
o que precisa de compra. Comente essa linha se quiser o retrato completo (com os
itens `Ok`) — é o que serve para dashboard de "% de itens em ruptura".
