# Relatórios de exemplo (fora do ar de propósito)

Estes arquivos **não aparecem** na página: o `datalake report` só lê os `.yml`
que estão na pasta acima (`conf/reports/`), sem entrar em subpastas.

Eles ficam aqui como referência de escrita — resumo por período, detalhe linha
a linha, filtro opcional, destaque condicional, pivô de série. Para colocar
qualquer um no ar, mova o arquivo uma pasta acima:

```
git mv conf/reports/exemplos/20_oficina_producao.yml conf/reports/
```

| Arquivo | O que demonstra |
|---|---|
| `10_pecas_margem.yml` | Resumo por período com percentuais recalculados sobre a soma |
| `11_pecas_margem_mensal.yml` | Mesma base, agrupada por mês |
| `20_oficina_producao.yml` | Contagem e média, com destaque em uma coluna só |
| `21_oficina_os.yml` | Detalhe linha a linha, com destaque na linha |
| `30_pecas_estoque_data.yml` | Consulta ao histórico diário (`historico_estoque`) |
| `31_pecas_estoque_agora.yml` | Foto do momento, sem campo de data |
| `41_funilaria_notas.yml` | Detalhe que sustenta o total do faturamento |
| `90_vendas_demo.yml` | Roda na base fictícia do `make demo` |
