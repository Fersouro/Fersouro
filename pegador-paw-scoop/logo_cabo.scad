// =============================================================================
//  Marca BageVet para o cabo do pegador de racao (Paw Scoop).
//  Substitui o nome do pet que vinha no painel rebaixado do cabo.
//  Origem: centro do bloco da marca, base em z = 0, leitura no sentido +X.
//
//  Desenho conforme a arte atual: coroa de SEIS patinhas, "bagevet" em caixa
//  baixa com acento e a cruz, e "medicina animal" alinhado a direita embaixo.
//  As cotas marcadas "(arte)" saem da medicao da propria imagem da marca,
//  reduzida para os 15,30 mm de altura que a peca comporta.
//
//  A silhueta da patinha e a mesma do chaveiro (pata2d): e a versao ja
//  conferida para bico 0,4 mm, com folga entre os dedinhos acima de 0,45 mm.
// =============================================================================
use <../chaveiro-3d/chaveiro_bagevet.scad>

relevo         = 1.0;    // mesma espessura do texto original do modelo

/* [Coroa de patinhas] ---------------------------------------------------- */
coroa_diam     = 15.30;  // diametro externo da coroa = altura total da marca
n_patas        = 6;      // (arte) seis patinhas
pata_tam       = 4.80;   // largura de cada patinha
coroa_giro     = 0;      // giro da coroa

/* [Texto] ---------------------------------------------------------------- */
texto_marca    = "bagévet";
texto_sub      = "medicina animal";
fonte_marca    = "URW Gothic:style=Book";
fonte_sub      = "URW Gothic:style=Demi";
alt_marca      = 9.52;   // (arte) altura do bloco, do 'b' ao pe do 'g'
alt_sub        = 2.60;   // subtitulo: acima da proporcao da arte (1,7 mm), que
                         // com bico 0,4 sairia com traco fino demais
esp_marca      = 1.00;   // espacejamento de "bagevet"
escala_x_marca = 0.870;  // condensa "bagevet" ate a largura da arte
esp_sub        = 1.22;   // espacejamento do subtitulo
engrossa_marca = 0.04;   // engrossa o traco para o bico 0,4
engrossa_sub   = 0.025;

/* [Cruz] ----------------------------------------------------------------- */
cruz_tam       = 3.55;   // (arte) tamanho da cruz
cruz_esp       = 0.75;   // (arte) espessura dos bracos

/* [Posicoes, medidas na arte e reduzidas] -------------------------------- */
folga_coroa    =  4.22;  // da borda da coroa ate o 'b'
folga_cruz     =  1.05;  // do fim do 't' ate a cruz
marca_base_y   = -1.13;  // linha de base de "bagevet", a partir do centro
sub_base_y     = -6.35;  // linha de base do subtitulo
cruz_dy        =  4.92;  // centro da cruz acima da linha de base

/* [Medidas do proprio desenho, para a composicao fechar] ----------------- */
// Conferidas rodando medir.py; refaca a medicao se mexer nas cotas acima.
marca_larg     = 33.39;  // largura de "bagevet" na altura acima
centro_dx      = 21.412;  // deslocamento que centra a marca inteira na origem

module coroa2d() {
    raio = coroa_diam/2 - pata_tam * 0.51;
    for (i = [0 : n_patas - 1])
        rotate(coroa_giro + i * 360 / n_patas)
            translate([0, raio]) pata2d(pata_tam);
}

// Texto ajustado pela altura, ancorado na linha de base e no alinhamento
// pedido: e assim que a arte posiciona as duas linhas.
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
