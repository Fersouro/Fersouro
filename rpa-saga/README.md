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
- `RODAR.bat --baixar` lê a lista e baixa os PDFs novos do DN.

## Resultado (pasta `saida/`)

- `lista_*.csv`: a tabela lida.
- `*_lista.png`: o print da tela.
- `pdfs/`: os PDFs baixados.
- `rpa.log`: o que o RPA fez. A senha nunca aparece aqui.

O `.env` (com a senha) e a pasta `saida/` não vão para o git.
