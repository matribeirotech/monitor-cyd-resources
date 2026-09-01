// ============================================================================
//  User_Setup.h  -  TFT_eSPI para a CYD "2 USB"
//  ESP32-2432S028R com micro USB + USB-C  ->  controlador ST7789
//
//  COPIE este arquivo por cima de:
//     ~/Arduino/libraries/TFT_eSPI/User_Setup.h
//  (faca um backup do original antes)
//
//  Se as cores sairem trocadas (azul <-> vermelho), troque TFT_BGR por TFT_RGB.
//  Se a imagem sair em negativo, troque TFT_INVERSION_OFF por TFT_INVERSION_ON.
//  Algumas unidades desta mesma placa vem com ILI9341: nesse caso comente
//  ST7789_DRIVER e descomente ILI9341_2_DRIVER.
// ============================================================================

#define USER_SETUP_INFO "CYD 2USB - Mike Monitor"

#define ST7789_DRIVER
// #define ILI9341_2_DRIVER          // alternativa para as unidades com ILI9341

#define TFT_WIDTH  240
#define TFT_HEIGHT 320

#define TFT_RGB_ORDER TFT_BGR
#define TFT_INVERSION_OFF

// ---- pinos do display (barramento HSPI) ----
#define TFT_MISO 12
#define TFT_MOSI 13
#define TFT_SCLK 14
#define TFT_CS   15
#define TFT_DC    2
#define TFT_RST  -1

// ---- backlight ----
#define TFT_BL   21
#define TFT_BACKLIGHT_ON HIGH

// ---- touch XPT2046 ----
// Na CYD o touch fica num SPI separado (VSPI). O sketch usa a biblioteca
// XPT2046_Touchscreen com seu proprio SPIClass, entao TOUCH_CS fica desativado
// aqui de proposito. Nao habilite TOUCH_CS.
// pinos usados pelo sketch: CLK 25, MISO 39, MOSI 32, CS 33, IRQ 36

// ---- fontes ----
#define LOAD_GLCD
#define LOAD_FONT2
#define LOAD_FONT4
#define LOAD_FONT6
#define LOAD_FONT7
#define LOAD_FONT8
#define LOAD_GFXFF
#define SMOOTH_FONT

// ---- SPI ----
#define SPI_FREQUENCY       55000000
#define SPI_READ_FREQUENCY  20000000
#define SPI_TOUCH_FREQUENCY  2500000

#define USE_HSPI_PORT
