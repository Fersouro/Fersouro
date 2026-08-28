-- =============================================================================
-- EXPORTAÇÃO DO CSV DE ENTRADA  |  SQL Server
-- Objetivo: gerar exatamente as 4 colunas que o gerador da planilha espera:
--           codigo_peca;descricao_peca;estoque_atual;estoque_minimo
-- =============================================================================
-- >>> TROQUE APENAS AS 3 LINHAS MARCADAS COM "ADAPTAR" <<<
-- =============================================================================

DECLARE @id_revenda INT = 1;   -- revenda alvo

SELECT
    LTRIM(RTRIM(p.codigo_peca))                         AS codigo_peca,      -- <<< ADAPTAR
    LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(
        ISNULL(p.descricao, ''), ';', ','), CHAR(13), ' '), CHAR(10), ' ')))
                                                        AS descricao_peca,   -- <<< ADAPTAR
    -- ; e quebras de linha viram vírgula/espaço: um ';' na descrição
    -- desalinharia todas as colunas do CSV.
    CAST(ISNULL(e.estoque_atual , 0) AS DECIMAL(18,3))  AS estoque_atual,    -- <<< ADAPTAR
    CAST(ISNULL(e.estoque_minimo, 0) AS DECIMAL(18,3))  AS estoque_minimo    -- <<< ADAPTAR

FROM dbo.estoque  AS e                                   -- <<< ADAPTAR: tabela de saldo
JOIN dbo.produto  AS p                                   -- <<< ADAPTAR: cadastro de peças
     ON p.id_produto = e.id_produto                      -- <<< ADAPTAR: chave do join

WHERE e.id_revenda = @id_revenda                         -- <<< ADAPTAR: id_revenda / cod_filial / id_loja
  AND ISNULL(e.estoque_minimo, 0) > 0                    -- só peças com política de mínimo
  AND ISNULL(e.estoque_atual, 0) <= ISNULL(e.estoque_minimo, 0)
  -- ^^^ COMENTE esta linha para exportar TODAS as peças (inclusive as 'Ok').
  --     Útil para Power BI, onde o cartão de "% em ruptura" precisa do total.

ORDER BY
    CASE WHEN ISNULL(e.estoque_atual,0) <= 0 THEN 1
         WHEN ISNULL(e.estoque_atual,0) <  ISNULL(e.estoque_minimo,0) THEN 2
         ELSE 3 END,
    ISNULL(e.estoque_minimo,0) DESC,
    p.codigo_peca;
