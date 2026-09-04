-- Consulta Gerencial > Pecas: venda, custo, lucro e desconto por filial,
-- ja liquidos de devolucao. Traducao da consulta do Apollo.
--
-- Tres diferencas propositais em relacao ao SQL original:
--
--   1. Todos os meses, nao so o atual. O original carimbava toda linha com
--      to_char(current_date) e filtrava pelo mes corrente; aqui a competencia
--      vem da propria data do movimento, entao o mesmo modelo da o historico e
--      permite comparar meses. Filtrando o mes atual no Power BI, o numero e o
--      mesmo.
--   2. Departamento vira coluna em vez de filtro fixo em 300. Filtre 300 no
--      relatorio para reproduzir a consulta original; os demais departamentos
--      ficam disponiveis sem escrever SQL novo.
--   3. Divisao protegida por nullif. Filial sem venda no mes fazia a consulta
--      original estourar com divisao por zero.
--
-- As formulas de venda, custo e lucro foram mantidas exatamente como estavam,
-- inclusive a diferenca entre venda e devolucao: venda soma o frete, devolucao
-- subtrai val_frete_pf. Sao regras do negocio, nao detalhe de implementacao.
WITH base AS (
    SELECT
        rev.empresa,
        rev.revenda,
        rev.cnpj,
        rev.nome_fantasia                                AS filial,
        fmc.departamento,
        date_trunc('month', fmc.dta_entrada_saida)       AS competencia,
        tt.tipo,
        tt.subtipo_transacao,
        fmi.val_total_real_item,
        coalesce(fmi.val_desconto, 0)                    AS val_desconto,
        coalesce(fmi.val_frete, 0)                       AS val_frete,
        coalesce(fmi.val_frete_pf, 0)                    AS val_frete_pf,
        fmi.val_custo_medio,
        coalesce(fmi.val_icms, 0)                        AS val_icms,
        coalesce(fmi.val_pis, 0)                         AS val_pis,
        coalesce(fmi.val_cofins, 0)                      AS val_cofins
    FROM ccm__fat_movimento_item AS fmi
    JOIN ccm__fat_movimento_capa AS fmc
      ON  fmc.empresa            = fmi.empresa
      AND fmc.revenda            = fmi.revenda
      AND fmc.numero_nota_fiscal = fmi.numero_nota_fiscal
      AND fmc.serie_nota_fiscal  = fmi.serie_nota_fiscal
      AND fmc.tipo_transacao     = fmi.tipo_transacao
      AND fmc.contador           = fmi.contador
    JOIN ccm__ger_revenda AS rev
      ON  rev.empresa = fmc.empresa
      AND rev.revenda = fmc.revenda
    JOIN ccm__pec_item_estoque AS pie
      ON  pie.empresa      = fmi.empresa
      AND pie.item_estoque = fmi.item_estoque
    JOIN ccm__fat_tipo_transacao AS tt
      ON  tt.tipo_transacao = fmc.tipo_transacao
    WHERE fmc.tipo_transacao <> 'P50'
      AND fmc.status = 'F'
      AND pie.tipo_industrializacao IS NULL   -- fora: item de industrializacao
),

vendas AS (
    SELECT
        empresa, revenda, cnpj, filial, departamento, competencia,
        sum(val_desconto)                                AS desconto,
        sum(val_total_real_item)                         AS valor_real,
        sum(val_total_real_item) - sum(val_desconto) + sum(val_frete)
                                                         AS venda_total,
        sum(val_custo_medio)                             AS custo,
        (sum(val_total_real_item) - sum(val_desconto) + sum(val_frete)
         - (sum(val_icms) + sum(val_pis) + sum(val_cofins))
         - sum(val_custo_medio))                         AS lucro
    FROM base
    WHERE tipo = 'S' AND subtipo_transacao IN ('N')
    GROUP BY empresa, revenda, cnpj, filial, departamento, competencia
),

devolucoes AS (
    SELECT
        empresa, revenda, departamento, competencia,
        sum(val_desconto)                                AS desconto,
        sum(val_total_real_item) - sum(val_desconto)     AS venda_total,
        sum(val_custo_medio)                             AS custo,
        (sum(val_total_real_item) - sum(val_desconto)
         - (sum(val_icms) + sum(val_pis) + sum(val_cofins))
         - sum(val_custo_medio)
         - sum(val_frete_pf))                            AS lucro
    FROM base
    WHERE tipo = 'E' AND subtipo_transacao = 'D'
    GROUP BY empresa, revenda, departamento, competencia
)

SELECT
    v.empresa || '.' || v.revenda                        AS codigo_empresa,
    v.empresa,
    v.revenda,
    v.filial,
    v.cnpj,
    v.departamento,
    v.competencia,
    strftime(v.competencia, '%m/%Y')                     AS mes_ano_resultado,

    v.venda_total - coalesce(d.venda_total, 0)           AS venda_total,
    v.custo       - coalesce(d.custo, 0)                 AS custo,
    v.lucro       - coalesce(d.lucro, 0)                 AS lucro,
    round(
        (v.lucro - coalesce(d.lucro, 0))
        / nullif(v.venda_total - coalesce(d.venda_total, 0), 0) * 100
    , 2)                                                 AS lucro_porcentagem,

    v.desconto                                           AS valor_desconto,
    round(v.desconto / nullif(v.valor_real, 0) * 100, 2) AS desconto_porcentagem,

    -- Devolucao separada: no original ela so aparecia subtraida, e um mes com
    -- devolucao alta ficava indistinguivel de um mes de venda fraca.
    coalesce(d.venda_total, 0)                           AS devolucao_total,
    coalesce(d.lucro, 0)                                 AS devolucao_lucro

FROM vendas AS v
LEFT JOIN devolucoes AS d
  ON  d.empresa      = v.empresa
  AND d.revenda      = v.revenda
  AND d.departamento = v.departamento
  AND d.competencia  = v.competencia
ORDER BY v.competencia DESC, v.empresa, v.revenda
