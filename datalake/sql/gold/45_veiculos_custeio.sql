-- Custeio de veiculos: uma linha por proposta, veiculo e linha de formula.
--
-- E a base das consultas de custeio (novos e venda direta). O pivo -- uma
-- coluna por linha de formula -- fica no relatorio, nao aqui: cada consulta
-- pivota a sua lista, e a lista muda com o tempo. O modelo guarda o dado no
-- grao em que ele existe.
--
-- Tres diferencas propositais em relacao aos SQL originais:
--
--   1. Sem intervalo de datas fixo: a data de aprovacao vira coluna e o
--      relatorio filtra o periodo escolhido na tela.
--   2. Sem filtro de linha de formula. Cada consulta escolhe a sua lista; o
--      modelo traz todas as linhas com valor.
--   3. O vendedor entra por LEFT JOIN. No original era INNER: proposta cujo
--      vendedor nao esta no cadastro sumia da consulta inteira -- junto com o
--      dinheiro dela. Com LEFT, a linha aparece e o nome fica vazio.
SELECT
    vp.empresa,
    vp.revenda,
    CAST(vp.empresa AS VARCHAR) || '.'
        || CAST(vp.revenda AS VARCHAR)                   AS codigo_empresa,
    CAST(gr.cnpj AS VARCHAR)                             AS cnpj,
    gr.nome_fantasia                                     AS filial,
    vp.proposta,
    vp.veiculo,
    CAST(vp.dta_emissao AS DATE)                         AS dta_emissao,
    CAST(vp.dta_aprovacao_financeiro AS DATE)            AS dta_aprovacao,

    -- O prefixo do codigo do veiculo diz a linha: VNBA e veiculo novo.
    CASE WHEN vp.veiculo LIKE 'VNBA%' THEN 'VNBA' ELSE 'Outros' END AS tipo_veiculo,

    vp.vendedor,
    fv.nome                                              AS vendedor_nome,
    vp.tipo_venda,
    CASE vp.tipo_venda
        WHEN 'D' THEN 'Venda Direta'
        WHEN 'F' THEN 'Frotista'
        ELSE CAST(vp.tipo_venda AS VARCHAR)
    END                                                  AS tipo_venda_descricao,

    trim(vf.des_linha_formula)                           AS linha_formula,
    CAST(vvc.val_presente AS DOUBLE)                     AS val_presente

FROM ccm__vei_proposta         AS vp
JOIN ccm__vei_veiculo_custeio  AS vvc ON vvc.veiculo = vp.veiculo
JOIN ccm__vei_formula_linha    AS vf  ON vf.linha_formula = vvc.linha_formula
JOIN ccm__ger_revenda          AS gr  ON gr.empresa = vp.empresa
                                     AND gr.revenda = vp.revenda
LEFT JOIN ccm__fat_vendedor    AS fv  ON fv.empresa = vp.empresa
                                     AND fv.revenda = vp.revenda
                                     AND fv.vendedor = vp.vendedor

WHERE vvc.val_presente IS NOT NULL
  AND vvc.val_presente <> 0
