# RPA do Portal Rede VW

Robô (Python + Playwright, dirigindo o Microsoft Edge) que abre
<https://www.portalredevw.com.br/>, faz login e entra num usuário específico.

## Arquivos

| No repositório | No servidor | Papel |
|---|---|---|
| `scripts/rpa_portal_vw.py` | `C:\datalake\rpa_portal_vw.py` | o robô |
| `conf/rpa/portal_vw.yml` | `C:\datalake\rpa_portal_vw.yml` | o que clicar (seletores) |
| `scripts/RPA-PORTAL-VW.bat` | `C:\datalake\RPA-PORTAL-VW.bat` | roda (duplo-clique) |
| `scripts/GRAVAR-PORTAL-VW.bat` | `C:\datalake\GRAVAR-PORTAL-VW.bat` | grava cliques para descobrir seletores |

O `instalar_app.ps1` copia tudo para `C:\datalake`. O `.yml` só é copiado
**na primeira vez**: depois ele é do operador, e as atualizações não o apagam.

## Credenciais

Vão em `C:\datalake\.env` (nunca no git nem no YAML):

```
RPA_PORTALVW_USUARIO=seu.login
RPA_PORTALVW_SENHA=sua-senha
RPA_PORTALVW_ALVO=Nome do usuário a escolher, como aparece na tela
```

`--alvo "OUTRO"` troca o usuário só naquela execução.

## Primeira configuração

1. Preencha o `.env` como acima.
2. Duplo-clique em `GRAVAR-PORTAL-VW.bat`. Abrem o Edge e a janela do
   Playwright. Faça o login e escolha o usuário: a janela mostra o código de
   cada clique, por exemplo `page.get_by_role("button", name="Entrar")`.
3. Passe esses seletores para o `C:\datalake\rpa_portal_vw.yml`:
   `get_by_role("button", name="Entrar")` vira `role=button[name="Entrar"]`,
   `get_by_text("Fulano")` vira `text=Fulano`, `locator("#id")` vira `#id`.
   O nome do usuário escolhido vira `{alvo}`, por exemplo `text={alvo}`.
4. Rode `RPA-PORTAL-VW.bat --visivel` e acompanhe. Sem `--visivel`, o robô roda
   sem janela, que é o modo para agendar.

O YAML já vem com seletores genéricos para o login (campo de e-mail/usuário,
`input[type=password]`, botão submit/"Entrar"/"Acessar"). Eles funcionam em
muitos portais, mas confirme no passo 2.

## Como ele trabalha

1. Abre a URL e espera carregar.
2. Preenche o usuário. Se a senha ainda não estiver na tela (login em duas
   etapas: usuário, "Avançar", senha), clica em avançar antes.
3. Preenche a senha e clica em entrar. Se o campo de senha continuar na tela, o
   login foi recusado: senha errada, captcha ou código de verificação.
4. `usuario_alvo`: abre a lista (opcional), digita na busca (opcional) e clica
   no usuário.
5. `confirmacao` (opcional): confere que está dentro do usuário certo.
6. Salva um print em `C:\datalake\logs\rpa\portal_vw_<data>_ok.png`. Se der erro,
   salva `_erro.png` e `_erro.html` com a tela onde parou.

Código de saída: `0` = entrou; `1` = falhou (o motivo aparece na tela).

## Problemas comuns

- **"nao achei na tela o seletor ..."**: a tela mudou ou o seletor não serve.
  Veja o `_erro.png` e regrave com `GRAVAR-PORTAL-VW.bat`.
- **"O login nao passou"**: confira o `.env`. Se o portal pede captcha ou
  código por SMS/e-mail, o robô não passa sozinho.
- **"nao consegui abrir o navegador"**: sem Edge na máquina. Instale o Edge ou
  rode `python -m playwright install chromium` e troque `navegador: chromium`.
- `--pausar` para no fim com o inspetor do Playwright aberto, útil para depurar.

## Pendências

- Definir o que o robô faz depois de entrar no usuário (baixar relatório,
  ler dados, etc.).
- Agendamento (Tarefa Agendada), se for rodar sozinho.
