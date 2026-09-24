// =============================================================================
//  Marca BageVet para o cabo do pegador de racao (Paw Scoop).
//  Substitui o nome do pet que vinha no painel rebaixado do cabo.
//  Origem: centro do bloco da marca, base em z = 0, leitura no sentido +X.
//  Reaproveita pata2d() e texto_fit() do chaveiro, para o desenho ser o mesmo.
// =============================================================================
use <../chaveiro-3d/chaveiro_bagevet.scad>

relevo        = 1.0;    // mesma espessura do texto original do modelo
coroa_diam    = 16.0;   // diametro da coroa de patinhas
n_patas       = 8;      // patinhas da coroa (igual ao chaveiro)
pata_tam      = 4.2;    // largura de cada patinha (>= 4.2 p/ bico 0,4)
coroa_giro    = 22.5;

texto_marca   = "BageVet";
texto_sub     = "MEDICINA ANIMAL";
alt_marca     = 5.6;    // altura das letras de BageVet
alt_sub       = 2.4;    // altura das letras do subtitulo
esp_marca     = 1.05;   // espacejamento de BageVet
esp_sub       = 1.22;   // espacejamento do subtitulo
engrossa_sub  = 0.04;   // engrossa o subtitulo (traco >= 0,5 mm)
marca_y       = 1.6;   // linha de base de BageVet
sub_y         = -4.6;   // linha de base do subtitulo
folga_coroa   =  2.6;   // espaco entre a coroa e o texto
// medidos no proprio desenho, para a composicao ficar centrada de verdade
coroa_larg    = 15.30;  // extensao real da coroa
texto_larg    = 35.85;  // extensao real do bloco de texto
texto_cx      = -0.137; // centro horizontal do bloco de texto
texto_cy      =  0.604; // centro vertical do bloco de texto

fonte         = "Liberation Sans:style=Bold";

module coroa2d() {
    raio = coroa_diam/2 - pata_tam * 0.51;
    for (i = [0 : n_patas - 1])
        rotate(coroa_giro + i * 360 / n_patas)
            translate([0, raio]) pata2d(pata_tam);
}

module bloco_texto2d() {
    translate([0, marca_y]) texto_fit(texto_marca, alt_marca, 1, esp_marca, 0, fonte);
    translate([0, sub_y])   texto_fit(texto_sub, alt_sub, 1, esp_sub,
                                      engrossa_sub, fonte);
}

module marca2d() {
    total = coroa_larg + folga_coroa + texto_larg;
    // coroa do lado da concha, texto ao lado, tudo centrado na origem
    translate([-total/2 + coroa_larg/2, 0]) coroa2d();
    translate([ total/2 - texto_larg/2 - texto_cx, -texto_cy]) bloco_texto2d();
}

linear_extrude(relevo) marca2d();
