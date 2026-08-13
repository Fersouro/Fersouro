-- Contatos de pos-venda da oficina: quem passou pela oficina, com a OS e os
-- telefones. Traducao da consulta usada hoje no Excel.
--
-- Duas diferencas propositais em relacao ao SQL original:
--
--   1. Sem intervalo de datas fixo. O lake guarda o periodo todo e o Power BI
--      filtra -- assim o mesmo modelo serve para qualquer semana, sem editar
--      SQL e recarregar.
--   2. Sem 'REVENDA = 1'. A revenda vira coluna e vira filtro no relatorio,
--      que serve a todas as lojas em vez de uma.
--
-- O filtro de TIPO_TRANSACAO fica, porque e ele que define o conjunto:
-- 'O21' e a nota fiscal de servico da oficina.
SELECT
    fmc.revenda,
    fmc.numero_nota_fiscal,
    fmc.dta_documento,
    CAST(fmc.dta_documento AS DATE)                      AS data,
    date_trunc('month', fmc.dta_documento)               AS competencia,
    oos.nro_os,
    fc.cliente,
    fc.nome,
    fc.ddd_telefone,
    fc.telefone,
    fc.ddd_celular,
    fc.celular,

    -- Telefone pronto para uso: prefere o celular, cai para o fixo, e junta o
    -- DDD. Sem isso, todo relatorio refaz essa concatenacao na mao.
    coalesce(
        nullif(trim(coalesce(fc.ddd_celular, '') || coalesce(fc.celular, '')), ''),
        nullif(trim(coalesce(fc.ddd_telefone, '') || coalesce(fc.telefone, '')), '')
    )                                                    AS telefone_contato,
    CASE
        WHEN nullif(trim(coalesce(fc.celular, '')), '') IS NOT NULL THEN 'celular'
        WHEN nullif(trim(coalesce(fc.telefone, '')), '') IS NOT NULL THEN 'fixo'
        ELSE 'sem telefone'
    END                                                  AS tipo_telefone

FROM ccm__fat_movimento_capa AS fmc
JOIN ccm__fat_cliente        AS fc  ON fc.cliente = fmc.cliente
LEFT JOIN ccm__ofi_ordem_servico AS oos ON oos.contato = fmc.contato
WHERE fmc.tipo_transacao = 'O21'
