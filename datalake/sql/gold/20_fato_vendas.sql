-- Fato de vendas em grao de item de pedido, ja com os atributos do cliente
-- que o Power BI costuma filtrar. Pedidos cancelados ficam de fora.
SELECT
    i.id_pedido,
    i.nr_item,
    p.dt_pedido,
    date_trunc('month', p.dt_pedido)                    AS competencia,
    p.id_cliente,
    c.nome                                              AS cliente,
    c.uf,
    i.id_produto,
    p.situacao,
    i.quantidade,
    i.vlr_unitario,
    round(i.quantidade * i.vlr_unitario, 2)             AS vlr_item,
    p.vlr_total                                         AS vlr_pedido
FROM itens_pedido AS i
JOIN pedidos      AS p ON p.id_pedido = i.id_pedido
LEFT JOIN clientes AS c ON c.id_cliente = p.id_cliente
WHERE p.situacao <> 'C'
