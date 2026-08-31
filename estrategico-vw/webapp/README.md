# Consolidador Estratégico VW — aplicação web

Página para subir o extrato do DataLake e baixar a planilha consolidada já
cruzada, sem precisar mexer em script nenhum. Roda na sua máquina/servidor e
é acessada pelo IP na rede interna.

## Como subir

### Windows (PowerShell ou Prompt de Comando)

Baixe o projeto uma vez:

```powershell
cd $HOME
git clone https://github.com/Fersouro/Fersouro.git
cd Fersouro
git checkout claude/estrategico-vw-consolidada-o8u9k5
cd estrategico-vw\webapp
```

Sem `git` instalado, baixe e extraia com um comando só:

```powershell
cd $HOME
$url = "https://github.com/Fersouro/Fersouro/archive/refs/heads/claude/estrategico-vw-consolidada-o8u9k5.zip"
Invoke-WebRequest $url -OutFile projeto.zip
Expand-Archive projeto.zip -DestinationPath . -Force
cd Fersouro-claude-estrategico-vw-consolidada-o8u9k5\estrategico-vw\webapp
```

Também funciona copiar `app.py`, `consolidar.py`, `index.html` e a planilha
Estratégico soltos numa pasta única — o servidor procura a planilha ao lado
do `app.py` e na pasta acima.

Depois, sempre que quiser subir:

```powershell
.\iniciar.bat          # porta 8000
.\iniciar.bat 8080     # outra porta
```

Ou, sem usar o atalho:

```powershell
pip install openpyxl
python app.py --porta 8000
```

Observações do Windows:

- Precisa de **Python 3.9+** com a opção *Add python.exe to PATH* marcada na
  instalação. Confira com `python --version`.
- Na primeira execução o **Firewall do Windows** vai perguntar se libera o
  Python — marque **redes privadas** e permita, senão os outros computadores
  não enxergam a página.
- `.\iniciar.bat` (com `.\` na frente) é o jeito certo de chamar no
  PowerShell. `.sh` é script de Linux e não roda aqui.

### Linux e macOS

```bash
cd estrategico-vw/webapp
./iniciar.sh          # porta 8000
./iniciar.sh 8080     # outra porta
```

O terminal mostra os dois endereços:

```
  local ...... http://127.0.0.1:8000
  na rede .... http://192.168.0.15:8000
```

Qualquer pessoa na mesma rede abre o segundo endereço no navegador. Só é
preciso Python 3.9+ e `openpyxl` (o `iniciar.sh` instala se faltar).

Para rodar em segundo plano (Linux/macOS):

```bash
nohup python3 app.py --porta 8000 > consolidador.log 2>&1 &
```

No Windows, deixe a janela do `iniciar.bat` aberta e minimizada — fechá-la
derruba o servidor.

## Como usar

1. **Arquivos** — arraste o extrato do DataLake (CSV, TSV ou XLSX). A planilha
   Estratégico é opcional: sem ela, usa-se a que está no servidor
   (`../Estrategico_PAC_VII_5.xlsx`). Ajuste o acréscimo se não for 40%.
2. **Conferência das colunas** — o sistema detecta pelo cabeçalho qual coluna é
   o código, o estoque e o preço público. Se errar (ou se o cabeçalho não tiver
   pista alguma), escolha na mão e clique em *Reprocessar*.
3. **Resultado** — confira os números do cruzamento e baixe em XLSX ou CSV.

## Cruzamento pelo código

A busca é feita em duas passadas:

| Selo | Significado |
|---|---|
| `Exato` | o código bateu letra por letra |
| `Normalizado` | bateu ignorando traços, espaços, acentos e maiúsculas (`04E115105BM` = `04E-115-105-BM`) |
| `Sem valor` | o código está no extrato, mas sem estoque nem preço |
| `Não encontrado` | o código não está no extrato (linha destacada em amarelo) |

Preços são lidos em formato pt-BR ou en-US: `R$ 1.234,56`, `1,234.56` e
`1234.56` são todos entendidos corretamente.

## Planilha gerada

Aba **Consolidado**, com exatamente as cinco colunas do pedido:

`Código da Peça` · `Estoque (DataLake)` · `Preço Público (DataLake)` ·
`Preço Original (Coluna H)` · `Preço Estratégico (+40%)`

Aba **Parâmetros**, com o acréscimo em célula própria (`B3`) e as estatísticas
do cruzamento. A coluna E é fórmula (`=D2*(1+Parâmetros!$B$3)`), então mudar
`B3` no Excel recalcula tudo.

## Arquivos

| Arquivo | Papel |
|---|---|
| `app.py` | servidor HTTP (só biblioteca padrão) e rotas da API |
| `consolidar.py` | leitura das planilhas, cruzamento e geração da saída |
| `index.html` | interface (sem CDN — funciona sem internet) |
| `iniciar.bat` | atalho de inicialização no Windows |
| `iniciar.sh` | atalho de inicialização no Linux/macOS |

## API

| Rota | O que faz |
|---|---|
| `GET /` | a página |
| `GET /api/status` | estado do servidor e planilha padrão |
| `POST /api/processar` | multipart: `extrato`, `pedido` (opcional), `acrescimo` |
| `POST /api/remapear` | JSON: `id`, `codigo`, `estoque`, `publico`, `acrescimo` |
| `GET /api/baixar/<id>.xlsx\|.csv` | baixa o resultado |

## Limites e segurança

- **Não há autenticação.** Use apenas na rede interna; não exponha à internet
  nem redirecione porta no roteador.
- Envio máximo de 40 MB por requisição.
- Os resultados ficam em memória por 6 horas (máx. 30); depois disso, é só
  reenviar o extrato. Nada é gravado em disco pelo servidor.
