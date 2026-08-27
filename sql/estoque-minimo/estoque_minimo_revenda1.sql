-- =============================================================================
-- Análise de Estoque Mínimo de Peças  |  Revenda 1
-- Dialeto base: Spark SQL / Databricks (compatível com Trino/Athena com ajustes
-- mínimos — ver sql/estoque-minimo/README.md para outros dialetos).
-- =============================================================================
-- >>> PONTOS DE ADAPTAÇÃO (troque pelos nomes reais do seu Data Lake) <<<
--   catálogo.schema ......... datalake.gold
--   fato .................... fato_estoque
--   dimensão ................ dim_produto
--   colunas ................. ver bloco WITH parametros / cte estoque_bruto
-- =============================================================================

WITH parametros AS (
    SELECT
        CAST(1   AS INT)           AS p_id_revenda,        -- <<< ADAPTAR: revenda alvo da análise
        CAST(1.0 AS DECIMAL(5,2))  AS p_fator_reposicao   -- lote de compra = estoque_minimo * fator
),

-- 1) Snapshot mais recente do fato -------------------------------------------
-- Fatos de estoque normalmente são snapshots diários particionados por data.
-- Sem este recorte, o mesmo item apareceria N vezes (uma por dia de carga).
ultima_carga AS (
    SELECT MAX(f.dt_referencia) AS dt_referencia   -- <<< ADAPTAR: dt_referencia / data_particao / dt_foto
    FROM datalake.gold.fato_estoque f              -- <<< ADAPTAR
    CROSS JOIN parametros p
    WHERE f.id_revenda = p.p_id_revenda            -- <<< ADAPTAR: id_revenda / cod_filial / id_loja
),

-- 2) Filtro principal: SOMENTE a Revenda 1 -----------------------------------
estoque_bruto AS (
    SELECT
        f.id_produto                                        AS id_peca,          -- <<< ADAPTAR: id_produto / sk_produto / cod_peca
        f.id_revenda                                        AS revenda,
        CAST(COALESCE(f.qtd_estoque_atual , 0) AS DECIMAL(18,3)) AS estoque_atual,  -- <<< ADAPTAR
        CAST(COALESCE(f.qtd_estoque_minimo, 0) AS DECIMAL(18,3)) AS estoque_minimo  -- <<< ADAPTAR
    FROM datalake.gold.fato_estoque f                        -- <<< ADAPTAR
    CROSS JOIN parametros p
    JOIN ultima_carga u
      ON f.dt_referencia = u.dt_referencia
    WHERE f.id_revenda = p.p_id_revenda                      -- filtro rigoroso da Revenda 1
      -- AND f.flag_ativo = 1                                -- <<< OPCIONAL: descartar itens inativos/bloqueados
),

-- 3) Consolidação por peça ----------------------------------------------------
-- Se o fato tiver granularidade abaixo de peça (depósito, prateleira, lote),
-- o SUM abaixo consolida tudo em uma linha por peça dentro da revenda.
-- Se o grão JÁ for uma linha por peça/revenda, este passo é inofensivo.
estoque_consolidado AS (
    SELECT
        id_peca,
        revenda,
        SUM(estoque_atual)  AS estoque_atual,
        MAX(estoque_minimo) AS estoque_minimo   -- mínimo é parâmetro do item, não soma
    FROM estoque_bruto
    GROUP BY id_peca, revenda
),

-- 4) Regras de negócio: déficit + classificação de risco ----------------------
classificado AS (
    SELECT
        e.id_peca,
        d.cod_peca                                   AS codigo_peca,      -- <<< ADAPTAR: código comercial/fabricante
        COALESCE(d.descricao_produto, '(SEM CADASTRO NA DIMENSÃO)')
                                                     AS descricao_peca,   -- <<< ADAPTAR
        e.revenda,
        e.estoque_atual,
        e.estoque_minimo,

        -- Necessidade de reposição: nunca negativa (item acima do mínimo => 0)
        GREATEST(e.estoque_minimo - e.estoque_atual, 0) AS quantidade_reposicao,

        -- Quanto efetivamente comprar. Peça EXATAMENTE no mínimo tem déficit 0,
        -- e um pedido de 0 peça não serve para nada: por isso o lote de compra é
        -- estoque_minimo * p_fator_reposicao, e leva-se o maior dos dois.
        GREATEST(
            GREATEST(e.estoque_minimo - e.estoque_atual, 0),
            ROUND(e.estoque_minimo * p.p_fator_reposicao, 0)
        ) AS quantidade_comprar,

        CASE
            WHEN e.estoque_atual <= 0                  THEN 'Crítico'            -- ruptura
            WHEN e.estoque_atual <  e.estoque_minimo   THEN 'Abaixo do Mínimo'
            WHEN e.estoque_atual =  e.estoque_minimo   THEN 'No Mínimo'          -- ponto de pedido
            ELSE                                            'Ok'
        END AS status_estoque,

        -- Chave de ordenação: ruptura > abaixo do mínimo > no mínimo > Ok
        CASE
            WHEN e.estoque_atual <= 0                  THEN 1
            WHEN e.estoque_atual <  e.estoque_minimo   THEN 2
            WHEN e.estoque_atual =  e.estoque_minimo   THEN 3
            ELSE                                            4
        END AS ordem_prioridade

    FROM estoque_consolidado e
    CROSS JOIN parametros p
    LEFT JOIN datalake.gold.dim_produto d            -- <<< ADAPTAR (LEFT para não perder peça sem cadastro)
           ON d.id_produto = e.id_peca               -- <<< ADAPTAR
          -- AND d.flag_registro_atual = 1           -- <<< OPCIONAL: se a dim for SCD tipo 2
)

SELECT
    id_peca,
    codigo_peca,
    descricao_peca,
    revenda,
    estoque_atual,
    estoque_minimo,
    quantidade_reposicao,   -- déficit puro (mínimo - atual); 0 para peça no mínimo
    quantidade_comprar,     -- o que entra no pedido de compra
    status_estoque
FROM classificado
WHERE estoque_minimo > 0        -- ignora peças sem política de mínimo (evita falso "Crítico")
  AND status_estoque <> 'Ok'    -- <<< COMENTE esta linha para trazer também os itens 'Ok'
ORDER BY
    ordem_prioridade      ASC,  -- 1) Crítico 2) Abaixo do Mínimo 3) No Mínimo 4) Ok
    quantidade_comprar    DESC, -- 2) maior pedido primeiro
    estoque_minimo        DESC, -- 3) desempate por peça de maior giro
    codigo_peca           ASC;  -- 4) desempate estável
