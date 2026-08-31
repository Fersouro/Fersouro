-- =============================================================================
-- EXPORTAÇÃO DO CSV DE ENTRADA  |  Oracle
-- Gera exatamente as 4 colunas que o gerador da planilha consome:
--     codigo_peca;descricao_peca;estoque_atual;estoque_minimo
-- =============================================================================
-- >>> TROQUE APENAS AS LINHAS MARCADAS COM "ADAPTAR" <<<
-- =============================================================================

SELECT
    TRIM(p.codigo_peca)                                   AS codigo_peca,     -- <<< ADAPTAR

    -- ';' e quebras de linha viram vírgula/espaço. Um ';' dentro da descrição
    -- desalinharia todas as colunas seguintes do CSV.
    TRIM(REPLACE(REPLACE(REPLACE(
        NVL(p.descricao, ' '), ';', ','), CHR(13), ' '), CHR(10), ' '))
                                                          AS descricao_peca,  -- <<< ADAPTAR

    -- NVL é obrigatório: em SQL, NULL <= 5 não é verdadeiro nem falso, e a peça
    -- sumiria silenciosamente do resultado.
    CAST(NVL(e.estoque_atual , 0) AS NUMBER(18,3))        AS estoque_atual,   -- <<< ADAPTAR
    CAST(NVL(e.estoque_minimo, 0) AS NUMBER(18,3))        AS estoque_minimo   -- <<< ADAPTAR

FROM estoque  e                                            -- <<< ADAPTAR: tabela/view de saldo
JOIN produto  p                                            -- <<< ADAPTAR: cadastro de peças
     ON p.id_produto = e.id_produto                        -- <<< ADAPTAR: chave do join

WHERE e.id_revenda = 1                                     -- <<< ADAPTAR: id_revenda / cod_filial / id_loja
  AND NVL(e.estoque_minimo, 0) > 0                         -- só peças com política de mínimo
  AND NVL(e.estoque_atual , 0) <= NVL(e.estoque_minimo, 0)
  -- ^^^ COMENTE esta linha para exportar TODAS as peças (inclusive as 'Ok').
  --     Necessário se o destino for painel de "% de itens em ruptura".

ORDER BY
    CASE WHEN NVL(e.estoque_atual,0) <= 0                        THEN 1
         WHEN NVL(e.estoque_atual,0) <  NVL(e.estoque_minimo,0)  THEN 2
         WHEN NVL(e.estoque_atual,0) =  NVL(e.estoque_minimo,0)  THEN 3
         ELSE 4 END,
    NVL(e.estoque_minimo,0) DESC,
    p.codigo_peca;
