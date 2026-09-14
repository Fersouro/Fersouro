-- Consulta ad hoc para rodar DIRETO no Oracle (Linx), fora do pipeline do
-- datalake. Contatos de clientes com nota fiscal tipo O21 (ordem de servico
-- faturada) na revenda 1, entre 20/07/2026 e 27/07/2026, com o numero da OS
-- vinculada via CONTATO.
--
-- Executar em SQL Developer/Toad, ou via:
--   setup_windows.ps1 -Sql "..." -SourceName ccm -LakeRoot C:\datalake
-- (precisa de acesso a rede interna e usuario datalake_ro -- este ambiente
-- remoto nao alcanca essa rede).
--
-- ATENCAO: qualifique com CNP. as tabelas -- o usuario de conexao (ex.:
-- FERNANDO_DEV) nao e o dono delas; sem o schema o Oracle procura no schema
-- do usuario da conexao e devolve ORA-00942.
SELECT
    fmc.REVENDA,
    fmc.NUMERO_NOTA_FISCAL,
    fmc.DTA_DOCUMENTO,
    oos.NRO_OS,
    fc.CLIENTE,
    fc.NOME,
    fc.DDD_TELEFONE,
    fc.TELEFONE,
    fc.DDD_CELULAR,
    fc.CELULAR
FROM CNP.FAT_CLIENTE fc
INNER JOIN CNP.FAT_MOVIMENTO_CAPA fmc
        ON fc.CLIENTE = fmc.CLIENTE
LEFT JOIN CNP.OFI_ORDEM_SERVICO oos
       ON fmc.CONTATO = oos.CONTATO
WHERE fmc.TIPO_TRANSACAO = 'O21'
  AND fmc.REVENDA = 1
  AND fmc.DTA_DOCUMENTO BETWEEN TO_DATE('2026-07-20 00:00:00', 'YYYY-MM-DD HH24:MI:SS')
                            AND TO_DATE('2026-07-27 23:59:59', 'YYYY-MM-DD HH24:MI:SS');
