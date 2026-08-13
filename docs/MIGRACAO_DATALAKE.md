# Migração do datalake GCP → máquina local

## Estado: fases 1 e 2 concluídas

Projeto do datalake: **`tterrasul-datalake`** (conta `fernando@tterrasul.com.br`).

> O primeiro inventário rodou em `carbon-virtue-504415-a4`, que é o
> "My First Project" criado por padrão pelo GCP e não contém nada. Ao rodar
> com `--project=tterrasul-datalake` o conteúdo real apareceu.

| Recurso | Conteúdo |
| --- | --- |
| `gs://tterrasul-datalake-lake` | 874.523.665 bytes (~834 MB, Parquet comprimido) |
| Dataset `lake` (bronze) | 848 tabelas **nativas** |
| Dataset `gold` | 11 views + 2 tabelas nativas |

Região dos datasets: `southamerica-east1`.

### Já feito

- Inventário completo levantado
- 848 tabelas confirmadas nativas, volume medido
- **11 views do `gold` extraídas e baixadas** para a máquina do operador
  (`Downloads/metadados-bq-20260812-191305/gold/views/`) — este era o único
  artefato irreproduzível da migração
- Service account `claude-leitor@tterrasul-datalake.iam.gserviceaccount.com`
  criada, somente leitura (objetos do Storage, dados do BigQuery, jobs do
  BigQuery), com a chave registrada como `GCP_SA_KEY_B64` no ambiente

### Falta

1. Exportar as 850 tabelas e baixar (`Migrar-Datalake.ps1`, no Windows)
2. Carregar no DuckDB (`carregar_duckdb.py`)
3. **Traduzir as 11 views** do dialeto BigQuery — o trabalho residual real
4. Mapear as dependências vivas (abaixo) antes de desativar qualquer coisa

---

## Dependências vivas — mapear antes da fase 5

O projeto tem outras service accounts com chave ativa, descobertas por acaso
ao criar a `claude-leitor`. Cada uma indica um sistema que consome ou alimenta
o datalake e que **quebra se o projeto for excluído**:

| Conta de serviço | Indício |
| --- | --- |
| `datalake-automacao` | Alimenta as 848 tabelas do bronze. Se rodar durante a exportação, a cópia nasce desatualizada. |
| `portal-relatorios` | "Portal de Relatórios TerraSul" — aplicação provavelmente em produção consumindo o datalake. |

Perguntas em aberto para ambas: onde rodam, quem usa, e se consultam o
BigQuery diretamente. Se o portal consulta direto, ele precisa ser reapontado
para o DuckDB — e as consultas dele têm o mesmo problema de dialeto das views.

Migrar os dados sem resolver isso faz a migração "concluir com sucesso" e
derrubar um sistema em produção.

### Como responder: `mapear_dependencias.py`

O histórico de jobs do BigQuery guarda 180 dias e é evidência, não suposição.
`mapear_dependencias.py` lê `INFORMATION_SCHEMA.JOBS_BY_PROJECT` e produz um
relatório com:

- **todos** os principais que tocaram o projeto — não só as duas contas que
  apareceram por acaso
- quem só **lê** (reapontar para o DuckDB) versus quem também **escreve**
  (parar na fase 5) — a distinção importa, porque a ação é oposta
- as tabelas que cada consumidor lê, ou seja, o que exatamente quebra
- a distribuição horária das escritas, que define a janela em que exportar
  não produz cópia desatualizada
- quantas consultas dos consumidores usam construções que não sobrevivem ao
  DuckDB, pela mesma lista que governa a tradução das views

```bash
python scripts/mapear_dependencias.py --projeto tterrasul-datalake
```

Ele **não** responde onde cada sistema roda: o histórico registra a
identidade, não a máquina. Para cada principal do relatório, rastreie onde a
chave da service account foi instalada — isso continua sendo trabalho manual,
e é pré-requisito da fase 6.

> `JOBS_BY_PROJECT` exige `bigquery.jobs.listAll`, que a permissão de leitura
> de dados não inclui. Se a `claude-leitor` ainda não tiver, conceda
> `roles/bigquery.resourceViewer` — continua sendo somente leitura. O script
> imprime o comando exato quando esbarra nisso.

> **Não versione a saída.** Com `--incluir-sql` o relatório inclui o SQL das
> aplicações, que é lógica de negócio, pela mesma razão que vale para as views.
> `.gitignore` já cobre `dependencias-*/`.

## Regra que governa todo o resto

> A exclusão da conta é irreversível e é o **último** passo.
> Nada é apagado antes da cópia estar verificada por checksum.

Projetos GCP excluídos entram num período de recuperação de aproximadamente
30 dias antes da destruição definitiva. É uma rede de segurança contra
engano, não uma etapa do plano.

---

## Fase 2 — Dimensionamento

O bucket é trivial: 834 MB significa espaço irrelevante, egress de centavos e
minutos de transferência. Transfer Appliance e migração por lotes estão
descartados para essa parte.

**Mas o bucket não é o datalake.** As 848 tabelas do `lake` e as 2 do `gold`
são `BASE TABLE` — **nativas**, não externas. Nenhuma URI `gs://` apareceu em
850 DDLs inspecionados.

Isso significa:

- Os 834 MB de Parquet no bucket são um componente, não o todo
- Cada uma das 850 tabelas tem storage próprio no BigQuery e precisa ser
  exportada individualmente
- O BigQuery guarda **5.174.505.016 bytes (~4,82 GiB)** em 22.877.524 linhas

### Volume total

| Origem | Bytes | Proporção |
| --- | --- | --- |
| Bucket (Parquet) | 874.523.665 | 14% |
| BigQuery (848 tabelas) | 5.174.505.016 | 86% |
| **Total** | **~5,6 GB** | |

Continua tratável: cabe em qualquer disco, egress de poucos dólares,
transferência em minutos. **O desafio não é volume — é o número de
operações.** São 848 exportações individuais, e é aí que a fase 3 pode
falhar parcialmente e passar despercebida.

---

## O maior risco desta migração: os 11 views

**Views não são dados. São definições SQL.**

Exportar o dataset `gold` como se fossem tabelas materializa o resultado
atual e **descarta a lógica que o produz**. Num datalake em camadas, essas 11
definições são a regra de negócio destilada — quase sempre o ativo mais
valioso e o mais fácil de perder, porque uma exportação "bem-sucedida"
devolve dados com aparência correta.

Os 834 MB de Parquet são reproduzíveis a partir da origem. As 11 views, não.

`bq_export_metadata.sh` salva cada uma como `.sql`. **Faça isso antes de
qualquer exportação de dados.**

> **Não versione essas views neste repositório.** `Fersouro/Fersouro` é o
> repositório público do perfil do GitHub — commitar o DDL ali publicaria a
> lógica de negócio do datalake. Guarde num repositório privado, ou baixe
> para uma máquina sua.

---

## Onde rodar

**Use a máquina Windows, não o Cloud Shell.** O Cloud Shell reciclou o
contêiner e perdeu as credenciais três vezes durante este trabalho — no meio
de uma exportação de 848 tabelas isso custa caro. A máquina de destino já tem
o gcloud e é onde os dados precisam chegar de qualquer forma.

**As sessões remotas do Claude Code também não servem para rodar isso.** O
contêiner delas não recebe `GCP_SA_KEY_B64` — a variável precisa estar
configurada no *ambiente* da sessão, não no repositório — e não traz `gcloud`,
`bq` nem `gsutil`. Os scripts em Python funcionam lá se a credencial for
provisionada no ambiente; os `.sh` e o `.ps1`, não. Escrever e revisar os
scripts é o que a sessão remota faz bem; executá-los contra o GCP é trabalho
da sua máquina.

```powershell
.\scripts\Migrar-Datalake.ps1 -Projeto tterrasul-datalake `
    -Staging gs://tterrasul-export-tmp `
    -Bucket gs://tterrasul-datalake-lake `
    -Destino D:\datalake
```

Os scripts `.sh` continuam válidos para quem estiver em Linux ou WSL.

O roteiro operacional completo — pré-requisitos, ordem dos passos e o que
costuma falhar em cada um — está em [`RUNBOOK_WINDOWS.md`](RUNBOOK_WINDOWS.md).

---

## Fase 3 — Cópia

**Bucket** (retomável, mas com 834 MB tende a terminar de primeira):

```bash
gcloud storage rsync -r gs://tterrasul-datalake-lake ./datalake/lake
```

**BigQuery — 850 tabelas nativas.** Não há atalho: cada tabela precisa de
`bq extract` para o GCS e depois download. Use **Parquet ou Avro, nunca CSV**
— CSV perde tipos, precisão numérica e estrutura aninhada.

Atenção: `bq extract` **escreve** no seu bucket (é o único passo da migração
que não é somente-leitura), e tabelas acima de 1 GB são divididas em vários
arquivos por exigência do BigQuery. Ambos precisam ser considerados na
verificação.

---

## Destino: DuckDB

Os dados aterrissam num banco DuckDB — arquivo único, sem servidor, que lê
Parquet nativamente e cujo SQL é o mais próximo do BigQuery entre as opções
locais. Para 5,6 GB e 22,9 milhões de linhas é folgado.

```bash
pip install duckdb
python scripts/carregar_duckdb.py D:/datalake --views D:/views/gold
```

Cada dataset vira um schema (`lake`, `gold`), e o banco resultante é portátil:
gere onde for e copie para a máquina que hospedará.

### As views exigem tradução

As 11 views do `gold` são SQL do BigQuery e **não rodam como estão**. O
carregador faz a parte mecânica — reescreve `projeto.dataset.tabela` para
`dataset.tabela` — e sinaliza o resto em vez de adivinhar.

Construções que divergem entre os dialetos: `SAFE_DIVIDE`, `SAFE_CAST`,
`PARSE_DATE`, `FORMAT_DATE`, `GENERATE_ARRAY`, `_TABLE_SUFFIX`. Cada uma
precisa de decisão sua — um ajuste errado aqui muda resultado de negócio em
silêncio, que é pior do que falhar.

**Esse é o trabalho residual real da migração**, e não some com automação.

O que some é a dúvida sobre ter acertado: `conferir_views.py` (fase 4) compara
o resultado da view traduzida com o que a original respondia, e acusa a
diferença. Ele não traduz por você — só não deixa um erro passar calado.

---

## Fase 4 — Verificação

"Parece tudo ok" não é verificação.

1. **Contagem** — número de objetos na origem e no destino batem?
2. **Checksum** — os hashes CRC32C conferem, objeto a objeto?
3. **Views** — as 11 views traduzidas respondem o mesmo que respondiam no
   BigQuery?

O item 3 é específico deste datalake e não aparece em checklist genérico
de migração.

### Conferir as views de verdade

Checar se os arquivos `.sql` existem e não estão vazios prova que o download
aconteceu, não que a tradução está certa — e a tradução é justamente onde o
erro não aparece. `COALESCE(x/NULLIF(y,0), 0)` parece um conserto razoável
para `SAFE_DIVIDE` e troca NULL por zero em toda média que a view alimenta.
`PARSE_DATE` com `%m/%d` no lugar de `%d/%m` desloca datas sem falhar em
nenhuma linha, desde que dia e mês sejam ambos ≤ 12.

`conferir_views.py` compara o conteúdo dos dois lados. Para cada view ele
calcula um perfil — contagem de linhas e, por coluna, não-nulos, distintos,
mínimo, máximo e soma — e confronta perfil com perfil:

```bash
# Na origem, ENQUANTO o BigQuery ainda existe:
python scripts/conferir_views.py bigquery --dataset gold --saida perfil-bq.json

# No destino, depois de carregar e traduzir:
python scripts/conferir_views.py duckdb D:/datalake/datalake.duckdb \
    --comparar-com perfil-bq.json
```

Sai com código 1 e lista cada divergência: qual view, qual coluna, qual
métrica, os dois valores. Os dois erros do parágrafo acima aparecem como
`nao_nulos` e `minimo` fora do lugar.

Não é igualdade linha a linha, e não promete ser — é o conjunto de agregados
que muda quando a semântica muda, que é o que se quer pegar. Colunas
`ARRAY`/`STRUCT` só são contadas, porque não ordenam.

> **Quando coletar o perfil da origem: depois de congelar as escritas, antes
> de excluir o projeto.** As duas pontas importam. Antes da fase 6 porque
> depois não existe mais contra o que comparar — o perfil é tão irreproduzível
> quanto as próprias views. E depois do congelamento da fase 5 porque, se a
> automação escrever entre a exportação e o perfil, o verificador vai acusar
> divergência que é só defasagem: alarme falso, no exato momento em que você
> precisa confiar no alarme. O perfil e o Parquet têm que descrever o mesmo
> estado. Guarde o `perfil-bq.json` junto com os `.sql`, fora do projeto GCP.

Antes de rodar na origem, `--estimar` faz um dry run e informa quantos bytes
cada perfil leria, sem executar nem cobrar — as views do `gold` cobrem as 848
tabelas do bronze, então vale olhar a conta antes.

O verificador tem teste próprio, que constrói uma tradução errada de
propósito e exige que ela seja acusada:

```bash
python tests/teste_conferir_views.py
```

---

## Fase 5 — Congelamento e revalidação

1. Pare tudo que escreve no bucket ou nos datasets
2. Remova permissões de escrita
3. Repita a fase 4 sobre um alvo agora estático

---

## Fase 6 — Desativação

Nesta ordem:

1. **Desative o faturamento.** Para o custo na hora e é reversível — a
   diferença crucial em relação ao passo seguinte.
2. **Espere dias, não minutos.** É nesse silêncio que aparece o que foi
   esquecido, enquanto ainda dá para voltar atrás.
3. **Exclua o projeto.**
4. **Encerre a conta.**

---

## Checklist

- [x] Fase 1 — inventário levantado
- [x] Fase 2 — tabelas confirmadas **nativas** (850 no total)
- [x] Fase 2 — volume medido: ~5,6 GB no total
- [ ] **Views do `gold` salvas como `.sql` e guardadas em local privado**
- [ ] Dependências vivas mapeadas (`mapear_dependencias.py`)
- [ ] Localizado onde roda cada principal do relatório
- [ ] Fase 3 — bucket copiado
- [ ] Fase 3 — 850 tabelas exportadas em Parquet/Avro
- [ ] Fase 4 — contagem, checksums e views conferidos
- [ ] DuckDB carregado e conferido contra o manifesto
- [ ] 11 views traduzidas do dialeto BigQuery
- [ ] Views traduzidas conferidas contra o perfil da origem
- [ ] Fase 5 — escritas congeladas, revalidado
- [ ] **Perfil das views coletado** com o alvo já estático (`conferir_views.py bigquery`)
- [ ] Fase 6 — faturamento desativado, período de espera cumprido
- [ ] Projeto excluído
- [ ] Conta encerrada

---

## Scripts

| Script | Função | Natureza |
| --- | --- | --- |
| `gcp_inventory.sh` | Inventário geral do projeto | Somente leitura |
| `bq_export_metadata.sh` | Classifica tabelas, mede storage, salva DDL e views | Somente leitura |
| `migrar_bucket.sh` | Copia o bucket e verifica a integridade | Lê do GCP, escreve só local |
| `exportar_bigquery.sh` | Exporta as 848 tabelas em Parquet | **Escreve** no bucket de staging |
| `Migrar-Datalake.ps1` | Fases 3 e 4 completas, para Windows | **Escreve** no staging |
| `carregar_duckdb.py` | Carrega o Parquet no DuckDB e confere contagens | Só local |
| `list_buckets.py` | Lista buckets via service account | Somente leitura |
| `mapear_dependencias.py` | Quem lê, quem escreve e quanto dialeto falta traduzir | Somente leitura |
| `conferir_views.py` | Perfila as views nos dois lados e confronta | Somente leitura |
| `gcp_credenciais.py` | Carrega a credencial (módulo, não executável) | — |

Só o `exportar_bigquery.sh` escreve no GCP, e apenas criando arquivos novos
no staging que você indicar — nenhum script altera ou apaga o datalake.
