# RPA BRAVOS: Notas Fiscais por SG

Consulta, no BRAVOS, as NFs e os valores de uma ou mais SGs. **Só leitura.**

Caminho: login → Relatórios → Relatórios → Faturamento → Relatório de Notas
Fiscais → Período de seleção: **duplo clique na data final** e atualiza →
**Gerar** (raio) → aguarda → **Nro O.S** = SG → pesquisa → NFs + valores.

## Instalar (uma vez)

1. Dê dois cliques em `INSTALAR.bat`.
2. No Bloco de Notas que abrir, preencha `BRAVOS_URL` (o endereço do BRAVOS) e
   `BRAVOS_USUARIO`. Salve e feche.
3. Digite a senha quando `CADASTRAR-SENHA.bat` pedir. Ela não aparece na tela
   e fica guardada no **Gerenciador de Credenciais do Windows**.

A senha nunca fica em arquivo, código, log, print ou git. Para trocá-la, rode
`CADASTRAR-SENHA.bat` de novo.

## Consultar

```
CONSULTAR.bat 210238
CONSULTAR.bat 210238 214074 214397
```

A data final padrão é hoje. Para usar outra: `CONSULTAR.bat 210238 --data-final 25/09/2026`.

## Resultado

- **Na tela:** `SG 210238: NF 208.040 valor R$ 1.234,56`. Se houver várias
  NFs, todas aparecem, com o valor exatamente como o BRAVOS mostra.
- **`saida/consulta_*.csv`:** o resultado desta consulta.
- **`saida/historico.jsonl`:** o histórico de todas as consultas.
- **SG sem NF:** "Nenhuma Nota Fiscal encontrada para a SG pesquisada no
  período selecionado".
- **Senha errada:** mostra a mensagem do BRAVOS e **não tenta de novo**.
- **Sessão expirada:** faz login outra vez e continua da mesma SG.

A tela de login **nunca** é fotografada.
