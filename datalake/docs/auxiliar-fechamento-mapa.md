# Auxiliar de Fechamento da Garantia VW: mapa técnico de dependências e acessos

> **Status: levantamento para validação. Nenhuma integração nova deve ser
> implementada antes da validação dos acessos e das permissões deste
> documento.**
> Versão 1 (24/09/2026). Rótulos usados em todo o texto:
> **[VERIFICADO]** foi observado por mim em arquivo ou sistema real;
> **[HIPÓTESE]** é indício que ainda precisa de prova;
> **[DESCONHECIDO]** não tenho informação.

## 0. Princípio

O Auxiliar não é um robô que preenche planilha. O ciclo dele é:
**consultar → identificar → extrair → relacionar → validar → comparar →
registrar → alertar → gerar evidência → preservar histórico.**

Sem evidência suficiente, o Auxiliar **para e pergunta** (INCONCLUSIVO). Ele
nunca escolhe uma possibilidade por conta própria e nunca interpreta uma falha
técnica como ausência de informação.

---

## 1. O que já sei com evidência

| Fato | Evidência |
|---|---|
| Os fechamentos ficam no Google Drive, pasta "Bagé" (dona: garantia2@), em `Ano / Mês / Nº FECHAMENTO … .xls` | [VERIFICADO] listagem de 2022–2026 |
| Os arquivos são **.xls (Excel 97-2003)**, aba "Quinzena", com cabeçalho `Nº OS · Nº NF P. · Nº NF S. · DATA EMISSÃO · VAL. NF. SERV. · VAL. NF. PEÇA · VALOR CRÉDITO · DIFERENÇA` e as seções Principal, Revisões, Reconsideração de Garantias e Locações, cada uma com TOTAL, mais o TOTAL GERAL | [VERIFICADO] 13 arquivos de jul–set/2026 lidos por completo |
| DIFERENÇA = crédito − (NF serviço + NF peça). Um valor negativo é **crédito menor que o faturado** | [VERIFICADO] fórmula `=(G-(F+E))` em 251 linhas |
| A mesma O.S. aparece em vários fechamentos quando o pagamento vem em partes ("Diferença deverá ser quitada no próximo fechamento" → "Diferença quitada") | [VERIFICADO] 45 casos entre jul e set/2026 |
| A quantidade de fechamentos por mês **varia** (jul/2026: 5; ago: 4). **Quem define é o Portal Rede**: não há número fixo (regra crítica em `saga-vh47.md`) | [VERIFICADO] Drive; regra definida pelo negócio |
| O.S. com letra no fim (ex.: `212.646A`) = relançamento manual da mesma O.S. | [VERIFICADO] regra do negócio; 1 caso na planilha |
| O Apache POI edita o `.xls` sem alterar nada além das células gravadas | [VERIFICADO] 13 arquivos regravados, 0 diferenças |
| O ERP Linx (Oracle, schema CNP) já chega ao datalake **somente leitura**: `OFI_ORDEM_SERVICO` (com `DTA_FIM_GARANTIA` e `SERVICO_GARANTIA`), `FAT_MOVIMENTO_CAPA` (notas), `FAT_MOVIMENTO_ITEM`, `FAT_FONTE` (fonte pagadora "garantia") | [VERIFICADO] `conf/sources/ccm.yml` e `sql/gold/*` |
| As colunas Nº OS, NF P., NF S., DATA EMISSÃO e VAL. NF da planilha vêm do Linx | **[HIPÓTESE]** os números (O.S. ~21xxxx, NF ~10xxxx) são compatíveis, mas não foram cruzados |
| 1 relatório SAGA VH47 = 1 fechamento | **[HIPÓTESE]** só a contagem por mês bate; nenhum PDF visto |
| VALOR CRÉDITO = "valor total da SG" do PDF | **[HIPÓTESE]** |
| A estrutura do PDF VH47, o que é "SG", e se SG = O.S. | **[DESCONHECIDO]** nenhum PDF visto |
| Portal Rede: login, MFA, CAPTCHA, termos de uso | **[DESCONHECIDO]** o portal é bloqueado no ambiente de desenvolvimento |
| eClaims, DISS, AOR, ITP, WPL: função, acesso e necessidade | **[DESCONHECIDO]** não tenho conhecimento confiável do papel de cada um na Terrasul e não vou presumir |

---

## 2. Fluxo técnico reconstruído

```
[1] Portal Rede VW (login)
      └─ Garantia Volkswagen → SAGA → SAGA2 - VH47 → "Lista de arquivos"
[2] Lista: Ano · Mês · Regional · DN (1079) · Nome do arquivo
      └─ o que é novo? (controle: chave do item + hash do PDF)
[3] Download do PDF → validação (é PDF? está inteiro? dá para ler?) → guarda com hash
[4] Extração por rótulo: SG/O.S., valor, período, tipo (garantia/revisão/…)
      └─ evidência: página, linha e trecho do texto de onde saiu cada valor
[5] Período de referência = o do RELATÓRIO (Ano/Mês da lista e do PDF), nunca o relógio
[6] Drive: Bagé / Ano / Mês → fechamentos do mês → qual recebe? (regra a provar)
      └─ ambíguo → INCONCLUSIVO, sem escrita
[7] Cruzamento (auditoria):
      ├─ O.S. no Linx? NF de serviço/peça, data e valores batem? [HIPÓTESE da fonte]
      ├─ O.S. já está neste fechamento? (duplicidade dentro do fechamento)
      ├─ O.S. em fechamentos anteriores com "diferença a quitar"? (acompanhamento)
      └─ O.S. com "A": relançamento válido; nunca é duplicata de "123456"
[8] Cópia de trabalho do .xls → POI grava na linha vazia da seção certa
[9] Validação: fórmulas, estilos e mesclagens intactos; totais conferem; só as células previstas mudaram
[10] Relatório ANTES × DEPOIS + evidências → aprovação humana
[11] (Fase posterior, com autorização) envio ao Drive como nova versão do mesmo arquivo
[12] Histórico: execução, fontes, arquivos, hashes, decisões, alertas
```

**Um ganho de auditoria que os dados já mostram:** as linhas "Diferença
deverá ser quitada no próximo fechamento" formam uma **lista de pendências
financeiras**. O Auxiliar pode acompanhar cada uma até aparecer "Diferença
quitada" e alertar quando uma diferença ficar em aberto por mais de N
fechamentos. É aí que se escondem os débitos que a empresa não percebe.

---

## 3. Matriz de fontes de dados

### 3.1 Resumo

| # | Fonte | Informação | Finalidade | Acesso | Autenticação | Permissão mínima | Integração | Risco | Necessária? |
|---|---|---|---|---|---|---|---|---|---|
| F1 | Portal Rede VW | sessão e navegação até a garantia | porta de entrada | leitura | login + senha; MFA/CAPTCHA [DESC.] | usuário que só **consulta** a Garantia/SAGA | navegador (Playwright); API não identificada | **Alto** | **Sim** |
| F2 | SAGA2 – VH47, "Lista de arquivos" | Ano, Mês, Regional, DN, Nome, link | saber o que existe e o que é novo | leitura e download | sessão do F1 | consulta e download de relatórios | navegador | Alto | **Sim** |
| F3 | PDF VH47 | SG/O.S., valor, período, tipo [HIP.] | dado principal do lançamento | arquivo local | nenhuma | nenhuma | arquivo (pypdf) | Médio (layout pode mudar) | **Sim** |
| F4 | Google Drive, pasta "Bagé" | fechamentos .xls, estrutura, histórico | destino e fonte de duplicidade/pendências | fase 1: **leitura**; fase 2: edição | OAuth (conta Google) | fase 1: **Leitor** na "Bagé"; fase 2: **Editor só na "Bagé"** | API do Drive | Médio (fase 1) / **Alto** (fase 2) | **Sim** |
| F5 | Planilha de fechamento (.xls) | linhas, fórmulas, totais, observações | escrita (fase 2) e conferência | arquivo local (cópia) | — | — | Apache POI | Alto na escrita | **Sim** |
| F6 | ERP Linx, via datalake (Oracle CNP) | O.S., NF serviço/peça, data de emissão, valores, fonte pagadora | **conferir** SG/O.S. × NF × valores; preencher NF/data depois | leitura (já existe) | usuário Oracle somente leitura (já existe) | SELECT nas tabelas usadas | datalake (Parquet/DuckDB) | Baixo | **Provável** (a confirmar pelo cruzamento) |
| F7 | E-mail corporativo | aviso de novo crédito/fechamento? [DESC.] | gatilho/confirmação | leitura | OAuth, escopo `gmail.readonly` | só leitura, filtrado por remetente | API do Gmail | Médio (dados pessoais) | **Não determinada** |
| F8 | eClaims | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | **Não determinada** |
| F9 | DISS | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | **Não determinada** |
| F10 | AOR | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | **Não determinada** |
| F11 | ITP | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | **Não determinada** |
| F12 | WPL | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | [DESC.] | **Não determinada** |
| F13 | Crédito efetivamente recebido (extrato/contas a receber) | valor pago pela VW por fechamento | provar que o crédito do fechamento entrou | leitura | [DESC.] | leitura | [DESC.] | Médio | **Não determinada** |
| F14 | Servidor `C:\datalake` (Windows) | execução, agendamento, cofre de credenciais | onde o Auxiliar roda | execução | conta Windows de serviço | usuário local sem privilégio de administrador | Agendador de Tarefas | Médio | **Sim** |
| F15 | Histórico do Auxiliar (SQLite + pasta de evidências) | execuções, arquivos, hashes, decisões | auditoria e anti-duplicidade | leitura/escrita local | ACL do Windows | só a conta de serviço e os administradores | local | Baixo | **Sim** |

**Sobre F8 a F12:** não vou atribuir função a esses sistemas sem informação
do setor. Para cada um preciso saber:
1. O que ele mostra (situação da SG? recusas? pagamentos? peças? tempos padrão?).
2. Se existe informação lá que **não** está no PDF VH47 nem no Linx.
3. Como se acessa (dentro do Portal Rede ou separado; login; MFA).
4. Se exporta relatório.

Só entra no projeto o que for necessário para uma conferência que hoje é feita
à mão.

### 3.2 Detalhe por fonte

#### F1/F2: Portal Rede VW e SAGA2 – VH47

- **URL:** https://www.portalredevw.com.br/portalredevw2/default.aspx (ASP.NET)
- **Informações:** Lista de arquivos com Ano, Mês, Regional, DN, Nome do arquivo
  e link. Paginação [DESC.]. Data de disponibilização [DESC.].
- **Autenticação:** usuário e senha [provável]. MFA, CAPTCHA, certificado,
  VPN ou restrição de IP: **[DESCONHECIDO]**. Duração da sessão e bloqueio
  após tentativas erradas: [DESC.].
- **API ou integração oficial:** não identificada. Precisa ser perguntado à VW
  ou à regional. **Os termos de uso do portal precisam permitir o acesso
  automatizado**. Se proibirem, o caminho é o download manual e o Auxiliar
  processa o arquivo.
- **Permissão mínima:** perfil que só **consulta e baixa** relatórios de
  Garantia/SAGA. **Não deve** ter permissão para transmitir, alterar ou
  cancelar SG, aprovar ou mexer em cadastro. Se a VW não oferecer perfil só de
  leitura, o risco sobe e o código precisa de uma lista fechada de páginas
  permitidas (ver §6).
- **O que NÃO acessar:** qualquer tela fora de Garantia → SAGA → VH47 → Lista
  de arquivos; formulários de envio e alteração de SG; dados de clientes; outras
  concessionárias (DN ≠ 1079).
- **Dependências:** Microsoft Edge ou Chromium, Playwright, rede com saída
  para o domínio. Quando houver CAPTCHA ou MFA, é preciso uma pessoa.
- **Frequência:** semanal (quarta-feira), mais execução sob demanda.
- **Automação:** possível tecnicamente, **não validada**. Depende de login,
  MFA, CAPTCHA e termos de uso.
- **Evidências a guardar:** data e hora da consulta; a lista lida (tabela
  inteira, em JSON); print da lista, **sem** a tela de login; PDFs com hash.
- **Indisponibilidade:** status ERRO DE ACESSO. **Nunca** "nenhum fechamento".
- **Responsável pelo acesso:** [a definir por Henrique].

#### F3: PDF VH47

- **Informações:** SG, O.S. (e se são a mesma coisa), valor por SG, valor
  total, período, tipo (garantia/revisão/reconsideração/locação), DN,
  identificador do relatório, várias SGs por PDF. **Tudo [DESCONHECIDO]
  até ver um PDF real.**
- **Integração:** leitura local de texto (pypdf). Se o PDF for imagem
  escaneada, precisa de OCR, o que traz um risco maior de erro de leitura.
- **Evidências:** hash SHA-256; página e linha de cada valor extraído; regra
  de extração usada; versão do layout.
- **Mudança de layout:** vira ERRO DE EXTRAÇÃO, com alerta de "PDF diferente
  do padrão". Não tenta adivinhar.

#### F4/F5: Google Drive e planilhas .xls

- **URL:** pasta "Bagé", `1phL9jeBABpyvfnLsk332v-ryDShByCkk`.
- **Situação atual:** a conta fernando@ lista, baixa e lê. Ela **aparenta**
  ter escrita (`canAddChildren = true`), mas isso **não foi testado**.
- **Permissão mínima:**
  - **fase 1 (só leitura): Leitor na "Bagé"**, com escopo OAuth
    `drive.readonly`;
  - **fase 2 (escrita): Editor só na "Bagé"**. O escopo `drive` é amplo, e o
    limite real passa a ser **o que a conta enxerga**. Por isso recomendo uma
    **conta Google dedicada** (ex.: `auxiliar.garantia@tterrasul.com.br`)
    compartilhada **somente** na "Bagé", e não a conta pessoal de alguém,
    que enxerga todo o Drive dessa pessoa.
- **Integração:** API do Drive (baixar, conferir o md5 e a revisão, enviar uma
  nova versão do **mesmo** arquivo). Edição com Apache POI. Nunca criar arquivo
  novo no lugar do oficial.
- **Evidências:** ID do arquivo, ID da revisão antes e depois, md5 antes e
  depois, as células alteradas (endereço, valor antes, valor depois), totais
  antes e depois.
- **Concorrência:** se o arquivo mudou entre o download e o envio, **não
  envia** e alerta.
- **Indisponibilidade:** ERRO DE ACESSO. A execução para antes de escrever;
  PDFs e extrações ficam guardados para a próxima.

#### F6: ERP Linx (via datalake)

- **Já existe:** usuário Oracle somente leitura e carga horária para o
  datalake.
- **Uso proposto:** **conferência**. A O.S. existe? Foi faturada em garantia?
  NF de serviço/peça, data e valores batem com a planilha?
  - Mais tarde, pode preencher NF e data que hoje são digitadas à mão, **só
    depois** de provado que é exatamente a mesma informação.
- **Investigação necessária:** cruzar as O.S. de um fechamento real com
  `OFI_ORDEM_SERVICO` e `FAT_MOVIMENTO_CAPA`. Com isso eu provo ou descarto a
  hipótese, sem escrever nada.
- **Risco:** baixo (leitura de uma cópia no lake).

---

## 4. Campos necessários (dicionário mínimo)

| Campo | Fonte primária | Conferência | Destino | Situação |
|---|---|---|---|---|
| DN | Lista SAGA / PDF | config (1079) | filtro | [VERIFICADO] lista tem DN |
| Ano, Mês de referência | Lista SAGA / PDF | nome da pasta e linha 1 da planilha | escolha da pasta | [VERIFICADO] lista; PDF [DESC.] |
| Regional | Lista SAGA | — | identidade do arquivo | [VERIFICADO] lista |
| Nome/ID do relatório | Lista SAGA | hash do PDF | anti-duplicidade | [VERIFICADO] lista |
| SG | PDF | — | chave (Nº OS?) | [DESCONHECIDO] relação SG × O.S. |
| O.S. | PDF [HIP.] / Linx | Linx | coluna Nº OS | [HIPÓTESE] |
| Valor da SG / crédito | PDF | soma do relatório × TOTAL | VALOR CRÉDITO [HIP.] | [HIPÓTESE] |
| Tipo (garantia/revisão/…) | PDF [HIP.] | Linx (`SERVICO_GARANTIA`, fonte) | seção da planilha | [DESCONHECIDO] |
| NF serviço, NF peça, data de emissão, valores de NF | Linx [HIP.] | planilha existente | colunas B–F | [HIPÓTESE] |
| Nº do fechamento | Drive (nome do arquivo + linha 1) | ordem de chegada dos relatórios | arquivo de destino | regra [DESCONHECIDA] |
| Observação ("diferença a quitar") | planilha | fechamentos seguintes | acompanhamento de pendências | [VERIFICADO] |

---

## 5. Credenciais: arquitetura segura

**Situação atual, a corrigir:**
- A senha do Oracle fica **em texto puro em `C:\datalake\.env`**. O arquivo
  está fora do git, mas qualquer pessoa com acesso à pasta a lê.
- O `rpa_portal_vw.py` foi desenhado para ler a senha do portal do mesmo `.env`.

**Proposta, adequada ao servidor Windows real:**

1. **Windows Credential Manager (DPAPI)**, acessado pela biblioteca `keyring`
   do Python.
   - O segredo fica cifrado e amarrado à **conta Windows de serviço** que roda
     a tarefa agendada. Outra conta, ou o disco copiado para outra máquina,
     não consegue decifrar.
   - Nomes, por exemplo: `auxiliar-garantia/portal-rede`,
     `auxiliar-garantia/google-oauth`, `datalake/oracle`.
2. **Cadastro por um script interativo** (`CADASTRAR-CREDENCIAL.bat`):
   - pede a senha com `getpass`, sem eco na tela;
   - grava no cofre;
   - **nunca** escreve em arquivo, log ou terminal.

   A troca de senha usa o mesmo script.
3. **Google:** OAuth de uma **conta dedicada**. O *refresh token* fica no
   Credential Manager, não num `token.json`.
   - Fase 1 com escopo `drive.readonly`.
   - Se o token for revogado ou expirar: ERRO DE ACESSO com alerta
     "credencial expirada", e pede novo consentimento.
4. **Oracle:** migrar a senha do `.env` para o cofre. O `.env` fica só com
   configuração não secreta: DN, IDs de pasta, caminhos.
5. **Perfil do navegador** (guarda cookies de sessão = equivalente a
   credencial): pasta com permissão **só** para a conta de serviço.
6. **Nunca:** segredo no código, no git, no CLAUDE.md, na documentação, em log,
   em print, em mensagem de erro ou em argumento de linha de comando (que
   aparece na lista de processos).
   - O log registra apenas "autenticação realizada com sucesso" ou "falhou
     (motivo técnico)".
   - O HTML de páginas de erro não pode ser salvo quando a página tiver campo
     de senha.
   - Os prints nunca mostram a tela de login.
7. **MFA:** se existir, a automação **não** contorna. O fluxo é:
   - a execução pausa com status "necessita MFA";
   - avisa o responsável;
   - a pessoa conclui o login no navegador do Auxiliar;
   - a sessão guardada é reaproveitada até expirar.
8. **Revisão periódica:** lista de quem tem acesso a cada credencial; troca de
   senha quando alguém sai do setor.

---

## 6. Menor privilégio e separação leitura × alteração

| Fase | O que o Auxiliar faz | O que é proibido |
|---|---|---|
| **1: Leitura e auditoria** (inicial) | consulta o portal, baixa PDFs, lê o Drive, lê o Linx, extrai, cruza, valida, gera relatório e alertas, gera **cópia de trabalho local** com ANTES × DEPOIS | gravar no Drive; qualquer ação no portal além de navegar e baixar |
| **2: Escrita assistida** (após validação) | envia a nova versão ao Drive **só depois da aprovação humana** de cada ANTES × DEPOIS | gravar sem aprovação; gravar em fechamento sem regra comprovada |
| **3: Escrita automática** (se um dia for aprovada) | grava sozinho casos inequívocos, com backup, versão e verificação | casos INCONCLUSIVOS continuam humanos |

**Proteção no código:** a navegação no portal usa uma **lista fechada** de
passos (os textos do caminho até a Lista de arquivos e o link de download).
Clicar em botão fora dessa lista é bloqueado e registrado. Botões como
"Enviar", "Transmitir", "Excluir", "Cancelar", "Aprovar" e "Salvar" nunca são
acionados pelo Auxiliar.

---

## 7. Histórico, auditoria e evidência

**Por execução:** id, início e fim, ambiente (DEV/HOMOLOG/PROD), status final
(§9), fontes consultadas e resultado de cada uma, período procurado.

**Por arquivo:** chave do item da lista, hash SHA-256, tamanho, origem, data de
download, caminho guardado, layout reconhecido e status.

**Por dado extraído:** a cadeia completa de evidência:

```
Fonte (Portal/SAGA, lista lida em dd/mm hh:mm)
 → documento (arquivo.pdf, sha256=…)
 → página 2, linha 14: "SG 210238 ... Total 1.245,80"
 → regra de extração "valor_total v1"
 → transformação: "1.245,80" → 1245.80
 → destino: "3º FECHAMENTO DE SETEMBRO 2026.xls", aba Quinzena, G45 (cópia de trabalho)
 → validações: fórmula H45 intacta; TOTAL G137 antes X / depois X+1245,80; nenhuma outra célula alterada
 → decisão: PRONTO PARA APROVAÇÃO | INCONCLUSIVO (motivo)
```

Fica guardado: a cópia de trabalho, o relatório ANTES × DEPOIS (HTML/XLSX) e o
JSON da cadeia acima. Nenhum dado sensível além do necessário; nenhum segredo.

---

## 8. Anti-duplicidade

| Nível | Chave | Observação |
|---|---|---|
| Item da lista | Ano + Mês + Regional + DN + Nome | nome pode mudar → complementado pelo hash |
| PDF | SHA-256 do conteúdo (+ tamanho) | renomeado ou reenviado com o mesmo conteúdo → "duplicado" |
| PDF corrigido | mesmo item, hash diferente | **INCONCLUSIVO**: "documento reenviado com conteúdo diferente" (nunca substitui em silêncio) |
| Fechamento | ID do arquivo no Drive + nº + mês/ano da linha 1 | nome do arquivo varia (º/°, espaços, "Matriz -") |
| SG/O.S. no fechamento | chave normalizada **dentro** do fechamento | repetir em **outro** fechamento é normal (pagamento parcial) |
| O.S. com "A" | chave própria (`212646A` ≠ `212646`) | relançamento; nunca é duplicata da O.S. sem "A" |
| Período | ano/mês + lista de itens processados | reprocessar um período mostra o que já foi feito |

---

## 9. Monitoramento semanal (quarta-feira): status

| Status | Quando | Ação |
|---|---|---|
| **NOVO FECHAMENTO** | acessou, achou item novo, baixou, extraiu e validou | gera cópia de trabalho + ANTES × DEPOIS, avisa |
| **NENHUM NOVO FECHAMENTO** | acessou a lista **com sucesso** e todos os itens do DN já estavam processados | registra "consultado às hh:mm, N itens, 0 novos" |
| **INCONCLUSIVO** | ambiguidade: dois fechamentos possíveis, período conflitante, PDF reenviado diferente, O.S. desconhecida no Linx… | para e explica: o que achou, as possibilidades, as evidências e o que falta |
| **ERRO DE ACESSO** | portal, Drive ou Linx fora do ar; login falhou; MFA; sessão expirada | **nunca** vira "nenhum fechamento"; alerta com o motivo técnico |
| **ERRO DE EXTRAÇÃO** | baixou, mas não conseguiu ler ou interpretar (layout novo, PDF corrompido, escaneado) | guarda o PDF e alerta "PDF diferente do padrão" |
| **ERRO DE VALIDAÇÃO** | leu, mas os dados não passaram nas regras (total ≠ soma, fórmula alterada, estrutura da planilha diferente) | nada é escrito; alerta com o detalhe |

Cada fonte tem o próprio status dentro da execução. O status geral é o
**pior** dos status das fontes.

---

## 10. Alertas

Novo fechamento · fechamento atrasado (quarta sem novidade por mais de N
semanas, a calibrar pelo histórico) · fechamento duplicado · PDF reenviado
com conteúdo diferente · PDF fora do padrão · período inesperado (futuro,
muito antigo, virada de mês) · SG não localizada · O.S. não localizada no Linx
· O.S. com "A" (informativo) · várias SGs · valor divergente (PDF × planilha ×
Linx) · **diferença em aberto há mais de N fechamentos** · fórmula alterada ·
total divergente · estrutura da planilha diferente do modelo · documento
incompleto ou corrompido · fonte indisponível · credencial expirada · sessão
expirada · MFA necessário · estrutura do portal mudou (passo do caminho não
encontrado).

Canal do alerta: [a definir: e-mail, arquivo, página do datalake].

---

## 11. Ambientes

| | DEV | HOMOLOGAÇÃO | PRODUÇÃO |
|---|---|---|---|
| Onde | ambiente de desenvolvimento (nuvem) e testes automatizados | servidor `C:\datalake`, pasta de trabalho separada | servidor `C:\datalake` |
| Dados | portal falso, PDFs sintéticos, cópias dos .xls | portal real (**só leitura**), **pasta de teste** no Drive, cópias | portal real, pasta "Bagé" |
| Credenciais | nenhuma real | conta real, **só leitura** | conta dedicada; escrita só na fase 2 |
| Escrita no Drive | nunca | só na pasta de teste | só após aprovação (fase 2) |

A configuração do ambiente fica no YAML (`ambiente: dev|homolog|prod`).
**Produção exige ID de pasta explícito**: sem ele, nada é escrito.

---

## 12. Contingência

| Situação | Comportamento |
|---|---|
| Portal fora do ar / lento | tenta de novo com espera crescente (3×); depois ERRO DE ACESSO. Não conclui nada sobre fechamentos |
| Login falha / senha expirada | ERRO DE ACESSO "credencial inválida ou expirada"; **não** repete tentativas (evita bloquear a conta) |
| MFA / CAPTCHA | pausa "necessita intervenção humana"; nunca tenta contornar |
| Portal mudou (passo não encontrado) | ERRO DE ACESSO "estrutura do portal mudou", com print da tela (sem dados de login) |
| PDF mudou de estrutura | ERRO DE EXTRAÇÃO; PDF guardado; nenhum valor é "chutado" |
| PDF corrompido / incompleto | ERRO DE EXTRAÇÃO; tenta baixar de novo uma vez |
| Planilha mudou de modelo (cabeçalho/seções/fórmulas) | ERRO DE VALIDAÇÃO; nada escrito |
| Google Drive indisponível | ERRO DE ACESSO no Drive; extrações ficam prontas para a próxima execução |
| Arquivo alterado por alguém durante a execução | não envia; INCONCLUSIVO "arquivo alterado durante o processamento" |
| Linx/datalake desatualizado | conferência marcada "base de dd/mm hh:mm"; divergência de O.S. recente vira aviso, não erro |
| Queda no meio do envio | o Drive guarda a revisão anterior; confere o md5 depois do envio; se falhar, alerta e mostra a revisão para restaurar |

---

## 13. Dependências

- **Servidor:** Windows (o existente), Agendador de Tarefas, **conta Windows
  de serviço** dedicada, Python 3.11/3.12 + venv do datalake, **Java 17+**
  (Apache POI; pode ser portátil).
- **Bibliotecas:** Playwright, pypdf, Apache POI 5.x (Java), keyring (Credential
  Manager), google-api-python-client e google-auth-oauthlib (Drive), duckdb
  (conferência no lake).
- **Navegador:** Microsoft Edge (já existe no Windows Server) ou Chromium.
- **Rede:** saída HTTPS para `portalredevw.com.br`, `googleapis.com` e
  `accounts.google.com`. VPN ou certificado do portal: [DESCONHECIDO].
- **Google Cloud:** um projeto com cliente OAuth "Desktop" e a API do Drive
  habilitada. Não é conta de serviço.

---

## 14. Impacto no que já existe no repositório

- `src/datalake/rpa/planilha.py` (openpyxl, .xlsx) **não serve** para os
  fechamentos .xls. Será substituído por um editor POI na fase 2. Na fase 1,
  nenhuma escrita no Drive.
- `saga_vh47.py` hoje grava direto numa planilha configurada. Precisa passar a
  **gerar cópia de trabalho + ANTES × DEPOIS** por padrão, com os status do §9.
- `rpa_portal_vw.py` lê a senha do `.env`: migrar para o Credential Manager.
- A senha do Oracle no `C:\datalake\.env`: migrar para o Credential Manager.

Nada disso será feito antes da validação deste documento.

---

## I. O que depende do Henrique

1. **Portal Rede:**
   - informar se o login tem MFA, CAPTCHA, certificado ou restrição de IP/VPN;
   - informar quanto dura a sessão;
   - informar quantas tentativas erradas bloqueiam a conta.
2. **Portal Rede:**
   - verificar com a VW ou a regional se os **termos de uso permitem acesso
     automatizado** e se existe **API, exportação ou integração oficial** para
     o VH47;
   - verificar se existe um **perfil de usuário somente consulta** para
     Garantia/SAGA.
3. **Definir a conta** que o Auxiliar usa no portal. Uma conta pessoal
   compartilhada é o pior caso.
4. **Enviar 2 ou 3 PDFs VH47 reais** e o print da Lista de arquivos
   correspondente. Sem isso, as hipóteses SG × O.S. × VALOR CRÉDITO × fechamento
   continuam abertas.
5. **Explicar o papel de eClaims, DISS, AOR, ITP e WPL** no fechamento (as 4
   perguntas do §3.1). Dizer também quais conferências manuais são feitas
   neles hoje.
6. **Dizer se a VW avisa por e-mail** quando sai um crédito ou relatório novo, e
   para qual caixa.
7. **Dizer como se confirma que o crédito foi realmente recebido** (extrato,
   contas a receber no Linx, nota de crédito), se isso fizer parte da
   conferência.
8. **Google:**
   - aprovar a criação de uma **conta dedicada** (ex.: `auxiliar.garantia@`);
   - compartilhar a "Bagé" com ela, **Leitor** na fase 1;
   - definir quem administra o projeto do Google Cloud para o cliente OAuth.
9. **Criar ou indicar a pasta de teste** no Drive, ou autorizar que eu crie
   `TESTE AUTOMAÇÃO SAGA` dentro da "Bagé".
10. **Servidor:**
    - criar a **conta Windows de serviço** que vai rodar o Auxiliar;
    - confirmar se o servidor pode ter Java 17 (ou autorizar o Java portátil);
    - informar se o servidor tem Excel ou LibreOffice (comando do diagnóstico
      já enviado).
11. **Ambiente de desenvolvimento:** liberar `www.portalredevw.com.br` na rede
    do ambiente, se quiser que eu teste no portal real daqui. Neste caso,
    credenciais **só de leitura**, cadastradas como segredo do ambiente,
    nunca no chat.
12. **Explicar o caso do 3º Fechamento de Setembro/2026**, que repete as mesmas
    105 O.S. do 1º.
13. **Definir o canal de alertas** e **quem aprova** o ANTES × DEPOIS.
14. **Decidir sobre os nomes fora do padrão** (lista já enviada). Nada será
    renomeado sem autorização.

## J. O que o Claude Code precisa verificar antes de implementar

1. **Com PDFs reais:**
   - o layout do VH47;
   - o que é SG e a relação SG × O.S.;
   - se há várias SGs por PDF;
   - onde estão o valor e o período;
   - se existe um identificador do relatório;
   - se o texto é extraível (e não imagem).
2. **Cruzar um PDF com os fechamentos:** 1 relatório = 1 fechamento? O total do
   PDF = TOTAL GERAL do crédito?
3. **Cruzar as O.S. de um fechamento real com o Linx** (`OFI_ORDEM_SERVICO`,
   `FAT_MOVIMENTO_CAPA`) para provar ou descartar que NF, data e valores vêm
   de lá.
4. **Regra de seção** (principal, revisões, reconsideração, locações): de onde
   vem a informação.
5. **Regra da linha:** seção cheia; linha vazia no meio; bordas da primeira e
   da última linha; ordenação por O.S. (os fechamentos estão sempre em ordem
   crescente).
6. **Estrutura do Portal Rede** (quando acessível): o caminho, paginação da
   lista e mecanismo de download (link direto, postback ou visualizador).
7. **Drive:**
   - comportamento do envio de nova versão (mantém ID, nome e
     compartilhamento; histórico de revisões);
   - conferência de md5 e revisão;
   - tudo testado **só na pasta de teste**.
8. **POI em mais cenários:**
   - propriedades do arquivo (autor, datas);
   - áreas de impressão;
   - fórmula que dependa da linha preenchida;
   - arquivo de 2025 em `.xlsx` (existe um);
   - abertura do resultado no Excel real.
9. **`keyring` com Credential Manager** na conta de serviço, pela tarefa agendada
   (sem sessão interativa).
10. **Histórico de "diferença a quitar":** medir, nos fechamentos de 2025–2026,
    quanto tempo as diferenças levam para ser quitadas. Isso calibra o alerta.
11. **Frequência real dos fechamentos** (datas de criação), para calibrar o
    alerta de "fechamento atrasado" da quarta-feira.
