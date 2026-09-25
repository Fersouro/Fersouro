// =============================================================================
//  Marca BageVet para o cabo do 22_scoop (Parametric Paw Pet Food Scoop).
//  Substitui o nome do pet que vinha em relevo no cabo.
//  Origem: centro do bloco da marca, base em z = 0, leitura no sentido +X.
//
//  O cabo deste modelo e uma tira plana de 18 mm de largura, entao a marca cabe
//  inteira: coroa de seis patinhas, "bagevet" com a cruz e "medicina animal"
//  alinhado a direita embaixo. O relevo e de 0,8 mm, o mesmo das pastilhas da
//  concha - o nome original tinha dois degraus (plinto + letra, 1,6 mm no
//  total), mas repetir o plinto aqui engordaria o desenho em 0,45 mm por lado
//  e fecharia os vaos entre os dedinhos e entre as letras.
// =============================================================================
use <../chaveiro-3d/chaveiro_bagevet.scad>

relevo         = 0.82;   // 0,80 mm acima do cabo + 0,02 mm enterrado nele

/* [Coroa de patinhas] ---------------------------------------------------- */
coroa_diam     = 13.40;  // diametro externo da coroa = altura da marca
n_patas        = 6;
pata_tam       = 4.20;   // mesma largura ja conferida no chaveiro
coroa_giro     = 0;

/* [Texto] ---------------------------------------------------------------- */
texto_marca    = "bagévet";
texto_sub      = "medicina animal";
fonte_marca    = "URW Gothic:style=Book";
fonte_sub      = "URW Gothic:style=Demi";
alt_marca      = 8.40;   // altura do bloco, do 'b' ao pe do 'g'
alt_sub        = 2.60;   // subtitulo no menor tamanho que o bico 0,4 resolve
esp_marca      = 1.00;
escala_x_marca = 0.870;  // condensa ate a proporcao da arte
esp_sub        = 1.22;
engrossa_marca = 0.035;
engrossa_sub   = 0.025;

/* [Cruz] ----------------------------------------------------------------- */
cruz_tam       = 3.13;
cruz_esp       = 0.66;

/* [Posicoes] ------------------------------------------------------------- */
folga_coroa    =  3.20;  // da borda da coroa ate o 'b'
folga_cruz     =  0.95;  // do fim do 't' ate a cruz
marca_base_y   = -0.85;  // linha de base de "bagevet", a partir do centro
sub_base_y     = -5.95;  // linha de base do subtitulo
cruz_dy        =  4.34;  // centro da cruz acima da linha de base

/* [Medidas do proprio desenho] ------------------------------------------- */
// Conferidas rodando medir22.py; refaca a medicao se mexer nas cotas acima.
marca_larg     = 29.47;  // largura de "bagevet" na altura acima
centro_dx      = 18.644;  // centra a marca inteira na origem

module coroa2d() {
    raio = coroa_diam/2 - pata_tam * 0.51;
    for (i = [0 : n_patas - 1])
        rotate(coroa_giro + i * 360 / n_patas)
            translate([0, raio]) pata2d(pata_tam);
}

module texto_alinhado(txt, alt, fnt, espaco = 1, engrossa = 0, alinha = "left",
                      esc_x = 1) {
    offset(r = engrossa)
        scale([esc_x, 1])
            resize([0, alt], auto = true)
                text(txt, size = 10, font = fnt, spacing = espaco,
                     halign = alinha, valign = "baseline", $fn = 32);
}

module cruz2d() {
    square([cruz_tam, cruz_esp], center = true);
    square([cruz_esp, cruz_tam], center = true);
}

module marca2d() {
    x_texto = coroa_diam/2 + folga_coroa;          // inicio do "b"
    x_cruz  = x_texto + marca_larg + folga_cruz;   // inicio da cruz
    x_fim   = x_cruz + cruz_tam;                   // borda direita da marca

    translate([-centro_dx, 0]) {
        coroa2d();
        translate([x_texto, marca_base_y])
            texto_alinhado(texto_marca, alt_marca, fonte_marca,
                           esp_marca, engrossa_marca, "left", escala_x_marca);
        translate([x_cruz + cruz_tam/2, marca_base_y + cruz_dy]) cruz2d();
        translate([x_fim, sub_base_y])
            texto_alinhado(texto_sub, alt_sub, fonte_sub,
                           esp_sub, engrossa_sub, "right");
    }
}

linear_extrude(relevo) marca2d();
