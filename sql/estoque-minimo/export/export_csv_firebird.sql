-- =============================================================================
-- EXPORTAÇÃO DO CSV DE ENTRADA  |  Firebird
-- Mesma saída do arquivo SQL Server, na sintaxe do Firebird.
-- =============================================================================
-- Firebird não tem ISNULL nem variável DECLARE fora de bloco: usa COALESCE e
-- literal (ou parâmetro :ID_REVENDA, se a sua ferramenta suportar).
-- =============================================================================

SELECT
    TRIM(p.codigo_peca)                                  AS codigo_peca,      -- <<< ADAPTAR
    TRIM(REPLACE(REPLACE(REPLACE(
        COALESCE(p.descricao, ''), ';', ','),
        ASCII_CHAR(13), ' '), ASCII_CHAR(10), ' '))      AS descricao_peca,   -- <<< ADAPTAR
    CAST(COALESCE(e.estoque_atual , 0) AS NUMERIC(18,3)) AS estoque_atual,    -- <<< ADAPTAR
    CAST(COALESCE(e.estoque_minimo, 0) AS NUMERIC(18,3)) AS estoque_minimo    -- <<< ADAPTAR

FROM estoque e                                           -- <<< ADAPTAR
JOIN produto p ON p.id_produto = e.id_produto            -- <<< ADAPTAR

WHERE e.id_revenda = 1                                   -- <<< ADAPTAR
  AND COALESCE(e.estoque_minimo, 0) > 0
  AND COALESCE(e.estoque_atual, 0) <= COALESCE(e.estoque_minimo, 0)
  -- ^^^ COMENTE para exportar todas as peças.

ORDER BY
    CASE WHEN COALESCE(e.estoque_atual,0) <= 0 THEN 1
         WHEN COALESCE(e.estoque_atual,0) <  COALESCE(e.estoque_minimo,0) THEN 2
         ELSE 3 END,
    COALESCE(e.estoque_minimo,0) DESC,
    p.codigo_peca;
