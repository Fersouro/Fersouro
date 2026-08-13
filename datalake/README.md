# Datalake local — Oracle → Parquet → Power BI

Datalake on-premise em arquitetura medalhão, sem nuvem e sem cluster: **Python +
DuckDB + Parquet**. Roda igual em Linux e Windows, o único requisito é Python 3.10+.

```
Oracle ──► BRONZE ──────► SILVER ─────────► GOLD ──────► Power BI / DuckDB
           cópia fiel     1 linha por       modelos      lake.duckdb
           particionada   chave, colunas    de negócio   ou pasta Parquet
           por data       normalizadas      em SQL
```

| Camada | O que é | Formato |
|---|---|---|
| **bronze** | Cópia fiel da origem + colunas de auditoria. Append-only, particionada por data de ingestão. | `data/bronze/<fonte>/<tabela>/_ingest_date=YYYY-MM-DD/*.parquet` |
| **silver** | Uma linha por chave primária, nomes em `snake_case`, deduplicada. | `data/silver/<fonte>/<tabela>/data.parquet` |
| **gold** | Fatos e dimensões definidos em SQL puro, prontos para dashboard. | `data/gold/<modelo>/data.parquet` |

---

## Começando em 3 minutos

```bash
cd datalake
make setup                       # instala as dependências
make demo                        # gera dados fictícios e roda o pipeline inteiro
```

`make demo` cria uma base DuckDB de mentira com clientes/pedidos/itens e executa
bronze → silver → gold → qualidade → catálogo. Serve para conhecer o fluxo antes
de apontar para o Oracle de verdade. Para ver o incremental funcionando:

```bash
make demo-incremental            # insere 200 pedidos, altera 50, roda de novo
python3 -m datalake.cli state    # mostra os watermarks e quantas linhas vieram
```

---

## Ligando no Oracle

**1. Credenciais** — copie `.env.example` para `.env` e preencha:

```ini
ORACLE_ERP_DSN=192.168.0.10:1521/ORCLPDB1
ORACLE_ERP_USER=datalake_ro
ORACLE_ERP_PASSWORD=...
```

O `.env` está no `.gitignore`. Use um usuário **somente leitura** — o datalake
nunca escreve na origem.

**2. Tabelas** — edite `conf/sources/oracle_erp.yml`:

```yaml
tables:
  - name: PEDIDOS
    load_mode: incremental         # full | incremental
    primary_key: [ID_PEDIDO]
    watermark_column: DT_ATUALIZACAO
    watermark_type: timestamp
    lookback: 1                    # reprocessa 1 dia antes do último watermark
    columns: [ID_PEDIDO, ...]      # opcional: projeção
    filter: "SITUACAO <> 'X'"      # opcional: entra no WHERE
    column_types:                  # opcional: sobrescreve o tipo inferido
      VLR_UNITARIO: decimal(18,4)
```

**3. Rodar**:

```bash
python3 -m datalake.cli test-connection -s oracle_erp
python3 -m datalake.cli run -s oracle_erp
```

Na primeira execução não existe watermark, então toda tabela vem inteira. Das
próximas em diante só entra o que mudou.

### Não sabe quais tabelas configurar? Deixe o `discover` montar o YAML

```bash
# 1. quais schemas o usuário enxerga
python3 -m datalake.cli discover -s oracle_erp --schemas

# 2. o que existe dentro de um schema (linhas, PK, candidatas a watermark)
python3 -m datalake.cli discover -s oracle_erp --schema ERP

# 3. gera a configuração já preenchida
python3 -m datalake.cli discover -s oracle_erp --schema ERP \
        --filter 'PED%' --write conf/sources/oracle_erp.yml --force
```

O `discover` lê `all_tables`, `all_tab_columns` e `all_constraints` e propõe,
para cada tabela: chave primária (a declarada no banco), coluna de watermark (por
nome — `DT_ATUALIZACAO`, `UPDATED_AT`, ...) e modo de carga (`full` até ~200 mil
linhas, `incremental` acima disso quando há PK e coluna de data).

**São sugestões, baseadas em nome e volume — não em regra de negócio.** Revise
antes de rodar o `ingest`, principalmente as tabelas que saírem marcadas como
"sem PK declarada".

### Quando a conexão falha

O erro já vem com o diagnóstico e a próxima ação. Os três casos comuns:

| Sintoma | Causa |
|---|---|
| `DPY-6005` / timeout | Não há rota TCP até o host — rede, VPN ou firewall. Acontece **antes** de validar usuário e senha. |
| `ORA-12514` | O listener respondeu mas não conhece o `service_name` (confira com `lsnrctl services` — é service_name, não SID). |
| `ORA-01017` | Usuário ou senha inválidos. |

O timeout de conexão é 15s por padrão; ajuste com `tcp_connect_timeout` no bloco
`connection` da fonte.

### thin vs thick

O modo padrão (**thin**) fala o protocolo Oracle direto em Python — não precisa
instalar o Instant Client. Use `thick_mode: true` só se precisar de
`tnsnames.ora`, wallet ou charset legado; aí informe também o `lib_dir`.

---

## Comandos

| Comando | O que faz |
|---|---|
| `init` | Cria os diretórios e o banco de controle |
| `sources` | Lista fontes e tabelas configuradas |
| `test-connection` | Testa a conexão e mostra versão/banco/usuário |
| `discover` | Lê o dicionário de dados e gera o YAML da fonte |
| `ingest` | Origem → bronze (`--full` ignora o watermark, `--dry-run` só conta) |
| `silver` | Bronze → silver |
| `gold` | Silver → gold (`-m modelo` roda um só) |
| `quality` | Testes de qualidade sobre a silver |
| `catalog` | Atualiza `data/lake.duckdb` |
| `run` | Pipeline completo, tudo com o mesmo `run_id` |
| `state` | Watermarks e histórico de execuções |
| `reset` | Zera o watermark de uma tabela (força recarga total) |
| `query "SQL"` | Consulta rápida sobre silver e gold |

Todos aceitam `-s/--source` e `-t/--table` (repetível). Código de saída: `0` ok,
`1` alguma etapa falhou, `2` erro de configuração — o que torna o `run` direto de
usar no agendador.

---

## Carga incremental: como o watermark funciona

1. O controle guarda o **maior valor** da `watermark_column` já ingerido.
2. A próxima carga filtra `WHERE watermark_column > :ultimo_valor`.
3. `lookback` recua essa janela (em dias) antes de comparar. Isso cobre a
   transação que estava aberta durante a carga anterior e gravou com data
   anterior ao fim dela — sem lookback, essa linha nunca seria vista.
4. As linhas repetidas que o lookback traz de volta são inofensivas: a silver
   deduplica pela chave primária.

Se a coluna de watermark não for confiável, use `load_mode: full` — para tabelas
de cadastro isso costuma custar segundos.

**Quando a versão de uma chave se repete**, vence a mais recente por
`watermark_column`, depois por `_ingested_at` e, em último caso, pela posição
física na bronze (arquivo + linha). O critério é determinístico: rodar de novo
sobre os mesmos dados dá exatamente o mesmo resultado.

---

## Modelos gold

Cada arquivo `sql/gold/*.sql` vira um dataset com o nome do arquivo (sem o
prefixo numérico). Antes de executar, o motor registra uma view por tabela da
silver:

- `<fonte>__<tabela>` — sempre;
- `<tabela>` — quando o nome não se repete entre as fontes.

Modelos já construídos na mesma execução também viram view, então um arquivo pode
usar outro como insumo. A ordem é alfabética — daí o prefixo numérico:

```
sql/gold/10_dim_cliente.sql        →  gold.dim_cliente
sql/gold/20_fato_vendas.sql        →  gold.fato_vendas
sql/gold/30_vendas_mensais_uf.sql  →  gold.vendas_mensais_uf   (usa fato_vendas)
```

Para lógica específica na silver, crie `sql/silver/<fonte>__<tabela>.sql` usando
`{{bronze}}` no lugar da origem — o arquivo substitui o SQL gerado.

---

## Qualidade

Declarada no YAML da tabela, executada sobre a silver e gravada no banco de
controle:

```yaml
quality:
  severity: error        # error faz o comando falhar; warn só avisa
  not_null: [id_pedido, dt_pedido]
  unique: [id_pedido]                  # lista simples = chave composta
  unique: [[id_pedido], [nr_nota]]     # lista de listas = várias chaves
  row_count_min: 1
  accepted_values:
    situacao: [A, C, X]
  freshness:
    column: dt_atualizacao
    max_age_hours: 26
  custom:
    - name: valor_nao_negativo
      sql: SELECT count(*) FROM {{silver}} WHERE vlr_total < 0
```

Em `custom` o SQL devolve um número e o esperado é zero.

---

## Consumindo no Power BI

**Opção 1 — pasta Parquet (mais simples).** Obter Dados → Parquet → aponte para
`data/gold/<modelo>/data.parquet`. Sem driver, sem configuração.

**Opção 2 — DuckDB via ODBC.** Instale o driver ODBC do DuckDB e aponte para
`data/lake.duckdb`. Aí todos os modelos aparecem como tabelas nos schemas
`silver` e `gold`, e dá para consultar antes de importar:

```sql
SELECT * FROM gold.vendas_mensais_uf;
```

Em ambos os casos o Power BI lê **arquivo**, não o Oracle: o refresh do relatório
não toca no banco de produção.

---

## Agendamento

**Linux (cron)** — todo dia às 3h:

```cron
0 3 * * * cd /srv/datalake && /usr/bin/python3 -m datalake.cli run >> logs/cron.log 2>&1
```

**Windows (Agendador de Tarefas)** — ação: `python.exe`, argumentos
`-m datalake.cli run`, iniciar em `D:\datalake`.

Como o `run` devolve código de saída diferente de zero quando algo falha, o
agendador consegue distinguir sucesso de falha sem ninguém ler log.

---

## Estrutura

```
datalake/
├── conf/
│   ├── settings.yml            # raiz do lake, memória, compressão, log
│   └── sources/
│       ├── oracle_erp.yml      # a fonte de verdade
│       └── demo_erp.yml        # base fictícia para testes
├── sql/
│   ├── silver/                 # overrides opcionais por tabela
│   └── gold/                   # modelos de negócio
├── src/datalake/
│   ├── cli.py                  # comandos
│   ├── config.py               # YAML + variáveis de ambiente
│   ├── duck.py                 # conexões DuckDB e snake_case
│   ├── connectors/             # oracle, duckdb
│   ├── layers/                 # bronze, silver, gold
│   ├── quality/                # testes declarativos
│   ├── state/                  # watermarks e histórico
│   ├── storage/                # layout de pastas e escrita Parquet
│   └── catalog/                # lake.duckdb
├── scripts/seed_demo.py
├── tests/
└── data/                       # gerado; fora do git
```

---

## Decisões de projeto

**Por que DuckDB e não Spark?** Até algumas dezenas de milhões de linhas, DuckDB
resolve num único processo, sem JVM, sem cluster e sem tuning. Spark só compensa
quando os dados não cabem numa máquina.

**Por que Parquet e não um banco?** Parquet é colunar, comprimido e lido por
praticamente tudo (DuckDB, Power BI, pandas, Spark). O lake não fica preso a
nenhum motor — trocar DuckDB por outra coisa não exige migrar dado nenhum.

**Por que a bronze não é transformada?** Porque quando a regra de negócio muda —
e ela muda — a silver é reconstruída a partir da bronze sem tocar no Oracle de
novo. Bronze é o seguro contra retrabalho de extração.

**Por que escrever em `.staging` e só depois promover?** Uma queda de rede no
meio da carga deixaria arquivos parciais que o Power BI leria como dados válidos.
Com a promoção no final, ou a carga inteira aparece, ou nada aparece.

---

## Próximos passos possíveis

- Detecção de exclusões (hoje um DELETE na origem não some da silver — a saída
  usual é uma carga `full` periódica ou uma tabela de log de exclusão);
- particionamento da silver por competência nas tabelas muito grandes;
- SCD tipo 2 nas dimensões que precisam de histórico;
- notificação (e-mail/Telegram) quando um teste de qualidade reprovar.
