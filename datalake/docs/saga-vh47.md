# RPA SAGA2 - VH47 → planilha de garantia

Substitui o processo manual: SAGA → baixar relatórios → abrir PDFs → achar SG e
valor → lançar no Excel.

```
Portal Rede VW ─login─▶ GARANTIA VOLKSWAGEN ▶ SAGA ▶ "Lista de arquivos" (SAGA2 - VH47)
      │  lê Ano / Mês / Regional / DN / Nome de cada arquivo, filtra o DN
      ▼
controle.sqlite ── o que falta? (tudo que não está "processado", do mais antigo ao mais novo)
      ▼
download ▶ valida o PDF ▶ extrai SG + Valor total ▶ upsert na planilha (SG = chave) ▶ marca processado
```

## Onde está cada coisa

| Arquivo | Papel |
|---|---|
| `src/datalake/rpa/saga_vh47.py` | ponto de entrada e orquestração (`python -m datalake.rpa.saga_vh47`) |
| `src/datalake/rpa/saga_portal.py` | navegador: login, menus, iframes/abas, lista, download |
| `src/datalake/rpa/pdf_extrator.py` | PDF → campos, por rótulo, regras no YAML |
| `src/datalake/rpa/planilha.py` | upsert na planilha existente |
| `src/datalake/rpa/controle.py` | estado em SQLite |
| `src/datalake/rpa/valores.py` | `R$ 1.234,56` → número; chave de SG |
| `conf/rpa/saga_vh47.yml` | **tudo que é ajustável**: textos do menu, colunas, rótulos do PDF, colunas da planilha |
| `scripts/SAGA-VH47.bat` | duplo-clique no servidor (copiado para `C:\datalake`) |
| `C:\datalake\rpa\saga_vh47\` | `pdfs\AAAA\MM\DN\`, `controle.sqlite`, `logs\saga_vh47.log`, `backup_planilha\`, `perfil_navegador\` |

A pasta de trabalho fica fora de `C:\datalake\app`, porque o `instalar_app.ps1`
apaga e baixa essa pasta de novo a cada atualização.

## Configuração (uma vez)

Em `C:\datalake\.env`:

```
SAGA_DN=1234                                   # DN da concessionária (vários: 1234,5678)
SAGA_PLANILHA=C:\caminho\da\planilha\garantia.xlsx
```

- **Login:** é manual. Na primeira execução, faça o login no navegador que
  abrir. A sessão fica guardada em `perfil_navegador\`, e a RPA espera até
  `espera_login_min` minutos. Para login automático, preencha
  `RPA_PORTALVW_USUARIO` e `RPA_PORTALVW_SENHA`. A RPA reaproveita o login do
  `rpa_portal_vw.py`. A senha nunca vai para o código.
- **Planilha:** precisa já existir, como `.xlsx` ou `.xlsm`. As colunas são
  achadas pelo texto do cabeçalho, em qualquer aba e em qualquer uma das 30
  primeiras linhas, sem diferenciar acento, maiúscula ou pontuação. Os apelidos
  aceitos ficam em `planilha.colunas` no YAML.

## Uso

| Comando | O que faz |
|---|---|
| `SAGA-VH47.bat` | fluxo completo |
| `SAGA-VH47.bat --so-listar` | lê a lista do portal e mostra o que falta, sem baixar nem gravar |
| `SAGA-VH47.bat --status` | mostra o que o controle sabe (pendentes e erros com o motivo) |
| `SAGA-VH47.bat --testar-pdf X.pdf --texto` | lê um PDF e mostra o texto e os campos extraídos, sem gravar |
| `SAGA-VH47.bat --importar PASTA` | processa PDFs baixados à mão, com a mesma extração, planilha e controle |
| `SAGA-VH47.bat --headless` | roda sem janela; só funciona com a sessão já guardada |

Códigos de saída: `0` ok · `2` terminou, mas algum arquivo deu erro · `1` falha geral.

**Primeiro teste recomendado**, antes do portal:

1. Baixe 2 ou 3 PDFs à mão.
2. Rode `--testar-pdf` num deles e confira se a SG e o valor saíram certos.
3. Rode `--importar` numa **cópia** da planilha.
4. Rode `--so-listar` para validar a navegação no portal.

## Regras de negócio implementadas

- **O que baixar:** todo arquivo do DN que não esteja `processado` no controle,
  do mais antigo para o mais novo (ano, mês, nome). Isso cobre os dois cenários:
  - **A (em dia):** baixa só os novos.
  - **B (atrasados):** baixa também os faltantes de meses anteriores. Por
    exemplo, os relatórios 03 e 04 de setembro não ficam para trás só porque o
    05 já saiu.
- **Quantidade de fechamentos:** não existe número esperado por mês (nem 4, nem
  5). Quem define é o Portal Rede. Veja a regra crítica abaixo.
- **Identidade do arquivo:** `(ano, mês, regional, DN, nome)`, mais o SHA-256
  do conteúdo. Se o portal renomear um arquivo, o conteúdo igual é reconhecido
  (status `duplicado`) e não entra de novo na planilha.
- **Download:** só conta quando o arquivo final existe. O `.crdownload` é
  tratado pelo Playwright e o arquivo é gravado como `.parcial` até ser
  validado. A validação exige cabeçalho `%PDF`, `%%EOF` no fim e leitura pelo
  pypdf. Se o portal devolver uma página HTML (por exemplo, sessão expirada), o
  arquivo vai para `.invalido`. Se o PDF abrir no visualizador em vez de baixar,
  a RPA busca o arquivo com a mesma sessão.
- **Extração:** por **rótulo**, nunca "o primeiro número do PDF".
  - O valor é procurado depois do rótulo: na mesma linha, com só separadores no
    meio; ou na linha de baixo, na coluna do rótulo (layout de tabela).
  - Os rótulos são testados em ordem de prioridade. "Valor Total da SG" vence
    "Valor Total".
  - O mesmo rótulo com valores diferentes dá **erro de ambiguidade**, em vez de
    escolher um dos valores.
  - Um PDF com várias SGs vira um registro por SG. O cabeçalho repetido em cada
    página não gera duplicidade.
- **Dinheiro:** vai para a planilha como **número** (formato `#,##0.00`). Os
  formatos aceitos estão em `valores.parse_brl`: `R$`, milhar, negativo com
  `-`/`( )`/`D`, NBSP. Formatos ambíguos, como `1,234`, são recusados.
- **Planilha (upsert pela SG):**
  - **SG nova:** vira uma linha nova no fim dos dados, herdando o estilo e as
    fórmulas da linha de cima.
  - **Excel Table:** se os dados estão numa Tabela do Excel, ela cresce junto.
  - **SG existente:** só preenche células **vazias**. Um valor diferente é
    registrado como `divergente` no log e no controle, e o valor da planilha é
    mantido. Isso muda com `ao_divergir: atualizar`.
  - **Campos sem fonte** (NF, data, MO, peças) ficam vazios. Nada é inventado.
  - **Nada é apagado.**
  - **Backup:** `backup_planilha\` recebe uma cópia antes da primeira gravação
    de cada execução. As 30 últimas são mantidas.
  - **Gravação atômica:** grava num arquivo temporário e depois troca.
  - **Planilha aberta no Excel** (existe o arquivo `~$...`): a RPA para com
    mensagem clara e os pendentes ficam para a próxima execução.
  - **Gráficos, imagens ou controles:** a planilha é recusada, porque o openpyxl
    os perderia ao regravar. A chave `permitir_perda_de_objetos` libera a
    gravação.
- **Erros:** se um PDF não puder ser lido, isso não para a execução. O log
  registra `Arquivo / Status: ERRO / Motivo`, o PDF fica guardado e o item é
  tentado de novo na próxima execução, reaproveitando o PDF já baixado. Um erro
  de planilha para a execução, porque seguir gravando não é seguro.
- **Idempotência:** rodar de novo sem relatório novo não baixa, não insere e não
  regrava a planilha (testado).

## Controle (`controle.sqlite`)

Abre no DB Browser for SQLite.

- `arquivos`: um por item da lista. Guarda status (`encontrado`, `baixado`,
  `processado`, `duplicado`, `erro`), tentativas, sha256, caminho do PDF,
  layout, erro e data e hora de encontrado, baixado e processado.
- `registros`: SG por arquivo. Guarda os dados extraídos (JSON), a ação na
  planilha (`inserida`, `atualizada`, `sem_mudanca`, `divergente`) e o detalhe.
- `execucoes`: início, fim, status e resumo de cada execução.

SQLite, e não o `control.duckdb` do lake, porque o DuckDB aceita um único
processo escrevendo, e as cargas de 6×/dia seguram esse arquivo.

## Acrescentar um campo novo (ex.: NF de peças)

1. `conf/rpa/saga_vh47.yml`: em `extracao.layouts[].campos`, acrescente
   `nf_pecas: {tipo: documento, rotulos: ['nf\s+(?:de\s+)?pecas']}`. Já há
   exemplos comentados.
2. Confira que `planilha.colunas.nf_pecas` tem o cabeçalho certo.
3. Rode `--testar-pdf` num PDF para conferir.

Não precisa mexer no código. Se um relatório tiver outro formato, crie mais um
item em `layouts` com `identificar: '<texto que só esse formato tem>'`.

## Regras de negócio confirmadas

### O.S. com letra no fim ("123456A") — relançamento manual

Definida pelo negócio em 24/09/2026.

- `123456A` **não** é erro de leitura nem uma O.S. nova do sistema. É a
  **mesma O.S. de origem relançada à mão** depois de um problema na cobrança.
  O "A" existe para o SAGA não barrar o relançamento como duplicata.
- A automação **preserva exatamente** a identificação: não remove o "A" e não
  converte `123456A` em `123456`.
- **Duplicidade:** `123456` e `123456A` são identificações **diferentes**.
  Nunca tratar uma como duplicata da outra.
  - Na comparação (`valores.chave_numerica`), só o ponto de milhar e os
    espaços são ignorados: `212.646A` casa com `212646A`, mas nunca com
    `212646`.
  - A extração do PDF aceita o sufixo.
- **Na dúvida sobre uma O.S. com "A":** tratar como válida, registrar no log e
  perguntar. Nunca inferir que ela é inválida.
- **Na planilha:** o único caso visto está gravado como **texto com ponto de
  milhar**, `212.646A` (5º Fechamento de Julho 2026). As O.S. numéricas são
  números com formato `#,##0`, que o Excel mostra como `212.646`.
  - **Pendente:** como o SAGA escreve essa O.S. no PDF, e se a automação deve
    gravar `212646A` ou `212.646A`.

## REGRA CRÍTICA: quantidade real de fechamentos do mês

Definida pelo negócio em 25/09/2026.

**O Portal Rede é a fonte de verdade.** A quantidade de fechamentos de um mês
**não** é presumida, fixada nem informada pelo usuário: o auxiliar a descobre
lendo a Lista de arquivos do SAGA2 - VH47 daquele mês (DN 1079).

1. **Não existe regra de 4 ou 5.** Se o portal mostra 4 relatórios, o mês tem 4
   fechamentos. Se mostra 5, tem 5.
2. **Não criar fechamento artificial.** Nada de 5º "reservado", pasta ou
   planilha vazia porque "normalmente existe".
3. **Toda execução compara Portal Rede × Drive:**
   - Portal 5 × Drive 4 → **existe 1 novo fechamento para processar**;
   - Portal 4 × Drive 4 → **nenhum novo fechamento**;
   - Portal 5 × Drive 5 → **todos os fechamentos já foram processados**.
4. **Não basta contar.** Cada fechamento é identificado pelo relatório: nome do
   arquivo, data, período, número de lançamento e SGs do PDF. Assim um arquivo
   duplicado ou uma versão diferente não é confundido com um fechamento novo.
5. **A ordem é:** Portal → analisar o mês → identificar todos os fechamentos →
   quantidade real → comparar com o Drive → identificar os não processados →
   **só então** criar o que falta. Nada é criado antes de saber qual fechamento
   está sendo processado.
6. **Processamento de um fechamento novo:**
   1. pasta/arquivo do fechamento;
   2. PDF;
   3. SGs/O.S.;
   4. planilha;
   5. BRAVOS (NFs e valores);
   6. preenchimento;
   7. conferência;
   8. status **PRONTO PARA CONFERÊNCIA**.
7. **Quando não dá para saber com segurança,** o resultado é **STATUS: NECESSITA
   CONFERÊNCIA** ("Não foi possível determinar com segurança a quantidade de
   fechamentos disponíveis no Portal Rede para o período"). A execução para
   antes de criar qualquer arquivo.

**Papéis:** o Portal Rede determina a realidade. O Drive registra e organiza. O
BRAVOS complementa as SGs/O.S. com NFs e valores. A planilha consolida. O
Henrique faz a conferência final.

Implementação: `rpa-saga/comparar_mes.py` (Portal × Drive, só leitura).

## O PDF VH47 real (analisado em 24/09/2026)

Arquivo de referência: `2026-09-22.001079_RELATORIO_VH47 (2).pdf`, na pasta do
Drive `2026/Mês 09 - Setembro`.

- **Nome do arquivo:** `AAAA-MM-DD.<DN com 6 dígitos>_RELATORIO_VH47.pdf`.
- **Formato:** 11 páginas em paisagem, geradas pelo iText. O texto é
  extraível (não é imagem).
- **Título:** "RELACAO DOS CREDITOS PROCESSADOS - VH47A".
- **Cabeçalho de cada página:**
  - `PERIODO: 21.09.2026 A 22.09.2026`
  - `DN: 001079-TTERRASUL…`
  - `FR: 0,9429` (significado **desconhecido**; vale 0,0000 em algumas páginas)
  - `NUM.LANCAMENTO: 5.969.254`
  - `DATA DO PROCESSAMENTO: 22.09.2026`
- **Um bloco por SG**, com as colunas:
  - `NUMERO O.S` (com "A" quando é relançamento: `214265A`, sem ponto)
  - `SR`, `VR` (versão)
  - `TG` (tipo), `DEF`, `FOR`, `N.IDS`
  - `DT.VENDA`, `DT.REPAR`, `KM`, `CHASSI`
  - `TOTAL M.OBRA`, `TOTAL MATERIAL`, **`TOTAL SG`**

  Abaixo de cada bloco vêm as linhas de peça e mão de obra.
- **Resumo na última página:** `QT.SG`, `TOTAL M.OBRA`, `TOTAL MAT`,
  `TOTAL SGS` (CRED/DEB/TOT), mais a seção **CANCELAMENTOS**.
- **Somas que conferem:**
  - em todos os 44 blocos, `TOTAL M.OBRA + TOTAL MATERIAL = TOTAL SG`;
  - a soma dos TOTAL SG = `TOTAL SGS` do resumo (14.471,50).

  A extração deve **validar essas duas somas**. Se uma não bater, o resultado é
  ERRO DE EXTRAÇÃO.

### Regras de negócio sobre o PDF

- **Crédito:** o **TOTAL SG** é o crédito pago naquela versão (VR). Ele vai
  para a coluna **VALOR CRÉDITO**. Se a mesma SG voltar paga como versão 02, o
  crédito é o valor da versão 02. (Definido pelo negócio.)
- **Chave da SG:** a mesma O.S. pode vir com **SR 01 e SR 02** no mesmo
  relatório (ex.: 214074, 214397). São **duas SGs** e viram duas linhas.
  - A chave da SG é **O.S. + SR (+ VR)**, e não só a O.S.
  - A planilha não guarda SR nem VR. Por isso o controle de duplicidade precisa
    guardar essa chave no histórico do Auxiliar.
- **Seção da planilha:** TG `1S1`/`1S2`/`1S3` = revisão → seção **REVISÕES**.
  - Evidência: nos 13 fechamentos de jul–set/2026, os 33 créditos com valor
    típico de revisão (649,71 / 754,76 / 772,71) estão todos em REVISÕES.
  - Não se sabe ainda para onde vão os outros TG (`710`, `110` = principal?)
    nem RECONSIDERAÇÃO e LOCAÇÕES.
- **Relatório × fechamento:** nenhuma das 42 O.S. deste relatório (de 22/09)
  está nos fechamentos existentes. O único vazio é o 4º de setembro, criado em
  23/09. Isso é consistente com **1 relatório = 1 fechamento**, mas foi
  observado **uma vez só**; confirmar com outros pares relatório × fechamento.

## Fechamentos no Drive (análise de 24/09/2026)

Veja a análise completa na conversa do projeto. Pontos que o código precisa
respeitar:

- **Formato:** os arquivos são **.xls (Excel 97-2003)** e têm de continuar
  `.xls`. O openpyxl (`planilha.py`) **não** serve para eles.
- **Ferramenta de edição:** a escolhida é o **Apache POI (Java)**.
  - Nos testes, só as células gravadas e os resultados de fórmula mudaram.
    Abrir e salvar os 13 fechamentos de jul–set/2026 deu **0 diferenças**.
  - O LibreOffice regrava a formatação (datas, larguras, estilos).
  - O xlutils transforma as fórmulas em números fixos.
- **Estrutura da planilha:** uma aba, "Quinzena".
  - Linha 1: `Nº Fechamento | Mês de AAAA | Matriz`.
  - Linha 2: cabeçalho `Nº OS | Nº NF P. | Nº NF S. | DATA EMISSÃO |
    VAL. NF. SERV. | VAL. NF. PEÇA | VALOR CRÉDITO | DIFERENÇA`.
  - Seções com linhas pré-formatadas e fórmula de DIFERENÇA: principal
    (linhas 3–136), REVISÕES, RECONSIDERAÇÃO DE GARANTIAS e LOCAÇÕES, cada
    uma com sua linha TOTAL, mais o TOTAL GERAL.
- **Estilo:** o das linhas vazias do meio de cada seção é **igual** ao das
  linhas lançadas à mão. Preencher uma linha vazia mantém o padrão.
- **A mesma O.S. em mais de um fechamento é normal.** Há 45 casos de
  pagamento em partes, com observações como "Diferença deverá ser quitada no
  próximo fechamento". A regra anti-duplicidade vale **dentro de cada
  fechamento**, não na pasta inteira.
- **Ainda não comprovado:**
  - se 1 relatório SAGA corresponde a 1 fechamento (a quantidade por mês varia;
    quem define é o Portal Rede);
  - qual seção cada SG ocupa;
  - se VALOR CRÉDITO é o "valor total da SG".

  Tudo isso depende dos PDFs reais.

## Padrão de entrega de um fechamento (obrigatório)

Toda planilha que o auxiliar entregar segue isto. Se algum item falhar, não
entrega: avisa o que falhou.

1. **Formato `.xls`** (Excel 97-2003), editado com POI em cima do modelo do
   mês. Nunca `.xlsx`, nunca Google Planilhas no lugar do arquivo oficial.
2. **Nome no padrão da pasta:** `Nº FECHAMENTO DE MÊS AAAA.xls`, por exemplo
   `4º FECHAMENTO DE SETEMBRO 2026.xls`. Sem sufixos como "- PREENCHIDO" ou
   "PRÉVIA".
3. **Design do modelo intacto:** aba "Quinzena", logo, seções, fórmulas de
   DIFERENÇA e TOTAL. Só as células lançadas mudam.
4. **Conferência antes de entregar:**
   - todas as SGs do PDF estão na planilha, sem sobra e sem O.S. repetida;
   - valor por O.S. = soma das versões (SR 01 + 02...);
   - SG com TG `1S*` fica em REVISÕES, as demais na seção principal;
   - O.S. com "A" no fim mantém o "A";
   - TOTAL GERAL do VALOR CRÉDITO = TOTAL SGS do resumo do PDF;
   - nenhum valor com 3 ou mais casas decimais.
5. **Colunas de NF** só com dado de fonte (BRAVOS/Linx). Sem fonte, ficam
   vazias.
6. **Nada de arquivo extra na pasta oficial** (prévias, cópias, testes).
   Testes vão para uma pasta de teste.
7. **Arquivo no Drive:** o conector do Drive só aceita o arquivo convertido em
   texto (base64). Um `.xls`/`.xlsx` real chega corrompido por esse caminho.
   Por isso o arquivo vai pela pasta do Drive sincronizada no servidor
   (`claude remote-control`) ou é arrastado pelo usuário. Depois de qualquer
   envio, confira se o tamanho no Drive é igual ao do arquivo local.

## Auditoria de débitos e erros (`rpa-saga/debitos.py`)

`DEBITOS.bat` lê todos os fechamentos e soma, por O.S., os créditos de todos
os fechamentos em que ela aparece. Esse total é comparado com a NF
(serviço + peça). Não altera nada.

- **Débito:** a NF é maior que o total creditado, com diferença acima de
  R$ 0,10, e a última observação da O.S. não diz "quitada".
- **Erros de planilha que ele aponta:**
  - valor com 3 ou mais casas decimais;
  - O.S. repetida no mesmo fechamento;
  - linha de O.S. sem crédito e sem NF.

Primeira auditoria (jul–set/2026 mais o 4º de setembro novo), em 26/09/2026:

- **11 O.S. com NF emitida no 1º de setembro e nenhum crédito da VW** até o
  4º de setembro: 213940, 213725, 213842, 213788, 214021, 213849, 214004,
  214019, 213785, 213644 e 213963.
- **213768:** crédito parcial, faltam R$ 201,70.
- **212825 e 213138:** NF de R$ 669,33 com crédito de R$ 639,14; faltam
  R$ 30,19 em cada uma.
- **213048:** faltam R$ 24,69.
- **3º de setembro de 2026:**
  - 12 linhas de O.S. sem crédito e sem NF, iguais às O.S. sem crédito do 1º
    (lista copiada?);
  - 213768 repetida (linhas 47 e 48);
  - 213893 com crédito 101,173.
- **1º de setembro de 2026:** a 213992 tem VAL. NF. SERV. 101,173.

## Lições aprendidas (erros do auxiliar e a correção)

| Erro | Correção / regra |
|---|---|
| `--baixar` pegava o PDF mais antigo | pega o mais recente pela data no nome do arquivo |
| Supor 4 ou 5 fechamentos por mês | a quantidade vem do Portal Rede (`comparar_mes.py`) |
| Prévia no Google Planilhas com ponto decimal virou texto (#VALOR!) | valores em pt-BR ("176,96"); e, pelo padrão acima, nada de prévia na pasta oficial |
| Prévia sem o design antigo | sempre partir do `.xls` modelo do mês, nunca montar do zero |
| Entregue `.xlsx` e nome com "- PREENCHIDO" | padrão de entrega, itens 1 e 2 |
| Upload pelo conector do Drive chegou corrompido (17 KB em vez de 26 KB) | padrão de entrega, item 7; o arquivo corrompido foi para a lixeira na hora |
| Falar em "planilha pronta" sem conferir débitos anteriores | rodar `debitos.py` junto com o fechamento novo e avisar o que está em aberto |

## Solução de problemas

| Sintoma | Causa provável / o que fazer |
|---|---|
| `Etapa 'SAGA': nao achei 'SAGA'` | o texto do menu é outro: ajuste `portal.caminho` (regex) |
| `Nao achei o link "Lista de arquivos" do relatorio SAGA2 - VH47` | ajuste `portal.relatorio` ou `portal.link_lista` |
| `nao achei a tabela` | os cabeçalhos da lista são outros: ajuste `lista.colunas` |
| `Nao foi possivel localizar o numero da SG` | rode `--testar-pdf X.pdf --texto`, veja como o rótulo aparece e ajuste `rotulos` |
| `... ambiguo` | o rótulo aparece com dois valores: use um rótulo mais específico |
| `PDF sem texto (imagem escaneada?)` | o PDF é imagem: precisa de OCR (não implementado) |
| `A planilha esta aberta no Excel` | feche a planilha e rode de novo |
| `A lista parece ter varias paginas` | a paginação não foi implementada: veja as pendências |

## Pendências

- **Validar com o portal e os PDFs reais.** Os textos do menu, os rótulos
  do PDF e os cabeçalhos são o melhor palpite. Os testes usam um portal e
  PDFs falsos que imitam o fluxo descrito. Depois do primeiro teste real,
  ajuste o YAML.
- Paginação da Lista de arquivos, se existir.
- Agendamento (Tarefa Agendada com `--headless`), depois que a sessão guardada
  se mostrar estável.
- OCR para PDF escaneado, se aparecer.
