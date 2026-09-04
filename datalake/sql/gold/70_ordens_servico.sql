-- Ordens de servico com loja, cliente, departamento e fonte pagadora.
-- Traducao da consulta de funilaria do Apollo.
--
-- Duas diferencas propositais em relacao ao SQL original:
--
--   1. Sem intervalo de datas fixo. O lake guarda tudo e o Power BI filtra --
--      o mesmo modelo serve para qualquer periodo, sem editar SQL.
--   2. Departamento vira coluna em vez de filtro fixo em 410. Filtre 410 no
--      relatorio para reproduzir a consulta de funilaria; oficina, revisao e
--      os demais departamentos vem juntos, de graca.
--
-- O CAST nos numeros e obrigatorio: concatenar numero com texto nao passa no
-- DuckDB, e empresa, revenda e a fonte sao numericos.
SELECT
    strftime(os.dta_encerramento, '%m/%Y')                   AS mes,
    date_trunc('month', os.dta_encerramento)                 AS competencia,
    CAST(os.empresa AS VARCHAR) || '.'
        || CAST(os.revenda AS VARCHAR)                       AS codigo_empresa,
    os.empresa,
    os.revenda,
    r.nome_fantasia                                          AS loja,
    atd.departamento,
    os.nro_os,
    CAST(os.dta_emissao      AS DATE)                        AS emissao,
    CAST(os.dta_encerramento AS DATE)                         AS encerramento,

    -- O nome do atendimento vem primeiro: e quem apareceu na loja, que nem
    -- sempre e o titular do cadastro.
    coalesce(atd.nome_contato, c.nome)                       AS cliente,
    os.contato,
    os.fonte_pagadora_ext                                    AS cod_fonte,
    coalesce(f.des_fonte,
             'cod ' || CAST(os.fonte_pagadora_ext AS VARCHAR)) AS fonte_pagadora,

    -- Quanto tempo a OS ficou aberta: a pergunta seguinte de todo relatorio
    -- de funilaria, e que ninguem calcula na planilha.
    date_diff('day', CAST(os.dta_emissao AS DATE),
                     CAST(os.dta_encerramento AS DATE))      AS dias_em_aberto

FROM ccm__ofi_ordem_servico AS os
JOIN ccm__ofi_atendimento   AS atd
  ON  atd.empresa = os.empresa
  AND atd.revenda = os.revenda
  AND atd.contato = os.contato
LEFT JOIN ccm__ger_revenda AS r
  ON  r.empresa = os.empresa AND r.revenda = os.revenda
LEFT JOIN ccm__fat_cliente AS c ON c.cliente = os.contato
LEFT JOIN ccm__fat_fonte   AS f ON f.fonte   = os.fonte_pagadora_ext
WHERE os.dta_encerramento IS NOT NULL
