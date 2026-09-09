-- Custeio de veiculos com a nota fiscal de venda (serie 03).
--
-- Acrescenta ao custeio a nota que faturou o veiculo. Serve as duas consultas
-- que precisam dela: veiculos novos (transacao V21) e usados (U21). O tipo e o
-- status ficam como COLUNA -- cada relatorio filtra o seu, em vez de existir um
-- modelo por transacao.
--
-- Uma diferenca proposital: a capa da nota e ligada tambem por empresa e
-- revenda, nao so pelo numero. Numero de nota se repete entre filiais e series;
-- ligando so pelo numero, a consulta podia pegar a nota de outra loja -- e, com
-- ela, um STATUS que nao era o daquela venda.
SELECT
    c.*,
    fmv.numero_nota_fiscal,
    fmv.tipo_transacao,
    fmc.status,
    CAST(fmv.val_total  AS DOUBLE)                       AS val_total,
    CAST(fmv.val_icms   AS DOUBLE)                       AS val_icms,
    CAST(fmv.val_pis    AS DOUBLE)                       AS val_pis,
    CAST(fmv.val_cofins AS DOUBLE)                       AS val_cofins

FROM veiculos_custeio AS c
JOIN ccm__fat_movimento_veiculo AS fmv
  ON fmv.veiculo = c.veiculo
JOIN ccm__fat_movimento_capa AS fmc
  ON  fmc.numero_nota_fiscal = fmv.numero_nota_fiscal
  AND fmc.empresa            = c.empresa
  AND fmc.revenda            = c.revenda

WHERE fmv.serie_nota_fiscal = '03'
  AND fmv.tipo_transacao IN ('V21', 'U21')
  AND coalesce(fmc.status, '') <> 'C'          -- nota cancelada nunca entra
