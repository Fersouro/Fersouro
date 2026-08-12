# Migração do datalake GCP → máquina local

## Estado: fase 1 concluída

Projeto do datalake: **`tterrasul-datalake`** (conta `fernando@tterrasul.com.br`).

> O primeiro inventário rodou em `carbon-virtue-504415-a4`, que é o
> "My First Project" criado por padrão pelo GCP e não contém nada. Ao rodar
> com `--project=tterrasul-datalake` o conteúdo real apareceu.

| Recurso | Conteúdo |
| --- | --- |
| `gs://tterrasul-datalake-lake` | 874.523.665 bytes (~834 MB, Parquet comprimido) |
| Dataset `lake` (bronze) | 848 tabelas |
| Dataset `gold` | 11 views |

## Regra que governa todo o resto

> A exclusão da conta é irreversível e é o **último** passo.
> Nada é apagado antes da cópia estar verificada por checksum.

Projetos GCP excluídos entram num período de recuperação de aproximadamente
30 dias antes da destruição definitiva. É uma rede de segurança contra
engano, não uma etapa do plano.

---

## Fase 2 — Dimensionamento: resolvida

834 MB torna irrelevantes as preocupações habituais de migração:

- **Espaço:** cabe em qualquer máquina, com folga para a verificação
- **Egress:** menos de 1 GB — custo na casa de centavos
- **Tempo:** minutos, não dias

Transfer Appliance, migração por lotes e redução de escopo estão descartados.

**A questão em aberto não é volume — é natureza.** As 848 tabelas do `lake`
são nativas ou externas?

- **Externas** (apontam para o Parquet no GCS): os 834 MB já são o datalake
  inteiro. Copiar o bucket + recriar as definições resolve tudo.
- **Nativas** (storage próprio do BigQuery): há dados adicionais que o
  inventário não mediu, e cada tabela precisa ser exportada.

Um bronze com Parquet no bucket e 848 tabelas sugere fortemente o primeiro
caso, mas isso precisa ser confirmado, não presumido:

```bash
./scripts/bq_export_metadata.sh tterrasul-datalake lake gold
```

O script classifica as tabelas, mede o storage nativo e — o mais importante —
salva o DDL de tudo.

---

## O maior risco desta migração: os 11 views

**Views não são dados. São definições SQL.**

Exportar o dataset `gold` como se fossem tabelas materializa o resultado
atual e **descarta a lógica que o produz**. Num datalake em camadas, essas 11
definições são a regra de negócio destilada — quase sempre o ativo mais
valioso e o mais fácil de perder, porque uma exportação "bem-sucedida"
devolve dados com aparência correta.

Os 834 MB de Parquet são reproduzíveis a partir da origem. As 11 views, não.

`bq_export_metadata.sh` salva cada uma como `.sql` versionável. **Faça isso
antes de qualquer exportação de dados**, e versione o resultado no git.

---

## Fase 3 — Cópia

**Bucket** (retomável, mas com 834 MB tende a terminar de primeira):

```bash
gcloud storage rsync -r gs://tterrasul-datalake-lake ./datalake/lake
```

**BigQuery** depende da fase 2:

- *Tabelas externas* → nada a exportar; os dados já vieram no bucket. Basta
  recriar as definições apontando para o caminho local.
- *Tabelas nativas* → `bq extract` para GCS em **Parquet ou Avro**, nunca
  CSV: CSV perde tipos, precisão numérica e estrutura aninhada.

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
- [ ] Fase 2 — confirmar se as tabelas são nativas ou externas
- [ ] **Views do `gold` salvas como `.sql` e versionadas**
- [ ] Fase 3 — bucket copiado
- [ ] Fase 3 — BigQuery tratado conforme a natureza das tabelas
- [ ] Fase 4 — contagem, checksums e views conferidos
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
| `list_buckets.py` | Lista buckets via service account | Somente leitura |
