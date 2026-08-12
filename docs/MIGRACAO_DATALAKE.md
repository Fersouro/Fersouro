# Migração do datalake GCP → máquina local

## Estado: fase 2 concluída

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

```powershell
.\scripts\Migrar-Datalake.ps1 -Projeto tterrasul-datalake `
    -Staging gs://tterrasul-export-tmp `
    -Bucket gs://tterrasul-datalake-lake `
    -Destino D:\datalake
```

Os scripts `.sh` continuam válidos para quem estiver em Linux ou WSL.

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

---

## Fase 4 — Verificação

"Parece tudo ok" não é verificação.

1. **Contagem** — número de objetos na origem e no destino batem?
2. **Checksum** — os hashes CRC32C conferem, objeto a objeto?
3. **Views** — os 11 arquivos `.sql` existem e não estão vazios?

O item 3 é específico deste datalake e não aparece em checklist genérico
de migração.

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
- [ ] Fase 3 — bucket copiado
- [ ] Fase 3 — 850 tabelas exportadas em Parquet/Avro
- [ ] Fase 4 — contagem, checksums e views conferidos
- [ ] DuckDB carregado e conferido contra o manifesto
- [ ] 11 views traduzidas do dialeto BigQuery
- [ ] Fase 5 — escritas congeladas, revalidado
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

Só o `exportar_bigquery.sh` escreve no GCP, e apenas criando arquivos novos
no staging que você indicar — nenhum script altera ou apaga o datalake.
