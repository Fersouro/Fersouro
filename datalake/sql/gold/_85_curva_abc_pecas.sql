-- =============================================================================
-- RASCUNHO -- NAO ENTRA NA CARGA ENQUANTO O NOME COMECAR COM "_"
--
-- gold.list_models() ignora arquivos iniciados por "_". Este modelo fica de
-- fora das cargas 6x/dia ate que a coluna de quantidade seja confirmada.
--
-- PARA ATIVAR: confirme o nome real da coluna de quantidade da
-- FAT_MOVIMENTO_ITEM (marcada abaixo como QUANTIDADE_ITEM), corrija, e renomeie
-- o arquivo para 85_curva_abc_pecas.sql.
--
--     datalake query "DESCRIBE ccm__fat_movimento_item"
-- =============================================================================
-- Curva ABC e demanda media de pecas, por revenda.
--
-- Responde: quais pecas merecem controle apertado (A), quais merecem controle
-- medio (B), e qual estoque minimo cada uma precisa para atender a demanda.
--
-- Tres decisoes de negocio, todas parametrizadas no bloco 'parametros':
--
--   1. Janela de 12 meses. Menos que isso e sazonalidade vira tendencia; mais
--      que isso e peca que saiu de linha continua puxando estoque.
--   2. Curva por VALOR e por QUANTIDADE, lado a lado. Sao respostas
--      diferentes: por valor, peca cara de giro baixo e A (capital parado);
--      por quantidade, filtro barato de giro alto e A (espaco de prateleira).
--      Quem compra olha valor; quem organiza o deposito olha quantidade.
--   3. Minimo sugerido = demanda media mensal x cobertura, ARREDONDADO PARA
--      CIMA. Nao existe meia peca, e arredondar para baixo transforma
--      "preciso de 1,2 por mes" em minimo 1 -- ruptura garantida.
--
-- ATENCAO ao efeito do arredondamento para cima: qualquer peca com demanda
-- maior que zero recebe minimo >= 1. Uma peca que vendeu 1 unidade em 12 meses
-- tem demanda media 0,08 e ganha minimo 1. Por isso o relatorio operacional
-- filtra curva A e B -- a cauda longa de giro esporadico fica fora.
WITH parametros AS (
    SELECT
        12    AS meses_janela,      -- periodo de apuracao da demanda
        1.0   AS meses_cobertura,   -- quantos meses de demanda o minimo cobre
        0.80  AS corte_a,           -- ate 80% acumulado = curva A
        0.95  AS corte_b            -- de 80% a 95% = curva B; acima = C
),

-- Movimento de pecas. Mesmas regras do 60_margem_pecas: nota faturada, fora
-- P50, fora item de industrializacao. A diferenca e que aqui interessa a
-- QUANTIDADE, nao a margem.
base AS (
    SELECT
        fmc.empresa,
        fmc.revenda,
        fmi.item_estoque,
        date_trunc('month', fmc.dta_entrada_saida)          AS competencia,
        tt.tipo,
        tt.subtipo_transacao,
        CAST(fmi.QUANTIDADE_ITEM AS DOUBLE)                 AS qtd,
        --   ^^^^^^^^^^^^^^^^ COLUNA A CONFIRMAR no schema real (ver docs)
        CAST(fmi.val_total_real_item AS DOUBLE)
          - coalesce(CAST(fmi.val_desconto AS DOUBLE), 0)   AS valor
    FROM ccm__fat_movimento_item AS fmi
    JOIN ccm__fat_movimento_capa AS fmc
      ON  fmc.empresa            = fmi.empresa
      AND fmc.revenda            = fmi.revenda
      AND fmc.numero_nota_fiscal = fmi.numero_nota_fiscal
      AND fmc.serie_nota_fiscal  = fmi.serie_nota_fiscal
      AND fmc.tipo_transacao     = fmi.tipo_transacao
      AND fmc.contador           = fmi.contador
    JOIN ccm__fat_tipo_transacao AS tt
      ON  tt.tipo_transacao = fmc.tipo_transacao
    JOIN ccm__pec_item_estoque AS pie
      ON  pie.empresa      = fmi.empresa
      AND pie.item_estoque = fmi.item_estoque
    CROSS JOIN parametros AS p
    WHERE fmc.status = 'F'
      AND fmc.tipo_transacao <> 'P50'
      AND pie.tipo_industrializacao IS NULL
      -- Janela movel, apenas MESES FECHADOS: incluir o mes corrente pela
      -- metade puxaria a media para baixo todo comeco de mes.
      AND fmc.dta_entrada_saida >= date_trunc('month', current_date)
                                   - to_months(CAST(p.meses_janela AS INTEGER))
      AND fmc.dta_entrada_saida <  date_trunc('month', current_date)
),

-- Demanda liquida: venda menos devolucao. Peca vendida e devolvida no mesmo
-- mes nao gerou demanda nenhuma, e contar so a venda inflaria o minimo.
demanda AS (
    SELECT
        empresa,
        revenda,
        item_estoque,
        sum(CASE WHEN tipo = 'S' AND subtipo_transacao = 'N' THEN qtd   ELSE 0 END)
          - sum(CASE WHEN tipo = 'E' AND subtipo_transacao = 'D' THEN qtd   ELSE 0 END)
                                                                AS qtd_liquida,
        sum(CASE WHEN tipo = 'S' AND subtipo_transacao = 'N' THEN valor ELSE 0 END)
          - sum(CASE WHEN tipo = 'E' AND subtipo_transacao = 'D' THEN valor ELSE 0 END)
                                                                AS valor_liquido,
        count(DISTINCT CASE WHEN tipo = 'S' AND subtipo_transacao = 'N'
                            THEN competencia END)               AS meses_com_venda
    FROM base
    GROUP BY empresa, revenda, item_estoque
),

-- So entra na curva quem teve saida liquida positiva. Peca com devolucao maior
-- que venda ficaria com valor negativo e baguncaria o acumulado de Pareto.
elegivel AS (
    SELECT d.*
    FROM demanda AS d
    WHERE d.qtd_liquida > 0 AND d.valor_liquido > 0
),

-- Pareto: acumulado dentro de cada revenda, uma vez por valor e outra por
-- quantidade. A revenda e a unidade de decisao de compra -- classificar o
-- grupo inteiro junto esconderia a peca que e A numa loja e C na outra.
acumulado AS (
    SELECT
        e.*,
        sum(e.valor_liquido) OVER (
            PARTITION BY e.revenda ORDER BY e.valor_liquido DESC, e.item_estoque
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) / nullif(sum(e.valor_liquido) OVER (PARTITION BY e.revenda), 0)
                                                                AS acum_valor,
        sum(e.qtd_liquida) OVER (
            PARTITION BY e.revenda ORDER BY e.qtd_liquida DESC, e.item_estoque
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) / nullif(sum(e.qtd_liquida) OVER (PARTITION BY e.revenda), 0)
                                                                AS acum_qtd
    FROM elegivel AS e
)

SELECT
    a.revenda,
    a.item_estoque,
    pie.item_estoque_pub                                        AS codigo,
    trim(pie.des_item_estoque)                                  AS descricao,
    pie.marca,

    -- Demanda
    round(a.qtd_liquida, 2)                                     AS qtd_12m,
    a.meses_com_venda,
    round(a.qtd_liquida / p.meses_janela, 4)                    AS demanda_media_mensal,
    round(a.valor_liquido, 2)                                   AS valor_12m,

    -- Curva por valor (quem compra olha esta) e por quantidade
    CASE WHEN a.acum_valor <= p.corte_a THEN 'A'
         WHEN a.acum_valor <= p.corte_b THEN 'B'
         ELSE 'C' END                                           AS curva_valor,
    CASE WHEN a.acum_qtd   <= p.corte_a THEN 'A'
         WHEN a.acum_qtd   <= p.corte_b THEN 'B'
         ELSE 'C' END                                           AS curva_qtd,
    round(a.acum_valor * 100, 2)                                AS acum_valor_pct,
    round(a.acum_qtd   * 100, 2)                                AS acum_qtd_pct,

    -- Minimo sugerido: demanda media x cobertura, SEMPRE PARA CIMA
    CAST(ceil(a.qtd_liquida / p.meses_janela * p.meses_cobertura) AS BIGINT)
                                                                AS minimo_sugerido,

    -- Situacao atual, para comparar com o sugerido
    CAST(coalesce(est.disponivel, 0) AS DOUBLE)                 AS disponivel,
    CAST(coalesce(est.disponivel, 0)
         - ceil(a.qtd_liquida / p.meses_janela * p.meses_cobertura) AS DOUBLE)
                                                                AS folga,
    -- Meses de estoque que o disponivel de hoje aguenta na demanda atual.
    -- NULL quando nao ha demanda (divisao protegida).
    round(coalesce(est.disponivel, 0)
          / nullif(a.qtd_liquida / p.meses_janela, 0), 1)       AS cobertura_meses,

    CASE WHEN coalesce(est.disponivel, 0) <= 0 THEN 'RUPTURA'
         WHEN coalesce(est.disponivel, 0)
              < ceil(a.qtd_liquida / p.meses_janela * p.meses_cobertura)
                                                  THEN 'ABAIXO DO SUGERIDO'
         ELSE 'OK' END                                          AS situacao,

    -- Codigo normalizado, mesma regra do 80_estoque_pecas, para casar com a
    -- lista de minimos sem tropecar em traco, espaco ou ponto.
    regexp_replace(upper(CAST(pie.item_estoque_pub AS VARCHAR)), '[^0-9A-Z]', '', 'g')
                                                                AS codigo_norm

FROM acumulado AS a
CROSS JOIN parametros AS p
JOIN ccm__pec_item_estoque AS pie
  ON  pie.empresa      = a.empresa
  AND pie.item_estoque = a.item_estoque
LEFT JOIN estoque_pecas AS est
  ON  est.revenda       = a.revenda
  AND est.item_estoque  = a.item_estoque
ORDER BY a.revenda, a.valor_liquido DESC
