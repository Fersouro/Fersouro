-- Estoque de pecas por revenda: o "Disponivel" da consulta gerencial.
--
-- Junta o saldo por loja (PEC_ITEM_REVENDA) com o cadastro da peca
-- (PEC_ITEM_ESTOQUE), que traz o codigo publico e a descricao. A chave e o
-- ITEM_ESTOQUE, o id interno; o codigo que o balconista conhece (05E145933) e
-- o item_estoque_pub do cadastro.
--
-- O "disponivel" e a QTD_CONTABIL: foi a coluna que reproduziu exatamente o
-- numero da tela do ERP (53 para a 05E145933 na revenda 1). As demais
-- quantidades (reserva, pedida) ficam a mao para quem quiser refinar depois.
SELECT
    rev.revenda,
    rev.item_estoque,
    pie.item_estoque_pub                    AS codigo,
    trim(pie.des_item_estoque)              AS descricao,
    pie.marca,
    CAST(rev.qtd_contabil AS DOUBLE)        AS disponivel,
    CAST(rev.qtd_reserva  AS DOUBLE)        AS reservado,
    CAST(rev.qtd_pedida   AS DOUBLE)        AS pedido,
    CAST(pie.preco_publico_atual AS DOUBLE) AS preco,

    -- Codigo normalizado (maiusculo, so alfanumerico) para casar com a lista
    -- de minimos sem tropecar em traco, espaco ou ponto.
    regexp_replace(upper(CAST(pie.item_estoque_pub AS VARCHAR)), '[^0-9A-Z]', '', 'g') AS codigo_norm

FROM ccm__pec_item_revenda AS rev
JOIN ccm__pec_item_estoque AS pie
  ON pie.item_estoque = rev.item_estoque
