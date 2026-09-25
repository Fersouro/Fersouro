# RPA SAGA2 - VH47 (independente)

Entra no Portal Rede VW, abre Garantia Volkswagen → SAGA → SAGA2 - VH47 →
Lista de arquivos, e lê a lista. **Só leitura**: não envia nem altera nada no
portal.

## Instalar (uma vez)

1. Dê dois cliques em `INSTALAR.bat`.
2. No Bloco de Notas que abrir, preencha `PORTAL_USUARIO` e `PORTAL_SENHA`.
   Salve e feche.

## Rodar

- `RODAR.bat` lê a lista.
- `RODAR.bat --baixar` baixa o relatório **mais recente** do DN (pela data do relatório, no nome do arquivo) e cruza com a planilha.
- `RODAR.bat --baixar-todos` baixa os que faltam, do mais antigo ao mais novo (relatórios atrasados).

## Resultado (pasta `saida/`)

- `lista_*.csv`: a tabela lida.
- `*_lista.png`: o print da tela.
- `pdfs/`: os PDFs baixados.
- `rpa.log`: o que o RPA fez. A senha nunca aparece aqui.

O `.env` (com a senha) e a pasta `saida/` não vão para o git.

## Cruzar o PDF com a planilha de fechamento

1. Baixe do Drive o `.xls` do fechamento (ex.: `4º FECHAMENTO DE SETEMBRO 2026.xls`)
   e coloque na pasta `planilhas`.
2. Rode `CRUZAR.bat`. Ele também roda sozinho no fim de `RODAR.bat --baixar`.

Para cada SG do PDF, o cruzamento mostra:

- **OK**: a SG está na planilha com o mesmo crédito.
- **VALOR DIFERENTE**: está na planilha, com outro crédito.
- **FALTA**: não está na planilha.
- **SO NA PLANILHA**: está na planilha e não está no PDF.

Versões da mesma O.S. são somadas. No fim aparece o **crédito total** do
relatório, e o detalhe fica em `saida/cruzamento_*.csv`.

O cruzamento **não altera** nenhuma planilha.

## Portal Rede × Drive (quantidade real de fechamentos)

`COMPARAR-MES.bat`, que também roda sozinho no `RODAR.bat`, mostra:

- quantos fechamentos o **Portal Rede** tem no mês;
- quantos já existem no **Drive** (os `.xls` da pasta `planilhas`);
- quais são **novos** e o que **necessita conferência**.

Não existe número fixo por mês: quem manda é o Portal Rede. Nenhuma pasta ou
planilha é criada por este passo.
