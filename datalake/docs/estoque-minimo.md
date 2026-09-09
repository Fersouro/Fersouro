# Estoque Mínimo de Peças — documentação

Sistema que compara o **disponível real** de cada peça (vindo do ERP, via
datalake) com uma **lista de mínimos** definida pela equipe, e publica o
resultado numa **página local** (rede interna) e numa planilha, marcando em
vermelho o que precisa comprar. Atualiza sozinho 6×/dia e guarda histórico
diário.

> **Handoff para um chat novo:** todo o código está no repositório
> `Fersouro/Fersouro`, branch `claude/datalake-from-scratch-jkv3wq`, dentro de
> `datalake/`. O sistema roda no servidor da empresa em `C:\datalake`. Abrir um
> chat novo sobre este repo/branch dá o contexto completo — nada precisa ser
> "transferido" e nada sai do ar.

---

## 1. De onde vem o número (a fonte da verdade)

O "Disponível" da consulta gerencial do ERP é a coluna **`QTD_CONTABIL`** da
tabela **`PEC_ITEM_REVENDA`** (schema `CNP` do Oracle Linx), por
`(ITEM_ESTOQUE, REVENDA)`.

- `PEC_ITEM_ESTOQUE` é o **cadastro** da peça (1 linha por peça). Tem o código
  público em `ITEM_ESTOQUE_PUB` (ex.: `05E145933`) e o id interno em
  `ITEM_ESTOQUE` (ex.: `96944`). **Não tem saldo.**
- `PEC_ITEM_REVENDA` é o **saldo por loja**. Liga-se ao cadastro por
  `ITEM_ESTOQUE`.

O cruzamento é: **código público → id interno (cadastro) → saldo por revenda**.
Conferido contra a tela do ERP: `05E145933` = **53** na Revenda 1 (bate com
`QTD_CONTABIL`).

Regra que o sistema segue: **nunca inventa número.** Peça sem saldo aparece como
0; código que não existe no cadastro aparece como "não cadastrado".

---

## 2. Arquitetura no datalake

Medalhão (bronze → silver → gold), Python + DuckDB + Parquet.

- **Fonte** (`conf/sources/ccm.yml`): carrega, entre outras, `PEC_ITEM_ESTOQUE`
  e `PEC_ITEM_REVENDA`.
- **Gold** (`sql/gold/80_estoque_pecas.sql`): disponível por peça/revenda, já
  com código público, descrição e o código normalizado para casar com a lista
  de mínimos. Serve também ao Power BI.
- **Gerador** (`scripts/gerar_estoque.py`): lê o silver + a lista de mínimos e
  produz a **página HTML** e a **planilha xlsx** na pasta `export`. Também grava
  o **snapshot diário** do histórico.

---

## 3. A lista de mínimos (o que a equipe edita)

Arquivo: **`C:\datalake\minimos_pecas.csv`** — formato `codigo;revenda;minimo`:

```
codigo;revenda;minimo
05E145933;1;15
05E145933;2;10
...
```

- Uma linha por **(código, revenda)**. Para monitorar uma peça na Revenda 1 e
  na 2, são duas linhas.
- Para **adicionar peça** ou **mudar mínimo**: edite este arquivo e salve. A
  próxima carga já reflete (ou rode a regeração manual — seção 8).
- O `revenda` no dropdown da página aparece a partir do que existe aqui. Se só
  houver linhas `;1;`, só aparece a Revenda 1.

> **Cuidado ao editar por PowerShell:** não cole o conteúdo como *here-string*
> (`@' ... '@`) — o terminal costuma juntar tudo numa linha só e o DuckDB falha
> ao ler (`maximum line size`). Edite pelo **Bloco de Notas**, ou grave via
> array (`$linhas = @("a;1;2","b;1;3"); $linhas | Set-Content ... -Encoding ascii`).

A semente inicial fica em `conf/minimos_pecas.csv` (Revenda 1 e 2, valores da 2
iguais aos da 1 como ponto de partida). Ela só é copiada para `C:\datalake` se o
arquivo lá ainda não existir — depois disso, o arquivo do servidor manda.

---

## 4. A página

`C:\datalake\export\estoque_minimo.html` — um arquivo único, sem internet.

- Seletor de **Data** (histórico), seletor de **Revenda**, busca por
  código/descrição, filtro "só o que precisa comprar", ordenação por coluna,
  **Exportar CSV**.
- Linhas em **vermelho** = disponível abaixo do mínimo (COMPRAR).
- Cabeçalho fixo dentro de um container com rolagem própria.

### Histórico por data
A cada carga, grava `C:\datalake\historico_estoque\AAAA-MM-DD.parquet` (o último
carregamento do dia manda). O seletor de data mostra qualquer dia registrado. O
histórico **vale a partir do primeiro registro** — o ERP só tem o saldo do
momento, então dias anteriores ao início não existem.

---

## 5. O servidor (acesso na rede)

- Script: `scripts/servir_pagina.py` (só serve arquivos da pasta `export`;
  manda cabeçalho *no-cache* para a página vir sempre atualizada).
- Instalado como **Tarefa Agendada** `DatalakeEstoquePagina` (roda na
  inicialização, conta SYSTEM, sem login) por `scripts/instalar_servidor.ps1`.
- **HTTPS na porta 8443.** Endereço: **`https://192.168.78.6:8443/`** (a raiz
  redireciona para a página; os relatórios ficam em `/relatorios/`). A porta
  **8080** continua respondendo e **redireciona** para o HTTPS, então links
  antigos salvos continuam funcionando.
- Somente **rede interna (LAN)** — não é acesso externo; para ver de fora, use
  VPN, não abra a porta na internet.

### Gerador de relatórios
Em **`https://192.168.78.6:8443/gerar`** dá para gerar qualquer relatório na
hora, escolhendo o período (e o departamento, no de funilaria), em vez de
esperar a próxima carga. O arquivo sai em `export/relatorios/gerados/` com data
e hora no nome. Detalhes em [`relatorios.md`](relatorios.md), seção 3.

### Login
O acesso pede **usuário e senha** — a pasta `export` tem margem, faturamento e
estoque, e sem login qualquer máquina da rede baixa tudo. A tela é a mesma
"Relatórios Tterrasul" de sempre.

- Usuários ficam em `C:\datalake\usuarios.json`, com a senha em **hash PBKDF2**
  (240 mil iterações, sal por usuário). A senha em claro não é gravada em lugar
  nenhum.
- Cadastrar (ou trocar a senha de) alguém:
  ```powershell
  & "C:\Program Files\Python312\python.exe" "C:\datalake\servir_pagina.py" --criar-usuario fernando
  ```
  > No PowerShell o **`&` na frente é obrigatório**: sem ele, uma linha que
  > começa com aspas é tratada como texto e devolve `Token inesperado`. O
  > caminho do Python tem espaço, então as aspas também são obrigatórias.
  A senha é pedida no prompt — nunca vai por argumento, que apareceria na lista
  de processos e no histórico do PowerShell.
- **Esqueceu a senha?** Rode o mesmo comando com o mesmo nome: ele regrava.
- Cadastro e troca de senha **valem na hora** — o servidor relê o
  `usuarios.json` quando o arquivo muda, sem reiniciar o serviço.
- **Sem terminal:** `C:\datalake\CADASTRAR-USUARIO.bat` (duplo-clique) cadastra
  ou troca senha, e `C:\datalake\DIAGNOSTICO-PAGINA.bat` roda o diagnóstico.
  Existem como `.bat` porque no PowerShell a linha com aspas vira texto.
- **O login recusa?** Rode o diagnóstico — ele diz quem está atendendo em cada
  porta, com que argumentos a tarefa sobe o servidor e quem está cadastrado:
  ```powershell
  & "C:\Program Files\Python312\python.exe" "C:\datalake\diagnostico_pagina.py"
  ```
  O caso mais comum é a 8443 estar com **outro portal** (o de `C:\Python`), que
  tem a própria lista de usuários — aí o usuário criado aqui não entra lá.
- **Confirmada a senha, sem navegador:**
  ```powershell
  & "C:\Program Files\Python312\python.exe" "C:\datalake\servir_pagina.py" --verificar-senha fernando
  ```
  Ele mostra o arquivo lido, quem está cadastrado e se a senha bate.
- As sessões vivem na memória e duram 12 h. Reiniciou o serviço, todo mundo
  entra de novo.
- Cinco senhas erradas do mesmo IP bloqueiam novas tentativas por 5 minutos.
- Para voltar ao acesso aberto (não recomendado): `-SemLogin` no instalador.

### O certificado
Autoassinado, gerado sozinho na primeira execução em
`C:\datalake\cert\servidor.pem` (validade de 10 anos). Ele cobre o nome da
máquina e todos os IPs dela — inclusive o `192.168.78.6` quando o serviço é
instalado com `-Escuta 192.168.78.6`.

Por ser autoassinado, o navegador avisa na primeira visita ("conexão não é
particular" → *Avançado* → *Continuar*). Para tirar o aviso da rede toda,
instale o `servidor.pem` como **Autoridade de Certificação Raiz Confiável** nas
máquinas (dá para distribuir por GPO).

Instalar/reinstalar o serviço (PowerShell como Administrador):
```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\datalake\instalar_servidor.ps1 -Escuta 192.168.78.6 -Usuario fernando
```
Ele pede a senha do usuário na hora, gera o certificado, libera o firewall e
registra a tarefa.
Volta ao HTTP antigo com `-Http`; muda a porta com `-Porta`.

Reiniciar o servidor:
```
schtasks /End /TN DatalakeEstoquePagina
schtasks /Run /TN DatalakeEstoquePagina
```

---

## 6. Automação (6×/dia)

- **6 Tarefas Agendadas** chamam `C:\datalake\ATUALIZAR.bat` (7:00, 10:00,
  12:00, 15:00, 17:50, 18:37).
- `ATUALIZAR.bat` usa o **projeto fixo** `C:\datalake\app` (NÃO baixa nada a
  cada run — evita o cache do GitHub entregar código velho), roda a carga com
  `--keep-going` (uma tabela com falha não trava o resto) e **sempre** regenera
  a página.

---

## 7. Instalar / atualizar o código

Único ponto que baixa do GitHub: **`C:\datalake\instalar_app.ps1`**.

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\datalake\instalar_app.ps1
```

Ele baixa a versão atual da branch para `C:\datalake\app`, constrói o venv, faz
uma carga e copia `ATUALIZAR.bat`, `servir_pagina.py`, `instalar_servidor.ps1` e
`instalar_app.ps1` para `C:\datalake`. Para fixar um commit exato: `... -Ref <sha>`.

A senha do Oracle é pedida **uma vez**: ela fica em `C:\datalake\.env`, que o
instalador devolve ao projeto a cada atualização. A pasta do projeto é apagada e
rebaixada inteira em cada execução — sem essa cópia estável, a senha teria de ser
digitada sempre. (Se a senha ficar vazia, o `setup` para em "Senha vazia" e a
carga não roda; a página e os relatórios continuam com os dados da carga
anterior.)

Rode isto **sempre que houver mudança de código publicada** no repositório. As
cargas do dia a dia não baixam — usam o que este script deixou.

---

## 8. Operação do dia a dia

- **Ver a página:** abrir `https://192.168.78.6:8443/` no navegador
  (a `http://...:8080/` redireciona para lá).
- **Mudar mínimos / adicionar peças:** editar `C:\datalake\minimos_pecas.csv`
  (Bloco de Notas). Reflete na próxima carga, ou force agora:
  ```
  C:\datalake\ATUALIZAR.bat
  ```
  (carrega + regenera), ou só a página, sem tocar no Oracle:
  ```
  python (Get-ChildItem C:\datalake\app -Recurse -Filter gerar_estoque.py | Select-Object -First 1).FullName C:\datalake\lake.duckdb
  ```
- Após regerar, **Ctrl+F5** no navegador para furar o cache.

---

## 9. Solução de problemas

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Página não muda | cache do navegador | **Ctrl+F5**; conferir se o `.html` tem `LastWriteTime` recente |
| Aviso de certificado no navegador | certificado autoassinado | é esperado; *Avançado → Continuar*, ou instale o `C:\datalake\cert\servidor.pem` como raiz confiável |
| `ERR_SSL_PROTOCOL_ERROR` | acessou `https://` numa porta servida sem TLS (ou vice-versa) | confira a porta: 8443 é HTTPS, 8080 só redireciona |
| Serviço não sobe na 8443 | porta ocupada por outro programa | `netstat -ano \| findstr :8443`; use `-Porta` diferente ou libere a porta |
| `Nao consegui gerar o certificado` | falta o pacote `cryptography` no Python do serviço | `python -m pip install cryptography` e reinicie a tarefa |
| Serviço não sobe: `Nenhum usuario cadastrado` | ninguém foi cadastrado ainda | `python C:\datalake\servir_pagina.py --criar-usuario <nome>` |
| Esqueceu a senha | — | rode o `--criar-usuario` com o mesmo nome; ele regrava |
| "Muitas tentativas. Espere alguns minutos." | 5 senhas erradas do mesmo IP | espere 5 minutos, ou reinicie a tarefa (zera o contador) |
| Todo mundo caiu para a tela de login | o serviço reiniciou (sessões vivem na memória) | é esperado; basta entrar de novo |
| "Usuário ou senha inválidos" com a senha certa | até 09/09/2026 o serviço lia os usuários só na subida: quem fosse cadastrado depois não entrava | atualize o código (hoje a lista é relida sozinha); no código antigo, reinicie a tarefa depois de cadastrar |
| Só aparece Revenda 1 | `minimos_pecas.csv` sem linhas `;2;` **ou** CSV corrompido (uma linha só) | reescrever o CSV via array/Bloco de Notas; conferir `read_csv` sem erro |
| `read_csv_auto ... maximum line size` | CSV colado virou uma linha só | regravar o CSV com quebras de linha reais |
| `ORA-00942` numa tabela com `filter` | tabela citada dentro do `filter` sem o schema | qualifique com `CNP.` no `ccm.yml` — o conector só qualifica a tabela do `FROM` principal |
| 1 tabela falha na carga | ingestão de uma tabela | a automação usa `--keep-going` e segue; investigar a tabela no `saida-datalake.txt` |
| Carga para no INGEST sem regerar a página | `C:\datalake\ATUALIZAR.bat` desatualizado (versão sem `--keep-going`) | rode `instalar_app.ps1`, que reescreve o `.bat` no servidor |
| Carga não conecta no Oracle | rota `10.15.111.254:1521` caiu | problema de rede/TI; `scripts/diagnostico_rede.ps1` ajuda a apontar onde quebra |
| Código velho após atualizar | cache do GitHub na hora do download | rode `instalar_app.ps1` de novo, ou fixe o commit com `-Ref <sha>` |
| `-File C:\datalake\instalar_servidor.ps1` não existe | versão do `instalar_app.ps1` anterior a 09/09/2026 não copiava esse arquivo | rode o `instalar_app.ps1` atual (ele passou a copiar), ou chame pelo caminho do projeto: `C:\datalake\app\Fersouro-*\datalake\scripts\instalar_servidor.ps1` |
| `setup` para em "Senha vazia" | a senha do Oracle não foi digitada | rode o `instalar_app.ps1` de novo e informe a senha de `FERNANDO_DEV`; a partir daí ela fica no `C:\datalake\.env` |

---

## 10. Mapa de arquivos

No repositório (`datalake/`):
- `conf/sources/ccm.yml` — fontes Oracle (inclui `PEC_ITEM_REVENDA`).
- `conf/minimos_pecas.csv` — semente da lista de mínimos.
- `sql/gold/80_estoque_pecas.sql` — modelo gold do disponível por revenda.
- `scripts/gerar_estoque.py` — gera página + planilha + snapshot do histórico.
- `scripts/servir_pagina.py` — servidor HTTP local.
- `scripts/instalar_servidor.ps1` — registra o servidor como Tarefa Agendada.
- `scripts/instalar_app.ps1` — instala/atualiza o código no projeto fixo.
- `scripts/setup_windows.ps1` — driver da carga (`-Run -KeepGoing`, `-Estoque`).
- `scripts/ATUALIZAR-DATALAKE.bat` — a rotina 6×/dia (vira `C:\datalake\ATUALIZAR.bat`).

No servidor (`C:\datalake`):
- `lake.duckdb` — catálogo. `silver/`, `gold/`, `export/` — dados e saídas.
- `export/relatorios/` — planilhas geradas pela camada de relatórios.
- `cert/servidor.pem` e `cert/servidor.key` — certificado do HTTPS (autoassinado).
- `usuarios.json` — quem pode entrar (senha em hash). Restrinja a ACL desse arquivo.
- `.env` — credenciais do Oracle, preservadas entre atualizações (fora do Git).
- `minimos_pecas.csv` — lista de mínimos (editável pela equipe).
- `historico_estoque/AAAA-MM-DD.parquet` — snapshots diários.
- `app/` — projeto fixo (código). `ATUALIZAR.bat`, `instalar_app.ps1`,
  `servir_pagina.py` — cópias estáveis.

---

## 11. Estado atual e pendências

- ✅ Página com Revenda(s), data e histórico; servidor na LAN; automação 6×/dia.
- ⏳ **Confirmar a Revenda 2 na lista de mínimos do servidor** — o CSV chegou a
  corromper num paste; a correção é gravar `C:\datalake\minimos_pecas.csv` com as
  20 linhas (10 por revenda) via array/Bloco de Notas e regerar.
- ✅ **A tabela que falhava na carga foi corrigida** (31/08/2026).
  Era a `FAT_MOVIMENTO_ITEM`, com `ORA-00942: table or view does not exist`.
  Causa: o conector qualifica com o schema apenas a tabela do `FROM` principal;
  o texto do `filter` entra verbatim no SQL, e a subconsulta citava
  `FAT_MOVIMENTO_CAPA` sem o `CNP.` — o Oracle procurava no schema do usuário da
  conexão (`FERNANDO_DEV`), onde a tabela não existe. Depois do fix a carga fica
  **11/11 tabelas**, e a `gold.margem_pecas` passa a ter dado de verdade.
  **Regra que fica:** qualifique com `CNP.` toda tabela citada dentro de um `filter`.
- 🔒 Segurança: a página não tem senha (uso interno). Não expor a porta na
  internet. As credenciais do Oracle ficam no `.env` (fora do Git).
