-- Agregado pronto para dashboard: usa o modelo gold construido antes
-- (arquivos sao executados em ordem alfabetica, por isso o prefixo numerico).
SELECT
    competencia,
    uf,
    count(DISTINCT id_pedido)        AS qtd_pedidos,
    count(*)                         AS qtd_itens,
    round(sum(vlr_item), 2)          AS vlr_vendido,
    round(avg(vlr_item), 2)          AS ticket_medio_item
FROM fato_vendas
GROUP BY competencia, uf
ORDER BY competencia DESC, vlr_vendido DESC
