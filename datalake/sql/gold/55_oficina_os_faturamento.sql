-- Faturamento da oficina no grao da ORDEM DE SERVICO: pecas e servicos juntos.
--
-- Traducao da consulta que a equipe roda no Apollo. Ela era um UNION de dois
-- selects (um so de peca, outro so de servico) agrupado por OS; aqui os dois
-- lados sao CTEs ligados por (empresa, revenda, nro_os), que e a mesma conta
-- escrita de forma direta -- e deixa a OS aparecer uma vez so, com as duas
-- colunas preenchidas.
--
-- Duas diferencas propositais:
--
--   1. Sem intervalo de datas fixo. O original comparava o MES corrente das
--      quatro datas de fim (externo, garantia, revisao, encerramento); aqui as
--      quatro viram coluna e o relatorio filtra o periodo escolhido na tela.
--   2. A franquia entra por 'max' em vez de 'sum(distinct ...)'. No grao de OS
--      as duas dao o mesmo numero -- ha um unico valor de franquia por OS --,
--      e 'max' diz isso explicitamente. 'sum(distinct)' era uma defesa contra a
--      multiplicacao de linhas do join, que aqui nao existe.
WITH os_base AS (
    SELECT
        os.empresa,
        os.revenda,
        os.nro_os,
        CAST(os.empresa AS VARCHAR) || '.'
            || CAST(os.revenda AS VARCHAR)               AS codigo_empresa,
        CAST(rv.cnpj AS VARCHAR)                         AS cnpj,
        rv.nome_fantasia                                 AS filial,
        atd.departamento,
        CAST(os.dta_fim_externo    AS DATE)              AS dta_fim_externo,
        CAST(os.dta_fim_garantia   AS DATE)              AS dta_fim_garantia,
        CAST(os.dta_fim_revisao    AS DATE)              AS dta_fim_revisao,
        CAST(os.dta_encerramento   AS DATE)              AS dta_encerramento,
        coalesce(os.val_franquia_pecas, 0)               AS val_franquia_pecas,
        coalesce(os.val_franquia_servicos, 0)            AS val_franquia_servicos
    FROM ccm__ofi_ordem_servico AS os
    JOIN ccm__ger_revenda AS rv
      ON rv.empresa = os.empresa AND rv.revenda = os.revenda
    JOIN ccm__ofi_atendimento AS atd
      ON  atd.empresa = os.empresa
      AND atd.revenda = os.revenda
      AND atd.contato = os.contato
    WHERE os.categoria_os <> 7
      AND atd.departamento <> 410            -- funilaria tem consulta propria
      AND os.situacao_os = 9                 -- OS fechada
      AND (os.servico_externo  = 9
        OR os.servico_garantia = 9
        OR os.servico_revisao  = 9)
),

pecas AS (
    SELECT
        b.empresa, b.revenda, b.nro_os,
        sum(fmi.val_total_real_item - coalesce(fmi.val_desconto, 0))
            + max(b.val_franquia_pecas)                  AS total_pecas,
        sum(coalesce(fmi.val_desconto, 0))               AS desconto_pecas,
        sum(fmi.val_total_real_item - coalesce(fmi.val_desconto, 0))
            + max(b.val_franquia_pecas)
            - sum(coalesce(fmi.val_pis, 0) + coalesce(fmi.val_cofins, 0))
            - sum(fmi.val_custo_medio)
            - sum(coalesce(fmi.val_frete_pf, 0))         AS lucro_pecas
    FROM os_base AS b
    JOIN ccm__ofi_ficha_movimento AS fim
      ON  fim.empresa = b.empresa
      AND fim.revenda = b.revenda
      AND fim.nro_os  = b.nro_os
    JOIN ccm__fat_movimento_capa AS fmc
      ON  fmc.empresa            = fim.empresa
      AND fmc.revenda            = fim.revenda
      AND fmc.numero_nota_fiscal = fim.numero_nota_fiscal
      AND fmc.serie_nota_fiscal  = fim.serie_nota_fiscal
      AND fmc.tipo_transacao     = fim.tipo_transacao
      AND fmc.contador           = fim.contador
    JOIN ccm__fat_movimento_item AS fmi
      ON  fmi.empresa            = fmc.empresa
      AND fmi.revenda            = fmc.revenda
      AND fmi.numero_nota_fiscal = fmc.numero_nota_fiscal
      AND fmi.serie_nota_fiscal  = fmc.serie_nota_fiscal
      AND fmi.tipo_transacao     = fmc.tipo_transacao
      AND fmi.contador           = fmc.contador
    GROUP BY b.empresa, b.revenda, b.nro_os
),

servicos AS (
    SELECT
        b.empresa, b.revenda, b.nro_os,
        sum(ofs.val_servico * ofs.quantidade)
            + max(b.val_franquia_servicos)
            - sum(coalesce(ofs.val_desconto, 0))         AS total_servico
    FROM os_base AS b
    JOIN ccm__ofi_servico_os AS ofs
      ON  ofs.empresa = b.empresa
      AND ofs.revenda = b.revenda
      AND ofs.nro_os  = b.nro_os
    WHERE ofs.situacao = 'N'                 -- servico fechado
    GROUP BY b.empresa, b.revenda, b.nro_os
)

SELECT
    b.codigo_empresa,
    b.empresa,
    b.revenda,
    b.cnpj,
    b.filial,
    b.departamento,
    b.nro_os,
    b.dta_fim_externo,
    b.dta_fim_garantia,
    b.dta_fim_revisao,
    b.dta_encerramento,
    CAST(coalesce(p.total_pecas, 0)    AS DOUBLE)        AS total_pecas,
    CAST(coalesce(p.desconto_pecas, 0) AS DOUBLE)        AS desconto_pecas,
    CAST(coalesce(p.lucro_pecas, 0)    AS DOUBLE)        AS lucro_pecas,
    CAST(coalesce(s.total_servico, 0)  AS DOUBLE)        AS total_servico

FROM os_base AS b
LEFT JOIN pecas    AS p ON p.empresa = b.empresa AND p.revenda = b.revenda AND p.nro_os = b.nro_os
LEFT JOIN servicos AS s ON s.empresa = b.empresa AND s.revenda = b.revenda AND s.nro_os = b.nro_os

-- OS sem peca e sem servico nao existia no original (os dois lados do UNION
-- eram INNER JOIN), e nao deve contar como passagem.
WHERE p.nro_os IS NOT NULL OR s.nro_os IS NOT NULL
