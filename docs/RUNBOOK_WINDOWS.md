# Runbook — rodar a migração na máquina Windows

Roteiro operacional das fases 3 a 5. O documento de estratégia é o
[`MIGRACAO_DATALAKE.md`](MIGRACAO_DATALAKE.md); aqui é só a sequência de
comandos, na ordem, com o que costuma dar errado em cada um.

Tudo abaixo roda na **sua máquina**, não numa sessão remota do Claude Code:
a exportação precisa de credencial de escrita e o destino é o seu disco.

---

## Antes de começar

| Requisito | Como conferir |
| --- | --- |
| Google Cloud CLI (`gcloud` e `bq`) | `gcloud version` |
| Sessão autenticada | `gcloud auth list` |
| ~15 GB livres no disco de destino | Parquet (~5 GB) + bucket (0,8 GB) + DuckDB (~5 GB) |
| Python 3 com as dependências | `pip install -r requirements.txt duckdb` |

Se acabou de instalar o Cloud CLI, **abra um PowerShell novo** — o script
checa `gcloud` no PATH e o PATH só atualiza em processo novo.

### Duas autenticações, não uma

São mecanismos separados, e confundir os dois custa meia hora de erro
confuso — `gcloud auth login` **não** autentica os scripts Python.

```powershell
gcloud auth login                      # o CLI: gcloud, bq, Migrar-Datalake.ps1
gcloud auth application-default login  # as bibliotecas Python: os scripts .py
```

Se algum script Python reclamar de quota project:

```powershell
gcloud auth application-default set-quota-project tterrasul-datalake
```

> **A `claude-leitor` não serve para a fase 3.** Ela é somente leitura de
> propósito, e `bq extract` escreve no staging. Use a sua conta.
>
> E para os scripts de leitura (`mapear_dependencias.py`, `conferir_views.py`)
> a sua conta é mais simples que a service account: como você é dono do
> projeto, já tem o `bigquery.jobs.listAll` que o histórico de jobs exige, sem
> precisar conceder papel nenhum. A `GCP_SA_KEY_B64` só é necessária onde não
> dá para fazer login interativo — numa sessão remota, por exemplo.

---

## Passo 0 — Criar o bucket de staging na região certa

O script **não cria** o staging, e essa é a falha mais provável de toda a
operação: `bq extract` recusa staging em região diferente do dataset. Os
datasets estão em `southamerica-east1`. Um bucket criado no padrão (US) faz
as 848 exportações falharem uma a uma.

```powershell
gcloud storage buckets create gs://tterrasul-export-tmp `
    --project=tterrasul-datalake `
    --location=southamerica-east1
```

Confira antes de seguir — vale mais que os cinco segundos que custa:

```powershell
gcloud storage buckets describe gs://tterrasul-export-tmp --format="value(location)"
# tem que responder: SOUTHAMERICA-EAST1
```

---

## Passo 1 — Pôr as 11 views em lugar seguro

Elas foram baixadas em 12/08 para
`Downloads/metadados-bq-20260812-191305/gold/views/`. Uma pasta de Downloads
não é lugar para o único artefato da migração que não tem como gerar de novo:
some numa limpeza de disco e não há de onde recuperar depois que o projeto for
excluído.

Mova para um repositório privado ou um backup antes de qualquer outra coisa.
**Não** para este repositório — `Fersouro/Fersouro` é o seu perfil público do
GitHub.

Se os arquivos se perderam, gere de novo enquanto o projeto existe:

```powershell
bash scripts/bq_export_metadata.sh tterrasul-datalake lake gold
```

---

## Passo 2 — Ensaio, sem exportar nada

`-SomenteVerificar` lista as tabelas, grava os manifestos e para. Serve para
confirmar acesso e contagem antes de disparar horas de trabalho.

```powershell
.\scripts\Migrar-Datalake.ps1 -Projeto tterrasul-datalake `
    -Staging gs://tterrasul-export-tmp `
    -Destino D:\datalake `
    -SomenteVerificar
```

Espere `848 tabelas` em `lake` e `2 tabelas` em `gold` (as 11 views não
aparecem — não têm dados a exportar; `type = 1` filtra só `BASE TABLE`).

---

## Passo 3 — Exportar e baixar

```powershell
.\scripts\Migrar-Datalake.ps1 -Projeto tterrasul-datalake `
    -Staging gs://tterrasul-export-tmp `
    -Bucket gs://tterrasul-datalake-lake `
    -Destino D:\datalake
```

**Conte com algumas horas, não minutos.** O volume é pequeno (~5,6 GB), mas
são 850 `bq extract` disparados **em sequência**, cada um com o custo de subir
o CLI e esperar o job. O gargalo é o número de operações, não os bytes.

É retomável: tabelas já exportadas são puladas por checagem no staging. Se
cair a rede, a VPN ou a energia, rode de novo o mesmo comando.

Se terminar com falhas, os nomes ficam em
`D:\datalake\_migracao-<carimbo>\falhas-lake.txt` e o script sai com código 1.
Rodar de novo refaz só o que faltou.

---

## Passo 4 — Carregar no DuckDB

```powershell
python scripts\carregar_duckdb.py D:\datalake `
    --views D:\views\gold `
    --saida D:\datalake\datalake.duckdb
```

Confere cada tabela contra o `row_count` de origem gravado no manifesto — é
essa comparação que transforma "os arquivos estão lá" em verificação.

As views entram traduzidas só na parte mecânica. O que o tradutor não resolve
sai listado como ressalva, e **é trabalho seu decidir cada uma**: `SAFE_DIVIDE`,
`PARSE_DATE`, `FORMAT_DATE` e companhia mudam resultado em silêncio se
ajustadas errado.

---

## Passo 5 — Congelar as escritas

Antes de verificar as views, pare quem escreve. Verificação sobre alvo em
movimento não vale nada.

Se ainda não rodou o mapeamento, é agora:

```powershell
python scripts\mapear_dependencias.py --projeto tterrasul-datalake
```

Ele diz quem escreve e quem só lê. Pare o que escreve — na origem do
pipeline, não revogando permissão no meio, que só produz erro em produção sem
avisar ninguém.

---

## Passo 6 — Conferir as views contra a origem

Com o alvo já estático, e **enquanto o BigQuery ainda existe**:

```powershell
python scripts\conferir_views.py bigquery --dataset gold --saida D:\views\perfil-bq.json
python scripts\conferir_views.py duckdb D:\datalake\datalake.duckdb --comparar-com D:\views\perfil-bq.json
```

Antes de rodar o primeiro, `--estimar` faz um dry run e diz quantos bytes cada
perfil leria, sem executar nem cobrar — as views do `gold` cobrem as 848
tabelas do bronze, então vale olhar a conta:

```powershell
python scripts\conferir_views.py bigquery --dataset gold --estimar
```

Sai com código 1 e lista view, coluna, métrica e os dois valores em cada
divergência. Enquanto houver divergência, não avance para a fase 6.

Guarde o `perfil-bq.json` junto com os `.sql`: depois da exclusão do projeto
ele é a única descrição do que as views respondiam.

---

## Passo 7 — Limpar o staging

O staging guarda uma segunda cópia de tudo dentro do GCP e continua sendo
cobrado enquanto existir. Só apague depois da verificação passar:

```powershell
gcloud storage rm -r gs://tterrasul-export-tmp
```

---

## Custos

| Item | Ordem de grandeza |
| --- | --- |
| Egress de ~5,6 GB (São Paulo → internet) | poucos dólares |
| Storage do staging (~5 GB no GCS) | centavos por dia, até apagar |
| Queries do `--estimar` | zero — dry run não executa |
| Queries do perfil das views | pagas por bytes lidos; use `--estimar` antes |

---

## Quando algo falha

| Sintoma | Causa provável |
| --- | --- |
| `bq extract` falha em todas as tabelas | staging em região diferente de `southamerica-east1` (passo 0) |
| `'gcloud' nao encontrado` | PowerShell aberto antes de instalar o CLI — abra outro |
| `Nenhuma conta autenticada` | falta `gcloud auth login` |
| Script Python diz "Nenhuma credencial encontrada", mas o `bq` funciona | falta `gcloud auth application-default login` — são autenticações separadas |
| `403` no histórico de jobs | a identidade não tem `bigquery.jobs.listAll`; o script imprime o comando que concede |
| Falha só em algumas tabelas | rode o mesmo comando de novo; ele pula o que já foi |
| Verificação acusa tabela sem arquivo | a pasta existe mas o extract não gerou nada — rode de novo |
| `conferir_views` acusa divergência em tudo | escritas não foram congeladas (passo 5) — o perfil e o Parquet descrevem estados diferentes |
