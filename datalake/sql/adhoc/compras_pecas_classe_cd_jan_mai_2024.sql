-- Consulta ad hoc para rodar DIRETO no Oracle (Linx), fora do pipeline do
-- datalake. Nao segue a convencao de sql/gold (que roda em DuckDB sobre as
-- tabelas ja replicadas com prefixo ccm__/erp__) -- usa sintaxe Oracle
-- (TO_CHAR, TO_DATE, CONCAT) e as tabelas do ERP com os nomes originais.
--
-- Objetivo: compras (tipo_transacao = 'P01') de pecas classe ABC C/D, com
-- saldo em estoque > 0, no periodo 01/01/2024 a 18/05/2024, por revenda.
--
-- Executar em SQL Developer/Toad ou via cliente Oracle com acesso a rede
-- interna (192.168.0.10:1521) e usuario datalake_ro -- este ambiente remoto
-- nao alcanca essa rede.
SELECT
    TO_CHAR(CONCAT(CONCAT(PIR.EMPRESA, '.'), PIR.REVENDA)) AS codigo_empresa,
    RV.NOME_FANTASIA AS filial,
    RV.CNPJ AS cnpj,
    fat_movimento_capa.numero_nota_fiscal,
    fat_movimento_capa.DTA_ENTRADA_SAIDA AS DATA_COMPRA,
    PIE.item_estoque_pub,
    PIE.des_item_estoque,
    PIR.class_abc,
    FATITEM.Quantidade AS QUANTIDADE_PEDIDO,
    PIR.QTD_CONTABIL AS QUANT_ESTOQUE_CONT,
    fatitem.val_total_real_item,
    TO_CHAR(PIR.dta_saida, 'dd/mm/yyyy') AS ULTIMA_VENDA
FROM
    fat_movimento_capa
INNER JOIN
    fat_tipo_transacao FTT ON FTT.tipo_transacao = fat_movimento_capa.tipo_transacao
INNER JOIN
    fat_movimento_item FATITEM ON FATITEM.EMPRESA = fat_movimento_capa.EMPRESA
                               AND FATITEM.REVENDA = fat_movimento_capa.REVENDA
                               AND FATITEM.numero_nota_fiscal = fat_movimento_capa.numero_nota_fiscal
                               AND FATITEM.serie_nota_fiscal = fat_movimento_capa.serie_nota_fiscal
INNER JOIN
    pec_item_estoque PIE ON PIE.item_estoque = FATITEM.item_estoque
INNER JOIN
    pec_item_revenda PIR ON PIR.empresa = PIE.empresa
                         AND PIR.Revenda = FATITEM.Revenda
                         AND PIR.item_estoque = PIE.item_estoque
                         AND PIR.item_estoque = FATITEM.item_estoque
INNER JOIN
    GER_REVENDA RV ON RV.empresa = fat_movimento_capa.empresa
                    AND RV.revenda = fat_movimento_capa.revenda
WHERE
    fat_movimento_capa.tipo_transacao = 'P01'
    AND fat_movimento_capa.dta_entrada_saida BETWEEN TO_DATE('01/01/2024', 'DD/MM/YYYY') AND TO_DATE('18/05/2024', 'DD/MM/YYYY')
    AND FTT.tipo = 'E'
    AND PIR.class_abc IN ( 'C', 'D' )
    AND PIR.qtd_contabil > 0
ORDER BY
    RV.NOME_FANTASIA;
