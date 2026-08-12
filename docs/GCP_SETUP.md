# Acesso ao Cloud Storage a partir do Claude Code

Sessões do Claude Code na web rodam em um contêiner isolado, sem navegador
autenticado na sua conta Google. Por isso o caminho manual do Console
(buscar "Cloud Storage" → "Buckets") não é acessível de dentro da sessão.

Este documento configura uma service account de leitura para que a lista de
buckets possa ser obtida via API.

## Passo 1 — Criar a service account

No projeto onde estão os buckets:

```bash
gcloud config set project SEU_PROJETO

gcloud iam service-accounts create claude-storage-reader \
  --display-name="Claude Code - leitor de buckets"
```

## Passo 2 — Conceder o papel mínimo

`roles/storage.bucketViewer` concede exatamente `storage.buckets.get` e
`storage.buckets.list` — o suficiente para listar buckets e ver seus
metadados, sem acesso a nenhum objeto armazenado dentro deles.

```bash
PROJETO=SEU_PROJETO
SA="claude-storage-reader@${PROJETO}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJETO" \
  --member="serviceAccount:${SA}" \
  --role="roles/storage.bucketViewer"
```

Não use `roles/storage.admin` aqui: ele dá acesso de escrita e leitura ao
conteúdo dos buckets, muito além do necessário.

## Passo 3 — Gerar a chave

```bash
gcloud iam service-accounts keys create chave.json --iam-account="$SA"
base64 -w0 chave.json          # macOS: base64 -i chave.json
```

Copie a string de base64 que sair. Em seguida **apague o arquivo local**:

```bash
rm chave.json
```

> Se sua organização aplica a política
> `constraints/iam.disableServiceAccountKeyCreation`, o passo acima falha por
> desenho. Nesse caso o caminho é Workload Identity Federation, que dispensa
> chaves de longa duração — porém exige um provedor OIDC que este contêiner
> não expõe hoje. A alternativa prática é rodar `scripts/list_buckets.py` na
> sua própria máquina e colar o resultado.

## Passo 4 — Registrar como variável de ambiente

No painel do ambiente do Claude Code (Settings → Environments → o ambiente
usado por este repositório), adicione:

| Variável | Valor |
| --- | --- |
| `GCP_SA_KEY_B64` | a string base64 do passo 3 |
| `GOOGLE_CLOUD_PROJECT` | o ID do projeto (opcional; a chave já o contém) |

**Não cole a chave no chat.** A conversa fica registrada no histórico da
sessão; a variável de ambiente, não. O script decodifica a chave em memória e
nunca a escreve em disco nem a imprime.

## Passo 5 — Usar

O hook `SessionStart` monta o virtualenv automaticamente em cada sessão nova.
Depois disso:

```bash
python scripts/list_buckets.py            # um nome de bucket por linha
python scripts/list_buckets.py --long     # nome, localização, classe
python scripts/list_buckets.py --json     # saída estruturada
```

Ou simplesmente peça no chat: "liste meus buckets".

## Rotação e revogação

Chaves de service account não expiram sozinhas. Convém rotacioná-las
periodicamente, e revogar imediatamente se a variável vazar:

```bash
gcloud iam service-accounts keys list --iam-account="$SA"
gcloud iam service-accounts keys delete ID_DA_CHAVE --iam-account="$SA"
```

## Diagnóstico

| Sintoma | Causa provável |
| --- | --- |
| `erro de configuracao: ... nao e base64 valido` | a variável foi truncada ou tem quebras de linha; regenere com `base64 -w0` |
| `invalid_grant: account not found` | a service account foi apagada, ou a chave é de outro projeto |
| `403` / `permission` | o papel do passo 2 não foi concedido, ou foi concedido em outro projeto |
| `(nenhum bucket neste projeto)` | autenticou certo, mas o projeto realmente não tem buckets — confira o ID do projeto |

## Rede

O proxy de egress desta sessão libera `storage.googleapis.com` e
`oauth2.googleapis.com`, que é tudo que este fluxo usa. Note que
`dl.google.com` está bloqueado, então o gcloud CLI oficial não pode ser
instalado dentro do contêiner — daí o uso da biblioteca Python via `pip`
(`pypi.org` está na lista de exceções do proxy).
