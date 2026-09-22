// =============================================================================
//  CHAVEIRO BAGEVET - tag circular personalizavel para impressao 3D
//  Unidades: milimetros. Origem no centro do disco, furo para o +Y.
//  Frente (lado A, +Z): coroa de patinhas + "BageVet" + "MEDICINA ANIMAL"
//  Verso  (lado B, -Z): patinha + nome do pet (parametrico)
// =============================================================================

/* [Personalizacao] ------------------------------------------------------- */
// Nome do pet gravado no verso (troque aqui, o resto do modelo nao muda)
nome              = "BOLINHA";
// Condensacao horizontal do nome (1 = natural). Use < 1 para nomes longos.
escala_x_nome     = 1.0;
// Marca da frente
texto_logo        = "BageVet";
texto_subtitulo   = "MEDICINA ANIMAL";
escala_x_logo     = 1.0;
escala_x_sub      = 1.0;

/* [Geometria do disco] --------------------------------------------------- */
diametro          = 50.0;   // diametro externo
espessura         = 3.5;    // espessura do corpo do disco (sem relevo)
raio_borda        = 1.0;    // arredondamento da borda externa (chanfro)
relevo            = 1.0;    // altura do relevo positivo (>= 0.8 p/ legibilidade)

/* [Furo da argola] ------------------------------------------------------- */
furo_diametro     = 5.0;    // diametro do furo
furo_margem       = 6.0;    // distancia da BORDA do furo ate a borda externa

/* [Frente - logo] -------------------------------------------------------- */
logo_diametro     = 34.0;   // diametro total da marca
n_patas           = 8;      // patinhas da coroa
coroa_giro        = 22.5;   // giro da coroa (evita patinha embaixo do furo)
pata_coroa        = 4.2;    // largura de cada patinha da coroa
altura_logo       = 4.0;    // altura das letras de "BageVet"
logo_y            = 1.0;    // linha de base de "BageVet"
altura_sub        = 1.8;    // altura das letras do subtitulo
sub_y             = -4.6;   // linha de base do subtitulo
espacamento_sub   = 1.06;   // espacejamento entre letras do subtitulo
engrossar_sub     = 0.06;   // engrossa o subtitulo (garante parede imprimivel)

/* [Verso - nome do pet] -------------------------------------------------- */
altura_nome       = 8.0;    // altura das letras do nome
nome_y            = -5.5;   // linha de base do nome
pata_verso        = 8.0;    // largura da patinha acima do nome
pata_verso_y      = 8.0;    // centro vertical da patinha do verso

/* [Fonte e qualidade] ---------------------------------------------------- */
fonte             = "Liberation Sans:style=Bold";
// "relevo" = alto-relevo nos dois lados (conforme especificacao)
// "baixo"  = verso gravado para baixo (permite imprimir deitado sem suporte)
modo_verso        = "relevo";
// "completo" = peca inteira | "corpo" / "detalhe" = arquivos p/ 2 cores (MMU)
parte             = "completo";
resolucao         = 180;    // segmentos do disco

/* [Calculos] ------------------------------------------------------------- */
R            = diametro / 2;
furo_r       = furo_diametro / 2;
furo_y       = R - furo_margem - furo_r;   // centro do furo
raio_coroa   = logo_diametro/2 - pata_coroa * 0.51;
eps          = 0.01;

// -----------------------------------------------------------------------------
//  Patinha 2D (largura total = tam, altura ~= 0.94 * tam)
// -----------------------------------------------------------------------------
// Proporcoes escolhidas para manter >= 0.45 mm de folga entre os dedinhos
// quando a patinha tem 4.2 mm (menor uso do desenho) -> separa bem com bico 0.4.
module pata2d(tam = 5) {
    scale(tam) {
        translate([0, -0.19]) scale([1, 0.86]) circle(r = 0.29, $fn = 48);
        for (d = [[-0.40, 0.10, -28], [-0.16, 0.38, -9],
                  [ 0.16, 0.38,   9], [ 0.40, 0.10,  28]])
            translate([d[0], d[1]]) rotate(d[2])
                scale([1, 1.20]) circle(r = 0.105, $fn = 32);
    }
}

// -----------------------------------------------------------------------------
//  Texto ajustado: altura da mancha grafica = alt, condensado por esc_x
// -----------------------------------------------------------------------------
module texto_fit(txt, alt, esc_x = 1, espaco = 1, engrossa = 0) {
    offset(r = engrossa)
        scale([esc_x, 1])
            resize([0, alt], auto = true)
                text(txt, size = 10, font = fonte, spacing = espaco,
                     halign = "center", valign = "baseline", $fn = 32);
}

// -----------------------------------------------------------------------------
//  Desenhos 2D de cada face
// -----------------------------------------------------------------------------
module frente2d() {
    for (i = [0 : n_patas - 1])
        rotate(coroa_giro + i * 360 / n_patas)
            translate([0, raio_coroa]) pata2d(pata_coroa);
    translate([0, logo_y]) texto_fit(texto_logo, altura_logo, escala_x_logo);
    translate([0, sub_y])  texto_fit(texto_subtitulo, altura_sub, escala_x_sub,
                                     espacamento_sub, engrossar_sub);
}

module verso2d() {
    translate([0, nome_y])       texto_fit(nome, altura_nome, escala_x_nome);
    translate([0, pata_verso_y]) pata2d(pata_verso);
}

// -----------------------------------------------------------------------------
//  Corpo do disco com borda arredondada (perfil convexo -> solido fechado)
// -----------------------------------------------------------------------------
module disco() {
    rotate_extrude($fn = resolucao)
        hull() {
            translate([0, -espessura/2]) square([eps, espessura]);
            translate([R - raio_borda,  espessura/2 - raio_borda])
                circle(r = raio_borda, $fn = 32);
            translate([R - raio_borda, -espessura/2 + raio_borda])
                circle(r = raio_borda, $fn = 32);
        }
}

// Relevo da frente (sobe a partir da face superior)
module detalhe_frente() {
    translate([0, 0, espessura/2 - eps])
        linear_extrude(relevo + eps) frente2d();
}

// Relevo do verso: desce a partir da face inferior. O giro e em torno de Y
// (eixo vertical da peca pendurada), entao ao virar o chaveiro o furo continua
// em cima e o nome aparece na leitura correta.
module detalhe_verso() {
    translate([0, 0, -espessura/2 + eps]) rotate([0, 180, 0])
        linear_extrude(relevo + eps) verso2d();
}

module furo() {
    translate([0, furo_y, 0])
        cylinder(h = espessura + 4*relevo + 4, r = furo_r,
                 center = true, $fn = 96);
}

// -----------------------------------------------------------------------------
//  Montagem
// -----------------------------------------------------------------------------
module corpo() {
    if (modo_verso == "baixo")
        difference() { disco(); detalhe_verso(); }
    else
        disco();
}

module chaveiro() {
    if (parte == "corpo")
        difference() { corpo(); furo(); }
    else if (parte == "detalhe")
        difference() {
            union() {
                detalhe_frente();
                if (modo_verso != "baixo") detalhe_verso();
            }
            furo();
        }
    else
        difference() {
            union() {
                corpo();
                detalhe_frente();
                if (modo_verso != "baixo") detalhe_verso();
            }
            furo();
        }
}

chaveiro();
