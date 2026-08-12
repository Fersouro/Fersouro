# Migração do datalake GCP → máquina local

## Estado atual: fase 1 de 6

Nada foi migrado ainda. O inventário do que existe no GCP ainda não foi
levantado — é por isso que este plano detalha a fase 1 e mantém as demais em
esboço: **as decisões das fases 2 a 6 dependem de números que ainda não
temos** (volume total, quantidade de objetos, quais serviços estão em uso).

## Regra que governa todo o resto

> A exclusão da conta é irreversível e é o **último** passo.
> Nada é apagado antes da cópia estar verificada por checksum.

Projetos GCP excluídos entram num período de recuperação de aproximadamente
30 dias antes da destruição definitiva. Isso é uma rede de segurança contra
engano, não uma etapa do plano — não conte com ela.

---

## Fase 1 — Inventário  ← você está aqui

**Objetivo:** saber exatamente o que existe, para depois conseguir provar que
a cópia veio completa.

```bash
gcloud auth login
./scripts/gcp_inventory.sh --with-sizes
```

O script é somente-leitura (apenas `list`, `describe`, `du`, `ls`) e gera um
relatório em markdown. `--with-sizes` percorre todos os objetos de cada
bucket para medir o volume; é lento, mas o número exato é o que permite
dimensionar a fase 2.

Rode **na sua máquina**, não aqui. O contêiner do Claude Code não consegue
instalar o gcloud CLI (`dl.google.com` bloqueado pelo proxy) e a service
account de leitura de buckets não enxerga BigQuery nem Dataproc.

**Saída desta fase:** o relatório `inventario-gcp-*/inventario.md`. Cole o
conteúdo aqui e eu detalho as fases seguintes com base nos números reais.

Confira a seção "APIs habilitadas" do relatório: ela revela serviços que o
script não cobre explicitamente mas que podem guardar dados (Firestore,
Spanner, Cloud SQL, Pub/Sub com retenção).

---

## Fase 2 — Dimensionamento

Com os números em mãos, três perguntas decidem a viabilidade:

- **Cabe?** Espaço livre no destino local, com folga para a verificação.
- **Quanto custa?** Sair com dados do GCP tem custo de egress por GB. Num
  datalake grande isso não é trivial e precisa ser estimado antes, não
  descoberto na fatura.
- **Quanto demora?** Volume ÷ banda real de upload/download. Terabytes numa
  conexão doméstica são dias, não horas.

Se o volume inviabilizar a cópia direta, as alternativas são Transfer
Appliance, ou reduzir o escopo (migrar só o que tem valor retido).

---

## Fase 3 — Cópia

**Cloud Storage:**

```bash
gcloud storage rsync -r gs://SEU_BUCKET /caminho/local/SEU_BUCKET
```

`rsync` é retomável — em transferências longas isso importa mais que
velocidade. Rode por bucket, não tudo de uma vez, para isolar falhas.

**BigQuery:** não dá para copiar direto. É preciso exportar para GCS primeiro
(`bq extract`) e então baixar. Prefira **Avro ou Parquet a CSV**: CSV perde
tipos, precisão numérica e estrutura aninhada.

---

## Fase 4 — Verificação

**Esta é a fase que não pode ser pulada.** "Parece que veio tudo" não é
verificação.

O GCS guarda CRC32C (e MD5, exceto em objetos compostos) de cada objeto.
A verificação tem duas partes:

1. **Contagem** — número de objetos na origem e no destino batem?
2. **Checksum** — os hashes conferem, objeto a objeto?

Só depois que ambas passarem a cópia é considerada válida.

---

## Fase 5 — Congelamento e revalidação

Se algo ainda escreve nos buckets, a cópia já nasceu desatualizada.

1. Identifique e pare tudo que escreve (jobs, pipelines, aplicações)
2. Remova permissões de escrita
3. Rode a fase 4 de novo — agora sobre um alvo estático

---

## Fase 6 — Desativação

Nesta ordem, sem pular etapas:

1. **Desative o faturamento** primeiro. Isso para o custo imediatamente e é
   reversível — a diferença crucial em relação ao passo seguinte.
2. **Espere.** Dias, não minutos. Se algo essencial foi esquecido, é agora
   que aparece, enquanto ainda dá para voltar atrás.
3. **Exclua o projeto** apenas depois desse período de silêncio.
4. **Encerre a conta** por último.

---

## Checklist

- [ ] Fase 1 — inventário gerado e revisado
- [ ] Fase 2 — volume, custo de egress e prazo estimados
- [ ] Fase 3 — cópia concluída
- [ ] Fase 4 — contagem e checksums conferem
- [ ] Fase 5 — escritas congeladas, revalidado
- [ ] Fase 6 — faturamento desativado, período de espera cumprido
- [ ] Projeto excluído
- [ ] Conta encerrada
