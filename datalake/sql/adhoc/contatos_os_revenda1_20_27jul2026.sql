-- Consulta ad hoc para rodar DIRETO no Oracle (Linx), fora do pipeline do
-- datalake. Contatos de clientes com nota fiscal tipo O21 (ordem de servico
-- faturada) na revenda 1, entre 20/07/2026 e 27/07/2026, com o numero da OS
-- vinculada via CONTATO.
--
-- Executar em SQL Developer/Toad, ou via:
--   setup_windows.ps1 -Sql "..." -SourceName ccm -LakeRoot C:\datalake
-- (precisa de acesso a rede interna e usuario datalake_ro -- este ambiente
-- remoto nao alcanca essa rede).
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
FROM FAT_CLIENTE fc
INNER JOIN FAT_MOVIMENTO_CAPA fmc
        ON fc.CLIENTE = fmc.CLIENTE
LEFT JOIN OFI_ORDEM_SERVICO oos
       ON fmc.CONTATO = oos.CONTATO
WHERE fmc.TIPO_TRANSACAO = 'O21'
  AND fmc.REVENDA = 1
  AND fmc.DTA_DOCUMENTO BETWEEN TO_DATE('2026-07-20 00:00:00', 'YYYY-MM-DD HH24:MI:SS')
                            AND TO_DATE('2026-07-27 23:59:59', 'YYYY-MM-DD HH24:MI:SS');
