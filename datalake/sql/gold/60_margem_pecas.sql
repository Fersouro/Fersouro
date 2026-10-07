-- Consulta Gerencial > Pecas: venda, custo, lucro e desconto por filial,
-- ja liquidos de devolucao. Traducao da consulta do Apollo.
--
-- Tres diferencas propositais em relacao ao SQL original:
--
--   0. Grao de DIA, nao de mes. O relatorio filtra um periodo escolhido na
--      tela (de 05/09 a 20/09, por exemplo), e isso so e possivel se a linha
--      souber o dia. Somar os dias de um mes da exatamente o total mensal de
--      antes -- venda, custo, lucro e desconto sao aditivos. As porcentagens
--      nao sao: elas saem do relatorio, sobre a soma do periodo.
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
        CAST(fmc.dta_entrada_saida AS DATE)              AS data,
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
        empresa, revenda, cnpj, filial, departamento, data,
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
    GROUP BY empresa, revenda, cnpj, filial, departamento, data
),

devolucoes AS (
    SELECT
        empresa, revenda, cnpj, filial, departamento, data,
        sum(val_desconto)                                AS desconto,
        sum(val_total_real_item) - sum(val_desconto)     AS venda_total,
        sum(val_custo_medio)                             AS custo,
        (sum(val_total_real_item) - sum(val_desconto)
         - (sum(val_icms) + sum(val_pis) + sum(val_cofins))
         - sum(val_custo_medio)
         - sum(val_frete_pf))                            AS lucro
    FROM base
    WHERE tipo = 'E' AND subtipo_transacao = 'D'
    GROUP BY empresa, revenda, cnpj, filial, departamento, data
)

SELECT
    coalesce(v.empresa, d.empresa) || '.'
        || coalesce(v.revenda, d.revenda)                AS codigo_empresa,
    coalesce(v.empresa, d.empresa)                       AS empresa,
    coalesce(v.revenda, d.revenda)                       AS revenda,
    coalesce(v.filial, d.filial)                         AS filial,
    coalesce(v.cnpj, d.cnpj)                             AS cnpj,
    coalesce(v.departamento, d.departamento)             AS departamento,
    coalesce(v.data, d.data)                             AS data,
    date_trunc('month', coalesce(v.data, d.data))        AS competencia,
    strftime(coalesce(v.data, d.data), '%m/%Y')          AS mes_ano_resultado,

    coalesce(v.venda_total, 0) - coalesce(d.venda_total, 0) AS venda_total,
    coalesce(v.custo, 0)       - coalesce(d.custo, 0)       AS custo,
    coalesce(v.lucro, 0)       - coalesce(d.lucro, 0)       AS lucro,
    round(
        (coalesce(v.lucro, 0) - coalesce(d.lucro, 0))
        / nullif(coalesce(v.venda_total, 0) - coalesce(d.venda_total, 0), 0) * 100
    , 2)                                                 AS lucro_porcentagem,

    coalesce(v.desconto, 0)                              AS valor_desconto,
    round(coalesce(v.desconto, 0)
          / nullif(v.valor_real, 0) * 100, 2)            AS desconto_porcentagem,

    -- Devolucao separada: no original ela so aparecia subtraida, e um mes com
    -- devolucao alta ficava indistinguivel de um mes de venda fraca.
    coalesce(d.venda_total, 0)                           AS devolucao_total,
    coalesce(d.lucro, 0)                                 AS devolucao_lucro

-- FULL OUTER, nao LEFT: no grao de dia e comum haver devolucao num dia sem
-- venda daquele departamento. Com LEFT JOIN essa devolucao sumia -- e o total
-- do mes ficava maior do que o da consulta original.
FROM vendas AS v
FULL OUTER JOIN devolucoes AS d
  ON  d.empresa      = v.empresa
  AND d.revenda      = v.revenda
  AND d.departamento = v.departamento
  AND d.data         = v.data
ORDER BY data DESC, empresa, revenda
