-- Consulta ad hoc para rodar DIRETO no Oracle (Linx), fora do pipeline do
-- datalake. Nao segue a convencao de sql/gold (que roda em DuckDB sobre as
-- tabelas ja replicadas com prefixo ccm__/erp__) -- usa sintaxe/nomes Oracle
-- originais, schema CNP.
--
-- Executar em SQL Developer/Toad ou via cliente Oracle com acesso a rede
-- interna (192.168.0.10:1521) e usuario datalake_ro -- este ambiente remoto
-- nao alcanca essa rede.
--
-- Objetivo: para cada chassi da aba "set26" do PIV Setembro/2026 (66 carros,
-- lista no final deste arquivo), achar Vendedor, Proposta e Preco Tabela.
--
-- O modelo gold sql/gold/45_veiculos_custeio.sql ja junta VEI_PROPOSTA +
-- VEI_VEICULO_CUSTEIO + VEI_FORMULA_LINHA + FAT_VENDEDOR, mas pelo codigo do
-- veiculo (VEICULO), nao pelo chassi -- e nao expoe o chassi nem isola a
-- linha "Preco Tabela" (ela deve ser uma das linhas de VEI_FORMULA_LINHA,
-- mas o nome exato nunca foi confirmado -- ver PARTE 1).

-- ============================================================ PARTE 1 -----
-- Descoberta: nome da coluna de chassi em VEI_VEICULO e o texto exato da(s)
-- linha(s) de formula que correspondem a "Preco Tabela". Rodar isso primeiro
-- e confirmar antes de ajustar a PARTE 2.
SELECT table_name, column_name, data_type
FROM all_tab_columns
WHERE owner = 'CNP'
  AND table_name IN ('VEI_VEICULO', 'VEI_PROPOSTA', 'FAT_MOVIMENTO_CAPA',
                      'FAT_MOVIMENTO_VEICULO', 'VEI_FORMULA_LINHA')
ORDER BY table_name, column_id;

-- Lista as descricoes de linha de formula existentes -- procurar a(s) que
-- falam de "tabela" (ex.: 'PRECO TABELA', 'PRECO DE TABELA', 'VALOR TABELA').
SELECT DISTINCT linha_formula, des_linha_formula
FROM CNP.VEI_FORMULA_LINHA
ORDER BY des_linha_formula;

-- ============================================================ PARTE 2 -----
-- Consulta final -- AJUSTAR apos confirmar a PARTE 1:
--   1. Troque VV.CHASSI pelo nome real da coluna de chassi em VEI_VEICULO,
--      se for diferente.
--   2. Troque o filtro UPPER(VF.DES_LINHA_FORMULA) LIKE '%TABELA%' pelo texto
--      exato encontrado na PARTE 1 (pode ser mais de uma linha).
SELECT
    VV.CHASSI,
    VP.PROPOSTA,
    VP.VENDEDOR,
    FV.NOME                    AS VENDEDOR_NOME,
    VP.VEICULO,
    VP.DTA_EMISSAO,
    VP.DTA_APROVACAO_FINANCEIRO,
    VF.DES_LINHA_FORMULA,
    VVC.VAL_PRESENTE            AS PRECO_TABELA
FROM CNP.VEI_VEICULO          VV
JOIN CNP.VEI_PROPOSTA         VP  ON VP.VEICULO = VV.VEICULO
JOIN CNP.VEI_VEICULO_CUSTEIO  VVC ON VVC.VEICULO = VP.VEICULO
JOIN CNP.VEI_FORMULA_LINHA    VF  ON VF.LINHA_FORMULA = VVC.LINHA_FORMULA
LEFT JOIN CNP.FAT_VENDEDOR    FV  ON FV.EMPRESA = VP.EMPRESA
                                 AND FV.REVENDA = VP.REVENDA
                                 AND FV.VENDEDOR = VP.VENDEDOR
WHERE UPPER(VF.DES_LINHA_FORMULA) LIKE '%TABELA%'
  AND TRIM(VV.CHASSI) IN (
    '9BWJL45U0VP021238','9BWBH6BF5V4013404','9BWKL45U5VP023488','9BWKL45U6VP025024',
    '9BWKL45U7VP025145','9BWJL45UXVP023191','9BWKL45U1VP025447','9BWBH6BF4V4018707',
    '9BWBH6BF5T4143910','9BWCH6CH8VP018731','9BWAG5R11TP062596','9BWBH6DF9TT454565',
    '3VVUX6RMXTM153431','9BWBH6BF6T4143334','9BWAG5R18TP056259','3VVJM6B25TM069344',
    '9BWAG5R1XTP062631','9BWBH6BF3T4122702','9BWCH6CH9VP022013','9BWBH6DF1TT457203',
    '9BWBH6BF0T4143409','9BWBH6BF0T4118509','9BWBH6BF4V4014463','9BWBH6BF6V4015856',
    '9BWDJ6BZ2T4026597','9BWCH6CH7VP019742','9BWBH6DF9TT450645','3VVUX6RM6TM123827',
    '9BWBH6BF4T4143932','9BWBG6DF4TT452192','3VVJM6B27TM085707','9BWCH6CHXVP021601',
    '9BWBH6BF8V4021822','9BWBH6BF0V4021992','9BWDJ6BZ4T4042879','3VVJM6B29TM064535',
    '9BWCH6CH2VP013038','9BWBG6DF8TT442474','9BWCH6CH1VP027481','9BWBJ6BF9T4143042',
    '9BWBH6BF8T4124011','9BWBH6BF0V4024021','9BWBH6BF3V4021789','9BWBG6DF6TT464571',
    '3VVJM6B23TM088099','3VVUX6RM2TM150605','9BWCH6CH8VP022049','9BWAG5R1XTP071586',
    '9BWBH6DF6TT462395','3VVUX6RM4TM152548','9BWBG6DF1TT441912','9BWBG6DF1TT469158',
    '3VVUX6RM6TM151708','3VVUX6RM7TM153001','9BWBJ6BF7V4004384','9BWAG5R15TT044951',
    '9BWAG5R10TT044808','9BWAG5R13TP072465','9BWJL45U9VP015910','9BWKL45U8VP018270',
    '9BWAG5R17TP075689','9BWAH5BZ1TT679226','9BWBH6BF0V4009048','9BWKL45U5VP023829',
    '9BWKL45U1VP023987','9BWBG6DF7TT473683'
  )
ORDER BY VV.CHASSI, VP.DTA_APROVACAO_FINANCEIRO DESC;

-- Se a PARTE 2 nao achar a linha "Preco Tabela" dentro do custeio (pode ser
-- que o campo esteja na nota fiscal de venda, nao no custeio), tentar via
-- FAT_MOVIMENTO_VEICULO + FAT_MOVIMENTO_CAPA -- confirmar colunas na PARTE 1
-- (procurar algo como VAL_TABELA, VAL_PRECO_TABELA na capa da nota).
