# Oracle → CSV, em 3 passos

## Passo 1 — abrir e adaptar

Abra `export_csv_oracle.sql`. Troque só as linhas marcadas `-- <<< ADAPTAR`:
nomes reais da tabela de saldo, do cadastro de peças, da chave do join e da
coluna de revenda. **Nada mais precisa mudar.**

## Passo 2 — rodar e salvar

Escolha UM dos caminhos.

### SQL Developer (o mais fácil, tudo no mouse)

1. Cole a query e execute (F5).
2. Botão direito na grade de resultados → **Export…**
3. Format: **csv** · Delimiter: **;** · Encoding: **UTF-8** · Left/Right Enclosure: **nenhum**
4. Salve como `estoque_revenda1.csv`.

### SQLcl ou SQL*Plus 12.2+ (sai pronto, sem clicar)

```sql
SET MARKUP CSV ON DELIMITER ; QUOTE OFF
SET FEEDBACK OFF
SET PAGESIZE 0
SET TERMOUT OFF
SPOOL estoque_revenda1.csv
@export_csv_oracle.sql
SPOOL OFF
```

Depois abra o arquivo e apague a última linha se vier em branco.

### Se o Oracle for Autonomous / ADW no OCI

Mesma query. Exporte pelo **Database Actions → SQL**, botão de download do
resultado, escolhendo CSV com separador `;`.

## Passo 3 — me mandar

Anexe o `.csv` aqui na conversa. Se for grande, suba no Google Drive e me passe
o link — eu leio de lá.

---

## Cuidados que salvam retrabalho

- **Codificação UTF-8.** Em Latin-1 a acentuação vira lixo na planilha.
- **Sem aspas** em volta dos campos (QUOTE OFF / Enclosure nenhum).
- **Cabeçalho na primeira linha**, exatamente:
  `codigo_peca;descricao_peca;estoque_atual;estoque_minimo`
- Se a sua ferramenta só exportar com vírgula, tudo bem — **me avise** que eu
  ajusto o gerador em vez de você mexer no arquivo.

## Uma decisão antes de rodar

O filtro `estoque_atual <= estoque_minimo` está **ligado**: traz só o que precisa
de compra. Comente aquela linha se quiser o retrato completo, com os itens `Ok`.
