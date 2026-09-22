// =============================================================================
//  CHAVEIRO BAGEVET - tag circular personalizavel para impressao 3D
//  Unidades: milimetros. Origem no centro do disco, furo para o +Y.
//  Frente (lado A, +Z): coroa de patinhas + "BageVet" + "MEDICINA ANIMAL"
//  Verso  (lado B, -Z): patinha + nome do pet (parametrico)
//
//  Uma cor .... uma peca so (parte = "completo").
//  Duas cores . quatro partes no mesmo sistema de coordenadas:
//               "corpo" e "nome" na cor 1 (verde), "casca" e "logo" na cor 2
//               (branco). Basta carregar as quatro no slicer e dar um filamento
//               a cada uma - elas ja vem encaixadas.
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
espessura         = 3.6;    // espessura do disco (18 camadas de 0,2 mm)
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
engrossar_sub     = 0.08;   // engrossa o subtitulo (traco de 0,52 mm)

/* [Verso - nome do pet] -------------------------------------------------- */
altura_nome       = 8.0;    // altura das letras do nome
nome_y            = -5.5;   // linha de base do nome
pata_verso        = 8.0;    // largura da patinha acima do nome
pata_verso_y      = 8.0;    // centro vertical da patinha do verso

/* [Cores e partes] ------------------------------------------------------- */
// Casca de outra cor no verso. 0 = sem casca (peca de uma cor so).
// Com casca > 0 o nome vira um embutido rente a superficie, na cor do corpo:
// imprime deitado, sem suporte nenhum, e fica igual a referencia.
casca_verso       = 0;
// Verso quando NAO ha casca: "relevo" (alto-relevo), "baixo" (gravado) ou
// "liso" (sem nada - corpo-base que serve para varios nomes)
modo_verso        = "relevo";
// "completo" = peca inteira | "corpo" | "casca" | "logo" | "nome" | "medalha"
parte             = "completo";

/* [Logo aplicada (cava + medalha)] --------------------------------------- */
// true = a frente recebe uma CAVA no lugar do relevo, e a logo vira uma
// medalha impressa em separado que encaixa nessa cava.
cava_logo         = false;
cava_profundidade = 1.0;    // profundidade da cava
cava_folga        = 0.15;   // folga lateral entre cava e medalha (por lado)
cava_folga_z      = 0.2;    // folga no fundo da cava (1 camada, para a cola)
medalha_margem    = 0.25;   // sobra da chapa da medalha alem da arte da logo
medalha_parede    = 1.2;    // material entre o recorte da medalha e o furo
// true = o verso tambem recebe cava, para a plaquinha do nome impressa a parte
cava_verso        = false;
cava_verso_prof   = 0.8;    // profundidade da cava do verso
plaquinha_diam    = 45.0;   // diametro da plaquinha do nome

/* [Fonte e qualidade] ---------------------------------------------------- */
fonte             = "Liberation Sans:style=Bold";
resolucao         = 180;    // segmentos do disco
renderizar_peca   = true;   // false so para montagens coloridas externas

/* [Calculos] ------------------------------------------------------------- */
R            = diametro / 2;
furo_r       = furo_diametro / 2;
furo_y       = R - furo_margem - furo_r;   // centro do furo
raio_coroa   = logo_diametro/2 - pata_coroa * 0.51;
verso_plano  = casca_verso > 0;            // nome embutido na casca
eps          = 0.01;
// Na peca unica os relevos entram 0.01 mm no corpo (evita faces coplanares na
// uniao). Exportando partes separadas por cor, elas saem exatamente encaixadas.
sobrepor     = (parte == "completo") ? eps : 0;

// -----------------------------------------------------------------------------
//  Patinha 2D (largura total = tam, altura ~= 0.94 * tam)
//  Proporcoes escolhidas para manter >= 0.45 mm de folga entre os dedinhos
//  quando a patinha tem 4.2 mm (menor uso do desenho) -> separa bem com bico 0.4.
// -----------------------------------------------------------------------------
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

// Espelhado em X: e o eixo pelo qual se vira um chaveiro pendurado, entao o
// furo continua em cima e o nome aparece na leitura correta.
module verso2d_espelhado() { mirror([1, 0, 0]) verso2d(); }

// -----------------------------------------------------------------------------
//  Solidos elementares
// -----------------------------------------------------------------------------
// Corpo do disco com borda arredondada (perfil convexo -> solido fechado)
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

// Relevo da frente: sobe a partir da face superior
module logo_solido() {
    translate([0, 0, espessura/2 - sobrepor])
        linear_extrude(relevo + sobrepor) frente2d();
}

// Contorno da medalha: disco da logo com um recorte em volta do furo da argola.
// folga > 0 aumenta a peca (usado para abrir a cava com folga de montagem).
module contorno_medalha2d(folga = 0) {
    difference() {
        circle(r = logo_diametro/2 + medalha_margem + folga, $fn = resolucao);
        translate([0, furo_y])
            circle(r = furo_r + medalha_parede - folga, $fn = 96);
    }
}

// Volume retirado da frente para receber a medalha
module cava_solida() {
    translate([0, 0, espessura/2 - cava_profundidade])
        linear_extrude(cava_profundidade + eps) contorno_medalha2d(cava_folga);
}

// Medalha da logo: chapa que entra na cava + relevo da marca por cima
module medalha() {
    union() {
        translate([0, 0, espessura/2 - cava_profundidade + cava_folga_z])
            linear_extrude(cava_profundidade - cava_folga_z) contorno_medalha2d(0);
        translate([0, 0, espessura/2 - eps])
            linear_extrude(relevo + eps) frente2d();
    }
}

// Contorno da plaquinha do nome (mesmo recorte em volta do furo)
module contorno_plaquinha2d(folga = 0) {
    difference() {
        circle(r = plaquinha_diam/2 + folga, $fn = resolucao);
        translate([0, furo_y])
            circle(r = furo_r + medalha_parede - folga, $fn = 96);
    }
}

// Volume retirado do verso para receber a plaquinha
module cava_verso_solida() {
    translate([0, 0, -espessura/2 - eps])
        linear_extrude(cava_verso_prof + eps) contorno_plaquinha2d(cava_folga);
}

// Nome do verso: embutido rente a face (com casca) ou em alto-relevo (sem casca)
module nome_solido() {
    if (verso_plano)
        translate([0, 0, -espessura/2])
            linear_extrude(casca_verso) verso2d_espelhado();
    else
        translate([0, 0, -espessura/2 - relevo])
            linear_extrude(relevo + sobrepor) verso2d_espelhado();
}

// Plaquinha do nome: chapa que entra na cava do verso + nome em relevo
module plaquinha() {
    union() {
        translate([0, 0, -espessura/2])
            linear_extrude(cava_verso_prof - cava_folga_z) contorno_plaquinha2d(0);
        nome_solido();
    }
}

// Volume a remover quando o verso e gravado em baixo-relevo
module nome_cavidade() {
    translate([0, 0, -espessura/2 - eps])
        linear_extrude(relevo + eps) verso2d_espelhado();
}

// Fatia que define a casca do verso (do fundo ate -espessura/2 + casca_verso)
module fatia_casca() {
    translate([-R - 2, -R - 2, -espessura/2 - relevo - 1])
        cube([2*R + 4, 2*R + 4, casca_verso + relevo + 1]);
}

module casca_solida() { intersection() { disco(); fatia_casca(); } }

module furo() {
    translate([0, furo_y, 0])
        cylinder(h = espessura + 4*relevo + 4, r = furo_r,
                 center = true, $fn = 96);
}

// -----------------------------------------------------------------------------
//  Corpo (cor 1), ja descontando casca / gravacao / embutido do nome
// -----------------------------------------------------------------------------
module corpo_solido() {
    difference() {
        union() {
            disco();
            if (!verso_plano && modo_verso == "relevo") nome_solido();
        }
        if (!verso_plano && modo_verso == "baixo") nome_cavidade();
        if (verso_plano) { fatia_casca(); nome_solido(); }
        if (cava_logo)    cava_solida();
        if (cava_verso)   cava_verso_solida();
    }
}

// -----------------------------------------------------------------------------
//  Partes exportaveis
// -----------------------------------------------------------------------------
module parte_corpo()    { difference() { corpo_solido(); furo(); } }
module parte_logo()     { difference() { logo_solido();  furo(); } }
module parte_nome()     { difference() { nome_solido();  furo(); } }
module parte_casca()    { difference() { casca_solida(); nome_solido(); furo(); } }
module parte_medalha()  { difference() { medalha();      furo(); } }
module parte_plaquinha(){ difference() { plaquinha();    furo(); } }
module parte_completa() {
    difference() {
        union() {
            corpo_solido();
            if (cava_logo) medalha(); else logo_solido();
            if (cava_verso) plaquinha();
            if (verso_plano) { casca_solida(); nome_solido(); }
        }
        furo();
    }
}

module chaveiro() {
    if      (parte == "corpo") parte_corpo();
    else if (parte == "logo")  parte_logo();
    else if (parte == "nome")  parte_nome();
    else if (parte == "casca") parte_casca();
    else if (parte == "medalha") parte_medalha();
    else if (parte == "plaquinha") parte_plaquinha();
    else                       parte_completa();
}

if (renderizar_peca) chaveiro();
