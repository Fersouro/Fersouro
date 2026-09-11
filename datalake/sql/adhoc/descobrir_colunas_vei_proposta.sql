-- Ajuda para mapear VEI_PROPOSTA e FAT_MOVIMENTO_CAPA antes de montar a
-- consulta final de vendedor/proposta/preco tabela por chassi (PIV 2026).
-- Rodar no Oracle (schema CNP) e mandar o resultado.
SELECT table_name, column_name, data_type
FROM all_tab_columns
WHERE owner = 'CNP'
  AND table_name IN ('VEI_PROPOSTA', 'FAT_MOVIMENTO_CAPA')
ORDER BY table_name, column_id;
