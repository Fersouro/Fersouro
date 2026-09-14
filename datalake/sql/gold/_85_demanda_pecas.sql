-- =============================================================================
-- DESARMADO PELA SEGUNDA VEZ -- NAO ENTRA NA CARGA COM O "_" NO NOME
--
-- Historico honesto das tentativas, para quem pegar isto depois nao repetir:
--
--   1. "o filtro de data nao e empurravel"   -> reestruturado. Nao era.
--   2. "os tipos das chaves divergem"        -> DESCRIBE provou que nao.
--                                               Sao 4 BIGINT e 2 VARCHAR dos
--                                               dois lados. Nao era.
--   3. "as janelas ROWS ... 1 PRECEDING"     -> trocadas por aritmetica.
--                                               Ajudou, mas nao resolveu.
--   4. "o JOIN com o cadastro multiplica"    -> virou semi-juncao (EXISTS).
--                                               Uma medicao deu 0,5s depois
--                                               disso, mas a carga voltou a
--                                               travar em 14/09.
--
-- O que esta MEDIDO e certo, no servidor, com dado real:
--   - capa recortada em 12 meses ......... 0,67s
--   - juncao de 6 colunas capa x item .... 0,75s
--   - fat_tipo_transacao e unica (144/144), entao nao ha contagem em dobro
--
-- O que NAO foi medido: qual etapa depois disso consome o tempo. Toda vez que
-- tentei deduzir, errei. A proxima pessoa deve MEDIR antes de mexer -- de
-- preferencia com EXPLAIN ANALYZE, que nenhuma das tentativas chegou a usar.
--
-- PLANO B, que dispensa este modelo inteiro: a curva ja vem pronta do ERP em
-- PEC_ITEM_REVENDA.CLASS_ABC, exposta pelo gold estoque_pecas. Para o minimo
-- por demanda basta a demanda media -- sem Pareto, sem janela, sem curva
-- calculada. E metade deste arquivo.
-- =============================================================================
-- Demanda de pecas por revenda: quanto cada peca realmente sai por mes.
--
-- E a base para dimensionar estoque minimo. O ERP diz o que ha em estoque
-- (estoque_pecas) e em que curva a peca esta (class_abc); este modelo diz
-- quanto ela consome.
--
-- Quatro decisoes, todas parametrizadas no bloco 'parametros':
--
--   1. Janela de 12 meses FECHADOS. Menos que isso e sazonalidade vira
--      tendencia. E o mes corrente fica de fora: conta-lo pela metade
--      derrubaria a media todo comeco de mes.
--   2. Demanda LIQUIDA: venda menos devolucao. Peca vendida e devolvida no
--      mesmo mes nao gerou demanda, e contar so a venda inflaria o minimo.
--   3. A media divide pela janela inteira, nao pelos meses com venda. Peca que
--      saiu uma vez em 12 meses tem demanda 0,08/mes -- e nao 1/mes, que e o
--      que dariam os "meses com venda".
--   4. Pareto calculado DENTRO de cada revenda, que e a unidade de decisao de
--      compra. Classificar o grupo junto esconderia a peca que e A numa loja e
--      C na outra.
--
-- As curvas daqui (curva_valor, curva_qtd) sao dos ultimos 12 meses e servem
-- para CONFERIR a class_abc do ERP, nao para substitui-la: divergencia grande
-- costuma ser peca que mudou de patamar e ficou com a classificacao velha.
WITH parametros AS (
    SELECT
        -- ATENCAO: o 12 aparece em DOIS lugares -- aqui (divisor da media) e no
        -- to_months(12) do recorte da capa, que precisa ser literal para o
        -- filtro ser empurravel. Mudar so um dos dois da media errada em
        -- silencio: janela de 24 meses dividida por 12 dobra a demanda.
        12    AS meses_janela,   -- periodo de apuracao -- casar com to_months()
        0.80  AS corte_a,        -- ate 80% do acumulado = A
        0.95  AS corte_b         -- de 80% a 95% = B; acima = C
),

-- POR QUE A CAPA E FILTRADA PRIMEIRO
--
-- A primeira versao deste modelo colocava o recorte de 12 meses no WHERE de um
-- FROM que comecava pela FAT_MOVIMENTO_ITEM (a maior tabela) e trazia a janela
-- de um CROSS JOIN de parametros. Com a data dependendo de uma coluna vinda do
-- cross join, o filtro deixa de ser empurravel para a leitura: o motor junta
-- item com capa inteira e so entao descarta o que esta fora da janela. Resultado
-- medido no servidor: 625 segundos e a consulta interrompida.
--
-- Aqui a capa e recortada sozinha, com literal, antes de qualquer juncao -- e a
-- juncao grande passa a mirar um conjunto ja pequeno. Mesma resposta, ordem de
-- grandeza diferente de custo.
--
-- Regra que fica: em modelo gold, valor de parametro que entra em filtro de
-- leitura vai como literal. O CROSS JOIN de parametros so no SELECT final.
capa AS (
    SELECT
        empresa,
        revenda,
        numero_nota_fiscal,
        serie_nota_fiscal,
        tipo_transacao,
        contador,
        date_trunc('month', dta_entrada_saida)              AS competencia
    FROM ccm__fat_movimento_capa
    WHERE status = 'F'
      AND tipo_transacao <> 'P50'
      -- 12 meses FECHADOS. Literal de proposito: ver o bloco acima.
      AND dta_entrada_saida >= date_trunc('month', current_date) - to_months(12)
      AND dta_entrada_saida <  date_trunc('month', current_date)
),

-- Peca de industrializacao fora, uma vez so, antes da juncao grande.
-- Cadastro reduzido a UMA linha por (empresa, item_estoque).
--
-- O join com o cadastro existe para duas coisas diferentes, e misturar as duas
-- foi o erro: FILTRAR item de industrializacao, e ETIQUETAR a peca com codigo e
-- descricao. Filtro com JOIN so e seguro se a chave for unica do outro lado --
-- se nao for, cada item da nota casa com varias linhas do cadastro, as linhas se
-- multiplicam e a demanda sai inflada. Alem de custar caro.
--
-- Aqui o filtro virou semi-juncao (EXISTS, no base) e a etiqueta vem deste
-- cadastro agregado. Nenhum dos dois pode multiplicar linha, haja duplicata no
-- cadastro ou nao.
cadastro AS (
    SELECT
        empresa,
        item_estoque,
        any_value(item_estoque_pub)  AS item_estoque_pub,
        any_value(des_item_estoque)  AS des_item_estoque,
        any_value(marca)             AS marca
    FROM ccm__pec_item_estoque
    GROUP BY empresa, item_estoque
),

base AS (
    SELECT
        c.empresa,
        c.revenda,
        fmi.item_estoque,
        c.competencia,
        tt.tipo,
        tt.subtipo_transacao,
        CAST(fmi.quantidade AS DOUBLE)                      AS qtd,
        CAST(fmi.val_total_real_item AS DOUBLE)
          - coalesce(CAST(fmi.val_desconto AS DOUBLE), 0)   AS valor
    FROM capa AS c
    JOIN ccm__fat_movimento_item AS fmi
      ON  fmi.empresa            = c.empresa
      AND fmi.revenda            = c.revenda
      AND fmi.numero_nota_fiscal = c.numero_nota_fiscal
      AND fmi.serie_nota_fiscal  = c.serie_nota_fiscal
      AND fmi.tipo_transacao     = c.tipo_transacao
      AND fmi.contador           = c.contador
    JOIN ccm__fat_tipo_transacao AS tt
      ON  tt.tipo_transacao = c.tipo_transacao
    -- Semi-juncao: filtra sem multiplicar, mesmo que o cadastro tenha a peca
    -- repetida. Um JOIN aqui duplicaria a nota uma vez por linha repetida.
    WHERE EXISTS (
        SELECT 1
        FROM ccm__pec_item_estoque AS pe
        WHERE pe.empresa              = fmi.empresa
          AND pe.item_estoque         = fmi.item_estoque
          AND pe.tipo_industrializacao IS NULL
    )
),

liquido AS (
    SELECT
        empresa,
        revenda,
        item_estoque,
        sum(CASE WHEN tipo = 'S' AND subtipo_transacao = 'N' THEN qtd   ELSE 0 END)
          - sum(CASE WHEN tipo = 'E' AND subtipo_transacao = 'D' THEN qtd   ELSE 0 END)
                                                            AS qtd_periodo,
        sum(CASE WHEN tipo = 'S' AND subtipo_transacao = 'N' THEN valor ELSE 0 END)
          - sum(CASE WHEN tipo = 'E' AND subtipo_transacao = 'D' THEN valor ELSE 0 END)
                                                            AS valor_periodo,
        count(DISTINCT CASE WHEN tipo = 'S' AND subtipo_transacao = 'N'
                            THEN competencia END)           AS meses_com_venda
    FROM base
    GROUP BY empresa, revenda, item_estoque
),

-- So entra no Pareto quem teve saida liquida positiva: peca com devolucao
-- maior que venda ficaria com valor negativo e desarrumaria o acumulado.
elegivel AS (
    SELECT * FROM liquido WHERE qtd_periodo > 0 AND valor_periodo > 0
),

-- Duas leituras do acumulado de Pareto, e a diferenca entre elas importa:
--
--   acum_*        inclui a propria linha  -> e o numero que se LE no relatorio
--                                            ("estas pecas sao 80% do valor")
--   acum_*_antes  para na linha anterior  -> e o numero que CLASSIFICA
--
-- Classificar pelo acumulado inclusivo joga para B justamente a peca que cruza
-- os 80%. No limite, uma peca que sozinha representa 90% do valor nao seria A
-- -- e a curva sairia sem nenhum item A, que e o contrario do que ela existe
-- para mostrar. A regra correta e: a peca e A enquanto o acumulado ANTES dela
-- ainda nao atingiu o corte.
-- Duas somas corridas simples (ROWS UNBOUNDED PRECEDING), nada mais.
--
-- A versao anterior pedia tambem um quadro ROWS BETWEEN UNBOUNDED PRECEDING
-- AND 1 PRECEDING para obter o acumulado ATE A LINHA ANTERIOR. Esse quadro nao
-- e uma soma corrida: dependendo do motor ele e avaliado linha a linha, O(n^2).
-- Com dezenas de milhares de pecas viram bilhoes de operacoes -- e foi o que
-- fez o modelo rodar horas sem terminar.
--
-- O mesmo numero sai por subtracao: o acumulado antes da linha e o acumulado
-- ate a linha menos o valor da propria linha. Aritmetica, nao janela.
corrida AS (
    SELECT
        e.*,
        sum(e.valor_periodo) OVER (
            PARTITION BY e.revenda ORDER BY e.valor_periodo DESC, e.item_estoque
            ROWS UNBOUNDED PRECEDING
        )                                                   AS soma_valor_ate_aqui,
        sum(e.valor_periodo) OVER (PARTITION BY e.revenda)  AS total_valor,
        sum(e.qtd_periodo) OVER (
            PARTITION BY e.revenda ORDER BY e.qtd_periodo DESC, e.item_estoque
            ROWS UNBOUNDED PRECEDING
        )                                                   AS soma_qtd_ate_aqui,
        sum(e.qtd_periodo)   OVER (PARTITION BY e.revenda)  AS total_qtd
    FROM elegivel AS e
),

acumulado AS (
    SELECT
        c.*,
        -- acum_*       : inclui a propria linha -> e o numero que se LE
        -- acum_*_antes : para na linha anterior -> e o numero que CLASSIFICA
        c.soma_valor_ate_aqui / nullif(c.total_valor, 0)                     AS acum_valor,
        (c.soma_valor_ate_aqui - c.valor_periodo) / nullif(c.total_valor, 0) AS acum_valor_antes,
        c.soma_qtd_ate_aqui   / nullif(c.total_qtd, 0)                       AS acum_qtd,
        (c.soma_qtd_ate_aqui  - c.qtd_periodo)  / nullif(c.total_qtd, 0)     AS acum_qtd_antes
    FROM corrida AS c
)

SELECT
    a.empresa,
    a.revenda,
    a.item_estoque,
    pie.item_estoque_pub                                    AS codigo,
    trim(pie.des_item_estoque)                              AS descricao,
    pie.marca,

    p.meses_janela,
    round(a.qtd_periodo, 2)                                 AS qtd_periodo,
    round(a.valor_periodo, 2)                               AS valor_periodo,
    a.meses_com_venda,
    round(a.qtd_periodo / p.meses_janela, 4)                AS demanda_media_mensal,

    CASE WHEN a.acum_valor_antes < p.corte_a THEN 'A'
         WHEN a.acum_valor_antes < p.corte_b THEN 'B'
         ELSE 'C' END                                       AS curva_valor,
    CASE WHEN a.acum_qtd_antes   < p.corte_a THEN 'A'
         WHEN a.acum_qtd_antes   < p.corte_b THEN 'B'
         ELSE 'C' END                                       AS curva_qtd,
    round(a.acum_valor * 100, 2)                            AS acum_valor_pct,
    round(a.acum_qtd   * 100, 2)                            AS acum_qtd_pct

FROM acumulado AS a
CROSS JOIN parametros AS p
JOIN cadastro AS pie
  ON  pie.empresa      = a.empresa
  AND pie.item_estoque = a.item_estoque
ORDER BY a.revenda, a.valor_periodo DESC
