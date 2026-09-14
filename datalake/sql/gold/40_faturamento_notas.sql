-- Faturamento liquido por nota fiscal de servico.
-- Traducao da consulta de faturamento da funilaria (series 03 e 08).
--
-- O grao aqui e a NOTA, nao o total por filial: a formula do liquido fica num
-- lugar so, e o relatorio agrega como precisar -- por filial, por mes, por
-- departamento -- sem repetir vinte linhas de CASE em cada aba.
--
-- Quatro diferencas propositais em relacao ao SQL original:
--
--   1. Sem intervalo de datas fixo. O original filtrava o mes corrente
--      (TRUNC(SYSDATE,'MM') ate LAST_DAY); aqui a competencia vem da propria
--      data do movimento, entao o mesmo modelo da o historico e permite
--      comparar meses. Filtrando o mes atual no relatorio, o numero e o mesmo.
--   2. Empresa, revenda e departamento viram coluna em vez de filtro fixo em
--      1, 1 e 410. O relatorio de funilaria filtra 410; as demais areas ficam
--      disponiveis sem escrever SQL novo.
--   3. As series 03 e 08 viram uma coluna 'serie' em vez de duas somas. O
--      relatorio pivota de volta para as duas colunas do original.
--   4. Fora o LEFT JOIN com FAT_NOTAS_VENDEDOR. Ele nao contribui com nenhuma
--      coluna do SELECT nem do GROUP BY -- e, se houver mais de um vendedor na
--      mesma nota, multiplica a linha e infla a soma. Tirando o join, o
--      numero fica igual quando ha um vendedor e correto quando ha varios.
--
-- Uma diferenca tecnica: o join com GER_REVENDA usa empresa E revenda. O
-- original ligava so por revenda, o que bastava porque ele fixava empresa = 1;
-- sem esse filtro, ligar so pela revenda repetiria a nota uma vez por empresa.
--
-- A FORMULA DO LIQUIDO FOI MANTIDA EXATAMENTE COMO ESTAVA, inclusive a
-- subtracao do ICMS desonerado que aparece DUAS VEZES no original (o primeiro
-- e o quarto CASE sao identicos). Parece engano de copia, mas mexer nisso
-- mudaria o numero que a empresa usa hoje -- entao fica como esta ate alguem
-- decidir o contrario. Para cobrar so uma vez, apague o bloco marcado abaixo.
SELECT
    fmc.empresa,
    fmc.revenda,
    CAST(fmc.empresa AS VARCHAR) || '.'
        || CAST(fmc.revenda AS VARCHAR)              AS codigo_empresa,
    rev.nome_fantasia                                AS filial,
    CAST(rev.cnpj AS VARCHAR)                        AS cnpj,
    fmc.departamento,
    date_trunc('month', fmc.dta_entrada_saida)       AS competencia,
    CAST(fmc.dta_entrada_saida AS DATE)              AS data,
    CAST(fmc.serie_nota_fiscal AS VARCHAR)           AS serie,
    fmc.numero_nota_fiscal,
    fmc.tipo_transacao,
    CAST(fmc.tot_nota_fiscal AS DOUBLE)              AS total_nota,

    CAST(
        fmc.tot_nota_fiscal
        - CASE WHEN coalesce(fmc.icmsdesonerado_descontadonota, 'N') = 'S'
               THEN coalesce(fmc.icms_desonerado, 0) ELSE 0 END
        - CASE WHEN coalesce(fmc.calcular_ipi, 'N') = 'S'
                AND coalesce(fmc.nf_despesa_val_liquido, '') <> ''
               THEN coalesce(fmc.tot_ipi, 0) ELSE 0 END
        - CASE WHEN coalesce(fmc.soma_icms_retido, 'N') = 'S'
                AND coalesce(fmc.nf_despesa_val_liquido, '') <> ''
               THEN coalesce(fmc.val_icms_retido, 0) ELSE 0 END
        -- >>> bloco repetido do original: identico ao primeiro CASE <<<
        - CASE WHEN coalesce(fmc.icmsdesonerado_descontadonota, 'N') = 'S'
               THEN coalesce(fmc.icms_desonerado, 0) ELSE 0 END
        -- >>> fim do bloco repetido <<<
        - CASE WHEN coalesce(fmc.nf_despesa_val_liquido, 'N') <> 'S'
               THEN coalesce(fmc.valdesconto, 0) + coalesce(fmc.valdesconto_mo, 0)
               ELSE 0 END
        - CASE WHEN fmc.nf_despesa_val_liquido = 'N'
               THEN coalesce(fmc.val_iss_retido, 0) + coalesce(fmc.val_imposto_renda, 0)
               ELSE 0 END
        - CASE WHEN coalesce(fmc.nf_despesa_abateu_pcc, 'N') = 'N'
                AND fmc.nf_despesa_val_liquido IS NOT NULL
                AND NOT (fmc.nf_despesa_abateu_pcc IS NULL
                         AND fmc.nf_despesa_val_liquido = 'S')
               THEN coalesce(fmc.val_pis_subst_tributaria, 0)
                  + coalesce(fmc.val_cofins_subst_tributa, 0)
                  + coalesce(fmc.val_csll, 0)
               ELSE 0 END
    AS DOUBLE)                                       AS valor_liquido

FROM ccm__fat_movimento_capa AS fmc
JOIN ccm__ger_revenda AS rev
  ON  rev.empresa = fmc.empresa
  AND rev.revenda = fmc.revenda

-- O21 e O31 sao as notas de servico da oficina; 'C' e nota cancelada.
WHERE fmc.tipo_transacao IN ('O21', 'O31')
  AND coalesce(fmc.status, '') <> 'C'
