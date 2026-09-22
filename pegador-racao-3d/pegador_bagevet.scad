// =============================================================================
//  PEGADOR DE RACAO BAGEVET - concha em forma de pata + cabo em forma de osso
//  Unidades: milimetros. Concha centrada na origem, patinha apontando para +X,
//  cabo saindo para -X. Peca apoiada em z = 0 (imprime deitada, boca para cima).
//  Reaproveita a patinha e o ajuste de texto do modelo do chaveiro.
// =============================================================================

use <../chaveiro-3d/chaveiro_bagevet.scad>   // pata2d() e texto_fit()

/* [Dimensoes gerais] ----------------------------------------------------- */
comprimento_total = 190.0;  // ponta do cabo ate a ponta da pata
largura_max       = 85.0;   // largura da concha (dedos da pata)
concha_compr      = 90.0;   // comprimento da concha
prof_interna      = 35.0;   // profundidade interna da concha
fundo             = 3.0;    // espessura do fundo
parede            = 2.5;    // espessura da parede da concha

/* [Cabo] ----------------------------------------------------------------- */
cabo_compr        = 100.0;  // comprimento livre do cabo
cabo_largura      = 30.0;   // largura maxima (lobos do osso)
cabo_barra        = 20.0;   // largura da barra central do osso
cabo_espessura    = 12.0;   // espessura do cabo
cabo_entrada      = 25.0;   // quanto o cabo entra na concha (vira parede)
filete_junta      = 5.0;    // filete da juncao cabo/concha

/* [Acabamento] ----------------------------------------------------------- */
raio_canto        = 2.0;    // arredondamento dos cantos em planta
concha_fundir     = 12;    // fusao dos dedos na almofada (unidades da pata)
raio_topo         = 1.25;   // meia-cana no topo da parede (metade de 2.5)
chanfro_base      = 1.5;    // chanfro a 45 graus na base (imprimivel)
filete_interno    = 3.0;    // concordancia no fundo da cavidade

/* [Nervuras] ------------------------------------------------------------- */
nervura_esp       = 2.0;
nervura_saliencia = 3.5;
nervura_altura    = 16.0;
nervura_angulos   = [160, 180, 200];  // 0 = ponta da pata (traseira, junto ao cabo)

/* [Logo no cabo] --------------------------------------------------------- */
logo_diam         = 22.0;   // diametro da coroa de patinhas
logo_relevo       = 0.6;    // altura do relevo
logo_x            = -73.0;  // posicao ao longo do cabo
logo_patas        = 6;      // patinhas da coroa
logo_pata_tam     = 4.2;    // largura de cada patinha (mesma do chaveiro)
texto_marca       = "BageVet";
texto_sub         = "MEDICINA ANIMAL";
alt_marca         = 7.0;    // altura das letras de BageVet
alt_sub           = 3.0;    // altura das letras do subtitulo
esp_sub           = 1.05;   // espacejamento do subtitulo
texto_meio        = 20.5;   // metade da largura do texto mais largo

concha_desloc     = -3.14;    // ajuste fino para centrar a concha em x
/* [Painel colorido do cabo] ---------------------------------------------- */
painel_borda      = 2.5;    // largura da moldura na cor do corpo
painel_prof       = 0.6;    // rebaixo onde o painel encaixa (fica rente)

// "completo" = peca unica | "corpo" | "painel" | "logo" (impressao multicor)
parte             = "completo";

renderizar_peca   = true;   // false so para montagens coloridas externas
res               = 64;     // segmentos dos arcos
eps               = 0.01;

/* [Calculados] ----------------------------------------------------------- */
altura_concha = fundo + prof_interna;
x_junta       = -concha_compr / 2;              // traseira da concha
x_ponta       = x_junta - cabo_compr;           // ponta do cabo
lobo_r        = cabo_largura / 2;

// -----------------------------------------------------------------------------
//  Utilitarios 2D
// -----------------------------------------------------------------------------
// Arredonda cantos convexos e concavos com o mesmo raio, sem mudar o tamanho
module arredondar(r) {
    offset(r = r) offset(r = -2 * r) offset(r = r) children();
}

// Silhueta da concha: patinha deitada, apontando para +X
// Silhueta da concha: a patinha do chaveiro tem os dedos soltos da almofada;
// o fechamento morfologico (offset +f depois -f) une tudo num contorno unico,
// mantendo os lobos visiveis, com concordancias bem maiores que o raio minimo.
module concha2d() {
    translate([concha_desloc, 0])
        resize([concha_compr, largura_max])
            offset(r = -concha_fundir) offset(r = concha_fundir)
                rotate(-90) pata2d(100);
}

// Silhueta do cabo: osso, da ponta ate dentro da concha
module cabo2d() {
    arredondar(raio_canto) union() {
        for (s = [-1, 1]) {
            translate([x_ponta + lobo_r, s * (cabo_largura/2 - lobo_r)])
                circle(r = lobo_r, $fn = res);
            translate([x_junta - lobo_r * 1.6, s * (cabo_largura/2 - lobo_r)])
                circle(r = lobo_r, $fn = res);
        }
        translate([x_ponta + lobo_r, -cabo_barra/2])
            square([cabo_compr - lobo_r + cabo_entrada, cabo_barra]);
    }
}

// -----------------------------------------------------------------------------
//  Extrusao com chanfro na base e meia-cana no topo (sem overhang)
// -----------------------------------------------------------------------------
// Fatias empilhadas: hull() convexificaria a silhueta da pata, entao o
// chanfro e a meia-cana sao aproximados por degraus menores que uma camada.
module extrudar(h, r_topo = 0, chanfro = 0, passos = 12) {
    if (chanfro > 0)
        for (i = [0 : passos - 1])
            translate([0, 0, chanfro * i / passos])
                linear_extrude(chanfro / passos + eps)
                    offset(r = -chanfro * (1 - i / passos)) children();
    translate([0, 0, chanfro])
        linear_extrude(max(h - chanfro - r_topo, eps)) children();
    if (r_topo > 0)
        for (i = [0 : passos - 1]) {
            a = 90 * i / passos;
            a1 = 90 * (i + 1) / passos;
            z = h - r_topo + r_topo * sin(a);
            translate([0, 0, z])
                linear_extrude(r_topo * (sin(a1) - sin(a)) + eps)
                    offset(r = -r_topo * (1 - cos(a))) children();
        }
}

// -----------------------------------------------------------------------------
//  Cavidade da concha, com concordancia no fundo
// -----------------------------------------------------------------------------
module cavidade(passos = 12) {
    translate([0, 0, fundo]) {
        for (i = [0 : passos - 1]) {
            a  = 90 * i / passos;
            a1 = 90 * (i + 1) / passos;
            z  = filete_interno * (1 - cos(a));
            translate([0, 0, z])
                linear_extrude(filete_interno * (cos(a) - cos(a1)) + eps)
                    offset(r = -parede - filete_interno * (1 - sin(a))) concha2d();
        }
        translate([0, 0, filete_interno])
            linear_extrude(prof_interna - filete_interno + 10)
                offset(r = -parede) concha2d();
    }
}

// -----------------------------------------------------------------------------
//  Cabo: planta do osso limitada pelo perfil lateral (que traz o filete de 5 mm)
// -----------------------------------------------------------------------------
module perfil_lateral(passos = 10) {
    pts = concat(
        [[x_ponta - 1, 0], [x_junta + cabo_entrada, 0],
         [x_junta + cabo_entrada, altura_concha], [x_junta, altura_concha]],
        [for (i = [0 : passos])
            let (a = 90 * i / passos)
            [x_junta - filete_junta + filete_junta * cos(a),
             cabo_espessura + filete_junta - filete_junta * sin(a)]],
        [[x_ponta - 1, cabo_espessura]]);
    rotate([90, 0, 0]) translate([0, 0, -largura_max])
        linear_extrude(2 * largura_max) polygon(pts);
}

module cabo() {
    intersection() {
        extrudar(altura_concha, raio_topo, chanfro_base) cabo2d();
        perfil_lateral();
    }
}

// -----------------------------------------------------------------------------
//  Nervuras externas de reforco
// -----------------------------------------------------------------------------
// Aletas verticais na parede externa traseira, com saliencia decrescente para
// cima (nenhuma face pendente): reforcam a regiao da juncao com o cabo.
module nervuras(passos = 10) {
    for (a = nervura_angulos)
        intersection() {
            rotate(a - 90) translate([-nervura_esp/2, 0, 0])
                cube([nervura_esp, largura_max, nervura_altura]);
            union() {
                for (i = [0 : passos - 1])
                    translate([0, 0, nervura_altura * i / passos])
                        linear_extrude(nervura_altura / passos + eps)
                            offset(r = nervura_saliencia * (1 - i / passos)) concha2d();
            }
        }
}

// -----------------------------------------------------------------------------
//  Logo BageVet em alto relevo no cabo
// -----------------------------------------------------------------------------
// Painel raso no topo do cabo: recebe a segunda cor e serve de fundo para a logo
module painel2d() {
    intersection() {
        offset(r = -painel_borda) cabo2d();
        translate([x_ponta - 5, -cabo_largura])
            square([cabo_compr - filete_junta - 4, 2 * cabo_largura]);
    }
}

module painel_solido() {
    translate([0, 0, cabo_espessura - painel_prof])
        linear_extrude(painel_prof) painel2d();
}

// Composicao da marca no cabo: coroa de patinhas do lado da concha e, ao lado,
// as duas linhas de texto lendo ao longo do cabo (cabem nos 25 mm do painel).
module logo2d() {
    raio_coroa = logo_diam/2 - logo_pata_tam * 0.51;
    for (i = [0 : logo_patas - 1])
        rotate(i * 360 / logo_patas)
            translate([0, raio_coroa]) pata2d(logo_pata_tam);
    translate([-logo_diam/2 - 3 - texto_meio, -1.0])
        texto_fit(texto_marca, alt_marca);
    translate([-logo_diam/2 - 3 - texto_meio, -5.5])
        texto_fit(texto_sub, alt_sub, 1, esp_sub);
}

module logo_no_cabo() {
    translate([logo_x, 0, cabo_espessura - eps])
        linear_extrude(logo_relevo + eps) logo2d();
}

// -----------------------------------------------------------------------------
//  Montagem
// -----------------------------------------------------------------------------
module corpo_solido() {
    difference() {
        union() {
            extrudar(altura_concha, raio_topo, chanfro_base) concha2d();
            cabo();
            nervuras();
        }
        cavidade();
        painel_solido();          // rebaixo do painel
    }
}

module pegador() {
    if      (parte == "corpo")  corpo_solido();
    else if (parte == "painel") painel_solido();
    else if (parte == "logo")   logo_no_cabo();
    else if (parte == "cavidade")            // so para medir a capacidade
        intersection() {
            cavidade();
            translate([-200, -100, 0]) cube([400, 200, altura_concha]);
        }
    else union() { corpo_solido(); painel_solido(); logo_no_cabo(); }
}

if (renderizar_peca) pegador();
