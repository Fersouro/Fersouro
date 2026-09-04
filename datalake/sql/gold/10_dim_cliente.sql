-- Dimensao de clientes.
-- Views disponiveis: <fonte>__<tabela> sempre; <tabela> quando o nome for unico.
SELECT
    c.id_cliente,
    c.nome,
    c.uf,
    c.situacao,
    CASE c.situacao WHEN 'A' THEN 'Ativo' WHEN 'I' THEN 'Inativo' ELSE 'Indefinido' END
        AS situacao_descricao,
    c.dt_cadastro,
    date_diff('month', c.dt_cadastro, current_date)         AS meses_de_casa,
    c.limite_credito
FROM clientes AS c
