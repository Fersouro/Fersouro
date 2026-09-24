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
- **Aviso de lacuna:** se um mês já fechado tem menos arquivos no portal que
  `esperado_por_mes` (4), a RPA registra um aviso no log.
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
