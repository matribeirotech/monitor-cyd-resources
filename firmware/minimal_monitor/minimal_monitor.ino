/*
 * ============================================================================
 *  CYD HARDWARE MONITOR - No-Touch Edition (100% PC Controlled)
 *  Placa: ESP32-2432S028R "CYD" (Display ST7789 / ILI9341 320x240)
 *
 *  Arquitetura Atualizada:
 *    - Controle de Touch (XPT2046) 100% REMOVIDO para economizar RAM/CPU e
 *      eliminar leituras fantasmas / travamentos de tela touch danificada.
 *    - Controle Total transferido para o Agente Python no PC via USB Serial.
 *    - Suporte a protocolo JSON estruturado {"sys": {...}, "ui": {...}} e
 *      atualizacoes orientadas a eventos (event-driven).
 *    - Suporte a imagens estaticas (.JPG / .JPEG via TJpg_Decoder e .BMP
 *      nativo) e animadas (.GIF) carregadas diretamente do Cartao SD.
 *    - Paleta de cores RGB565 / HEX dinamica em tempo real e controle de
 *      brilho PWM (0-255) no pino 21.
 * ============================================================================
 */

#include <SPI.h>
#include <TFT_eSPI.h>
#include <ArduinoJson.h>
#include <SD.h>
#include <Preferences.h>
#include <AnimatedGIF.h>
#include <TJpg_Decoder.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include "mbedtls/base64.h"

#include "ui_theme.h"

// ------------------------------------------------ Wi-Fi & UDP Telemetry ----
// Credenciais padrao de fallback (podem ser definidas aqui OU configuradas
// dinamicamente pelo Painel Desktop Flet e salvas na memoria Flash NVS)
#ifndef WIFI_SSID_DEFAULT
#define WIFI_SSID_DEFAULT "SUA_REDE_WIFI"
#endif
#ifndef WIFI_PASS_DEFAULT
#define WIFI_PASS_DEFAULT "SUA_SENHA_WIFI"
#endif
#define UDP_PORT          8888

WiFiUDP   udp;
bool      udpListening      = false;
char      wifiSsid[64]      = WIFI_SSID_DEFAULT;
char      wifiPass[64]      = WIFI_PASS_DEFAULT;
char      udpBuf[2560];
uint32_t  lastWifiCheckMs   = 0;
bool      wifiWasConnected  = false;
IPAddress lastUdpRemoteIP;
uint16_t  lastUdpRemotePort = 0;
bool      replyViaUdp       = false; // true enquanto applyJson() processa um pacote vindo do UDP

// Responde SOMENTE pelo canal de origem do comando (USB ou UDP). Se respondesse pelos
// dois, o agente receberia cada TERM_LOG/ACK em duplicidade quando ambos estao ativos.
void sendReplyLine(const char* line) {
  if (!line || !line[0]) return;
  if (replyViaUdp && udpListening && WiFi.status() == WL_CONNECTED && lastUdpRemotePort > 0) {
    udp.beginPacket(lastUdpRemoteIP, lastUdpRemotePort);
    udp.write((const uint8_t*)line, strlen(line));
    udp.write((const uint8_t*)"\n", 1);
    udp.endPacket();
    return;
  }
  Serial.println(line);
}

// ------------------------------------------------------------- hardware ----
// NOTA: Inicializacao e leitura de Touch (XPT2046) foram totalmente removidas
// pois o controle agora e 100% realizado pelo Agente Python via Serial USB.

// LED RGB embutido (catodo comum invertido: LOW = aceso)
#define LED_R 4
#define LED_G 16
#define LED_B 17

// Backlight PWM
#define PIN_BL      21
#define BL_PWM_CH   2
#define BL_PWM_FREQ 5000
#define BL_PWM_RES  8

// Alto-falante embutido da CYD
#define PIN_SPK     26
#define SPK_PWM_CH  1
#define SOUND_ENABLED 1

// Botao fisico BOOT (GPIO 0) na traseira da placa (fallback fisico opcional)
#define PIN_BOOT 0

// Pinos do Cartao MicroSD na CYD (barramento VSPI)
#define SD_SCK  18
#define SD_MISO 19
#define SD_MOSI 23
#define SD_CS   5

// Rotacao da tela (1 = Landscape 320x240; use 3 se ficar invertido)
#define SCREEN_ROTATION 1

TFT_eSPI tft = TFT_eSPI();
SPIClass sdSPI(VSPI);
Preferences prefs;

// Decodificador de GIFs (mantido para retrocompatibilidade caso bg seja .gif)
AnimatedGIF gif;
File gifFile;
File uploadFile;
bool hasSD = false;
bool isGifPlaying = false;
bool initOrVerifySD();

// ------------------------------------------------------- estado da UI ------
uint16_t C_BG        = 0x0000;
uint16_t C_CARD      = 0x0841; // Cinza grafite muito escuro para contraste sobre fundos
uint16_t C_CARD_HI   = 0x03E0;
uint16_t C_TRACK     = 0x0120;
uint16_t C_TEXT      = 0x07E0;
uint16_t C_DIM       = 0x03E0;
uint16_t C_ACCENT    = 0x07E0;
uint16_t C_ACCENT_DK = 0x0000;
uint16_t C_OK        = 0x07E0;
uint16_t C_WARN      = 0xFFE0;
uint16_t C_HOT       = 0xF800;
uint16_t C_COOL      = 0x07E0;
uint16_t C_PINK      = 0xF81F;

uint8_t  currentScreen     = SCR_RESUMO;
uint16_t currentColor565   = 0x07E0; // Verde Matrix padrao
int      currentBrightness = 200;    // 0-255
char     bgImage[64]       = "none"; // Ex: "cyberpunk.jpg", "terminal", "z1p0", "none"
bool     hasBgBitmap       = false;  // true quando ha um JPG/BMP desenhado no fundo
bool     alarmEnabled      = false;

// Escurece uma cor RGB565 aplicando um fator (num/den)
static uint16_t scale565(uint16_t c, uint8_t num, uint8_t den) {
  uint16_t r = ((c >> 11) & 0x1F) * num / den;
  uint16_t g = ((c >> 5)  & 0x3F) * num / den;
  uint16_t b = (c         & 0x1F) * num / den;
  return (r << 11) | (g << 5) | b;
}

static uint16_t dim565(uint16_t c) {
  return scale565(c, 2, 5);
}

// Converte RGB888 (0-255) para RGB565
static uint16_t rgb888to565(uint8_t r, uint8_t g, uint8_t b) {
  return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
}

// Aplica qualquer cor RGB565 na interface inteira em tempo real
void applyColor565(uint16_t c) {
  if (c == 0) c = 0x07E0; // Evita texto invisivel preto sobre preto
  currentColor565 = c;

  uint16_t dim  = scale565(c, 1, 2);
  uint16_t dark = scale565(c, 1, 5);

  C_BG        = 0x0000;
  C_CARD      = 0x0841; // Fundo escuro dos cards para nitidez sobre imagens
  C_TEXT      = c;
  C_ACCENT    = c;
  C_OK        = c;
  C_COOL      = c;
  C_PINK      = c;
  C_DIM       = dim;
  C_CARD_HI   = dim;
  C_TRACK     = dark;
  C_ACCENT_DK = scale565(c, 1, 8);
  C_WARN      = 0xFD20; // Laranja alerta
  C_HOT       = 0xF800; // Vermelho critico
}

// Converte string HEX ("0x07E0", "#00FF00") ou indice legado (0-4) para RGB565
uint16_t parseColorVariant(JsonVariant v) {
  if (v.is<const char*>()) {
    const char* s = v.as<const char*>();
    if (!s || !s[0]) return currentColor565;

    // Formato Web Hex "#RRGGBB"
    if (s[0] == '#' && strlen(s) == 7) {
      uint32_t rgb = strtoul(s + 1, nullptr, 16);
      uint8_t r = (rgb >> 16) & 0xFF;
      uint8_t g = (rgb >> 8)  & 0xFF;
      uint8_t b =  rgb        & 0xFF;
      return rgb888to565(r, g, b);
    }
    // Formato RGB565 Hex "0x07E0" ou "07E0"
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
      return (uint16_t)strtoul(s + 2, nullptr, 16);
    }
    return (uint16_t)strtoul(s, nullptr, 16);
  }
  if (v.is<int>() || v.is<uint32_t>()) {
    uint32_t val = v.as<uint32_t>();
    // Retrocompatibilidade com indices 0..4
    if (val == 0) return 0x07E0; // Verde
    if (val == 1) return 0x07FF; // Ciano
    if (val == 2) return 0xFD20; // Laranja
    if (val == 3) return 0xF81F; // Magenta
    if (val == 4) return 0xF800; // Vermelho
    return (uint16_t)(val & 0xFFFF);
  }
  return currentColor565;
}

// --------------------------------------------------- Backlight PWM ---------
void initBacklight(int brt) {
  currentBrightness = constrain(brt, 5, 255);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN_BL, BL_PWM_FREQ, BL_PWM_RES);
  ledcWrite(PIN_BL, currentBrightness);
#else
  ledcSetup(BL_PWM_CH, BL_PWM_FREQ, BL_PWM_RES);
  ledcAttachPin(PIN_BL, BL_PWM_CH);
  ledcWrite(BL_PWM_CH, currentBrightness);
#endif
}

void setBacklight(int targetBrt, bool smooth = true) {
  targetBrt = constrain(targetBrt, 0, 255);
  if (!smooth || targetBrt == currentBrightness) {
    currentBrightness = targetBrt;
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWrite(PIN_BL, currentBrightness);
#else
    ledcWrite(BL_PWM_CH, currentBrightness);
#endif
    return;
  }

  // Transição suave de brilho (fade-in / fade-out) usando delay(2)
  int step = (targetBrt > currentBrightness) ? 1 : -1;
  while (currentBrightness != targetBrt) {
    currentBrightness += step;
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWrite(PIN_BL, currentBrightness);
#else
    ledcWrite(BL_PWM_CH, currentBrightness);
#endif
    delay(2);
  }
}

// ========================================== Carregamento de Imagens do SD ==
// Inicializa ou re-detecta o Cartao MicroSD dinamicamente (suporte a Hot-Plug)
bool initOrVerifySD() {
  if (hasSD) return true;

  pinMode(SD_CS, OUTPUT);
  digitalWrite(SD_CS, HIGH);
  delay(15);

  sdSPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);

  // Inicializa em 4 MHz (frequencia padrao estavel para microSD em modo SPI no ESP32)
  if (SD.begin(SD_CS, sdSPI, 4000000)) {
    hasSD = true;
    gif.begin(LITTLE_ENDIAN_PIXELS);
    Serial.println("SD_INIT:OK_4MHZ");
    return true;
  }

  // Fallback para 1 MHz caso haja interferencia ou trilhas longas
  if (SD.begin(SD_CS, sdSPI, 1000000)) {
    hasSD = true;
    gif.begin(LITTLE_ENDIAN_PIXELS);
    Serial.println("SD_INIT:OK_1MHZ");
    return true;
  }

  hasSD = false;
  uint8_t cType = SD.cardType();
  Serial.printf("SD_INIT:FAIL (cardType=%d)\n", cType);
  return false;
}

// Ativa efeito de vidro translucido (alpha-blend RGB565 em tempo real) sobre a capa de album na SCR_MEDIA
bool gMediaOverlayMode = false;

// Callback chamado pela biblioteca TJpg_Decoder para desenhar blocos no TFT
bool tft_output(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* bitmap) {
  if (y >= tft.height() || x >= tft.width()) return 1; // clip, mas retorna 1 para nao abortar a decodificacao!
  uint16_t origStride = w;
  uint16_t drawW = (x + w > tft.width())  ? (tft.width()  - x) : w;
  uint16_t drawH = (y + h > tft.height()) ? (tft.height() - y) : h;

  if (gMediaOverlayMode) {
    // Como TJpgDec.setSwapBytes(true) esta ativo, desfazemos o swap, aplicamos translucidez e refazemos o swap
    for (uint16_t row = 0; row < drawH; row++) {
      int16_t py = y + row;
      for (uint16_t col = 0; col < drawW; col++) {
        int16_t px = x + col;
        bool inHdr = (py < HDR_H);
        bool inHud = (py >= 136 && py < TICKER_Y && px >= 8 && px < (SCR_W - 8));
        if (inHdr || inHud) {
          uint16_t idx = row * origStride + col;
          uint16_t raw = bitmap[idx];
          uint16_t c565 = (raw >> 8) | (raw << 8);
          uint16_t r = (c565 >> 11) & 0x1F;
          uint16_t g = (c565 >> 5)  & 0x3F;
          uint16_t b =  c565        & 0x1F;
          // Mistura 22% da arte do album + vidro fumê escuro para nitidez absoluta do texto
          r = (r * 7) >> 5;
          g = ((g * 7) >> 5) + 2;
          b = ((b * 7) >> 5) + 1;
          if (r > 31) r = 31;
          if (g > 63) g = 63;
          if (b > 31) b = 31;
          uint16_t out565 = (r << 11) | (g << 5) | b;
          bitmap[idx] = (out565 >> 8) | (out565 << 8);
        }
      }
    }
  }

  if (drawW == origStride) {
    tft.pushImage(x, y, drawW, drawH, bitmap);
  } else {
    for (uint16_t row = 0; row < drawH; row++) {
      tft.pushImage(x, y + row, drawW, 1, bitmap + row * origStride);
    }
  }
  return 1;
}

// Resolve o caminho do arquivo no Cartao SD (procura em "/", "/bg/" e "/wallpapers/")
String resolveSdPath(const char* name) {
  if (!initOrVerifySD() || !name || !name[0]) return "";
  String base = String(name);
  if (base.startsWith("/")) base = base.substring(1);

  String candidates[3] = {
    "/" + base,
    "/bg/" + base,
    "/wallpapers/" + base
  };
  for (int i = 0; i < 3; i++) {
    if (SD.exists(candidates[i])) return candidates[i];
  }

  // Fallback: Busca ignorando diferencas de maiusculas/minusculas
  File root = SD.open("/");
  if (root && root.isDirectory()) {
    File f = root.openNextFile();
    while (f) {
      if (!f.isDirectory()) {
        String fn = String(f.name());
        int slash = fn.lastIndexOf('/');
        if (slash >= 0) fn = fn.substring(slash + 1);
        if (fn.equalsIgnoreCase(base)) {
          String matchPath = "/" + fn;
          f.close();
          root.close();
          return matchPath;
        }
      }
      f = root.openNextFile();
    }
    root.close();
  }
  return "";
}

// Leitor nativo de arquivos .BMP (16-bit ou 24-bit nao comprimido) direto do SD
static uint16_t read16(File &f) {
  uint16_t result;
  ((uint8_t *)&result)[0] = f.read();
  ((uint8_t *)&result)[1] = f.read();
  return result;
}

static uint32_t read32(File &f) {
  uint32_t result;
  ((uint8_t *)&result)[0] = f.read();
  ((uint8_t *)&result)[1] = f.read();
  ((uint8_t *)&result)[2] = f.read();
  ((uint8_t *)&result)[3] = f.read();
  return result;
}

bool drawSdBmp(const char *filename, int16_t x, int16_t y) {
  if ((x >= tft.width()) || (y >= tft.height())) return false;
  File bmpFS = SD.open(filename, FILE_READ);
  if (!bmpFS) return false;

  if (read16(bmpFS) != 0x4D42) { // Assinatura 'BM'
    bmpFS.close();
    return false;
  }

  read32(bmpFS); // File size
  read32(bmpFS); // Creator bytes
  uint32_t seekOffset = read32(bmpFS); // Inicio do bitmap
  read32(bmpFS); // Header size
  int32_t w = (int32_t)read32(bmpFS);
  int32_t h = (int32_t)read32(bmpFS);

  bool flip = true;
  if (h < 0) { h = -h; flip = false; }

  uint16_t planes = read16(bmpFS);
  uint16_t depth  = read16(bmpFS);
  uint32_t comp   = read32(bmpFS);

  if (planes != 1 || (depth != 24 && depth != 16) || comp != 0) {
    bmpFS.close();
    return false;
  }

  int16_t drawW = (x + w > tft.width())  ? (tft.width()  - x) : w;
  int16_t drawH = (y + h > tft.height()) ? (tft.height() - y) : h;

  uint32_t rowSize = ((w * depth / 8) + 3) & ~3;
  uint16_t lineBuffer[SCR_W];
  uint8_t  sdbuffer[SCR_W * 3];

  bool oldSwap = tft.getSwapBytes();
  tft.setSwapBytes(true);

  for (int16_t row = 0; row < drawH; row++) {
    uint32_t pos = seekOffset + (flip ? (h - 1 - row) : row) * rowSize;
    if (bmpFS.position() != pos) bmpFS.seek(pos);

    if (depth == 24) {
      bmpFS.read(sdbuffer, drawW * 3);
      for (int16_t col = 0; col < drawW; col++) {
        uint8_t b = sdbuffer[col * 3];
        uint8_t g = sdbuffer[col * 3 + 1];
        uint8_t r = sdbuffer[col * 3 + 2];
        lineBuffer[col] = tft.color565(r, g, b);
      }
    } else {
      bmpFS.read(sdbuffer, drawW * 2);
      for (int16_t col = 0; col < drawW; col++) {
        lineBuffer[col] = sdbuffer[col * 2] | (sdbuffer[col * 2 + 1] << 8);
      }
    }
    tft.pushImage(x, y + row, drawW, 1, lineBuffer);
  }

  tft.setSwapBytes(oldSwap);
  bmpFS.close();
  return true;
}

// Callbacks para GIF animado
void * GIFOpenFile(const char *fname, int32_t *pSize) {
  gifFile = SD.open(fname);
  if (gifFile) { *pSize = gifFile.size(); return (void *)&gifFile; }
  return NULL;
}
void GIFCloseFile(void *pHandle) { ((File *)pHandle)->close(); }
int32_t GIFReadFile(GIFFILE *pFile, uint8_t *pBuf, int32_t iLen) {
  File *f = static_cast<File *>(pFile->fHandle);
  int32_t bytes = f->read(pBuf, iLen);
  pFile->iPos = f->position();
  return bytes;
}
int32_t GIFSeekFile(GIFFILE *pFile, int32_t iPosition) {
  File *f = static_cast<File *>(pFile->fHandle);
  f->seek(iPosition);
  pFile->iPos = f->position();
  return pFile->iPos;
}

bool isBehindUI(int x, int y);

void GIFDraw(GIFDRAW *pDraw) {
  uint16_t *usPalette = pDraw->pPalette;
  int y = pDraw->iY + pDraw->y;
  if (y < HDR_H || y >= SCR_H) return;
  for (int x = 0; x < pDraw->iWidth; x++) {
    if (pDraw->ucHasTransparency && pDraw->pPixels[x] == pDraw->ucTransparent) continue;
    if (!isBehindUI(pDraw->iX + x, y)) {
      tft.drawPixel(pDraw->iX + x, y, usPalette[pDraw->pPixels[x]]);
    }
  }
}

// Lista arquivos de imagem do Cartao SD e envia para o PC via Serial
void listSdFilesToSerial() {
  if (!initOrVerifySD()) {
    sendReplyLine("SD_FILES:[]");
    return;
  }
  JsonDocument doc;
  JsonArray arr = doc.to<JsonArray>();

  const char* dirs[3] = {"/", "/bg", "/wallpapers"};
  for (int d = 0; d < 3; d++) {
    File root = SD.open(dirs[d]);
    if (!root || !root.isDirectory()) continue;
    File file = root.openNextFile();
    while (file) {
      if (!file.isDirectory()) {
        String fname = String(file.name());
        int slash = fname.lastIndexOf('/');
        if (slash >= 0) fname = fname.substring(slash + 1);
        String low = fname;
        low.toLowerCase();
        if (low.startsWith("_media")) {
          file = root.openNextFile();
          continue; // Oculta o cache interno de capa de album da lista de wallpapers
        }
        if (low.endsWith(".jpg") || low.endsWith(".jpeg") ||
            low.endsWith(".bmp") || low.endsWith(".gif")) {
          bool exists = false;
          for (JsonVariant v : arr) {
            if (fname.equalsIgnoreCase(v.as<const char*>())) {
              exists = true;
              break;
            }
          }
          if (!exists) arr.add(fname);
        }
      }
      file = root.openNextFile();
    }
    root.close();
  }
  String out = "SD_FILES:";
  serializeJson(doc, out);
  sendReplyLine(out.c_str());
}

// =========================================================== telemetria ====
struct Stats {
  float cpu = 0, cput = -1, cpuf = 0, load = 0;
  float gpu = -1, gput = -1, vram = -1, vramu = -1, vramt = -1, gpuw = -1;
  float ram = 0, ramu = 0, ramt = 0, swap = 0;
  float dsk = 0, dskf = 0, dr = 0, dw = 0;
  float rx = 0, tx = 0;
  int   cores = 0, fan = -1, gpufan = -1, fps = -1;
  int8_t hh = -1, mm = -1;
  bool  game = false;
  uint32_t up = 0;
  char host[16] = "PC-HOST";
  char top[16] = "";
  char gpuname[12] = "GPU";
} st;

// ======================================= Mercado Financeiro & Cripto =======
#define BTC_HIST_LEN 50
#define TICKER_H     18
#define TICKER_Y     (SCR_H - TICKER_H) // y = 222..239

struct MarketStats {
  bool  valid   = false;
  float usd     = 0.0f, usdc   = 0.0f; // USD/BRL e variacao 24h (%)
  float eur     = 0.0f, eurc   = 0.0f; // EUR/BRL e variacao 24h (%)
  float ibov    = 0.0f, ibovc  = 0.0f; // IBOVESPA pts e variacao (%)
  float sp500   = 0.0f, sp500c = 0.0f; // S&P 500 pts e variacao (%)
  float btc     = 0.0f, btcc   = 0.0f; // BTC/USD e variacao 24h (%)
  float btc_brl = 0.0f;                // BTC em Reais (R$)
  float eth     = 0.0f, ethc   = 0.0f; // ETH/USD e variacao 24h (%)
  float sol     = 0.0f, solc   = 0.0f; // SOL/USD e variacao 24h (%)
  float bnb     = 0.0f, bnbc   = 0.0f; // BNB/USD e variacao 24h (%)
  float xrp     = 0.0f, xrpc   = 0.0f; // XRP/USD e variacao 24h (%)
  uint8_t hBtc[BTC_HIST_LEN];          // Curva 24h normalizada (0..100) do Bitcoin
  uint8_t hBtcCount = 0;
} mkt;

// ======================================= Portfolio de Investimentos ========
struct PortfolioStats {
  bool    valid      = false;
  float   tot        = 0.0f;  // Saldo Total / Patrimonio consolidado (R$)
  float   pnl_pct    = 0.0f;  // Lucro/Prejuizo percentual (%)
  float   pnl_val    = 0.0f;  // Lucro/Prejuizo financeiro (R$)
  float   day_pct    = 0.0f;  // Variacao diaria 24h da carteira (%)
  uint8_t count      = 0;     // Quantidade total de ativos na carteira
  char    top3[3][10] = {"---", "---", "---"};
  float   top3c[3]    = {0.0f, 0.0f, 0.0f};
  float   top3w[3]    = {0.0f, 0.0f, 0.0f};
  bool    hasTop3c    = false;
  uint8_t topCount    = 0;
} portf;

static float lookupPortfolioAssetChange(int idx) {
  if (idx < 0 || idx >= 3) return 0.0f;
  if (portf.hasTop3c) return portf.top3c[idx];
  const char* s = portf.top3[idx];
  if (strcasecmp(s, "BTC") == 0)   return mkt.btcc;
  if (strcasecmp(s, "ETH") == 0)   return mkt.ethc;
  if (strcasecmp(s, "SOL") == 0)   return mkt.solc;
  if (strcasecmp(s, "BNB") == 0)   return mkt.bnbc;
  if (strcasecmp(s, "XRP") == 0)   return mkt.xrpc;
  if (strcasecmp(s, "USD") == 0)   return mkt.usdc;
  if (strcasecmp(s, "EUR") == 0)   return mkt.eurc;
  if (strcasecmp(s, "IBOV") == 0)  return mkt.ibovc;
  if (strcasecmp(s, "SP500") == 0) return mkt.sp500c;
  return 0.0f;
}

// ======================================= Pomodoro & Multimidia (Mod. 3) ====
struct PomodoroStats {
  bool     valid      = false;
  char     state[10]  = "WORK";   // "WORK", "BREAK", "LONG"
  bool     running    = false;
  int32_t  rem        = 1500;     // Segundos restantes sincronizados pelo PC
  int32_t  tot        = 1500;     // Duracao total do ciclo atual (s)
  uint16_t cycles     = 0;        // Quantidade de ciclos concluidos
  uint32_t syncMs     = 0;        // millis() do ultimo pacote recebido
  bool     chimeGuard = false;    // Evita tocar bipe duplicado no mesmo fim de ciclo
} pomo;

struct MediaStats {
  bool     valid         = false;
  bool     playing       = false;
  char     source[14]    = "NONE";  // "SPOTIFY", "YT MUSIC", "MEDIA", "NONE"
  char     title[48]     = "Nenhuma midia em reproducao";
  char     artist[40]    = "Abra o Spotify ou YouTube Music";
  char     album[36]     = "";
  int32_t  pos           = 0;       // Segundos decorridos
  int32_t  dur           = 0;       // Duracao total em segundos
  char     coverFile[32] = "_media_cov.jpg";
  char     coverId[16]   = "";
  bool     hasCover      = false;
  uint32_t syncMs        = 0;
} mediaSt;

// ======================================= Clima Regional, Data & Gemini Gems =
struct WeatherGemsStats {
  bool     valid        = false;
  char     city[24]     = "Votuporanga";
  char     dateShort[8] = "--/--";       // "07/11" exibido no Menu Superior ao lado da Hora
  char     dateFull[16] = "--/--/----";  // "07/11/2026" exibido na Tela 10
  char     dow[8]       = "---";         // "SAB", "DOM", "SEG"...
  float    temp         = 0.0f;          // Temperatura atual na regiao (C)
  float    feels        = 0.0f;          // Sensacao termica (C)
  float    tmin         = 0.0f;          // Minima do dia (C)
  float    tmax         = 0.0f;          // Maxima do dia (C)
  uint8_t  hum          = 0;             // Umidade relativa (%)
  float    wind         = 0.0f;          // Velocidade do vento (km/h)
  uint8_t  rainProb     = 0;             // Probabilidade de chuva (%)
  uint8_t  icon         = 0;             // 0=Sol, 1=Nublado, 2=Chuva, 3=Tempestade
  char     cond[24]     = "Sincronizando...";
  bool     alert        = false;         // Alerta de tempestade / clima severo ativo
  char     alertMsg[56] = "TEMPESTADE / CHUVA FORTE EM VOTUPORANGA!";
  // Retrocompatibilidade (Gems / Resumo)
  bool     gemValid     = false;
  char     gemTitle[34] = "News Feed";
  char     gemText[420] = "Aguardando manchetes do Cyber Deck News Feed...";
  char     gemTime[10]  = "--:--";
  char     gemModel[20] = "RSS-LIVE";
} wth;

// ======================================= Modulo 1: Feed de Noticias (SCR_NEWS) =
#define NEWS_QUEUE_MAX  8
#define NEWS_ROTATE_MS  15000UL
#define NEWS_SPR_W      296
#define NEWS_SPR_H      26

struct NewsItem {
  char topic[28];
  char headline[220];
  char source[24];
  char tm[10];
};

struct NewsFeedState {
  bool     valid                  = false;
  NewsItem queue[NEWS_QUEUE_MAX];
  uint8_t  count                  = 0;
  uint8_t  activeIdx              = 0;
  uint32_t lastRotateMs           = 0;
  int16_t  scrollX                = 0;
  int16_t  headlinePxW            = 0;
} newsSt;

TFT_eSprite newsSpr      = TFT_eSprite(&tft);
bool        newsSprReady = false;

// ======================================= Modulo 2: O Terminal CYD (SCR_TERMINAL)
#define TERM_MAX_LINES 14
#define TERM_COLS      48

struct TerminalState {
  char     lines[TERM_MAX_LINES][TERM_COLS + 4];
  uint8_t  count       = 0;
  uint32_t totalLogged = 0;
  bool     dirty       = true;
  char     lastCmd[40] = "ready";
} termSt;

static bool isMatrixRain = false;

// Sanitiza strings UTF-8 caso algum caractere acentuado escape para o TFT_eSPI
static void sanitizeAscii(char* dst, const char* src, size_t maxLen) {
  if (!dst || maxLen == 0) return;
  if (!src) { dst[0] = '\0'; return; }
  size_t j = 0;
  for (size_t i = 0; src[i] != '\0' && j < maxLen - 1; i++) {
    uint8_t c = (uint8_t)src[i];
    if (c >= 0x20 && c <= 0x7E) {
      dst[j++] = (char)c;
    } else if (c == 0xC3 && src[i + 1] != '\0') {
      // Mapeamento rapido Latin-1 comum em PT-BR (UTF-8 0xC3 xx)
      uint8_t n = (uint8_t)src[++i];
      char rep = 0;
      if      (n >= 0x80 && n <= 0x85) rep = 'A';
      else if (n == 0x87)              rep = 'C';
      else if (n >= 0x88 && n <= 0x8B) rep = 'E';
      else if (n >= 0x8C && n <= 0x8F) rep = 'I';
      else if (n >= 0x92 && n <= 0x96) rep = 'O';
      else if (n >= 0x99 && n <= 0x9C) rep = 'U';
      else if (n >= 0xA0 && n <= 0xA5) rep = 'a';
      else if (n == 0xA7)              rep = 'c';
      else if (n >= 0xA8 && n <= 0xAB) rep = 'e';
      else if (n >= 0xAC && n <= 0xAF) rep = 'i';
      else if (n >= 0xB2 && n <= 0xB6) rep = 'o';
      else if (n >= 0xB9 && n <= 0xBC) rep = 'u';
      if (rep) dst[j++] = rep;
    }
  }
  dst[j] = '\0';
}

static uint16_t getMediaAccentColor() {
  if (strcasecmp(mediaSt.source, "SPOTIFY") == 0)  return 0x1EE9; // Verde Oficial Spotify (#1DB954)
  if (strcasecmp(mediaSt.source, "YT MUSIC") == 0) return 0xF806; // Vermelho Oficial YouTube Music (#FF0033)
  return C_ACCENT;
}

bool        showTickerBar = true; // Exibe o letreiro infinito da bolsa no rodape das telas
TFT_eSprite tickerSpr     = TFT_eSprite(&tft);
bool        tickerSprReady = false;
int16_t     tickerScrollX  = 0;

bool     linked       = false;
uint32_t lastPacket   = 0;
uint32_t packets      = 0;
bool     needFullDraw = true;

// Historico para os graficos de hardware
uint8_t  hCpu[HIST], hGpu[HIST], hRam[HIST], hTmp[HIST];
uint16_t hPos    = 0;
bool     hFilled = false;

char     lineBuf[4096];
uint16_t lineLen = 0;

// Caches de desenho dos gauges circulares e boxes dinamicos (evita flicker)
int32_t  gGaugeEnd[2]   = {-999, -999};
uint16_t gGaugeCol[2]   = {0, 0};
int8_t   gLastPortfSign = -99;
int8_t   gLastPomoPhase = -99;
char     gLastMediaSig[128] = "";
bool     gLastMediaPlay = false;
int32_t  gLastMediaFillW = -1;
char     gLastWthSig[96] = "";
char     gLastGemSig[160] = "";
char     gLastNewsSig[240] = "";
int8_t   gLastGemPage = -1;
int8_t   gLastNewsRemainS = -1;
bool     gLastStormAlert = false;
uint8_t  gLastStormFlash = 255;

void resetDrawCache() {
  gGaugeEnd[0] = gGaugeEnd[1] = -999;
  gGaugeCol[0] = gGaugeCol[1] = 0;
  gLastPortfSign = -99;
  gLastPomoPhase = -99;
  gLastMediaSig[0] = '\0';
  gLastMediaFillW = -1;
  gLastWthSig[0] = '\0';
  gLastGemSig[0] = '\0';
  gLastNewsSig[0] = '\0';
  gLastGemPage = -1;
  gLastNewsRemainS = -1;
  gLastStormFlash = 255;
  termSt.dirty = true;
}

static void setLed(uint8_t r, uint8_t g, uint8_t b) {
  digitalWrite(LED_R, r ? LOW : HIGH);
  digitalWrite(LED_G, g ? LOW : HIGH);
  digitalWrite(LED_B, b ? LOW : HIGH);
}

// --------------------------------- Alertas Fisicos (Buzzer e LED RGB) -------
static bool spkInitialized = false;

static void buzzerOff() {
#if SOUND_ENABLED
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  if (spkInitialized) ledcWrite(PIN_SPK, 0);
#else
  if (spkInitialized) ledcWrite(SPK_PWM_CH, 0);
#endif
#endif
}

static void buzzerTone(uint32_t freq) {
#if SOUND_ENABLED
  if (freq == 0) {
    buzzerOff();
    return;
  }
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN_SPK, freq, 8);
  ledcWrite(PIN_SPK, 128);
#else
  ledcSetup(SPK_PWM_CH, freq, 8);
  ledcAttachPin(PIN_SPK, SPK_PWM_CH);
  ledcWrite(SPK_PWM_CH, 128);
#endif
  spkInitialized = true;
#endif
}

static void setLedFrom565(uint16_t c565) {
  uint8_t r = ((c565 >> 11) & 0x1F) > 8 ? 1 : 0;
  uint8_t g = ((c565 >> 5)  & 0x3F) > 16 ? 1 : 0;
  uint8_t b = (c565         & 0x1F) > 8 ? 1 : 0;
  setLed(r, g, b);
}

struct AlertEngineState {
  bool active = false;
  bool useBuzzer = false;
  uint16_t ledColor = 0xF800;
  uint8_t pattern = 1;       // 1=Info (1 bipe), 2=Aviso (2 bipes), 3=Critico (3 bipes)
  uint8_t currentStep = 0;
  uint32_t stepEndTime = 0;
};

static AlertEngineState alertEngine;

void triggerAlert(bool buzzer, uint16_t ledCol, uint8_t pat) {
  alertEngine.active = true;
  alertEngine.useBuzzer = buzzer;
  alertEngine.ledColor = ledCol;
  alertEngine.pattern = (pat < 1) ? 1 : (pat > 3 ? 3 : pat);
  alertEngine.currentStep = 0;
  alertEngine.stepEndTime = 0;
}

void pumpAlerts() {
  if (!alertEngine.active) return;

  uint32_t now = millis();
  if (now < alertEngine.stepEndTime) return;

  uint8_t maxSteps = 2; // p=1 -> 2 passos (ON, OFF)
  if (alertEngine.pattern == 2) maxSteps = 4; // ON, OFF, ON, OFF
  else if (alertEngine.pattern == 3) maxSteps = 6; // ON, OFF, ON, OFF, ON, OFF

  if (alertEngine.currentStep >= maxSteps) {
    buzzerOff();
    setLed(0, 0, 0);
    alertEngine.active = false;
    return;
  }

  bool isOn = (alertEngine.currentStep % 2 == 0);
  uint32_t dur = 100;
  uint32_t freq = 2400;

  if (alertEngine.pattern == 1) {
    dur = isOn ? 90 : 100;
    freq = 2400;
  } else if (alertEngine.pattern == 2) {
    dur = isOn ? 100 : 80;
    freq = 2200;
  } else {
    dur = isOn ? 120 : 70;
    freq = (alertEngine.currentStep == 4) ? 3000 : 2800;
  }

  if (isOn) {
    if (alertEngine.useBuzzer) buzzerTone(freq);
    setLedFrom565(alertEngine.ledColor);
  } else {
    buzzerOff();
    setLed(0, 0, 0);
  }

  alertEngine.stepEndTime = now + dur;
  alertEngine.currentStep++;
}

static float maxTemp() {
  float t = st.cput;
  if (st.gput > t) t = st.gput;
  return t;
}

static void fmtUptime(uint32_t s, char *out, size_t n) {
  uint32_t d = s / 86400, h = (s % 86400) / 3600, m = (s % 3600) / 60;
  if (d > 0) snprintf(out, n, "%lud %02luh", (unsigned long)d, (unsigned long)h);
  else       snprintf(out, n, "%02lu:%02lu", (unsigned long)h, (unsigned long)m);
}

// ========================================== Fundos Procedural & SD Card ====
const uint8_t leaf_sprite[] PROGMEM = {
  0b00010000, 0b01010100, 0b01010100, 0b11111110,
  0b01111100, 0b00111000, 0b00010000, 0b00010000
};

void drawTerminalDecor() {
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(scale565(C_ACCENT, 1, 3), C_BG);
  tft.drawString("root@cyd:~# telemetry --watch", 8, HDR_H + 4, 1);
  tft.drawString("usb0: link_up 115200bps [JSON_V2]", 8, TICKER_Y - 10, 1);
}

void drawZ1p0Decor() {
  for (int i = 0; i < 28; i++) {
    int x = (i * 37 + 13) % (SCR_W - 16) + 4;
    int y = HDR_H + 4 + ((i * 53 + 7) % (TICKER_Y - HDR_H - 12));
    tft.drawBitmap(x, y, leaf_sprite, 8, 8, scale565(C_ACCENT, 1, 3));
  }
}

// Renderiza o fundo de tela configurado em `bgImage`
void renderBackground() {
  if (isGifPlaying) {
    gif.close();
    isGifPlaying = false;
  }
  hasBgBitmap = false;

  String bg = String(bgImage);
  bg.trim();
  String bgLow = bg;
  bgLow.toLowerCase();

  if (bgLow == "" || bgLow == "none" || bgLow == "dark" || bgLow == "padrao") {
    tft.fillScreen(C_BG);
    // Grade sutil cyberpunk ao fundo
    uint16_t gridCol = scale565(C_ACCENT, 1, 9);
    for (int x = 0; x < SCR_W; x += 32) tft.drawFastVLine(x, HDR_H, TICKER_Y - HDR_H, gridCol);
    for (int y = HDR_H; y < TICKER_Y; y += 32) tft.drawFastHLine(0, y, SCR_W, gridCol);
    return;
  }

  if (bgLow == "terminal") {
    tft.fillScreen(C_BG);
    drawTerminalDecor();
    return;
  }

  if (bgLow == "z1p0") {
    tft.fillScreen(C_BG);
    drawZ1p0Decor();
    return;
  }

  // Caso contrario, e um arquivo no Cartao SD (.jpg, .jpeg, .bmp, .gif)
  if (!initOrVerifySD()) {
    tft.fillScreen(C_BG);
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(C_HOT, C_BG);
    tft.drawString("CARTAO SD NAO DETECTADO", SCR_W / 2, 60, 2);
    tft.setTextColor(C_TEXT, C_BG);
    tft.drawString("Insira o MicroSD na CYD", SCR_W / 2, 85, 2);
    tft.setTextColor(C_DIM, C_BG);
    tft.drawString("Formato obrigatorio: FAT32", SCR_W / 2, 105, 1);
    tft.drawString("Pressione 'Ler SD' no Agente do PC", SCR_W / 2, 125, 1);
    return;
  }

  String path = resolveSdPath(bg.c_str());
  if (path.length() == 0) {
    tft.fillScreen(C_BG);
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(C_WARN, C_BG);
    char buf[64];
    snprintf(buf, sizeof(buf), "Imagem '%s'", bg.c_str());
    tft.drawString(buf, SCR_W / 2, 60, 2);
    tft.drawString("nao encontrada no Cartao SD", SCR_W / 2, 82, 2);
    tft.setTextColor(C_TEXT, C_BG);
    tft.drawString("Copie para a raiz do cartao ou", SCR_W / 2, 105, 1);
    tft.drawString("use o botao 'Enviar Imagem' no PC", SCR_W / 2, 120, 1);
    return;
  }

  if (bgLow.endsWith(".jpg") || bgLow.endsWith(".jpeg")) {
    JRESULT res = TJpgDec.drawSdJpg(0, 0, path.c_str());
    if (res == JDR_OK || res == JDR_INTR) {
      hasBgBitmap = true;
    } else {
      Serial.printf("JPG_ERR:%d\n", res);
      tft.fillScreen(C_BG);
      tft.setTextDatum(MC_DATUM);
      tft.setTextColor(C_WARN, C_BG);
      char buf[64];
      snprintf(buf, sizeof(buf), "Erro ao decodificar JPG (%d)", res);
      tft.drawString(buf, SCR_W / 2, 70, 2);
      tft.drawString(bg.c_str(), SCR_W / 2, 95, 2);
    }
  } else if (bgLow.endsWith(".bmp")) {
    if (drawSdBmp(path.c_str(), 0, 0)) {
      hasBgBitmap = true;
    } else {
      tft.fillScreen(C_BG);
    }
  } else if (bgLow.endsWith(".gif")) {
    tft.fillScreen(C_BG);
    if (gif.open(path.c_str(), GIFOpenFile, GIFCloseFile, GIFReadFile, GIFSeekFile, GIFDraw)) {
      isGifPlaying = true;
    }
  } else {
    tft.fillScreen(C_BG);
  }
}

// Protege os cards da UI caso um GIF esteja rodando ao fundo
bool isBehindUI(int x, int y) {
  if (y < HDR_H || y >= TICKER_Y) return true;
  if (currentScreen == SCR_WALLPAPER) {
    return (y >= TICKER_Y - 54);
  }
  return true;
}

// ======================================= Componentes Graficos Modernos =====
void drawHeader() {
  tft.fillRect(0, 0, SCR_W, HDR_H - 2, C_ACCENT_DK);
  tft.fillRect(0, HDR_H - 2, SCR_W, 2, C_ACCENT);

  // Icone moderno de terminal/sistema
  tft.fillRoundRect(4, 4, 14, 14, 3, C_ACCENT);
  tft.fillRoundRect(6, 6, 10, 10, 2, C_ACCENT_DK);
  tft.drawPixel(9, 10, C_ACCENT);
  tft.drawPixel(10, 11, C_ACCENT);
  tft.drawPixel(9, 12, C_ACCENT);
  tft.drawFastHLine(11, 13, 3, C_ACCENT);

  // Titulo compacto da tela atual a esquerda (x = 21..96)
  const char* scrTitle = "RESUMO";
  if      (currentScreen == SCR_CPU_RAM)      scrTitle = "sys.mon_";
  else if (currentScreen == SCR_CPU_RAM_DUAL) scrTitle = "CPU+RAM";
  else if (currentScreen == SCR_GPU_FOCUS)    scrTitle = "GPU FOCUS";
  else if (currentScreen == SCR_GRAPH)        scrTitle = "4x GRAF";
  else if (currentScreen == SCR_WALLPAPER)    scrTitle = "WALLPAPER";
  else if (currentScreen == SCR_MARKET)       scrTitle = "MERCADO";
  else if (currentScreen == SCR_PORTFOLIO)    scrTitle = "PORTFOLIO";
  else if (currentScreen == SCR_POMODORO)     scrTitle = "POMODORO";
  else if (currentScreen == SCR_MEDIA)        scrTitle = "PLAYER";
  else if (currentScreen == SCR_NEWS)         scrTitle = "NEWS FEED";
  else if (currentScreen == SCR_TERMINAL)     scrTitle = "CYBER TERM";

  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(C_ACCENT, C_ACCENT_DK);
  tft.drawString(scrTitle, 21, (HDR_H - 2) / 2, 2);
}

// Renderiza no Menu Superior: [HORA (HH:MM)] + [DATA (DD/MM)] + [TEMP (°C)] + [REGIAO / STATUS]
void drawClock() {
  char timeDateBuf[20];
  bool hasTime = (linked && st.hh >= 0 && st.mm >= 0);
  bool hasDate = (wth.dateShort[0] != '\0' && wth.dateShort[0] != '-');

  if (hasTime && hasDate) {
    snprintf(timeDateBuf, sizeof(timeDateBuf), "%02d:%02d %s", st.hh, st.mm, wth.dateShort);
  } else if (hasTime) {
    snprintf(timeDateBuf, sizeof(timeDateBuf), "%02d:%02d", st.hh, st.mm);
  } else {
    snprintf(timeDateBuf, sizeof(timeDateBuf), "--:-- --/--");
  }

  // Limpa faixa central-direita do Header (x = 96..319) sem piscar
  tft.fillRect(96, 0, SCR_W - 96, HDR_H - 2, C_ACCENT_DK);

  // 1) Hora + Data Atual (x = 98)
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(C_TEXT, C_ACCENT_DK);
  int wTD = tft.drawString(timeDateBuf, 98, (HDR_H - 2) / 2, 2);

  // 2) Pill de Temperatura da Regiao ao lado da Data (ex: 29°C)
  int pillX = 98 + wTD + 5;
  int pillW = 42;
  uint16_t tCol = 0x07FF; // Ciano agradavel
  if (wth.valid) {
    if      (wth.alert || wth.temp >= 35.0f) tCol = 0xF800; // Vermelho calor extremo/alerta
    else if (wth.temp >= 30.0f)              tCol = 0xFD20; // Laranja quente
    else if (wth.temp >= 20.0f)              tCol = 0x07E0; // Verde confortavel
    else                                     tCol = 0x07FF; // Ciano frio
  } else {
    tCol = C_DIM;
  }

  uint16_t pillBg = scale565(tCol, 1, 5);
  tft.fillRoundRect(pillX, 3, pillW, 16, 3, pillBg);
  tft.drawRoundRect(pillX, 3, pillW, 16, 3, tCol);

  char tBuf[10];
  if (wth.valid) {
    snprintf(tBuf, sizeof(tBuf), "%.0fC", wth.temp);
  } else {
    snprintf(tBuf, sizeof(tBuf), "--C");
  }
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(wth.valid ? 0xFFFF : C_DIM, pillBg);
  tft.drawString(tBuf, pillX + pillW / 2, 11, 2);
  // Desenha bolinha de grau (°) antes do C se temperatura valida
  if (wth.valid) {
    int degX = pillX + pillW - 12;
    tft.drawCircle(degX, 6, 1, tCol);
  }

  // 3) Extremo Direito do Menu Superior: Alerta de Tempestade, Cidade ou Status da Tela
  tft.setTextDatum(MR_DATUM);
  if (wth.alert) {
    bool flashOn = ((millis() / 450) % 2 == 0);
    uint16_t aBg = flashOn ? 0xF800 : 0xFFE0;
    uint16_t aFg = flashOn ? 0xFFFF : 0x0000;
    tft.fillRoundRect(232, 3, 84, 16, 3, aBg);
    tft.setTextColor(aFg, aBg);
    tft.drawString("! ALERTA !", 312, 11, 1);
  } else if (currentScreen == SCR_POMODORO) {
    bool isBrk = (strcasecmp(pomo.state, "WORK") != 0);
    uint16_t pCol = !pomo.running ? 0xFD20 : (isBrk ? 0x07FF : 0x07E0);
    tft.setTextColor(pCol, C_ACCENT_DK);
    tft.drawString(!pomo.running ? "PAUSADO" : (isBrk ? "PAUSA" : "EM FOCO"), SCR_W - 4, 11, 1);
  } else if (currentScreen == SCR_MEDIA) {
    uint16_t mCol = getMediaAccentColor();
    tft.setTextColor(mCol, C_ACCENT_DK);
    const char* sLbl = (strcasecmp(mediaSt.source, "NONE") == 0) ? "PLAYER" : mediaSt.source;
    tft.drawString(sLbl, SCR_W - 4, 11, 1);
  } else if (wth.valid && wth.city[0]) {
    char cityShort[14];
    snprintf(cityShort, sizeof(cityShort), "%.11s", wth.city);
    for (int i = 0; cityShort[i]; i++) cityShort[i] = toupper((unsigned char)cityShort[i]);
    tft.setTextColor(C_ACCENT, C_ACCENT_DK);
    tft.drawString(cityShort, SCR_W - 4, 11, 1);
  } else {
    tft.setTextColor(linked ? C_TEXT : C_WARN, C_ACCENT_DK);
    tft.drawString(linked ? st.host : "OFFLINE", SCR_W - 4, 11, 1);
  }
}

// Banner de Emergencia / Aviso de Tempestade na Tela da Placa CYD
void drawStormAlertBanner() {
  if (!wth.alert) {
    if (gLastStormAlert) {
      gLastStormAlert = false;
      gLastStormFlash = 255;
      needFullDraw = true; // Restaura a tela limpa quando o alerta de tempestade encerra
    }
    return;
  }
  gLastStormAlert = true;
  uint8_t flashPhase = (uint8_t)((millis() / 500) % 2);
  if (flashPhase == gLastStormFlash && !needFullDraw) return;
  gLastStormFlash = flashPhase;

  uint16_t bgCol = flashPhase ? 0xC800 : 0xFFE0; // Alterna Vermelho Intenso e Amarelo Alerta
  uint16_t fgCol = flashPhase ? 0xFFFF : 0x0000;
  uint16_t bdCol = flashPhase ? 0xFFE0 : 0xF800;

  const int by = HDR_H;
  const int bh = 18;
  tft.fillRect(0, by, SCR_W, bh, bgCol);
  tft.drawRect(0, by, SCR_W, bh, bdCol);

  // Icone de raio a esquerda e a direita
  tft.fillTriangle(12, by + 2, 7, by + 9, 12, by + 9, fgCol);
  tft.fillTriangle(10, by + 9, 15, by + 9, 9, by + 16, fgCol);

  char bannerTxt[58];
  snprintf(bannerTxt, sizeof(bannerTxt), "AVISO %s: %.34s", wth.city, wth.alertMsg);
  for (int i = 0; bannerTxt[i]; i++) bannerTxt[i] = toupper((unsigned char)bannerTxt[i]);

  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(fgCol, bgCol);
  tft.drawString(bannerTxt, SCR_W / 2, by + bh / 2, 1);
}

// ======================================= Letreiro Infinito (Ticker Tape) ===
// Desenha um item individual no sprite do Ticker Tape e devolve a largura ocupada (px)
int drawTickerSegment(int x, const char* sym, const char* priceStr, float chgPct) {
  int startX = x;
  char chgBuf[16];
  snprintf(chgBuf, sizeof(chgBuf), "%s%.2f%%", chgPct >= 0.0f ? "+" : "", chgPct);
  uint16_t chgCol = (chgPct >= 0.0f) ? 0x07E0 : 0xF800; // Verde alta / Vermelho baixa

  tickerSpr.setTextDatum(ML_DATUM);
  // Simbolo em destaque
  tickerSpr.setTextColor(C_ACCENT, 0x0421);
  int wSym = tickerSpr.drawString(sym, x, 10, 2);
  x += wSym + 4;

  // Preco em Branco Brilhante
  tickerSpr.setTextColor(0xFFFF, 0x0421);
  int wPrc = tickerSpr.drawString(priceStr, x, 10, 2);
  x += wPrc + 4;

  // Variacao percentual colorida
  tickerSpr.setTextColor(chgCol, 0x0421);
  int wChg = tickerSpr.drawString(chgBuf, x, 10, 2);
  x += wChg + 10;

  // Separador estilo bolsa
  tickerSpr.fillCircle(x, 9, 2, C_DIM);
  x += 12;

  return x - startX;
}

// Renderiza uma passagem completa de todos os ativos financeiros a partir de `baseX`
int drawFullTickerCycle(int baseX) {
  int x = baseX;
  char pBuf[64];

  // 0) Se houver Alerta de Tempestade ativo na regiao, destaca em vermelho/amarelo no inicio do letreiro!
  if (wth.alert) {
    tickerSpr.setTextDatum(ML_DATUM);
    tickerSpr.setTextColor(0xFFE0, 0x0421);
    int wA = tickerSpr.drawString("[! ALERTA CLIMA !] ", x, 10, 2);
    x += wA;
    snprintf(pBuf, sizeof(pBuf), "%s: %s (%.0fC | Chuva %u%%)   ", wth.city, wth.alertMsg, wth.temp, (unsigned)wth.rainProb);
    tickerSpr.setTextColor(0xF800, 0x0421);
    x += tickerSpr.drawString(pBuf, x, 10, 2) + 12;
  } else if (wth.valid) {
    // Clima da regiao configurada (ex: VOTUPORANGA 29.4C)
    tickerSpr.setTextDatum(ML_DATUM);
    tickerSpr.setTextColor(0x07FF, 0x0421);
    x += tickerSpr.drawString(wth.city, x, 10, 2) + 4;
    snprintf(pBuf, sizeof(pBuf), "%.1fC (%s)", wth.temp, wth.cond);
    tickerSpr.setTextColor(0xFFFF, 0x0421);
    x += tickerSpr.drawString(pBuf, x, 10, 2) + 10;
    tickerSpr.fillCircle(x, 9, 2, C_DIM);
    x += 12;
  }

  if (!mkt.valid) {
    tickerSpr.setTextDatum(ML_DATUM);
    tickerSpr.setTextColor(C_TEXT, 0x0421);
    int w = tickerSpr.drawString("Sincronizando cotacoes em tempo real (USD/BRL, EUR/BRL, BTC, ETH, SOL, BNB, XRP, IBOV, S&P500)...   ", x, 10, 2);
    return max((x - baseX) + w, 320);
  }

  // 1) Dolar (USD/BRL)
  snprintf(pBuf, sizeof(pBuf), "R$%.2f", mkt.usd);
  x += drawTickerSegment(x, "USD", pBuf, mkt.usdc);

  // 2) Euro (EUR/BRL)
  snprintf(pBuf, sizeof(pBuf), "R$%.2f", mkt.eur);
  x += drawTickerSegment(x, "EUR", pBuf, mkt.eurc);

  // 3) Bitcoin em USD + BRL
  if (mkt.btc_brl > 0) snprintf(pBuf, sizeof(pBuf), "$%.0f (R$%.0fk)", mkt.btc, mkt.btc_brl / 1000.0f);
  else                 snprintf(pBuf, sizeof(pBuf), "$%.0f", mkt.btc);
  x += drawTickerSegment(x, "BTC", pBuf, mkt.btcc);

  // 4) Ethereum (ETH/USD)
  snprintf(pBuf, sizeof(pBuf), "$%.0f", mkt.eth);
  x += drawTickerSegment(x, "ETH", pBuf, mkt.ethc);

  // 5) Solana (SOL/USD)
  snprintf(pBuf, sizeof(pBuf), "$%.2f", mkt.sol);
  x += drawTickerSegment(x, "SOL", pBuf, mkt.solc);

  // 6) BNB (BNB/USD)
  snprintf(pBuf, sizeof(pBuf), "$%.1f", mkt.bnb);
  x += drawTickerSegment(x, "BNB", pBuf, mkt.bnbc);

  // 7) XRP (XRP/USD)
  snprintf(pBuf, sizeof(pBuf), "$%.2f", mkt.xrp);
  x += drawTickerSegment(x, "XRP", pBuf, mkt.xrpc);

  // 8) IBOVESPA (B3)
  if (mkt.ibov > 0) {
    snprintf(pBuf, sizeof(pBuf), "%.1fk pts", mkt.ibov / 1000.0f);
    x += drawTickerSegment(x, "IBOV", pBuf, mkt.ibovc);
  }

  // 9) S&P 500
  if (mkt.sp500 > 0) {
    snprintf(pBuf, sizeof(pBuf), "%.0f pts", mkt.sp500);
    x += drawTickerSegment(x, "S&P500", pBuf, mkt.sp500c);
  }

  // Se estiver nas telas financeiras (Mercado ou Portfolio), tambem mostra CPU/RAM no ticker!
  if ((currentScreen == SCR_MARKET || currentScreen == SCR_PORTFOLIO) && linked) {
    snprintf(pBuf, sizeof(pBuf), "CPU %.0f%% | RAM %.0f%%", st.cpu, st.ram);
    x += drawTickerSegment(x, "PC", pBuf, 0.0f);
  } else if (portf.valid && portf.tot > 0.0f) {
    snprintf(pBuf, sizeof(pBuf), "R$%.1fk", portf.tot / 1000.0f);
    x += drawTickerSegment(x, "CART", pBuf, portf.pnl_pct);
  }

  return x - baseX;
}

// Atualiza e empurra o Letreiro Infinito (Ticker Tape) sem piscar (Flicker-Free)
void updateTickerTape() {
  if (!showTickerBar || !tickerSprReady) return;

  tickerSpr.fillSprite(0x0421); // Fundo escuro elegante da fita da bolsa
  tickerSpr.drawFastHLine(0, 0, SCR_W, C_ACCENT);
  tickerSpr.drawFastHLine(0, 1, SCR_W, C_ACCENT_DK);

  const int badgeW = 38;
  int cycleW = drawFullTickerCycle(badgeW - tickerScrollX);
  if (cycleW < 100) cycleW = 320;

  // Desenha a segunda copia imediatamente atras para loop infinito continuo
  if (badgeW - tickerScrollX + cycleW < SCR_W) {
    drawFullTickerCycle(badgeW - tickerScrollX + cycleW);
  }

  tickerScrollX += 2; // Velocidade suave do letreiro
  if (tickerScrollX >= cycleW) {
    tickerScrollX = 0;
  }

  // Badge fixo a esquerda "[B3/$]" sobrepondo o inicio da fita
  tickerSpr.fillRect(0, 2, badgeW, TICKER_H - 2, C_ACCENT_DK);
  tickerSpr.fillRoundRect(2, 3, badgeW - 4, TICKER_H - 4, 3, C_ACCENT);
  tickerSpr.setTextDatum(MC_DATUM);
  tickerSpr.setTextColor(0x0000, C_ACCENT);
  tickerSpr.drawString("MKT", badgeW / 2, 10, 1);

  tickerSpr.pushSprite(0, TICKER_Y);
}

// Card moderno com cantos arredondados, preenchimento escuro para nitidez e detalhes de borda
void drawModernCard(int x, int y, int w, int h, const char *title) {
  tft.fillRoundRect(x, y, w, h, 6, C_CARD);
  tft.drawRoundRect(x, y, w, h, 6, C_CARD_HI);
  // Detalhe de destaque no topo do card
  tft.drawFastHLine(x + 8, y, w - 16, C_ACCENT);

  if (title && title[0]) {
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(C_ACCENT, C_CARD);
    tft.drawString(title, x + 8, y + 3, 1);
  }
}

// Barra de progresso estilizada com cantos arredondados e marcador de nivel
void drawModernBar(int x, int y, int w, int h, const char *label, float pct,
                   const char *rightText, float warn, float hot) {
  float v = constrain(pct, 0.0f, 100.0f);
  uint16_t col = levelColor(v, warn, hot);

  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString(label, x, y, 1);

  if (rightText) {
    tft.setTextDatum(TR_DATUM);
    tft.setTextColor(C_TEXT, C_CARD);
    tft.setTextPadding(72);
    tft.drawString(rightText, x + w, y, 1);
    tft.setTextPadding(0);
  }

  int barY = y + 9;
  int barH = max(5, h - 9);
  int radius = min(3, barH / 2);

  tft.fillRoundRect(x, barY, w, barH, radius, C_TRACK);
  tft.drawRoundRect(x, barY, w, barH, radius, C_CARD_HI);

  int fillW = (int)((w - 2) * v / 100.0f);
  if (fillW > 2) {
    tft.fillRoundRect(x + 1, barY + 1, fillW, barH - 2, max(1, radius - 1), col);
  }
}

// Barra de progresso segmentada estilo terminal moderno (como em main_screen.jpg)
void drawSegmentedBar(int x, int y, int w, int h, float pct, float warn, float hot) {
  float v = constrain(pct, 0.0f, 100.0f);
  uint16_t col = levelColor(v, warn, hot);
  tft.drawRoundRect(x, y, w, h, 2, C_ACCENT);

  const int segments = 14;
  int innerW = w - 4;
  int segW = (innerW / segments) - 1;
  int activeSegs = (int)((v / 100.0f) * segments + 0.5f);

  for (int i = 0; i < segments; i++) {
    int sx = x + 2 + i * (segW + 1);
    uint16_t sc = (i < activeSegs) ? col : C_TRACK;
    tft.fillRect(sx, y + 2, segW, h - 4, sc);
  }
}

// Gauge circular suave com cache anti-flicker
void drawGauge(int cx, int cy, int r, float value, const char *label,
               bool valid, float warn, float hot, int8_t slot) {
  const int ir = r - 7;
  const int A0 = 35, A1 = 325;
  float v = valid ? constrain(value, 0.0f, 100.0f) : 0.0f;
  int aEnd = A0 + (int)((A1 - A0) * v / 100.0f);
  uint16_t col = valid ? levelColor(v, warn, hot) : C_TRACK;

  bool changed = (slot < 0) || (gGaugeEnd[slot] != aEnd) || (gGaugeCol[slot] != col);
  if (changed) {
    if (aEnd > A0 + 1) tft.drawSmoothArc(cx, cy, r, ir, A0, aEnd, col, C_CARD, true);
    if (aEnd < A1 - 1) tft.drawSmoothArc(cx, cy, r, ir, aEnd, A1, C_TRACK, C_CARD, true);
    if (slot >= 0) { gGaugeEnd[slot] = aEnd; gGaugeCol[slot] = col; }
  }

  tft.setTextDatum(MC_DATUM);
  tft.setTextPadding(r + 10);
  tft.setTextColor(valid ? C_TEXT : C_DIM, C_CARD);
  char buf[12];
  if (valid) snprintf(buf, sizeof(buf), "%d%%", (int)(v + 0.5f));
  else       snprintf(buf, sizeof(buf), "--");
  tft.drawString(buf, cx, cy - 3, 4);
  tft.setTextPadding(0);

  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString(label, cx, cy + 14, 1);
}

// Grafico de linha com area sombreada (Sparkline individual)
void plotGraph(int x, int y, int w, int h, uint8_t *data, uint16_t col, const char *unit) {
  tft.fillRect(x, y, w, h, C_CARD);
  uint16_t area = scale565(col, 1, 4);

  for (int i = 1; i < 4; i++) {
    int gy = y + h * i / 4;
    for (int gx = x; gx < x + w; gx += 6) {
      tft.drawPixel(gx, gy, C_TRACK);
    }
  }
  for (int gx = x + w / 4; gx < x + w; gx += w / 4) {
    for (int gy = y; gy < y + h; gy += 6) {
      tft.drawPixel(gx, gy, C_TRACK);
    }
  }

  uint16_t n = hFilled ? HIST : hPos;
  if (n >= 2) {
    int prevY = -1;
    for (int i = 0; i < w && i < n; i++) {
      uint16_t idx = (hPos - 1 - i + HIST * 2) % HIST;
      int px = x + w - 1 - i;
      int v  = constrain((int)data[idx], 0, 100);
      int py = y + h - 1 - (h - 2) * v / 100;
      tft.drawFastVLine(px, py, y + h - py, area);
      if (prevY >= 0) tft.drawLine(px + 1, prevY, px, py, col);
      tft.drawPixel(px, py, col);
      prevY = py;
    }
  }

  if (unit && n > 0) {
    uint16_t last = (hPos - 1 + HIST) % HIST;
    char buf[14];
    snprintf(buf, sizeof(buf), "%d%s", data[last], unit);
    tft.setTextDatum(TR_DATUM);
    tft.setTextColor(col, C_CARD);
    tft.setTextPadding(44);
    tft.drawString(buf, x + w - 2, y - 10, 1);
    tft.setTextPadding(0);
  }
}

// Grafico DUPLO (Uso de CPU % + Uso de RAM % simultaneos no mesmo grafico!)
void plotDualCpuRamGraph(int x, int y, int w, int h) {
  tft.fillRect(x, y, w, h, C_CARD);

  uint16_t colCpu = C_ACCENT;
  uint16_t colRam = (abs((int)C_ACCENT - (int)0x07FF) < 200) ? 0xFD20 : 0x07FF;
  uint16_t areaCpu = scale565(colCpu, 1, 4);
  uint16_t areaRam = scale565(colRam, 1, 6);

  for (int i = 1; i < 4; i++) {
    int gy = y + h * i / 4;
    for (int gx = x; gx < x + w; gx += 6) tft.drawPixel(gx, gy, C_TRACK);
  }
  for (int i = 1; i < 6; i++) {
    int gx = x + w * i / 6;
    for (int gy = y; gy < y + h; gy += 6) tft.drawPixel(gx, gy, C_TRACK);
  }

  uint16_t n = hFilled ? HIST : hPos;
  if (n >= 2) {
    int prevCpuY = -1;
    int prevRamY = -1;
    for (int i = 0; i < w && i < n; i++) {
      uint16_t idx = (hPos - 1 - i + HIST * 2) % HIST;
      int px = x + w - 1 - i;

      int vCpu = constrain((int)hCpu[idx], 0, 100);
      int vRam = constrain((int)hRam[idx], 0, 100);

      int pyCpu = y + h - 1 - (h - 2) * vCpu / 100;
      int pyRam = y + h - 1 - (h - 2) * vRam / 100;

      tft.drawFastVLine(px, pyRam, y + h - pyRam, areaRam);
      tft.drawFastVLine(px, pyCpu, y + h - pyCpu, areaCpu);

      if (prevRamY >= 0) tft.drawLine(px + 1, prevRamY, px, pyRam, colRam);
      tft.drawPixel(px, pyRam, colRam);
      if (pyRam + 1 < y + h) tft.drawPixel(px, pyRam + 1, colRam);

      if (prevCpuY >= 0) tft.drawLine(px + 1, prevCpuY, px, pyCpu, colCpu);
      tft.drawPixel(px, pyCpu, colCpu);
      if (pyCpu + 1 < y + h) tft.drawPixel(px, pyCpu + 1, colCpu);

      prevCpuY = pyCpu;
      prevRamY = pyRam;
    }
  }

  char buf[24];
  tft.setTextDatum(TR_DATUM);
  tft.setTextPadding(64);
  tft.setTextColor(colCpu, C_CARD);
  snprintf(buf, sizeof(buf), "CPU:%.0f%%", st.cpu);
  tft.drawString(buf, x + w - 68, y - 10, 1);

  tft.setTextColor(colRam, C_CARD);
  snprintf(buf, sizeof(buf), "RAM:%.0f%%", st.ram);
  tft.drawString(buf, x + w - 2, y - 10, 1);
  tft.setTextPadding(0);
}

// =========================================== TELA 0: RESUMO (CPU + RAM) ====
void screenResumoStatic() {
  renderBackground();
  drawHeader();

  // Topo: Cards de CPU e RAM com Gauges circulares (y=26..122)
  drawModernCard(6,   HDR_H + 2, 150, 96, "CPU");
  drawModernCard(164, HDR_H + 2, 150, 96, "RAM");

  // Base: Cards de Temperatura/Disco e Rede/Sistema (y=125..220, acima do Ticker)
  drawModernCard(6,   HDR_H + 101, 150, 95, "TEMP & DISCO");
  drawModernCard(164, HDR_H + 101, 150, 95, "REDE & SISTEMA");
}

void screenResumoDynamic() {
  char buf[40];

  // ---- Card CPU (Esquerda) ----
  drawGauge(50, HDR_H + 53, 35, st.cpu, "CPU", linked, 65, 85, 0);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(54);
  if (st.cput > 0) {
    snprintf(buf, sizeof(buf), "%.0f C", st.cput);
    tft.setTextColor(levelColor(st.cput, T_TEMP_HOT, T_TEMP_MAX), C_CARD);
  } else {
    snprintf(buf, sizeof(buf), "-- C");
    tft.setTextColor(C_DIM, C_CARD);
  }
  tft.drawString(buf, 96, HDR_H + 22, 2);

  tft.setTextColor(C_TEXT, C_CARD);
  if (st.cpuf > 0) snprintf(buf, sizeof(buf), "%.1fGHz", st.cpuf / 1000.0f);
  else             snprintf(buf, sizeof(buf), "%d Cores", st.cores);
  tft.drawString(buf, 96, HDR_H + 45, 2);

  tft.setTextColor(C_DIM, C_CARD);
  snprintf(buf, sizeof(buf), "Temp/Clk");
  tft.drawString(buf, 96, HDR_H + 68, 1);
  tft.setTextPadding(0);

  // ---- Card RAM (Direita) ----
  drawGauge(208, HDR_H + 53, 35, st.ram, "RAM", linked, 75, 90, 1);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(54);
  tft.setTextColor(C_TEXT, C_CARD);
  if (st.ramt > 0) snprintf(buf, sizeof(buf), "%.1fG", st.ramu);
  else             snprintf(buf, sizeof(buf), "%.0f%%", st.ram);
  tft.drawString(buf, 254, HDR_H + 22, 2);

  tft.setTextColor(C_DIM, C_CARD);
  if (st.ramt > 0) snprintf(buf, sizeof(buf), "/ %.0fG", st.ramt);
  else             snprintf(buf, sizeof(buf), "Swp %.0f%%", st.swap);
  tft.drawString(buf, 254, HDR_H + 45, 2);

  snprintf(buf, sizeof(buf), "Usado/Tot");
  tft.drawString(buf, 254, HDR_H + 68, 1);
  tft.setTextPadding(0);

  // ---- Card Temp & Disco (Base Esquerda) ----
  snprintf(buf, sizeof(buf), "%.0fG livre", st.dskf);
  drawModernBar(14, HDR_H + 115, 134, 18, "DISCO", st.dsk, buf, 80, 92);

  float gpuVal = (st.gpu >= 0) ? st.gpu : 0.0f;
  if (st.fps >= 0)      snprintf(buf, sizeof(buf), "%d FPS", st.fps);
  else if (st.gput > 0) snprintf(buf, sizeof(buf), "%.0f%% (%.0fC)", gpuVal, st.gput);
  else                  snprintf(buf, sizeof(buf), "%.0f%%", gpuVal);
  drawModernBar(14, HDR_H + 142, 134, 18, "GPU", gpuVal, buf, 70, 90);

  if (st.vram >= 0) {
    snprintf(buf, sizeof(buf), "%.0f%%", st.vram);
    drawModernBar(14, HDR_H + 169, 134, 17, "VRAM", st.vram, buf, 75, 90);
  } else {
    snprintf(buf, sizeof(buf), "%.0f%%", st.swap);
    drawModernBar(14, HDR_H + 169, 134, 17, "SWAP", st.swap, buf, 60, 85);
  }

  // ---- Card Rede & Sistema (Base Direita) ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(132);
  tft.setTextColor(C_ACCENT, C_CARD);
  snprintf(buf, sizeof(buf), "DL: %.2f MB/s", st.rx);
  tft.drawString(buf, 174, HDR_H + 117, 2);

  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "UL: %.2f MB/s", st.tx);
  tft.drawString(buf, 174, HDR_H + 137, 2);

  char upStr[16];
  fmtUptime(st.up, upStr, sizeof(upStr));
  tft.setTextColor(C_DIM, C_CARD);
  snprintf(buf, sizeof(buf), "UP: %s", upStr);
  tft.drawString(buf, 174, HDR_H + 157, 2);

  if (st.top[0]) {
    snprintf(buf, sizeof(buf), "TOP: %s", st.top);
  } else {
    snprintf(buf, sizeof(buf), "BRI: %d%%", (currentBrightness * 100) / 255);
  }
  tft.drawString(buf, 174, HDR_H + 178, 1);
  tft.setTextPadding(0);
}

// =========================================== TELA 1: PAINEL CPU + RAM ======
// Coluna Esquerda: Barra segmentada de CPU + % + Temp + Grafico de Uso de CPU
// Coluna Direita:  Barra segmentada de RAM + % + GB   + Grafico de Uso de RAM
// Sub-barra:       Uptime + Rede + Barra de Disco
// Rodape (y=222):  Letreiro Infinito (Ticker Tape) do Mercado Financeiro!
void screenCpuRamStatic() {
  renderBackground();
  drawHeader();

  // Topo: Status + Barras de CPU e RAM lado a lado (y=26..78)
  drawModernCard(6,   HDR_H + 2, 150, 52, "C P U");
  drawModernCard(164, HDR_H + 2, 150, 52, "R A M");

  // Meio: Graficos de Uso de CPU (%) e Uso de RAM (%) lado a lado (y=80..170)
  drawModernCard(6,   HDR_H + 56, 150, 90, "CPU USE (%)");
  drawModernCard(164, HDR_H + 56, 150, 90, "RAM USE (%)");

  // Base (acima do Ticker Tape): Sistema, Rede e Disco (y=172..220)
  drawModernCard(6,   HDR_H + 148, 308, 48, nullptr);
}

void screenCpuRamDynamic() {
  char buf[48];

  // ---- Topo Esquerdo: CPU ----
  drawSegmentedBar(14, HDR_H + 15, 134, 13, st.cpu, 65, 85);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(66);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "USE: %.0f%%", st.cpu);
  tft.drawString(buf, 14, HDR_H + 32, 2);

  tft.setTextDatum(TR_DATUM);
  if (st.cput > 0) {
    snprintf(buf, sizeof(buf), "%.0f C", st.cput);
    tft.setTextColor(levelColor(st.cput, T_TEMP_HOT, T_TEMP_MAX), C_CARD);
  } else {
    snprintf(buf, sizeof(buf), "-- C");
    tft.setTextColor(C_DIM, C_CARD);
  }
  tft.drawString(buf, 148, HDR_H + 32, 2);
  tft.setTextPadding(0);

  // ---- Topo Direito: RAM ----
  drawSegmentedBar(172, HDR_H + 15, 134, 13, st.ram, 75, 90);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(68);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "USE: %.0f%%", st.ram);
  tft.drawString(buf, 172, HDR_H + 32, 2);

  tft.setTextDatum(TR_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  if (st.ramt > 0) snprintf(buf, sizeof(buf), "%.1f/%.0fG", st.ramu, st.ramt);
  else             snprintf(buf, sizeof(buf), "%.0fMHz", st.cpuf);
  tft.drawString(buf, 306, HDR_H + 32, 2);
  tft.setTextPadding(0);

  // ---- Meio: Grafico de CPU (Esquerda) e Grafico de RAM (Direita) ----
  plotGraph(14,  HDR_H + 70, 134, 70, hCpu, C_ACCENT, "%");
  plotGraph(172, HDR_H + 70, 134, 70, hRam, C_ACCENT, "%");

  // ---- Base: Uptime, Rede e Disco ----
  char upStr[16];
  fmtUptime(st.up, upStr, sizeof(upStr));

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(144);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "UP: %s", upStr);
  tft.drawString(buf, 14, HDR_H + 154, 2);

  tft.setTextColor(C_ACCENT, C_CARD);
  snprintf(buf, sizeof(buf), "NET ^%.1f v%.1fM", st.tx, st.rx);
  tft.drawString(buf, 14, HDR_H + 173, 2);
  tft.setTextPadding(0);

  snprintf(buf, sizeof(buf), "%.0f%% (%.0fG)", st.dsk, st.dskf);
  drawModernBar(166, HDR_H + 158, 140, 22, "DISK", st.dsk, buf, 80, 92);
}

// =========================================== TELA 2: GRAFICO DUPLO CPU+RAM =
void screenCpuRamDualStatic() {
  renderBackground();
  drawHeader();

  drawModernCard(6,   HDR_H + 2,  150, 62, "PROCESSADOR (CPU)");
  drawModernCard(164, HDR_H + 2,  150, 62, "MEMORIA (RAM)");
  drawModernCard(6,   HDR_H + 67, 308, 129, "GRAFICO: CPU % vs RAM %");
}

void screenCpuRamDualDynamic() {
  char buf[40];

  // Card Superior Esquerdo: CPU
  if (st.cput > 0) snprintf(buf, sizeof(buf), "%.1f%% | %.0fC", st.cpu, st.cput);
  else             snprintf(buf, sizeof(buf), "%.1f%%", st.cpu);
  drawModernBar(14, HDR_H + 16, 134, 20, "CPU", st.cpu, buf, 65, 85);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(134);
  tft.setTextColor(C_DIM, C_CARD);
  snprintf(buf, sizeof(buf), "Clock: %.0f MHz (%dC)", st.cpuf, st.cores);
  tft.drawString(buf, 14, HDR_H + 42, 2);
  tft.setTextPadding(0);

  // Card Superior Direito: RAM
  if (st.ramt > 0) snprintf(buf, sizeof(buf), "%.1f/%.0f GB", st.ramu, st.ramt);
  else             snprintf(buf, sizeof(buf), "%.1f%%", st.ram);
  drawModernBar(172, HDR_H + 16, 134, 20, "RAM", st.ram, buf, 75, 90);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(134);
  tft.setTextColor(C_DIM, C_CARD);
  snprintf(buf, sizeof(buf), "Uso: %.1f%% | Swp: %.0f%%", st.ram, st.swap);
  tft.drawString(buf, 172, HDR_H + 42, 2);
  tft.setTextPadding(0);

  // Card Inferior Grande: Grafico Combinado CPU + RAM
  plotDualCpuRamGraph(14, HDR_H + 82, 292, 108);
}

// =========================================== TELA 3: GPU FOCUS =============
void screenGpuFocusStatic() {
  renderBackground();
  drawHeader();

  drawModernCard(6,   HDR_H + 2, 144, 194, "PLACA DE VIDEO (GPU)");
  drawModernCard(156, HDR_H + 2, 158, 92,  "VRAM & TEMPERATURA");
  drawModernCard(156, HDR_H + 98, 158, 98, "HISTORICO GPU (%)");
}

void screenGpuFocusDynamic() {
  char buf[40];
  float gpuVal = (st.gpu >= 0) ? st.gpu : 0.0f;

  // Gauge Grande de GPU
  drawGauge(78, HDR_H + 68, 48, gpuVal, st.gpuname[0] ? st.gpuname : "GPU LOAD",
            linked && (st.gpu >= 0), 70, 90, 0);

  // Barra de temperatura da GPU no card esquerdo
  float gTemp = st.gput > 0 ? st.gput : 0.0f;
  if (st.gput > 0) snprintf(buf, sizeof(buf), "%.0f C", st.gput);
  else             snprintf(buf, sizeof(buf), "-- C");
  drawModernBar(16, HDR_H + 134, 124, 20, "GPU TEMP", gTemp, buf, T_TEMP_HOT, T_TEMP_MAX);

  tft.setTextDatum(MC_DATUM);
  tft.setTextPadding(124);
  tft.setTextColor(C_TEXT, C_CARD);
  if (st.fps >= 0)      snprintf(buf, sizeof(buf), "FPS: %d (Game)", st.fps);
  else if (st.gpuw > 0) snprintf(buf, sizeof(buf), "Power: %.1f W", st.gpuw);
  else                  snprintf(buf, sizeof(buf), "Modo: Desktop");
  tft.drawString(buf, 78, HDR_H + 174, 2);
  tft.setTextPadding(0);

  // Card VRAM & Temperatura
  tft.setTextDatum(ML_DATUM);
  tft.setTextPadding(138);
  if (st.gput > 0) {
    snprintf(buf, sizeof(buf), "%.1f C", st.gput);
    tft.setTextColor(levelColor(st.gput, T_TEMP_HOT, T_TEMP_MAX), C_CARD);
  } else {
    snprintf(buf, sizeof(buf), "-- C");
    tft.setTextColor(C_DIM, C_CARD);
  }
  tft.drawString(buf, 166, HDR_H + 30, 4);

  tft.setTextColor(C_TEXT, C_CARD);
  if (st.gpuw > 0) snprintf(buf, sizeof(buf), "Consumo: %.0f W", st.gpuw);
  else             snprintf(buf, sizeof(buf), "GPU: %s", st.gpuname[0] ? st.gpuname : "N/A");
  tft.drawString(buf, 166, HDR_H + 52, 2);
  tft.setTextPadding(0);

  float vramPct = (st.vram >= 0) ? st.vram : st.ram;
  if (st.vramu > 0 && st.vramt > 0) snprintf(buf, sizeof(buf), "%.1f/%.0fG", st.vramu, st.vramt);
  else                              snprintf(buf, sizeof(buf), "%.0f%%", vramPct);
  drawModernBar(166, HDR_H + 68, 138, 18, st.vram >= 0 ? "VRAM" : "RAM", vramPct, buf, 75, 90);

  // Grafico de historico GPU
  plotGraph(164, HDR_H + 114, 142, 74, hGpu, C_ACCENT, "%");
}

// =========================================== TELA 4: GRAFICOS (4x) =========
void screenGraphStatic() {
  renderBackground();
  drawHeader();

  drawModernCard(6,   HDR_H + 2,   150, 94, "CPU %");
  drawModernCard(164, HDR_H + 2,   150, 94, "RAM %");
  drawModernCard(6,   HDR_H + 100, 150, 96, "GPU %");
  drawModernCard(164, HDR_H + 100, 150, 96, "TEMP C");
}

void screenGraphDynamic() {
  plotGraph(14,  HDR_H + 17,  134, 72, hCpu, C_ACCENT, "%");
  plotGraph(172, HDR_H + 17,  134, 72, hRam, C_COOL,   "%");
  plotGraph(14,  HDR_H + 115, 134, 74, hGpu, C_OK,     "%");
  plotGraph(172, HDR_H + 115, 134, 74, hTmp, C_WARN,   "C");
}

// =========================================== TELA 5: WALLPAPER HUD =========
void screenWallpaperStatic() {
  renderBackground();
  drawHeader();
  drawModernCard(6, TICKER_Y - 52, SCR_W - 12, 49, nullptr);
}

void screenWallpaperDynamic() {
  char buf[24];

  snprintf(buf, sizeof(buf), "%.0fC", st.cput > 0 ? st.cput : 0);
  drawModernBar(14, TICKER_Y - 46, 92, 18, "CPU", st.cpu, buf, 65, 85);

  snprintf(buf, sizeof(buf), "%.1fG", st.ramu);
  drawModernBar(114, TICKER_Y - 46, 92, 18, "RAM", st.ram, buf, 75, 90);

  float gpuVal = st.gpu >= 0 ? st.gpu : 0;
  snprintf(buf, sizeof(buf), "%.0f%%", gpuVal);
  drawModernBar(214, TICKER_Y - 46, 92, 18, "GPU", gpuVal, buf, 70, 90);

  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(C_TEXT, C_CARD);
  tft.setTextPadding(290);
  char line[64];
  snprintf(line, sizeof(line), "CPU: %.0f%%   RAM: %.0f%% (%.1fG)   GPU: %.0f%%   NET: %.1fM/s",
           st.cpu, st.ram, st.ramu, gpuVal, st.rx + st.tx);
  tft.drawString(line, 14, TICKER_Y - 14, 1);
  tft.setTextPadding(0);
}

// =========================================== TELA 6: MERCADO & CRIPTO ======
// Painel completo estilo Terminal Bloomberg / Bolsa de Valores:
//   - Topo (3 Cards): Dolar (USD/BRL), Euro (EUR/BRL) e IBOVESPA (B3)
//   - Esquerda: Tabela Top 5 Criptomoedas (BTC, ETH, SOL, BNB, XRP) + Var 24h
//   - Direita:  Card Bitcoin (BTC) com preco USD + BRL + Grafico Sparkline 24h
//   - Rodape:   Letreiro Infinito (Ticker Tape) correndo em tempo real
void screenMarketStatic() {
  renderBackground();
  drawHeader();

  // 3 Cards Superiores de Cambio & Bolsa
  drawModernCard(6,   HDR_H + 2, 100, 52, "DOLAR (USD)");
  drawModernCard(110, HDR_H + 2, 100, 52, "EURO (EUR)");
  drawModernCard(214, HDR_H + 2, 100, 52, "IBOVESPA");

  // Coluna Esquerda: Top 5 Criptomoedas
  drawModernCard(6,   HDR_H + 57, 160, 139, "CRIPTOMOEDAS (24H)");

  // Coluna Direita: Destaque Bitcoin + Grafico 24h
  drawModernCard(170, HDR_H + 57, 144, 139, "BITCOIN (BTC)");
}

static void drawChangeBadge(int x, int y, int w, int h, float pct) {
  uint16_t fg = (pct >= 0.0f) ? 0x07E0 : 0xF800;
  uint16_t bg = (pct >= 0.0f) ? 0x0180 : 0x3000;
  tft.fillRoundRect(x, y, w, h, 3, bg);
  tft.drawRoundRect(x, y, w, h, 3, fg);
  char b[16];
  snprintf(b, sizeof(b), "%s%.2f%%", pct >= 0.0f ? "+" : "", pct);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(fg, bg);
  tft.drawString(b, x + w / 2, y + h / 2, 1);
}

static void drawCryptoRow(int y, const char* sym, float priceUsd, float chgPct) {
  uint16_t trendCol = (chgPct >= 0.0f) ? 0x07E0 : 0xF800;

  // Pilula vertical de tendencia
  tft.fillRoundRect(12, y + 2, 3, 16, 1, trendCol);

  // Simbolo da cripto
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(C_ACCENT, C_CARD);
  tft.setTextPadding(32);
  tft.drawString(sym, 19, y + 10, 2);

  // Preco em USD
  char pBuf[20];
  if (priceUsd >= 1000.0f)     snprintf(pBuf, sizeof(pBuf), "$%.0f", priceUsd);
  else if (priceUsd >= 10.0f)  snprintf(pBuf, sizeof(pBuf), "$%.2f", priceUsd);
  else                         snprintf(pBuf, sizeof(pBuf), "$%.3f", priceUsd);

  tft.setTextColor(0xFFFF, C_CARD);
  tft.setTextPadding(58);
  tft.drawString(pBuf, 52, y + 10, 2);
  tft.setTextPadding(0);

  // Variacao 24h (%)
  drawChangeBadge(114, y + 3, 46, 14, chgPct);
}

void plotBtcSparkline(int x, int y, int w, int h) {
  tft.fillRect(x, y, w, h, C_CARD);
  uint16_t col = (mkt.btcc >= 0.0f) ? 0x07E0 : 0xF800;
  uint16_t area = scale565(col, 1, 5);

  for (int i = 1; i < 4; i++) {
    int gy = y + h * i / 4;
    for (int gx = x; gx < x + w; gx += 6) tft.drawPixel(gx, gy, C_TRACK);
  }

  int n = mkt.hBtcCount;
  if (n >= 2) {
    int prevX = -1, prevY = -1;
    for (int i = 0; i < n; i++) {
      int px = x + (i * (w - 1)) / (n - 1);
      int v  = constrain((int)mkt.hBtc[i], 0, 100);
      int py = y + h - 2 - ((h - 4) * v) / 100;

      if (prevX >= 0) {
        for (int fx = prevX; fx <= px; fx++) {
          int fy = prevY + ((py - prevY) * (fx - prevX)) / max(1, px - prevX);
          tft.drawFastVLine(fx, fy, y + h - fy, area);
        }
        tft.drawLine(prevX, prevY, px, py, col);
        if (py + 1 < y + h) tft.drawLine(prevX, prevY + 1, px, py + 1, col);
      }
      prevX = px;
      prevY = py;
    }
  } else {
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(C_DIM, C_CARD);
    tft.drawString("Aguardando dados BTC...", x + w / 2, y + h / 2, 1);
  }
}

void screenMarketDynamic() {
  char buf[32];

  // ---- Card 1: DOLAR (USD/BRL) ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(86);
  tft.setTextColor(0xFFFF, C_CARD);
  if (mkt.usd > 0) snprintf(buf, sizeof(buf), "R$ %.2f", mkt.usd);
  else             snprintf(buf, sizeof(buf), "R$ --.--");
  tft.drawString(buf, 14, HDR_H + 15, 2);
  tft.setTextPadding(0);
  drawChangeBadge(14, HDR_H + 34, 84, 14, mkt.usdc);

  // ---- Card 2: EURO (EUR/BRL) ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(86);
  tft.setTextColor(0xFFFF, C_CARD);
  if (mkt.eur > 0) snprintf(buf, sizeof(buf), "R$ %.2f", mkt.eur);
  else             snprintf(buf, sizeof(buf), "R$ --.--");
  tft.drawString(buf, 118, HDR_H + 15, 2);
  tft.setTextPadding(0);
  drawChangeBadge(118, HDR_H + 34, 84, 14, mkt.eurc);

  // ---- Card 3: IBOVESPA (B3) ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(86);
  tft.setTextColor(0xFFFF, C_CARD);
  if (mkt.ibov > 0) snprintf(buf, sizeof(buf), "%.1fk pts", mkt.ibov / 1000.0f);
  else              snprintf(buf, sizeof(buf), "---k pts");
  tft.drawString(buf, 222, HDR_H + 15, 2);
  tft.setTextPadding(0);
  drawChangeBadge(222, HDR_H + 34, 84, 14, mkt.ibovc);

  // ---- Coluna Esquerda: Top 5 Criptomoedas ----
  int baseY = HDR_H + 71;
  drawCryptoRow(baseY + 0,   "BTC", mkt.btc, mkt.btcc);
  drawCryptoRow(baseY + 24,  "ETH", mkt.eth, mkt.ethc);
  drawCryptoRow(baseY + 48,  "SOL", mkt.sol, mkt.solc);
  drawCryptoRow(baseY + 72,  "BNB", mkt.bnb, mkt.bnbc);
  drawCryptoRow(baseY + 96,  "XRP", mkt.xrp, mkt.xrpc);

  // ---- Coluna Direita: Bitcoin (BTC) + Grafico Sparkline 24h ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(128);
  tft.setTextColor(0xFFFF, C_CARD);
  if (mkt.btc > 0) snprintf(buf, sizeof(buf), "$ %.0f", mkt.btc);
  else             snprintf(buf, sizeof(buf), "$ --,---");
  tft.drawString(buf, 178, HDR_H + 72, 4);

  tft.setTextColor(C_ACCENT, C_CARD);
  if (mkt.btc_brl > 0) snprintf(buf, sizeof(buf), "R$ %.1f mil", mkt.btc_brl / 1000.0f);
  else                 snprintf(buf, sizeof(buf), "R$ --- mil");
  tft.drawString(buf, 178, HDR_H + 98, 2);
  tft.setTextPadding(0);

  plotBtcSparkline(178, HDR_H + 118, 128, 70);
}

// ======================================= TELA 7: PORTFOLIO PESSOAL =========
// Painel dedicado ao Patrimonio Pessoal & Carteira de Investimentos:
//   - Esquerda/Centro (186px): Saldo Total em destaque, Box PnL dinamico
//     (Verde lucro / Vermelho prejuizo), barra de alocacao e resumo da carteira.
//   - Direita (118px): Lista lateral com a variacao (%) e peso dos Top 3 ativos.
void screenPortfolioStatic() {
  renderBackground();
  drawHeader();

  // Painel Principal: Patrimonio & PnL Consolidado
  drawModernCard(6,   HDR_H + 2, 186, 194, "PATRIMONIO PESSOAL");

  // Painel Lateral: Top 3 Ativos da Carteira
  drawModernCard(196, HDR_H + 2, 118, 194, "TOP 3 ATIVOS");
  tft.drawFastHLine(204, HDR_H + 73,  102, C_TRACK);
  tft.drawFastHLine(204, HDR_H + 129, 102, C_TRACK);
}

void screenPortfolioDynamic() {
  char buf[48];

  // ---- 1) Saldo Total em Destaque (Font 4) ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("SALDO TOTAL CONSOLIDADO", 14, HDR_H + 16, 1);

  tft.setTextPadding(170);
  tft.setTextColor(0xFFFF, C_CARD);
  if (!portf.valid) {
    snprintf(buf, sizeof(buf), "R$ 0.00");
  } else if (portf.tot >= 1000000.0f) {
    snprintf(buf, sizeof(buf), "R$ %.2fM", portf.tot / 1000000.0f);
  } else if (portf.tot >= 100000.0f) {
    snprintf(buf, sizeof(buf), "R$ %.0f", portf.tot);
  } else {
    snprintf(buf, sizeof(buf), "R$ %.2f", portf.tot);
  }
  tft.drawString(buf, 14, HDR_H + 28, 4);
  tft.setTextPadding(0);

  // ---- 2) Box Dinamico de PnL (Verde Lucro / Vermelho Prejuizo) ----
  int8_t curSign = (portf.pnl_val >= 0.0f) ? 1 : -1;
  uint16_t pnlFg = (curSign >= 0) ? 0x07E0 : 0xF800;
  uint16_t pnlBg = (curSign >= 0) ? 0x0120 : 0x2800;
  int boxX = 14, boxY = HDR_H + 60, boxW = 170, boxH = 60;

  if (curSign != gLastPortfSign) {
    tft.fillRoundRect(boxX, boxY, boxW, boxH, 5, pnlBg);
    tft.drawRoundRect(boxX, boxY, boxW, boxH, 5, pnlFg);
    gLastPortfSign = curSign;
  }

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(150);
  tft.setTextColor(pnlFg, pnlBg);
  tft.drawString(curSign >= 0 ? "RESULTADO: LUCRO (PnL)" : "RESULTADO: PREJUIZO (PnL)", boxX + 8, boxY + 6, 1);

  tft.setTextPadding(94);
  float absPnl = fabsf(portf.pnl_val);
  if (absPnl >= 100000.0f) {
    snprintf(buf, sizeof(buf), "%sR$ %.1fk", curSign >= 0 ? "+" : "-", absPnl / 1000.0f);
  } else {
    snprintf(buf, sizeof(buf), "%sR$ %.2f", curSign >= 0 ? "+" : "-", absPnl);
  }
  tft.drawString(buf, boxX + 8, boxY + 20, 2);
  tft.setTextPadding(0);

  // Badge percentual ao lado do valor financeiro
  drawChangeBadge(boxX + 106, boxY + 20, 56, 16, portf.pnl_pct);

  // Linha interna de variacao 24h da carteira
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(152);
  tft.setTextColor(0xDEFB, pnlBg);
  snprintf(buf, sizeof(buf), "Hoje (24h): %s%.2f%%", portf.day_pct >= 0.0f ? "+" : "", portf.day_pct);
  tft.drawString(buf, boxX + 8, boxY + 43, 1);
  tft.setTextPadding(0);

  // ---- 3) Barra de Distribuicao / Alocacao dos Top 3 ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("COMPOSICAO DA CARTEIRA", 14, HDR_H + 130, 1);

  int barX = 14, barY = HDR_H + 142, barW = 170, barH = 10;
  tft.fillRoundRect(barX, barY, barW, barH, 3, C_TRACK);
  if (portf.valid && portf.topCount > 0) {
    const uint16_t segCols[3] = {0x07E0, 0x07FF, 0xFD20};
    int curX = barX;
    for (int i = 0; i < portf.topCount && i < 3; i++) {
      float wPct = portf.top3w[i];
      if (wPct <= 0.0f) wPct = 100.0f / (float)portf.topCount;
      int segW = (int)((barW * constrain(wPct, 0.0f, 100.0f)) / 100.0f);
      if (curX + segW > barX + barW) segW = (barX + barW) - curX;
      if (segW > 2) {
        tft.fillRect(curX, barY + 1, segW - 1, barH - 2, segCols[i]);
        curX += segW;
      }
    }
  }
  tft.drawRoundRect(barX, barY, barW, barH, 3, C_CARD_HI);

  // Rodape informativo do card principal
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(170);
  tft.setTextColor(C_TEXT, C_CARD);
  uint8_t nAssets = portf.count > 0 ? portf.count : portf.topCount;
  if (mkt.usd > 0) snprintf(buf, sizeof(buf), "Ativos: %u  |  USD: R$ %.2f", nAssets, mkt.usd);
  else             snprintf(buf, sizeof(buf), "Ativos na carteira: %u", nAssets);
  tft.drawString(buf, 14, HDR_H + 162, 1);

  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString(portf.valid ? "Sincronizado via USB Serial" : "Cadastre ativos no Agente PC", 14, HDR_H + 176, 1);
  tft.setTextPadding(0);

  // ---- 4) Lista Lateral: Variacao dos Top 3 Ativos ----
  const uint16_t rankCols[3] = {0x07E0, 0x07FF, 0xFD20};
  for (int i = 0; i < 3; i++) {
    int ry = HDR_H + 22 + i * 56;
    bool hasItem = (portf.valid && i < portf.topCount && strcmp(portf.top3[i], "---") != 0);

    float chg = hasItem ? lookupPortfolioAssetChange(i) : 0.0f;
    uint16_t pillCol = !hasItem ? C_TRACK : ((chg >= 0.0f) ? 0x07E0 : 0xF800);

    // Barra vertical lateral indicando alta/baixa
    tft.fillRoundRect(203, ry + 3, 3, 40, 1, pillCol);

    // Ticker do ativo
    tft.setTextDatum(TL_DATUM);
    tft.setTextPadding(68);
    tft.setTextColor(hasItem ? 0xFFFF : C_DIM, C_CARD);
    if (hasItem) snprintf(buf, sizeof(buf), "%d.%s", i + 1, portf.top3[i]);
    else         snprintf(buf, sizeof(buf), "%d. ---", i + 1);
    tft.drawString(buf, 211, ry + 3, 2);
    tft.setTextPadding(0);

    // Peso % no canto superior direito do slot
    tft.setTextDatum(TR_DATUM);
    tft.setTextPadding(30);
    tft.setTextColor(hasItem ? rankCols[i] : C_DIM, C_CARD);
    if (hasItem && portf.top3w[i] > 0.0f) snprintf(buf, sizeof(buf), "%.0f%%", portf.top3w[i]);
    else                                  snprintf(buf, sizeof(buf), "");
    tft.drawString(buf, 306, ry + 6, 1);
    tft.setTextPadding(0);

    // Badge de variacao (%) verde/vermelha
    if (hasItem) {
      drawChangeBadge(211, ry + 24, 95, 16, chg);
    } else {
      tft.fillRoundRect(211, ry + 24, 95, 16, 3, C_TRACK);
      tft.setTextDatum(MC_DATUM);
      tft.setTextColor(C_DIM, C_TRACK);
      tft.drawString("Sem ativo", 211 + 47, ry + 32, 1);
    }
  }
}

// ======================================= TELA 8: POMODORO FOCUS HUB ========
// Esquerda: Anel circular suave (flicker-free) com cronometro MM:SS e progresso
// Direita:  Status do ciclo (Trabalho 25m / Pausa 5m / Longa 15m), contador de
//           tomates concluidos, faixa musical ativa e saude termica do PC
void screenPomodoroStatic() {
  renderBackground();
  drawHeader();

  drawModernCard(6,   HDR_H + 2, 152, 194, "CRONOMETRO FOCO");
  drawModernCard(164, HDR_H + 2, 150, 194, "CICLOS & SESSAO");
  tft.drawFastHLine(172, HDR_H + 88,  134, C_TRACK);
  tft.drawFastHLine(172, HDR_H + 140, 134, C_TRACK);
}

void screenPomodoroDynamic() {
  char buf[52];

  // Interpola localmente 1s caso o timer esteja rodando entre pacotes USB
  int32_t effRem = pomo.rem;
  if (pomo.running && pomo.syncMs > 0) {
    uint32_t elap = (millis() - pomo.syncMs) / 1000;
    effRem = (int32_t)pomo.rem - (int32_t)elap;
    if (effRem < 0) effRem = 0;
  }

  // Aciona Buzzer fisico automaticamente na virada local para 00:00
  if (pomo.running && effRem == 0 && pomo.rem > 0 && !pomo.chimeGuard) {
    pomo.chimeGuard = true;
    bool wasBreak = (strcasecmp(pomo.state, "WORK") != 0);
    triggerAlert(true, wasBreak ? 0x07E0 : 0x07FF, 3);
  }

  int32_t totSec = (pomo.tot > 0) ? pomo.tot : 1500;
  float pctDone = constrain(100.0f * (float)(totSec - effRem) / (float)totSec, 0.0f, 100.0f);

  bool isLong  = (strcasecmp(pomo.state, "LONG") == 0);
  bool isBreak = isLong || (strcasecmp(pomo.state, "BREAK") == 0);
  int8_t phaseCode = !pomo.running ? 0 : (isLong ? 3 : (isBreak ? 2 : 1));

  uint16_t ringCol = C_ACCENT;
  if (!pomo.running) ringCol = 0xFD20;      // Ambar pausado
  else if (isLong)   ringCol = 0x7BFF;      // Azul celeste pausa longa
  else if (isBreak)  ringCol = 0x07FF;      // Ciano pausa curta

  // ---- Anel Circular Suave (slot 0 do cache anti-flicker) ----
  const int cx = 82, cy = HDR_H + 92, r = 54, ir = 45;
  const int A0 = 30, A1 = 330;
  int aEnd = A0 + (int)((A1 - A0) * pctDone / 100.0f);

  if (gGaugeEnd[0] != aEnd || gGaugeCol[0] != ringCol) {
    if (aEnd > A0 + 1) tft.drawSmoothArc(cx, cy, r, ir, A0, aEnd, ringCol, C_CARD, true);
    if (aEnd < A1 - 1) tft.drawSmoothArc(cx, cy, r, ir, aEnd, A1, C_TRACK, C_CARD, true);
    gGaugeEnd[0] = aEnd;
    gGaugeCol[0] = ringCol;
  }

  // Tempo MM:SS grande no centro do anel
  int mm = effRem / 60;
  int ss = effRem % 60;
  snprintf(buf, sizeof(buf), "%02d:%02d", mm, ss);
  tft.setTextDatum(MC_DATUM);
  tft.setTextPadding(76);
  tft.setTextColor(0xFFFF, C_CARD);
  tft.drawString(buf, cx, cy - 4, 4);

  tft.setTextPadding(72);
  tft.setTextColor(ringCol, C_CARD);
  const char* subSt = !pomo.running ? "PAUSADO" : (isBreak ? "DESCANSO" : "FOCO ATIVO");
  tft.drawString(subSt, cx, cy + 18, 1);

  // Rodape percentual do card esquerdo
  snprintf(buf, sizeof(buf), "Progresso: %.0f%% concluido", pctDone);
  tft.setTextPadding(136);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString(buf, cx, HDR_H + 174, 1);
  tft.setTextPadding(0);

  // ---- Card Direito: Badge de Estado + Ciclos + Midia + PC ----
  int bx = 172, by = HDR_H + 18, bw = 134, bh = 24;
  if (phaseCode != gLastPomoPhase) {
    uint16_t badgeBg = scale565(ringCol, 1, 6);
    tft.fillRoundRect(bx, by, bw, bh, 4, badgeBg);
    tft.drawRoundRect(bx, by, bw, bh, 4, ringCol);
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(ringCol, badgeBg);
    const char* pName = isLong ? "PAUSA LONGA (15m)" : (isBreak ? "PAUSA CURTA (5m)" : "TRABALHO (25m)");
    if (!pomo.running) pName = "TIMER EM PAUSA";
    tft.drawString(pName, bx + bw / 2, by + bh / 2, 1);
    gLastPomoPhase = phaseCode;
    drawHeader();
  }

  // Contador de ciclos + bolinhas indicadoras (meta de 4 ciclos)
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(90);
  tft.setTextColor(0xFFFF, C_CARD);
  snprintf(buf, sizeof(buf), "Ciclos: #%u", (unsigned)pomo.cycles);
  tft.drawString(buf, 172, HDR_H + 50, 2);
  tft.setTextPadding(0);

  uint8_t modCyc = pomo.cycles % 4;
  if (pomo.cycles > 0 && modCyc == 0 && isLong) modCyc = 4;
  for (int i = 0; i < 4; i++) {
    int dx = 180 + i * 22;
    int dy = HDR_H + 74;
    if (i < modCyc) {
      tft.fillCircle(dx, dy, 5, 0x07E0);
    } else if (i == modCyc && !isBreak && pomo.running) {
      tft.fillCircle(dx, dy, 5, ringCol);
      tft.fillCircle(dx, dy, 2, C_CARD);
    } else {
      tft.fillCircle(dx, dy, 5, C_TRACK);
      tft.drawCircle(dx, dy, 5, C_DIM);
    }
  }

  // Bloco intermediario: Musica tocando (Spotify / YT Music) durante o foco
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(134);
  if (mediaSt.valid && strcasecmp(mediaSt.source, "NONE") != 0) {
    tft.setTextColor(getMediaAccentColor(), C_CARD);
    snprintf(buf, sizeof(buf), "%s %s", mediaSt.playing ? "|>" : "||", mediaSt.source);
    tft.drawString(buf, 172, HDR_H + 96, 1);

    tft.setTextColor(0xFFFF, C_CARD);
    snprintf(buf, sizeof(buf), "%.20s", mediaSt.title);
    tft.drawString(buf, 172, HDR_H + 109, 1);

    tft.setTextColor(C_DIM, C_CARD);
    snprintf(buf, sizeof(buf), "%.20s", mediaSt.artist);
    tft.drawString(buf, 172, HDR_H + 122, 1);
  } else {
    tft.setTextColor(C_ACCENT, C_CARD);
    tft.drawString("MODO DEEP WORK", 172, HDR_H + 98, 1);
    tft.setTextColor(C_DIM, C_CARD);
    tft.drawString("Buzzer ativo ao fim", 172, HDR_H + 112, 1);
    tft.drawString("de cada ciclo!", 172, HDR_H + 124, 1);
  }
  tft.setTextPadding(0);

  // Rodape compacto de telemetria PC
  snprintf(buf, sizeof(buf), "%.0f%%", st.cpu);
  drawModernBar(172, HDR_H + 147, 134, 17, "CPU", st.cpu, buf, 70, 88);
  snprintf(buf, sizeof(buf), "%.0f%%", st.ram);
  drawModernBar(172, HDR_H + 169, 134, 17, "RAM", st.ram, buf, 75, 90);
}

// ======================================= TELA 9: HUB MULTIMIDIA (SD COVER) ==
// Renderiza a capa 320x240 do Spotify / YouTube Music gravada no Cartao SD com
// overlay de vidro translucido (pixel alpha-blend em tft_output) contendo:
// Badge da Fonte (Spotify Verde / YT Music Vermelho), Titulo, Artista e Barra!
void drawMediaBackdropAndOverlay() {
  bool coverDrawn = false;
  if (initOrVerifySD() && mediaSt.coverFile[0]) {
    String cPath = resolveSdPath(mediaSt.coverFile);
    if (cPath.length() > 0) {
      gMediaOverlayMode = true;
      uint16_t res = TJpgDec.drawSdJpg(0, 0, cPath.c_str());
      gMediaOverlayMode = false;
      if (res == 0) {
        coverDrawn = true;
      }
    }
  }

  if (!coverDrawn) {
    // Visualizador estudio elegante caso esteja sem Cartao SD ou aguardando capa
    tft.fillRect(0, HDR_H, SCR_W, TICKER_Y - HDR_H, 0x0841);
    uint16_t ac = getMediaAccentColor();
    uint16_t acDk = scale565(ac, 1, 6);
    for (int r = 56; r >= 16; r -= 10) {
      tft.drawCircle(SCR_W / 2, 82, r, acDk);
    }
    tft.fillCircle(SCR_W / 2, 82, 14, ac);
    tft.fillCircle(SCR_W / 2, 82, 4, 0x0841);
    // Card escuro simulando o overlay na parte inferior
    tft.fillRoundRect(8, 136, SCR_W - 16, 82, 7, 0x0021);
  }

  drawHeader();
  drawClock();

  uint16_t mCol = getMediaAccentColor();
  // Moldura luminosa de vidro sobre o overlay translucido (y=136..218)
  tft.drawRoundRect(8, 136, SCR_W - 16, 82, 7, scale565(mCol, 3, 4));
  tft.drawFastHLine(18, 136, SCR_W - 36, mCol);

  // Badge da Plataforma (SPOTIFY / YT MUSIC / MEDIA)
  const char* srcTxt = (strcasecmp(mediaSt.source, "NONE") == 0) ? "WINDOWS MEDIA" : mediaSt.source;
  int pillW = max(62, (int)strlen(srcTxt) * 6 + 16);
  tft.fillRoundRect(16, 143, pillW, 14, 3, mCol);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(0x0000, mCol);
  tft.drawString(srcTxt, 16 + pillW / 2, 150, 1);

  // Titulo e Artista desenhados com fundo TRANSPARENTE sobre o vidro translucido!
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(0xFFFF); // 1 argumento = fundo 100% transparente sobre a arte!
  char line1[42];
  snprintf(line1, sizeof(line1), "%.34s", mediaSt.title);
  tft.drawString(line1, 16, 161, 2);

  tft.setTextColor(0xCE79); // Prata claro legivel sobre o vidro escuro
  char line2[48];
  if (mediaSt.album[0]) {
    snprintf(line2, sizeof(line2), "%.22s  -  %.18s", mediaSt.artist, mediaSt.album);
  } else {
    snprintf(line2, sizeof(line2), "%.38s", mediaSt.artist);
  }
  tft.drawString(line2, 16, 181, 2);

  gLastMediaFillW = -1;
}

void screenMediaStatic() {
  if (isGifPlaying) {
    gif.close();
    isGifPlaying = false;
  }
  snprintf(gLastMediaSig, sizeof(gLastMediaSig), "%s|%s|%s|%s",
           mediaSt.source, mediaSt.coverId, mediaSt.title, mediaSt.artist);
  gLastMediaPlay = !mediaSt.playing; // Forca desenho inicial do badge Play/Pause
  drawMediaBackdropAndOverlay();
}

void screenMediaDynamic() {
  char curSig[128];
  snprintf(curSig, sizeof(curSig), "%s|%s|%s|%s",
           mediaSt.source, mediaSt.coverId, mediaSt.title, mediaSt.artist);

  // So recarrega o JPG + vidro translucido quando muda a musica ou chega nova capa!
  if (strcmp(curSig, gLastMediaSig) != 0) {
    strlcpy(gLastMediaSig, curSig, sizeof(gLastMediaSig));
    drawMediaBackdropAndOverlay();
    gLastMediaPlay = !mediaSt.playing;
  }

  uint16_t mCol = getMediaAccentColor();

  // Pill Play / Pause no canto superior direito do vidro
  if (mediaSt.playing != gLastMediaPlay || gLastMediaFillW < 0) {
    gLastMediaPlay = mediaSt.playing;
    uint16_t stBg = mediaSt.playing ? scale565(mCol, 1, 5) : 0x1082;
    uint16_t stFg = mediaSt.playing ? mCol : 0xFD20;
    tft.fillRoundRect(236, 143, 68, 14, 3, stBg);
    tft.drawRoundRect(236, 143, 68, 14, 3, stFg);
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(stFg, stBg);
    tft.drawString(mediaSt.playing ? "|> TOCANDO" : "|| PAUSADO", 270, 150, 1);
  }

  // Interpola segundos da musica suavemente quando em reproducao
  int32_t effPos = mediaSt.pos;
  if (mediaSt.playing && mediaSt.syncMs > 0) {
    effPos += (int32_t)((millis() - mediaSt.syncMs) / 1000);
  }
  if (mediaSt.dur > 0 && effPos > mediaSt.dur) effPos = mediaSt.dur;
  if (effPos < 0) effPos = 0;

  // Barra de progresso da faixa (sem flicker)
  const int barX = 16, barY = 204, barW = 204, barH = 6;
  float pct = (mediaSt.dur > 0) ? constrain((float)effPos / (float)mediaSt.dur, 0.0f, 1.0f) : 0.0f;
  int fillW = (int)((barW - 2) * pct);
  if (fillW != gLastMediaFillW) {
    tft.fillRoundRect(barX, barY, barW, barH, 3, 0x1082);
    if (fillW > 2) {
      tft.fillRoundRect(barX + 1, barY + 1, fillW, barH - 2, 2, mCol);
    }
    gLastMediaFillW = fillW;
  }

  // Micro-pill de tempo MM:SS / MM:SS
  char tBuf[20];
  if (mediaSt.dur > 0) {
    snprintf(tBuf, sizeof(tBuf), "%02d:%02d/%02d:%02d",
             (int)(effPos / 60), (int)(effPos % 60),
             (int)(mediaSt.dur / 60), (int)(mediaSt.dur % 60));
  } else {
    snprintf(tBuf, sizeof(tBuf), "%02d:%02d / LIVE", (int)(effPos / 60), (int)(effPos % 60));
  }
  tft.fillRoundRect(226, 200, 78, 13, 3, 0x0841);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(0xFFFF, 0x0841);
  tft.drawString(tBuf, 265, 206, 1);
}

// ================================================= TELA 10: CLIMA & GEMINI ==
// Desenha icone vetorial de clima (0=Sol, 1=Nublado, 2=Chuva, 3=Tempestade)
void drawWeatherIcon(int cx, int cy, uint8_t iconType, bool isAlert) {
  tft.fillRect(cx - 24, cy - 22, 48, 44, C_CARD);
  if (isAlert || iconType == 3) {
    // Nuvem de tempestade escura + Raio Amarelo Brilhante + Gotas
    uint16_t cld = 0x7BEF;
    tft.fillCircle(cx - 8, cy - 5, 9, cld);
    tft.fillCircle(cx + 2, cy - 9, 11, cld);
    tft.fillCircle(cx + 12, cy - 4, 8, cld);
    tft.fillRoundRect(cx - 16, cy - 5, 34, 10, 4, cld);
    // Raio amarelo
    tft.fillTriangle(cx + 2, cy + 1, cx - 6, cy + 11, cx + 1, cy + 11, 0xFFE0);
    tft.fillTriangle(cx - 1, cy + 10, cx + 6, cy + 10, cx - 3, cy + 20, 0xFFE0);
    // Gotas laterais
    tft.drawLine(cx - 12, cy + 8, cx - 15, cy + 15, 0x07FF);
    tft.drawLine(cx + 12, cy + 8, cx + 9,  cy + 15, 0x07FF);
  } else if (iconType == 2) {
    // Nuvem prateada + Chuva Ciano
    uint16_t cld = 0xAD55;
    tft.fillCircle(cx - 8, cy - 6, 9, cld);
    tft.fillCircle(cx + 2, cy - 10, 11, cld);
    tft.fillCircle(cx + 12, cy - 5, 8, cld);
    tft.fillRoundRect(cx - 16, cy - 6, 34, 10, 4, cld);
    for (int i = -10; i <= 10; i += 10) {
      tft.drawLine(cx + i, cy + 7, cx + i - 3, cy + 16, 0x07FF);
      tft.drawLine(cx + i + 1, cy + 7, cx + i - 2, cy + 16, 0x07FF);
    }
  } else if (iconType == 1) {
    // Sol atras da nuvem (Parcialmente nublado)
    tft.fillCircle(cx - 9, cy - 10, 8, 0xFFE0);
    uint16_t cld = 0xDEFB;
    tft.fillCircle(cx - 6, cy - 2, 9, cld);
    tft.fillCircle(cx + 4, cy - 6, 11, cld);
    tft.fillCircle(cx + 13, cy - 1, 8, cld);
    tft.fillRoundRect(cx - 14, cy - 2, 33, 10, 4, cld);
  } else {
    // Sol Radiante (Ceu limpo)
    tft.fillCircle(cx, cy, 11, 0xFFE0);
    tft.drawCircle(cx, cy, 13, 0xFD20);
    for (int a = 0; a < 360; a += 45) {
      float rad = a * 0.0174532925f;
      int x0 = cx + (int)(cosf(rad) * 15.0f);
      int y0 = cy + (int)(sinf(rad) * 15.0f);
      int x1 = cx + (int)(cosf(rad) * 20.0f);
      int y1 = cy + (int)(sinf(rad) * 20.0f);
      tft.drawLine(x0, y0, x1, y1, 0xFFE0);
    }
  }
}

// Quebra `wth.gemText` em linhas de ate `maxChars` caracteres sem cortar palavras no meio
static int wrapGemLines(const char* txt, char lines[][40], int maxLines, int maxChars) {
  if (!txt || !txt[0]) return 0;
  int lineCount = 0;
  int len = strlen(txt);
  int pos = 0;

  while (pos < len && lineCount < maxLines) {
    while (pos < len && (txt[pos] == ' ' || txt[pos] == '\n' || txt[pos] == '\r')) {
      pos++;
    }
    if (pos >= len) break;

    // Respeita quebras de linha explicitas ('\n' ou '|')
    int nlPos = -1;
    for (int k = pos; k < len && (k - pos) <= maxChars; k++) {
      if (txt[k] == '\n' || txt[k] == '|') {
        nlPos = k;
        break;
      }
    }

    int endPos = pos + maxChars;
    if (nlPos >= 0) {
      endPos = nlPos;
    } else if (endPos < len) {
      int lastSpace = -1;
      for (int k = pos; k < endPos; k++) {
        if (txt[k] == ' ') lastSpace = k;
      }
      if (lastSpace > pos + 10) endPos = lastSpace;
    } else {
      endPos = len;
    }

    int copyLen = endPos - pos;
    if (copyLen > maxChars) copyLen = maxChars;
    memcpy(lines[lineCount], txt + pos, copyLen);
    lines[lineCount][copyLen] = '\0';
    lineCount++;
    pos = endPos;
    if (pos < len && (txt[pos] == '\n' || txt[pos] == '|')) pos++;
  }
  return lineCount;
}

// ======================================= Modulo 1: SCR_NEWS (Tela 10) ======
// Adiciona ou atualiza uma manchete na fila local do ESP32 (ate 8 manchetes)
static void pushNewsToQueue(const char* topic, const char* headline, const char* src, const char* tm, bool makeActive) {
  if (!headline || !headline[0]) return;

  char cleanTopic[28], cleanHead[220], cleanSrc[24], cleanTm[10];
  sanitizeAscii(cleanTopic, topic && topic[0] ? topic : "Noticias", sizeof(cleanTopic));
  sanitizeAscii(cleanHead,  headline, sizeof(cleanHead));
  sanitizeAscii(cleanSrc,   src && src[0] ? src : "RSS Live", sizeof(cleanSrc));
  sanitizeAscii(cleanTm,    tm && tm[0] ? tm : "--:--", sizeof(cleanTm));

  // Verifica se a manchete ja existe na fila para evitar duplicatas
  for (uint8_t i = 0; i < newsSt.count; i++) {
    if (strcmp(newsSt.queue[i].headline, cleanHead) == 0) {
      strlcpy(newsSt.queue[i].topic,  cleanTopic, sizeof(newsSt.queue[i].topic));
      strlcpy(newsSt.queue[i].source, cleanSrc,   sizeof(newsSt.queue[i].source));
      strlcpy(newsSt.queue[i].tm,     cleanTm,    sizeof(newsSt.queue[i].tm));
      if (makeActive && newsSt.activeIdx != i) {
        newsSt.activeIdx    = i;
        newsSt.lastRotateMs = millis();
        newsSt.scrollX      = -20; // Pequena pausa inicial antes de deslizar
      }
      newsSt.valid = true;
      return;
    }
  }

  uint8_t slot = 0;
  if (newsSt.count < NEWS_QUEUE_MAX) {
    slot = newsSt.count++;
  } else {
    // Desloca fila e insere no fim
    for (uint8_t i = 1; i < NEWS_QUEUE_MAX; i++) {
      newsSt.queue[i - 1] = newsSt.queue[i];
    }
    slot = NEWS_QUEUE_MAX - 1;
  }

  strlcpy(newsSt.queue[slot].topic,    cleanTopic, sizeof(newsSt.queue[slot].topic));
  strlcpy(newsSt.queue[slot].headline, cleanHead,  sizeof(newsSt.queue[slot].headline));
  strlcpy(newsSt.queue[slot].source,   cleanSrc,   sizeof(newsSt.queue[slot].source));
  strlcpy(newsSt.queue[slot].tm,       cleanTm,    sizeof(newsSt.queue[slot].tm));

  if (makeActive || !newsSt.valid) {
    newsSt.activeIdx    = slot;
    newsSt.lastRotateMs = millis();
    newsSt.scrollX      = -20;
  }
  newsSt.valid = true;
}

static const NewsItem* getActiveNewsItem() {
  static const NewsItem defaultItem = {
    "TECNOLOGIA",
    "Sincronizando feed de manchetes em tempo real pelo Cyber Deck Agent...",
    "CYD RSS",
    "--:--"
  };
  if (!newsSt.valid || newsSt.count == 0) return &defaultItem;
  if (newsSt.activeIdx >= newsSt.count) newsSt.activeIdx = 0;
  return &newsSt.queue[newsSt.activeIdx];
}

// Desliza suavemente a manchete atual usando TFT_eSprite (28 FPS) e rotaciona a cada 15s
void updateNewsHeadlineSprite() {
  if (currentScreen != SCR_NEWS || !newsSprReady) return;

  uint32_t now = millis();
  if (newsSt.lastRotateMs == 0) newsSt.lastRotateMs = now;

  // Troca de manchete automaticamente a cada 15 segundos (NEWS_ROTATE_MS)
  if (newsSt.count > 1 && (now - newsSt.lastRotateMs >= NEWS_ROTATE_MS)) {
    newsSt.activeIdx    = (newsSt.activeIdx + 1) % newsSt.count;
    newsSt.lastRotateMs = now;
    newsSt.scrollX      = -24;
    gLastNewsSig[0]     = '\0'; // Forca atualizacao dos metadados e resumo
  }

  const NewsItem* item = getActiveNewsItem();

  newsSpr.fillSprite(0x0421);
  newsSpr.drawRect(0, 0, NEWS_SPR_W, NEWS_SPR_H, C_ACCENT_DK);
  newsSpr.drawFastVLine(0, 0, NEWS_SPR_H, C_ACCENT);
  newsSpr.drawFastVLine(1, 0, NEWS_SPR_H, C_ACCENT);

  newsSpr.setTextDatum(ML_DATUM);
  newsSpr.setTextColor(0xFFFF, 0x0421);

  int drawX = 8 - max((int16_t)0, newsSt.scrollX);
  int pxW = newsSpr.drawString(item->headline, drawX, NEWS_SPR_H / 2 + 1, 4);
  newsSt.headlinePxW = pxW;

  // Se o titulo for longo, faz loop continuo suave com separador ciano
  int loopGap = 54;
  if (pxW > (NEWS_SPR_W - 16)) {
    int secondX = drawX + pxW + loopGap;
    newsSpr.setTextColor(C_ACCENT, 0x0421);
    newsSpr.drawString("///", drawX + pxW + 16, NEWS_SPR_H / 2 + 1, 2);
    newsSpr.setTextColor(0xFFFF, 0x0421);
    if (secondX < NEWS_SPR_W) {
      newsSpr.drawString(item->headline, secondX, NEWS_SPR_H / 2 + 1, 4);
    }
    newsSt.scrollX += 2;
    if (newsSt.scrollX >= (pxW + loopGap)) {
      newsSt.scrollX = 0;
    }
  } else {
    newsSt.scrollX = 0;
  }

  newsSpr.pushSprite(12, 130);
}

void screenNewsStatic() {
  renderBackground();
  drawHeader();
  drawClock();

  // Card Superior: Data Atual, Localizacao (Votuporanga) & Temperatura Regional
  drawModernCard(6, 27, 308, 76, "CLIMA REGIONAL & DATA ATUAL");

  // Card Inferior: Feed de Noticias Customizavel (SCR_NEWS)
  drawModernCard(6, 106, 308, 112, "");
  tft.fillRoundRect(12, 110, 32, 13, 3, C_ACCENT);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(0x0000, C_ACCENT);
  tft.drawString("NEWS", 28, 116, 1);

  gLastWthSig[0]  = '\0';
  gLastNewsSig[0] = '\0';
  gLastNewsRemainS = -1;
}

void screenNewsDynamic() {
  // 1) Atualiza Card Superior (Clima Regional, Data e Localidade)
  char wSig[96];
  snprintf(wSig, sizeof(wSig), "%s|%s|%s|%.1f|%.1f|%u|%.0f|%u|%u|%d|%s",
           wth.city, wth.dateFull, wth.dow, wth.temp, wth.feels,
           (unsigned)wth.hum, wth.wind, (unsigned)wth.rainProb,
           (unsigned)wth.icon, wth.alert ? 1 : 0, wth.cond);

  if (strcmp(wSig, gLastWthSig) != 0) {
    strlcpy(gLastWthSig, wSig, sizeof(gLastWthSig));

    char dtBadge[28];
    if (wth.dow[0] && wth.dow[0] != '-') {
      snprintf(dtBadge, sizeof(dtBadge), "%s %s", wth.dow, wth.dateFull);
    } else {
      snprintf(dtBadge, sizeof(dtBadge), "DATA: %s", wth.dateFull);
    }
    tft.fillRoundRect(184, 29, 124, 12, 3, scale565(C_ACCENT, 1, 5));
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(0xFFFF, scale565(C_ACCENT, 1, 5));
    tft.drawString(dtBadge, 246, 35, 1);

    drawWeatherIcon(34, 68, wth.icon, wth.alert);
    tft.fillRect(62, 42, 140, 58, C_CARD);

    char cityLine[28];
    snprintf(cityLine, sizeof(cityLine), "LOCAL: %s", wth.city);
    for (int i = 0; cityLine[i]; i++) cityLine[i] = toupper((unsigned char)cityLine[i]);
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(C_ACCENT, C_CARD);
    tft.drawString(cityLine, 64, 42, 1);

    uint16_t tCol = 0x07E0;
    if      (wth.alert || wth.temp >= 35.0f) tCol = 0xF800;
    else if (wth.temp >= 30.0f)              tCol = 0xFD20;
    else if (wth.temp <  20.0f)              tCol = 0x07FF;

    char tempBig[16];
    if (wth.valid) snprintf(tempBig, sizeof(tempBig), "%.1f", wth.temp);
    else           snprintf(tempBig, sizeof(tempBig), "--.-");
    tft.setTextColor(tCol, C_CARD);
    int wT = tft.drawString(tempBig, 64, 53, 4);
    tft.drawCircle(64 + wT + 4, 57, 2, tCol);
    tft.drawString("C", 64 + wT + 9, 54, 2);

    char condLine[36];
    if (wth.valid) {
      snprintf(condLine, sizeof(condLine), "%.13s | %.0f/%.0fC", wth.cond, wth.tmin, wth.tmax);
    } else {
      snprintf(condLine, sizeof(condLine), "Buscando clima...");
    }
    tft.setTextColor(C_TEXT, C_CARD);
    tft.drawString(condLine, 64, 83, 2);

    char p1[22], p2[22], p3[22];
    snprintf(p1, sizeof(p1), "SENSACAO: %.1fC", wth.feels);
    snprintf(p2, sizeof(p2), "UMID:%u%% CHV:%u%%", (unsigned)wth.hum, (unsigned)wth.rainProb);
    if (wth.alert) {
      snprintf(p3, sizeof(p3), "! TEMPESTADE !");
    } else {
      snprintf(p3, sizeof(p3), "VENTO: %.0f km/h", wth.wind);
    }

    tft.fillRoundRect(204, 44, 102, 16, 3, 0x1082);
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(C_TEXT, 0x1082);
    tft.drawString(p1, 255, 52, 1);

    tft.fillRoundRect(204, 63, 102, 16, 3, 0x1082);
    tft.setTextColor(0x07FF, 0x1082);
    tft.drawString(p2, 255, 71, 1);

    uint16_t p3Bg = wth.alert ? 0xF800 : 0x1082;
    uint16_t p3Fg = wth.alert ? 0xFFFF : C_DIM;
    tft.fillRoundRect(204, 82, 102, 16, 3, p3Bg);
    tft.setTextColor(p3Fg, p3Bg);
    tft.drawString(p3, 255, 90, 1);
  }

  // 2) Atualiza Card Inferior: Feed de Noticias Customizavel (SCR_NEWS)
  const NewsItem* item = getActiveNewsItem();
  char nSig[240];
  snprintf(nSig, sizeof(nSig), "%u|%u|%s|%s|%s",
           (unsigned)newsSt.activeIdx, (unsigned)newsSt.count,
           item->topic, item->source, item->headline);

  uint32_t elapsed = (newsSt.lastRotateMs > 0) ? (millis() - newsSt.lastRotateMs) : 0;
  uint32_t clampedElapsed = (elapsed > (uint32_t)NEWS_ROTATE_MS) ? (uint32_t)NEWS_ROTATE_MS : elapsed;
  int8_t remSec = (int8_t)constrain((int)(((uint32_t)NEWS_ROTATE_MS - clampedElapsed) / 1000U), 0, 15);

  if (strcmp(nSig, gLastNewsSig) != 0) {
    strlcpy(gLastNewsSig, nSig, sizeof(gLastNewsSig));

    // Cabecalho do topico ativo (ex: [POLITICA] • Fonte)
    tft.fillRect(48, 109, 196, 15, C_CARD);
    char topBuf[44];
    snprintf(topBuf, sizeof(topBuf), "[%s] %s", item->topic, item->source);
    for (int i = 0; topBuf[i]; i++) topBuf[i] = toupper((unsigned char)topBuf[i]);
    tft.setTextDatum(ML_DATUM);
    tft.setTextColor(0x07FF, C_CARD);
    tft.drawString(topBuf, 48, 116, 1);

    tft.drawFastHLine(12, 125, 296, C_CARD_HI);

    // Resumo em 2 linhas estaticas abaixo do Sprite deslizante para leitura confortavel
    char wrapped[4][40];
    int nLines = wrapGemLines(item->headline, wrapped, 4, 37);
    tft.fillRect(12, 160, 296, 52, C_CARD);
    tft.setTextDatum(TL_DATUM);
    for (int r = 0; r < min(nLines, 3); r++) {
      tft.setTextColor(r == 0 ? 0xDEFB : C_DIM, C_CARD);
      tft.drawString(wrapped[r], 14, 161 + r * 16, 2);
    }
  }

  // Contador regressivo de 15s + posicao da fila no canto superior direito do Card News
  if (remSec != gLastNewsRemainS) {
    gLastNewsRemainS = remSec;
    char metaBuf[22];
    uint8_t tot = max((uint8_t)1, newsSt.count);
    uint8_t cur = (newsSt.activeIdx % tot) + 1;
    snprintf(metaBuf, sizeof(metaBuf), "%u/%u • %02ds", (unsigned)cur, (unsigned)tot, (int)remSec);
    tft.fillRect(244, 109, 64, 15, C_CARD);
    tft.setTextDatum(MR_DATUM);
    tft.setTextColor(C_WARN, C_CARD);
    tft.drawString(metaBuf, 306, 116, 1);
  }
}

// ======================================= Modulo 2: SCR_TERMINAL (Tela 11) ===
static void appendRawTerminalLine(const char* s) {
  if (termSt.count < TERM_MAX_LINES) {
    strlcpy(termSt.lines[termSt.count], s, sizeof(termSt.lines[0]));
    termSt.count++;
  } else {
    // Scroll vertical: desloca todas as linhas para cima e escreve na ultima
    for (int i = 1; i < TERM_MAX_LINES; i++) {
      strlcpy(termSt.lines[i - 1], termSt.lines[i], sizeof(termSt.lines[0]));
    }
    strlcpy(termSt.lines[TERM_MAX_LINES - 1], s, sizeof(termSt.lines[0]));
  }
  termSt.totalLogged++;
  termSt.dirty = true;
}

// Funcao publica pedida na especificacao: faz o texto rolar para cima conforme novas linhas chegam
void log_to_terminal(String text) {
  isMatrixRain = false;
  char cleanBuf[512];
  sanitizeAscii(cleanBuf, text.c_str(), sizeof(cleanBuf));
  if (!cleanBuf[0]) return;

  int len = strlen(cleanBuf);
  int pos = 0;
  while (pos < len) {
    while (pos < len && (cleanBuf[pos] == '\r')) pos++;
    if (pos >= len) break;
    if (cleanBuf[pos] == '\n') {
      pos++;
      continue;
    }

    // Encontra o proximo '\n' ou quebra em TERM_COLS (48 colunas monospace)
    int lineEnd = pos;
    while (lineEnd < len && cleanBuf[lineEnd] != '\n' && cleanBuf[lineEnd] != '\r' && (lineEnd - pos) < TERM_COLS) {
      lineEnd++;
    }

    char chunk[TERM_COLS + 4];
    int copyLen = lineEnd - pos;
    memcpy(chunk, cleanBuf + pos, copyLen);
    chunk[copyLen] = '\0';
    appendRawTerminalLine(chunk);

    pos = lineEnd;
    if (pos < len && cleanBuf[pos] == '\n') pos++;
  }
}

void clearTerminal() {
  isMatrixRain = false;
  termSt.count = 0;
  termSt.totalLogged = 0;
  log_to_terminal("CYD CYBER DECK OS v4.2 [ESP32-2432S028R]");
  log_to_terminal("Console pronto. Comandos: help | ping | docker | esp info");
  termSt.dirty = true;
}

void screenTerminalStatic() {
  isMatrixRain = false;
  if (isGifPlaying) {
    gif.close();
    isGifPlaying = false;
  }
  tft.fillScreen(0x0000); // Tela preta classica de terminal
  drawHeader();
  drawClock();

  // Moldura Cyber Deck Verde Fosforo (0x07E0)
  const int tx = 4, ty = 26, tw = 312, th = 193;
  tft.fillRect(tx, ty, tw, th, 0x0000);
  tft.drawRect(tx, ty, tw, th, 0x07E0);

  // Barra de titulo interna do Terminal (root@cyd-cyberdeck:~#)
  tft.fillRect(tx + 1, ty + 1, tw - 2, 13, 0x0120);
  tft.drawFastHLine(tx + 1, ty + 14, tw - 2, 0x03E0);
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(0x07E0, 0x0120);
  tft.drawString("root@cyd-deck:~# ttyUSB0 [115200]", tx + 6, ty + 7, 1);

  // Barra inferior de prompt interativo
  tft.drawFastHLine(tx + 1, ty + th - 14, tw - 2, 0x0120);

  if (termSt.count == 0) {
    clearTerminal();
  }
  termSt.dirty = true;
}

// ======================================= Easter Egg: Matrix Rain (SCR_TERMINAL) ===
static uint32_t lastMatrixTick = 0;
#define MATRIX_COLS 25
static int16_t matrixHeadY[MATRIX_COLS];
static uint8_t matrixSpeed[MATRIX_COLS];
static uint8_t matrixLen[MATRIX_COLS];
static uint8_t matrixTickCount[MATRIX_COLS];

static void initMatrixRain() {
  isMatrixRain = true;
  strlcpy(termSt.lastCmd, "cmatrix", sizeof(termSt.lastCmd));
  tft.fillRect(4, 26, 312, 193, 0x0000);
  tft.drawRect(4, 26, 312, 193, 0x07E0);
  tft.fillRect(5, 27, 310, 13, 0x0120);
  tft.drawFastHLine(5, 40, 310, 0x03E0);
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(0x07E0, 0x0120);
  tft.drawString("matrix@cyd-deck:~# running [qualquer tecla p/ sair]", 10, 33, 1);

  for (int i = 0; i < MATRIX_COLS; i++) {
    matrixHeadY[i] = random(44, 120);
    matrixSpeed[i] = random(1, 4);
    matrixLen[i]   = random(5, 14);
    matrixTickCount[i] = 0;
  }
  Serial.println("TERM_LOG:[MATRIX] Easter egg Matrix Rain iniciado na CYD!");
}

static void updateMatrixRain() {
  if (!isMatrixRain) return;
  uint32_t now = millis();
  if (now - lastMatrixTick < 40) return;
  lastMatrixTick = now;

  const int topY = 44;
  const int botY = 205;
  const int tx = 8;
  const int colW = 12;

  for (int i = 0; i < MATRIX_COLS; i++) {
    matrixTickCount[i]++;
    if (matrixTickCount[i] < matrixSpeed[i]) continue;
    matrixTickCount[i] = 0;

    int x = tx + i * colW;
    int y = matrixHeadY[i];

    // Ponta brilhante em branco
    if (y >= topY && y < botY) {
      char ch = (char)random(33, 126);
      tft.setTextColor(0xFFFF, 0x0000);
      tft.drawChar(ch, x, y, 1);
    }

    // Corpo em verde fosforo 0x07E0
    int prevY = y - 8;
    if (prevY >= topY && prevY < botY) {
      char prevCh = (char)random(33, 126);
      tft.setTextColor(0x07E0, 0x0000);
      tft.drawChar(prevCh, x, prevY, 1);
    }

    // Apaga cauda anterior
    int tailY = y - (matrixLen[i] * 8);
    if (tailY >= topY && tailY < botY) {
      tft.fillRect(x, tailY, 7, 8, 0x0000);
    }

    matrixHeadY[i] += 8;
    if (matrixHeadY[i] > botY + (matrixLen[i] * 8)) {
      matrixHeadY[i] = topY;
      matrixSpeed[i] = random(1, 4);
      matrixLen[i] = random(5, 14);
    }
  }
}

void screenTerminalDynamic() {
  if (isMatrixRain) {
    updateMatrixRain();
    return;
  }
  const int tx = 4, ty = 26, tw = 312, th = 193;

  // Redesenha o buffer de linhas rolantes apenas quando novas linhas chegam
  if (termSt.dirty) {
    termSt.dirty = false;

    // Atualiza contador de linhas no topo direito da janela do terminal
    char lnBuf[18];
    snprintf(lnBuf, sizeof(lnBuf), "LN:%lu", (unsigned long)termSt.totalLogged);
    tft.fillRect(tx + tw - 66, ty + 2, 62, 11, 0x0120);
    tft.setTextDatum(MR_DATUM);
    tft.setTextColor(0x07FF, 0x0120);
    tft.drawString(lnBuf, tx + tw - 6, ty + 7, 1);

    // Area util das 14 linhas: y = 42..196 (11 px por linha, Fonte 1 6x8 monospace)
    tft.fillRect(tx + 2, ty + 16, tw - 4, th - 31, 0x0000);
    tft.setTextDatum(TL_DATUM);

    for (uint8_t i = 0; i < termSt.count; i++) {
      const char* ln = termSt.lines[i];
      uint16_t fg = 0x07E0; // Verde fosforo classico por padrao
      if (ln[0] == '$' || (ln[0] == '>' && ln[1] == ' ')) {
        fg = 0x07FF; // Ciano brilhante para comandos digitados
      } else if (strstr(ln, "[ERR]") || strstr(ln, "FAIL") || strstr(ln, "OFFLINE") || strstr(ln, "ERRO")) {
        fg = 0xF800; // Vermelho para erros/falhas
      } else if (strstr(ln, "[WIFI]") || strstr(ln, "CYD CYBER DECK") || strstr(ln, "WARN")) {
        fg = 0xFFE0; // Amarelo para cabecalhos e scan Wi-Fi
      } else if (strstr(ln, "200 OK") || strstr(ln, "[OK]")) {
        fg = 0x07E0; // Verde brilhante
      }
      tft.setTextColor(fg, 0x0000);
      tft.drawString(ln, tx + 6, ty + 17 + i * 11, 1);
    }
  }

  // Prompt inferior com cursor verde piscante (efeito terminal autentico)
  bool cursorOn = ((millis() / 450) % 2 == 0);
  char promptBuf[54];
  snprintf(promptBuf, sizeof(promptBuf), "cyd@deck:~$ %.30s%s",
           termSt.lastCmd, cursorOn ? "_" : " ");
  tft.fillRect(tx + 3, ty + th - 13, tw - 6, 11, 0x0000);
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(0x07E0, 0x0000);
  tft.drawString(promptBuf, tx + 6, ty + th - 7, 1);
}

// Executa Wi-Fi Scan nativo no ESP32 e imprime os resultados (SSID e RSSI) direto na SCR_TERMINAL
void runWifiScanOnTerminal() {
  strlcpy(termSt.lastCmd, "wifi scan", sizeof(termSt.lastCmd));
  if (currentScreen != SCR_TERMINAL) {
    currentScreen = SCR_TERMINAL;
    prefs.putUChar("screen", currentScreen);
    resetDrawCache();
    screenTerminalStatic();
    needFullDraw = false;
  }

  log_to_terminal("$ wifi scan");
  log_to_terminal("[WIFI] Escaneando redes 2.4GHz no ESP32...");
  screenTerminalDynamic(); // Exibe mensagem imediatamente antes do bloqueio do radio
  sendReplyLine("TERM_LOG:[WIFI] Escaneando redes 2.4GHz no hardware ESP32...");

  WiFi.mode(WIFI_STA);
  delay(20);

  int n = WiFi.scanNetworks(false, false);
  if (n <= 0) {
    log_to_terminal("[WIFI] Nenhuma rede Wi-Fi encontrada (0 APs).");
    sendReplyLine("TERM_LOG:[WIFI] Nenhuma rede Wi-Fi encontrada (0 APs).");
  } else {
    char hdr[48];
    snprintf(hdr, sizeof(hdr), "[WIFI] %d redes encontradas (SSID / RSSI):", n);
    log_to_terminal(hdr);
    char lHdr[64];
    snprintf(lHdr, sizeof(lHdr), "TERM_LOG:%s", hdr);
    sendReplyLine(lHdr);

    int maxShow = min(n, 11);
    for (int i = 0; i < maxShow; i++) {
      String ssidStr = WiFi.SSID(i);
      char cleanSsid[24];
      sanitizeAscii(cleanSsid, ssidStr.c_str(), sizeof(cleanSsid));
      if (!cleanSsid[0]) strlcpy(cleanSsid, "<OCULTA>", sizeof(cleanSsid));

      int32_t rssi = WiFi.RSSI(i);
      int32_t ch   = WiFi.channel(i);
      bool openNet = (WiFi.encryptionType(i) == WIFI_AUTH_OPEN);

      char row[52];
      snprintf(row, sizeof(row), "%02d) %-18.18s %4lddBm CH%02ld %s",
               i + 1, cleanSsid, (long)rssi, (long)ch, openNet ? "OPEN" : "WPA");
      log_to_terminal(row);
      char lRow[68];
      snprintf(lRow, sizeof(lRow), "TERM_LOG:%s", row);
      sendReplyLine(lRow);
    }
    if (n > maxShow) {
      char more[44];
      snprintf(more, sizeof(more), "... +%d redes adicionais omitidas", n - maxShow);
      log_to_terminal(more);
      char lMore[60];
      snprintf(lMore, sizeof(lMore), "TERM_LOG:%s", more);
      sendReplyLine(lMore);
    }
  }

  WiFi.scanDelete();
  // Mantem Wi-Fi STA conectado para Telemetria UDP (nao desliga o radio!)
  if (WiFi.status() != WL_CONNECTED && wifiSsid[0] != '\0' && strcmp(wifiSsid, "SUA_REDE_WIFI") != 0) {
    WiFi.begin(wifiSsid, wifiPass);
  }
  screenTerminalDynamic();
}

// ================================================= Serial & UDP / Protocolo JSON =
void applyJson(const char *json) {
  JsonDocument doc;
  if (deserializeJson(doc, json)) return;

  // 00) Heartbeat UDP do agente: responde uptime + IP (nao conta como pacote de telemetria)
  if (doc["cmd"] == "udp_ping") {
    char pong[48];
    snprintf(pong, sizeof(pong), "UDP_PONG:%lu:%s",
             (unsigned long)(millis() / 1000UL), WiFi.localIP().toString().c_str());
    sendReplyLine(pong);
    return;
  }

  // 0) Provisionamento dinamico de Wi-Fi via JSON: {"wifi_cfg": {"ssid": "...", "pass": "..."}}
  JsonVariant wcfg = doc["wifi_cfg"];
  if (!wcfg.isNull()) {
    const char* newSsid = wcfg["ssid"] | "";
    const char* newPass = wcfg["pass"] | "";
    if (newSsid[0] != '\0') {
      strlcpy(wifiSsid, newSsid, sizeof(wifiSsid));
      strlcpy(wifiPass, newPass, sizeof(wifiPass));
      prefs.putString("wifi_ssid", wifiSsid);
      prefs.putString("wifi_pass", wifiPass);
      WiFi.disconnect(false);
      delay(20);
      WiFi.mode(WIFI_STA);
      WiFi.setSleep(false);
      WiFi.begin(wifiSsid, wifiPass);
      wifiWasConnected = false;
      lastWifiCheckMs  = millis();
      char wMsg[64];
      snprintf(wMsg, sizeof(wMsg), "[WIFI] Conectando a '%s' (UDP :%d)...", wifiSsid, UDP_PORT);
      log_to_terminal(wMsg);
      char lW[80];
      snprintf(lW, sizeof(lW), "TERM_LOG:%s", wMsg);
      sendReplyLine(lW);
    }
    if (doc.size() == 1) return;
  }

  // 1) Comandos nativos delegados para o ESP32 ("cmd")
  if (doc["cmd"] == "list_sd") {
    listSdFilesToSerial();
    return;
  }
  if (doc["cmd"] == "wifi_scan") {
    isMatrixRain = false;
    runWifiScanOnTerminal();
    return;
  }
  if (doc["cmd"] == "term_clear") {
    isMatrixRain = false;
    clearTerminal();
    return;
  }
  if (doc["cmd"] == "cmatrix") {
    if (currentScreen != SCR_TERMINAL) {
      currentScreen = SCR_TERMINAL;
      prefs.putUChar("screen", currentScreen);
      resetDrawCache();
      screenTerminalStatic();
      needFullDraw = false;
    }
    initMatrixRain();
    return;
  }
  if (doc["cmd"] == "esp_reboot") {
    isMatrixRain = false;
    if (currentScreen != SCR_TERMINAL) {
      currentScreen = SCR_TERMINAL;
      prefs.putUChar("screen", currentScreen);
      resetDrawCache();
      screenTerminalStatic();
      needFullDraw = false;
    }
    strlcpy(termSt.lastCmd, "esp reboot", sizeof(termSt.lastCmd));
    log_to_terminal("$ esp reboot");
    log_to_terminal("[ESP32] REINICIANDO PLACA CYD EM 1.5S...");
    Serial.println("TERM_LOG:[ESP32] Reiniciando placa CYD em 1.5s...");
    screenTerminalDynamic();
    delay(1500);
    ESP.restart();
    return;
  }
  if (doc["cmd"] == "esp_mem") {
    isMatrixRain = false;
    if (currentScreen != SCR_TERMINAL) {
      currentScreen = SCR_TERMINAL;
      prefs.putUChar("screen", currentScreen);
      resetDrawCache();
      screenTerminalStatic();
      needFullDraw = false;
    }
    strlcpy(termSt.lastCmd, "esp mem", sizeof(termSt.lastCmd));
    log_to_terminal("$ esp mem");
    char m1[54], m2[54], m3[54];
    uint32_t freeH = ESP.getFreeHeap();
    uint32_t totH  = ESP.getHeapSize();
    uint32_t minH  = ESP.getMinFreeHeap();
    uint32_t maxA  = ESP.getMaxAllocHeap();
    float pctF     = totH > 0 ? ((float)freeH * 100.0f / (float)totH) : 0.0f;
    snprintf(m1, sizeof(m1), "[HEAP] Livre: %lu B / %lu B (%.1f%%)", (unsigned long)freeH, (unsigned long)totH, pctF);
    snprintf(m2, sizeof(m2), "[HEAP] Minimo: %lu B | Max Bloco: %lu B", (unsigned long)minH, (unsigned long)maxA);
    snprintf(m3, sizeof(m3), "[HEAP] PSRAM: %s | Uptime: %lu s", psramFound() ? "PRESENTE" : "N/A", (unsigned long)(millis() / 1000UL));
    log_to_terminal(m1);
    log_to_terminal(m2);
    log_to_terminal(m3);
    char lm1[70], lm2[70], lm3[70];
    snprintf(lm1, sizeof(lm1), "TERM_LOG:%s", m1);
    snprintf(lm2, sizeof(lm2), "TERM_LOG:%s", m2);
    snprintf(lm3, sizeof(lm3), "TERM_LOG:%s", m3);
    sendReplyLine(lm1);
    sendReplyLine(lm2);
    sendReplyLine(lm3);
    return;
  }
  if (doc["cmd"] == "esp_info") {
    isMatrixRain = false;
    if (currentScreen != SCR_TERMINAL) {
      currentScreen = SCR_TERMINAL;
      prefs.putUChar("screen", currentScreen);
      resetDrawCache();
      screenTerminalStatic();
      needFullDraw = false;
    }
    strlcpy(termSt.lastCmd, "esp info", sizeof(termSt.lastCmd));
    log_to_terminal("$ esp info");
    char b1[54], b2[54], b3[54], b4[54];
    String ipStr = (WiFi.status() == WL_CONNECTED) ? WiFi.localIP().toString() : "OFFLINE (USB Serial)";
    int rssiVal = (WiFi.status() == WL_CONNECTED) ? WiFi.RSSI() : 0;
    snprintf(b1, sizeof(b1), "[ESP32] IP: %s:%d | RSSI: %d dBm", ipStr.c_str(), UDP_PORT, rssiVal);
    snprintf(b2, sizeof(b2), "[ESP32] MAC: %s", WiFi.macAddress().c_str());
    snprintf(b3, sizeof(b3), "[ESP32] Firmware: v4.3 Cyber Deck [UDP + USB]");
    snprintf(b4, sizeof(b4), "[ESP32] Chip: %s Rev %d @ %lu MHz | SD: %s",
             ESP.getChipModel(), ESP.getChipRevision(), (unsigned long)ESP.getCpuFreqMHz(), hasSD ? "OK" : "AUSENTE");
    log_to_terminal(b1);
    log_to_terminal(b2);
    log_to_terminal(b3);
    log_to_terminal(b4);
    char lb1[70], lb2[70], lb3[70], lb4[70];
    snprintf(lb1, sizeof(lb1), "TERM_LOG:%s", b1);
    snprintf(lb2, sizeof(lb2), "TERM_LOG:%s", b2);
    snprintf(lb3, sizeof(lb3), "TERM_LOG:%s", b3);
    snprintf(lb4, sizeof(lb4), "TERM_LOG:%s", b4);
    sendReplyLine(lb1);
    sendReplyLine(lb2);
    sendReplyLine(lb3);
    sendReplyLine(lb4);
    if (WiFi.status() == WL_CONNECTED) {
      char wip[48];
      snprintf(wip, sizeof(wip), "WIFI_IP:%s", ipStr.c_str());
      sendReplyLine(wip);
    }
    return;
  }

  // 2) Transferencia de arquivos via Serial / UDP (Chunked Base64 para o Cartao SD)
  JsonVariant vFile = doc["file_name"];
  JsonVariant vMode = doc["file_mode"];
  if (!vFile.isNull() && !vMode.isNull()) {
    if (!initOrVerifySD()) {
      sendReplyLine("ERR_NO_SD");
      return;
    }
    String fName = String(vFile.as<const char*>());
    if (!fName.startsWith("/")) fName = "/" + fName;
    const char* fMode = vMode.as<const char*>();

    if (strcmp(fMode, "w") == 0) {
      if (isGifPlaying) { gif.close(); isGifPlaying = false; }
      if (uploadFile) { uploadFile.close(); }
      if (SD.exists(fName)) SD.remove(fName);
      uploadFile = SD.open(fName, FILE_WRITE);
      if (!uploadFile) {
        sendReplyLine("ERR_OPEN");
        return;
      }
      sendReplyLine("ACK_START");
      return;
    }

    if (strcmp(fMode, "a") == 0) {
      if (!uploadFile) {
        uploadFile = SD.open(fName, FILE_APPEND);
      }
      if (!uploadFile) {
        sendReplyLine("ERR_OPEN");
        return;
      }
      JsonVariant vData = doc["file_data"];
      if (!vData.isNull()) {
        const char* b64 = vData.as<const char*>();
        size_t b64Len = strlen(b64);
        if (b64Len > 0) {
          uint8_t* bin = (uint8_t*)malloc(b64Len);
          if (bin) {
            size_t olen = 0;
            if (mbedtls_base64_decode(bin, b64Len, &olen, (const unsigned char*)b64, b64Len) == 0) {
              uploadFile.write(bin, olen);
              uploadFile.flush();
            }
            free(bin);
          }
        }
      }
      int seq = doc["seq"] | 0;
      char ackBuf[28];
      snprintf(ackBuf, sizeof(ackBuf), "ACK_CHUNK:%d", seq);
      sendReplyLine(ackBuf);
      return;
    }

    if (strcmp(fMode, "eof") == 0) {
      if (uploadFile) {
        uploadFile.flush();
        uploadFile.close();
      }
      String cleanName = fName.startsWith("/") ? fName.substring(1) : fName;
      String cleanLow = cleanName;
      cleanLow.toLowerCase();
      bool isMediaCover = (doc["is_cover"] | false) || cleanLow.startsWith("_media");
      if (isMediaCover) {
        strlcpy(mediaSt.coverFile, cleanName.c_str(), sizeof(mediaSt.coverFile));
        if (!doc["cid"].isNull()) {
          strlcpy(mediaSt.coverId, doc["cid"] | "cov", sizeof(mediaSt.coverId));
        } else {
          snprintf(mediaSt.coverId, sizeof(mediaSt.coverId), "%lu", (unsigned long)(millis() & 0xFFFF));
        }
        mediaSt.hasCover = true;
        gLastMediaSig[0] = '\0'; // Forca redesenho imediato da nova capa na SCR_MEDIA
        sendReplyLine("ACK_EOF");
        return;
      }
      strlcpy(bgImage, cleanName.c_str(), sizeof(bgImage));
      prefs.putString("bg", bgImage);
      needFullDraw = true;
      sendReplyLine("ACK_EOF");
      listSdFilesToSerial();
      return;
    }
  }

  // 3) Processa bloco "ui" (ou chaves na raiz para retrocompatibilidade)
  JsonVariant root = doc.as<JsonVariant>();
  JsonVariant ui = root["ui"].isNull() ? root : root["ui"].as<JsonVariant>();

  // -- Tela (current_screen / screen) --
  JsonVariant vScr = ui["screen"];
  if (vScr.isNull()) vScr = ui["current_screen"];
  if (vScr.isNull()) vScr = root["current_screen"];
  if (!vScr.isNull()) {
    uint8_t newScr = currentScreen;
    if (vScr.is<int>()) {
      newScr = (uint8_t)(vScr.as<int>() % SCREENS);
    } else if (vScr.is<const char*>()) {
      String s = String(vScr.as<const char*>());
      s.toLowerCase();
      if (s.indexOf("term") >= 0 || s.indexOf("deck") >= 0 || s.indexOf("cmd") >= 0 || s.indexOf("sh") >= 0) newScr = SCR_TERMINAL;
      else if (s.indexOf("news") >= 0 || s.indexOf("notic") >= 0 || s.indexOf("wth") >= 0 || s.indexOf("clim") >= 0 || s.indexOf("gem") >= 0 || s.indexOf("vot") >= 0) newScr = SCR_NEWS;
      else if (s.indexOf("pomo") >= 0 || s.indexOf("foco") >= 0) newScr = SCR_POMODORO;
      else if (s.indexOf("med") >= 0 || s.indexOf("spot") >= 0 || s.indexOf("yt") >= 0 || s.indexOf("mus") >= 0) newScr = SCR_MEDIA;
      else if (s.indexOf("port") >= 0 || s.indexOf("cart") >= 0 || s.indexOf("patr") >= 0) newScr = SCR_PORTFOLIO;
      else if (s.indexOf("mkt") >= 0 || s.indexOf("merc") >= 0 || s.indexOf("bolsa") >= 0) newScr = SCR_MARKET;
      else if (s.indexOf("dual") >= 0) newScr = SCR_CPU_RAM_DUAL;
      else if (s.indexOf("cpu") >= 0)  newScr = SCR_CPU_RAM;
      else if (s.indexOf("gpu") >= 0)  newScr = SCR_GPU_FOCUS;
      else if (s.indexOf("graf") >= 0 || s.indexOf("graph") >= 0) newScr = SCR_GRAPH;
      else if (s.indexOf("wall") >= 0) newScr = SCR_WALLPAPER;
      else                             newScr = SCR_RESUMO;
    }
    if (newScr != currentScreen) {
      currentScreen = newScr;
      prefs.putUChar("screen", currentScreen);
      needFullDraw = true;
    }
  }

  // -- Cor dos Textos/UI (text_color / color / cmd_color) --
  JsonVariant vCol = ui["color"];
  if (vCol.isNull()) vCol = ui["text_color"];
  if (vCol.isNull()) vCol = root["text_color"];
  if (vCol.isNull()) vCol = root["cmd_color"];
  if (!vCol.isNull()) {
    uint16_t newCol = parseColorVariant(vCol);
    if (newCol != currentColor565) {
      applyColor565(newCol);
      prefs.putUShort("color565", currentColor565);
      needFullDraw = true;
    }
  }

  // -- Imagem de Fundo (bg / bg_image / cmd_gif) --
  JsonVariant vBg = ui["bg"];
  if (vBg.isNull()) vBg = ui["bg_image"];
  if (vBg.isNull()) vBg = root["bg_image"];
  if (vBg.isNull()) vBg = root["cmd_gif"];
  if (!vBg.isNull() && vBg.is<const char*>()) {
    const char* newBg = vBg.as<const char*>();
    if (newBg && strcmp(newBg, bgImage) != 0) {
      strlcpy(bgImage, newBg, sizeof(bgImage));
      prefs.putString("bg", bgImage);
      needFullDraw = true;
    }
  }

  // -- Brilho PWM (brt / brightness / cmd_bright) --
  JsonVariant vBrt = ui["brt"];
  if (vBrt.isNull()) vBrt = ui["brightness"];
  if (vBrt.isNull()) vBrt = root["brightness"];
  if (vBrt.isNull()) vBrt = root["cmd_bright"];
  if (!vBrt.isNull()) {
    int newBrt = constrain(vBrt.as<int>(), 0, 255);
    if (newBrt != currentBrightness) {
      setBacklight(newBrt, true);
      if (newBrt > 0) {
        prefs.putInt("bright", currentBrightness);
      }
    }
  }

  // -- Controle do Ticker Tape no rodape (ticker: true/false) --
  if (!ui["ticker"].isNull()) {
    bool newT = ui["ticker"].as<bool>();
    if (newT != showTickerBar) {
      showTickerBar = newT;
      needFullDraw = true;
    }
  }

  // 4) Processa Dados do Mercado Financeiro ("mkt")
  JsonVariant jm = root["mkt"];
  if (!jm.isNull()) {
    mkt.usd     = jm["usd"]     | mkt.usd;
    mkt.usdc    = jm["usdc"]    | mkt.usdc;
    mkt.eur     = jm["eur"]     | mkt.eur;
    mkt.eurc    = jm["eurc"]    | mkt.eurc;
    mkt.ibov    = jm["ibov"]    | mkt.ibov;
    mkt.ibovc   = jm["ibovc"]   | mkt.ibovc;
    mkt.sp500   = jm["sp500"]   | mkt.sp500;
    mkt.sp500c  = jm["sp500c"]  | mkt.sp500c;
    mkt.btc     = jm["btc"]     | mkt.btc;
    mkt.btcc    = jm["btcc"]    | mkt.btcc;
    mkt.btc_brl = jm["btc_brl"] | mkt.btc_brl;
    mkt.eth     = jm["eth"]     | mkt.eth;
    mkt.ethc    = jm["ethc"]    | mkt.ethc;
    mkt.sol     = jm["sol"]     | mkt.sol;
    mkt.solc    = jm["solc"]    | mkt.solc;
    mkt.bnb     = jm["bnb"]     | mkt.bnb;
    mkt.bnbc    = jm["bnbc"]    | mkt.bnbc;
    mkt.xrp     = jm["xrp"]     | mkt.xrp;
    mkt.xrpc    = jm["xrpc"]    | mkt.xrpc;

    if (jm["btch"].is<JsonArray>()) {
      JsonArray arr = jm["btch"].as<JsonArray>();
      uint8_t idx = 0;
      for (JsonVariant v : arr) {
        if (idx >= BTC_HIST_LEN) break;
        mkt.hBtc[idx++] = (uint8_t)constrain(v.as<int>(), 0, 100);
      }
      if (idx > 0) mkt.hBtcCount = idx;
    }
    if (mkt.usd > 0 || mkt.btc > 0) {
      mkt.valid = true;
    }
  }

  // 4.5) Processa Gestao de Portfolio de Investimentos ("portf")
  JsonVariant jp = root["portf"];
  if (!jp.isNull()) {
    portf.tot     = jp["tot"]     | portf.tot;
    portf.pnl_pct = jp["pnl_pct"] | portf.pnl_pct;
    portf.pnl_val = jp["pnl_val"] | portf.pnl_val;
    portf.day_pct = jp["day_pct"] | portf.day_pct;
    portf.count   = jp["cnt"]     | portf.count;

    if (jp["top3"].is<JsonArray>()) {
      JsonArray arr = jp["top3"].as<JsonArray>();
      for (int k = 0; k < 3; k++) {
        strlcpy(portf.top3[k], "---", sizeof(portf.top3[k]));
        portf.top3c[k] = 0.0f;
        portf.top3w[k] = 0.0f;
      }
      uint8_t idx = 0;
      for (JsonVariant v : arr) {
        if (idx >= 3) break;
        const char* sym = v.as<const char*>();
        if (sym && sym[0]) {
          strlcpy(portf.top3[idx], sym, sizeof(portf.top3[idx]));
          idx++;
        }
      }
      portf.topCount = idx;
    }

    if (jp["top3c"].is<JsonArray>()) {
      JsonArray arrC = jp["top3c"].as<JsonArray>();
      uint8_t idx = 0;
      for (JsonVariant v : arrC) {
        if (idx >= 3) break;
        portf.top3c[idx++] = v.as<float>();
      }
      portf.hasTop3c = (idx > 0);
    } else {
      portf.hasTop3c = false;
    }

    if (jp["top3w"].is<JsonArray>()) {
      JsonArray arrW = jp["top3w"].as<JsonArray>();
      uint8_t idx = 0;
      for (JsonVariant v : arrW) {
        if (idx >= 3) break;
        portf.top3w[idx++] = v.as<float>();
      }
    }

    portf.valid = (portf.topCount > 0 || portf.tot > 0.0f);
    linked = true;
    lastPacket = millis();
  }

  // 5) Processa Telemetria de Hardware em "sys" (ou na raiz do JSON)
  JsonVariant sys = root["sys"].isNull() ? root : root["sys"].as<JsonVariant>();
  if (!sys["cpu"].isNull() || !sys["ram"].isNull() || !sys["gpu"].isNull()) {
    st.cpu   = sys["cpu"]   | st.cpu;
    if (!sys["cput"].isNull())      st.cput = sys["cput"].as<float>();
    else if (!sys["temp"].isNull()) st.cput = sys["temp"].as<float>();

    st.cpuf  = sys["cpuf"]  | st.cpuf;
    st.cores = sys["cores"] | st.cores;
    st.load  = sys["load"]  | st.load;
    st.gpu   = sys["gpu"]   | -1.0f;
    st.gput  = sys["gput"]  | -1.0f;
    st.vram  = sys["vram"]  | -1.0f;
    st.vramu = sys["vramu"] | -1.0f;
    st.vramt = sys["vramt"] | -1.0f;
    st.gpuw  = sys["gpuw"]  | -1.0f;
    st.ram   = sys["ram"]   | st.ram;
    st.ramu  = sys["ramu"]  | st.ramu;
    st.ramt  = sys["ramt"]  | st.ramt;
    st.swap  = sys["swap"]  | st.swap;
    st.dsk   = sys["dsk"]   | st.dsk;
    st.dskf  = sys["dskf"]  | st.dskf;
    st.dr    = sys["dr"]    | 0.0f;
    st.dw    = sys["dw"]    | 0.0f;
    st.rx    = sys["rx"]    | 0.0f;
    st.tx    = sys["tx"]    | 0.0f;
    st.fan   = sys["fan"]   | -1;
    st.hh    = sys["hh"]    | st.hh;
    st.mm    = sys["mm"]    | st.mm;
    st.game  = sys["game"]  | false;
    st.fps   = sys["fps"]   | -1;
    st.up    = sys["up"]    | st.up;

    if (!sys["host"].isNull())    strlcpy(st.host,    sys["host"]    | "PC",  sizeof(st.host));
    if (!sys["top"].isNull())     strlcpy(st.top,     sys["top"]     | "",    sizeof(st.top));
    if (!sys["gpuname"].isNull()) strlcpy(st.gpuname, sys["gpuname"] | "GPU", sizeof(st.gpuname));

    hCpu[hPos] = (uint8_t)constrain(st.cpu, 0.0f, 100.0f);
    hGpu[hPos] = (uint8_t)constrain(st.gpu < 0 ? 0.0f : st.gpu, 0.0f, 100.0f);
    hRam[hPos] = (uint8_t)constrain(st.ram, 0.0f, 100.0f);
    float t = maxTemp();
    hTmp[hPos] = (uint8_t)constrain(t < 0 ? 0.0f : t, 0.0f, 100.0f);
    hPos = (hPos + 1) % HIST;
    if (hPos == 0) hFilled = true;

    packets++;
    lastPacket = millis();
    if (!linked) {
      linked = true;
      needFullDraw = true;
    }
  }

  // 6) Processa Bloco Pomodoro ("pomo") - Modulo 3
  JsonVariant pm = root["pomo"];
  if (!pm.isNull()) {
    if (!pm["st"].isNull()) sanitizeAscii(pomo.state, pm["st"] | "WORK", sizeof(pomo.state));
    pomo.running = pm["run"] | pomo.running;
    int32_t newRem = pm["rem"] | pomo.rem;
    if (newRem > 2) pomo.chimeGuard = false;
    pomo.rem     = newRem;
    pomo.tot     = pm["tot"] | pomo.tot;
    pomo.cycles  = pm["cyc"] | pomo.cycles;
    pomo.syncMs  = millis();
    pomo.valid   = true;

    if (pm["done"] | false) {
      bool isBrk = (strcasecmp(pomo.state, "WORK") != 0);
      triggerAlert(true, isBrk ? 0x07FF : 0x07E0, 3);
      pomo.chimeGuard = true;
    }
  }

  // 7) Processa Bloco Multimidia Spotify / YouTube Music ("media") - Modulo 3
  JsonVariant md = root["media"];
  if (!md.isNull()) {
    if (!md["src"].isNull()) sanitizeAscii(mediaSt.source, md["src"] | "MEDIA", sizeof(mediaSt.source));
    mediaSt.playing = md["play"] | false;
    if (!md["tit"].isNull()) sanitizeAscii(mediaSt.title,  md["tit"] | "", sizeof(mediaSt.title));
    if (!md["art"].isNull()) sanitizeAscii(mediaSt.artist, md["art"] | "", sizeof(mediaSt.artist));
    if (!md["alb"].isNull()) sanitizeAscii(mediaSt.album,  md["alb"] | "", sizeof(mediaSt.album));
    mediaSt.pos = md["pos"] | 0;
    mediaSt.dur = md["dur"] | 0;
    if (!md["cov"].isNull()) sanitizeAscii(mediaSt.coverFile, md["cov"] | "_media_cov.jpg", sizeof(mediaSt.coverFile));
    if (!md["cid"].isNull()) sanitizeAscii(mediaSt.coverId,   md["cid"] | "", sizeof(mediaSt.coverId));
    mediaSt.syncMs = millis();
    mediaSt.valid  = true;
  }

  // 7.5) Processa Clima Regional, Data & Localidade ("wth") + Gemini Gems ("gem")
  JsonVariant jw = root["wth"];
  if (!jw.isNull()) {
    if (!jw["city"].isNull()) sanitizeAscii(wth.city, jw["city"] | "Votuporanga", sizeof(wth.city));
    if (!jw["dt"].isNull())   sanitizeAscii(wth.dateShort, jw["dt"]  | "--/--", sizeof(wth.dateShort));
    if (!jw["dtf"].isNull())  sanitizeAscii(wth.dateFull,  jw["dtf"] | "--/--/----", sizeof(wth.dateFull));
    if (!jw["dow"].isNull())  sanitizeAscii(wth.dow,       jw["dow"] | "---", sizeof(wth.dow));
    if (!jw["temp"].isNull()) {
      wth.temp  = jw["temp"]  | wth.temp;
      wth.valid = true;
    }
    wth.feels    = jw["feels"] | wth.feels;
    wth.tmin     = jw["tmin"]  | wth.tmin;
    wth.tmax     = jw["tmax"]  | wth.tmax;
    wth.hum      = (uint8_t)constrain((int)(jw["hum"]  | wth.hum), 0, 100);
    wth.wind     = jw["wind"]  | wth.wind;
    wth.rainProb = (uint8_t)constrain((int)(jw["rain"] | wth.rainProb), 0, 100);
    wth.icon     = (uint8_t)constrain((int)(jw["icon"] | wth.icon), 0, 3);
    if (!jw["cond"].isNull()) sanitizeAscii(wth.cond, jw["cond"] | "Normal", sizeof(wth.cond));
    if (!jw["amsg"].isNull()) sanitizeAscii(wth.alertMsg, jw["amsg"] | "TEMPESTADE NA REGIAO!", sizeof(wth.alertMsg));

    bool newAlert = jw["alert"] | false;
    if (newAlert && !wth.alert) {
      // Dispara aviso sonoro + LED vermelho critico ao iniciar um Alerta de Tempestade!
      triggerAlert(true, 0xF800, 3);
    }
    wth.alert = newAlert;
  }

  JsonVariant jg = root["gem"];
  if (!jg.isNull()) {
    if (!jg["tit"].isNull()) sanitizeAscii(wth.gemTitle, jg["tit"] | "News Feed", sizeof(wth.gemTitle));
    if (!jg["txt"].isNull()) sanitizeAscii(wth.gemText,  jg["txt"] | "", sizeof(wth.gemText));
    if (!jg["tm"].isNull())  sanitizeAscii(wth.gemTime,  jg["tm"]  | "--:--", sizeof(wth.gemTime));
    if (!jg["mdl"].isNull()) sanitizeAscii(wth.gemModel, jg["mdl"] | "RSS-LIVE", sizeof(wth.gemModel));
    wth.gemValid = true;
    // Se nenhuma noticia dedicada foi recebida ainda, popula a fila a partir do resumo
    if (!newsSt.valid && wth.gemText[0]) {
      pushNewsToQueue(wth.gemTitle, wth.gemText, wth.gemModel, wth.gemTime, true);
    }
  }

  // 7.6) Processa Modulo 1: Feed de Noticias Customizavel ("news")
  JsonVariant jn = root["news"];
  if (!jn.isNull()) {
    // Se enviou uma fila completa de manchetes ("queue")
    if (jn["queue"].is<JsonArray>()) {
      JsonArray qArr = jn["queue"].as<JsonArray>();
      for (JsonVariant item : qArr) {
        const char* tp = item["topic"]    | (jn["topic"] | "Noticias");
        const char* hl = item["headline"] | "";
        const char* sr = item["src"]      | "News RSS";
        const char* tm = item["tm"]       | "--:--";
        if (hl && hl[0]) {
          pushNewsToQueue(tp, hl, sr, tm, false);
        }
      }
    }
    // Manchete principal em destaque {"news": {"topic": "Politica", "headline": "Titulo da noticia aqui..."}}
    const char* topic    = jn["topic"]    | "Noticias";
    const char* headline = jn["headline"] | "";
    const char* src      = jn["src"]      | "News API";
    const char* tm       = jn["tm"]       | "--:--";
    bool forceActive     = jn["force"]    | true;
    if (headline && headline[0]) {
      pushNewsToQueue(topic, headline, src, tm, forceActive);
    }
  }

  // 7.7) Processa Modulo 2: O Terminal CYD ("term")
  JsonVariant jt = root["term"];
  if (!jt.isNull()) {
    if (jt["clear"] | false) {
      clearTerminal();
    }
    if (!jt["cmd"].isNull()) {
      sanitizeAscii(termSt.lastCmd, jt["cmd"] | "cmd", sizeof(termSt.lastCmd));
    }
    if ((jt["auto_scr"] | false) && currentScreen != SCR_TERMINAL) {
      currentScreen = SCR_TERMINAL;
      prefs.putUChar("screen", currentScreen);
      needFullDraw = true;
    }
    if (!jt["line"].isNull()) {
      const char* ln = jt["line"] | "";
      if (ln && ln[0]) log_to_terminal(String(ln));
    }
    if (jt["lines"].is<JsonArray>()) {
      JsonArray lArr = jt["lines"].as<JsonArray>();
      for (JsonVariant v : lArr) {
        const char* ln = v.as<const char*>();
        if (ln && ln[0]) log_to_terminal(String(ln));
      }
    }
  }

  // 8) Processa Bloco de Alertas Fisicos ("alrt") - Buzzer e LED RGB
  JsonVariant alrt = root["alrt"];
  if (!alrt.isNull()) {
    bool bz = alrt["bz"] | false;
    uint16_t ledCol = C_WARN;
    if (!alrt["led"].isNull()) {
      ledCol = parseColorVariant(alrt["led"]);
    }
    uint8_t pat = alrt["p"] | 1;
    triggerAlert(bz, ledCol, pat);
  }
}

void pumpSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen > 2) {
        lineBuf[lineLen] = 0;
        applyJson(lineBuf);
      }
      lineLen = 0;
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    } else {
      lineLen = 0;
    }
  }
}

// ======================================= Listener UDP Nao-Bloqueante (Wi-Fi) ==
void initWiFiAndUDP() {
  String savedSsid = prefs.getString("wifi_ssid", "");
  String savedPass = prefs.getString("wifi_pass", "");
  if (savedSsid.length() > 0) {
    strlcpy(wifiSsid, savedSsid.c_str(), sizeof(wifiSsid));
    strlcpy(wifiPass, savedPass.c_str(), sizeof(wifiPass));
  }

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false); // Desativa modem-sleep para latencia UDP minima e zero perda de pacotes

  if (wifiSsid[0] != '\0' && strcmp(wifiSsid, "SUA_REDE_WIFI") != 0) {
    WiFi.begin(wifiSsid, wifiPass);
    // Aguarda ate ~3.0s na tela de boot (em passos curtos de 100ms) sem travar caso o roteador demore
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - t0) < 3000) {
      pumpSerial();
      delay(100);
    }
    if (WiFi.status() == WL_CONNECTED) {
      wifiWasConnected = true;
      udp.begin(UDP_PORT);
      udpListening = true;
      String ipStr = WiFi.localIP().toString();
      Serial.printf("WIFI_IP:%s\n", ipStr.c_str());
      char uLog[64];
      snprintf(uLog, sizeof(uLog), "[UDP] Online em %s:%d", ipStr.c_str(), UDP_PORT);
      log_to_terminal(uLog);
    }
  }
}

void pumpUDP() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiWasConnected) {
      wifiWasConnected = true;
      if (!udpListening) {
        udp.begin(UDP_PORT);
        udpListening = true;
      }
      String ipStr = WiFi.localIP().toString();
      char wip[48];
      snprintf(wip, sizeof(wip), "WIFI_IP:%s", ipStr.c_str());
      sendReplyLine(wip);
      char uLog[64];
      snprintf(uLog, sizeof(uLog), "[UDP] Wi-Fi Conectado! IP: %s:%d", ipStr.c_str(), UDP_PORT);
      log_to_terminal(uLog);
      char lU[80];
      snprintf(lU, sizeof(lU), "TERM_LOG:%s", uLog);
      sendReplyLine(lU);
    }

    // Drena todos os pacotes UDP pendentes na porta 8888 sem bloquear o loop de 28 FPS
    int packetSize = udp.parsePacket();
    while (packetSize > 0) {
      lastUdpRemoteIP   = udp.remoteIP();
      lastUdpRemotePort = udp.remotePort();
      int len = udp.read(udpBuf, sizeof(udpBuf) - 1);
      if (len > 2) {
        udpBuf[len] = '\0';
        // Remove quebras de linha finais opcionais e roteia para o mesmo parser da Serial
        while (len > 0 && (udpBuf[len - 1] == '\n' || udpBuf[len - 1] == '\r')) {
          udpBuf[--len] = '\0';
        }
        replyViaUdp = true;
        applyJson(udpBuf);
        replyViaUdp = false;
      }
      packetSize = udp.parsePacket();
    }
  } else {
    if (wifiWasConnected) {
      wifiWasConnected = false;
    }
    // Reconexao automatica nao-bloqueante a cada 12 segundos se houver SSID configurado
    if (wifiSsid[0] != '\0' && strcmp(wifiSsid, "SUA_REDE_WIFI") != 0) {
      if (millis() - lastWifiCheckMs >= 12000) {
        lastWifiCheckMs = millis();
        WiFi.reconnect();
      }
    }
  }
}

// Botao BOOT fisico na placa (opcional para alternar telas manualmente)
void pumpBootButton() {
  static uint32_t bootDown = 0;
  if (digitalRead(PIN_BOOT) == LOW) {
    if (bootDown == 0) bootDown = millis();
  } else {
    if (bootDown > 0 && (millis() - bootDown > 40)) {
      currentScreen = (currentScreen + 1) % SCREENS;
      needFullDraw = true;
    }
    bootDown = 0;
  }
}

// ================================================================ setup ====
void setup() {
  Serial.begin(115200);

  pinMode(LED_R, OUTPUT);
  pinMode(LED_G, OUTPUT);
  pinMode(LED_B, OUTPUT);
  setLed(0, 0, 0);

  pinMode(PIN_BOOT, INPUT_PULLUP);

  // Carrega configuracoes persistidas na Flash (NVS)
  prefs.begin("cyd_mon", false);
  currentScreen     = prefs.getUChar("screen", SCR_CPU_RAM) % SCREENS;
  currentColor565   = prefs.getUShort("color565", 0x07E0);
  currentBrightness = prefs.getInt("bright", 200);
  alarmEnabled      = prefs.getBool("alarm", false);
  String savedBg    = prefs.getString("bg", "none");
  strlcpy(bgImage, savedBg.c_str(), sizeof(bgImage));

  applyColor565(currentColor565);
  initBacklight(currentBrightness);

  tft.init();
  tft.setRotation(SCREEN_ROTATION);
  tft.fillScreen(C_BG);

  // Inicializa Sprite de 320x18 para o Letreiro Infinito da Bolsa (Ticker Tape Flicker-Free)
  tickerSpr.setColorDepth(16);
  if (tickerSpr.createSprite(SCR_W, TICKER_H) != nullptr) {
    tickerSprReady = true;
    tickerSpr.setTextWrap(false, false);
  }

  // Inicializa Sprite de 296x26 para o Feed de Noticias Deslizante (SCR_NEWS)
  newsSpr.setColorDepth(16);
  if (newsSpr.createSprite(NEWS_SPR_W, NEWS_SPR_H) != nullptr) {
    newsSprReady = true;
    newsSpr.setTextWrap(false, false);
  }

  // Inicializa buffer do Terminal Cyber Deck (SCR_TERMINAL)
  clearTerminal();

  // Inicializa decodificador JPEG para imagens estaticas do Cartao SD
  TJpgDec.setJpgScale(1);
  TJpgDec.setCallback(tft_output);
  TJpgDec.setSwapBytes(true);

  // Inicializa Cartao SD no barramento VSPI (Pinos 18, 19, 23, CS=5)
  initOrVerifySD();

  memset(hCpu, 0, sizeof(hCpu));
  memset(hGpu, 0, sizeof(hGpu));
  memset(hRam, 0, sizeof(hRam));
  memset(hTmp, 0, sizeof(hTmp));
  memset(mkt.hBtc, 50, sizeof(mkt.hBtc));

  // Splash Screen Moderna + Inicializacao Wi-Fi UDP (Porta 8888)
  tft.fillScreen(C_BG);
  drawModernCard(24, 28, SCR_W - 48, SCR_H - 56, "SYSTEM BOOT • HYBRID UDP/USB");
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(C_ACCENT, C_CARD);
  tft.drawString("CYD CYBER DECK", SCR_W / 2, 70, 4);
  tft.drawString("v4.3 WI-FI UDP", SCR_W / 2, 98, 4);
  tft.setTextColor(C_TEXT, C_CARD);
  tft.drawString("Iniciando Wi-Fi & Listener UDP :8888...", SCR_W / 2, 130, 2);
  tft.setTextColor(hasSD ? C_OK : C_WARN, C_CARD);
  tft.drawString(hasSD ? "SD Card: OK (JPG/BMP/GIF Prontos)" : "SD Card: Nao Detectado (FAT32)", SCR_W / 2, 152, 2);

  initWiFiAndUDP();

  if (WiFi.status() == WL_CONNECTED) {
    char ipSplash[48];
    snprintf(ipSplash, sizeof(ipSplash), "Wi-Fi OK! UDP -> %s:%d", WiFi.localIP().toString().c_str(), UDP_PORT);
    tft.setTextColor(C_OK, C_CARD);
    tft.drawString(ipSplash, SCR_W / 2, 174, 2);
  } else {
    tft.setTextColor(C_DIM, C_CARD);
    tft.drawString("USB Serial 115200 Ativo (Wi-Fi em standby)", SCR_W / 2, 174, 2);
  }
  delay(750);

  Serial.println("MONITOR_READY");
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("WIFI_IP:%s\n", WiFi.localIP().toString().c_str());
  }
  listSdFilesToSerial();
}

// ================================================================= loop ====
void loop() {
  pumpSerial();
  pumpUDP();
  pumpBootButton();
  pumpAlerts(); // Execucao de bipes e flashes do alerta sem bloquear a CPU

  // Perdeu sinal do PC apos 5 segundos?
  if (linked && millis() - lastPacket > 5000) {
    linked = false;
    needFullDraw = true;
  }

  // LED RGB traseiro: so aplica status termico se nao houver alerta ativo!
  if (!alertEngine.active) {
    float t = maxTemp();
    if (!linked)              setLed(0, 0, 1); // Azul aguardando conexao
    else if (t >= T_TEMP_MAX) setLed(1, 0, 0); // Vermelho critico
    else if (t >= T_TEMP_HOT) setLed(1, 1, 0); // Amarelo atencao
    else                      setLed(0, 1, 0); // Verde normal
  }

  // Redesenho completo da estrutura estatica apenas quando muda tela, cor ou imagem de fundo
  if (needFullDraw) {
    resetDrawCache();
    if      (currentScreen == SCR_RESUMO)       screenResumoStatic();
    else if (currentScreen == SCR_CPU_RAM)      screenCpuRamStatic();
    else if (currentScreen == SCR_CPU_RAM_DUAL) screenCpuRamDualStatic();
    else if (currentScreen == SCR_GPU_FOCUS)    screenGpuFocusStatic();
    else if (currentScreen == SCR_GRAPH)        screenGraphStatic();
    else if (currentScreen == SCR_WALLPAPER)    screenWallpaperStatic();
    else if (currentScreen == SCR_MARKET)       screenMarketStatic();
    else if (currentScreen == SCR_PORTFOLIO)    screenPortfolioStatic();
    else if (currentScreen == SCR_POMODORO)     screenPomodoroStatic();
    else if (currentScreen == SCR_MEDIA)        screenMediaStatic();
    else if (currentScreen == SCR_NEWS)         screenNewsStatic();
    else if (currentScreen == SCR_TERMINAL)     screenTerminalStatic();
    needFullDraw = false;
  }

  // Se o usuario escolheu um GIF animado no SD, avanca o frame
  if (isGifPlaying && hasSD) {
    if (!gif.playFrame(true, NULL)) {
      gif.reset();
    }
  }

  // Atualizacao fluida do Letreiro Infinito da Bolsa e do Sprite de Noticias (~28 FPS)
  static uint32_t lastTicker = 0;
  if (millis() - lastTicker >= 35) {
    lastTicker = millis();
    updateTickerTape();
    if (currentScreen == SCR_NEWS) {
      updateNewsHeadlineSprite();
    }
  }

  // Atualizacao dinamica das metricas (sem piscar o fundo!)
  static uint32_t lastRefresh = 0;
  if (millis() - lastRefresh >= 250) {
    lastRefresh = millis();
    if      (currentScreen == SCR_RESUMO)       screenResumoDynamic();
    else if (currentScreen == SCR_CPU_RAM)      screenCpuRamDynamic();
    else if (currentScreen == SCR_CPU_RAM_DUAL) screenCpuRamDualDynamic();
    else if (currentScreen == SCR_GPU_FOCUS)    screenGpuFocusDynamic();
    else if (currentScreen == SCR_GRAPH)        screenGraphDynamic();
    else if (currentScreen == SCR_WALLPAPER)    screenWallpaperDynamic();
    else if (currentScreen == SCR_MARKET)       screenMarketDynamic();
    else if (currentScreen == SCR_PORTFOLIO)    screenPortfolioDynamic();
    else if (currentScreen == SCR_POMODORO)     screenPomodoroDynamic();
    else if (currentScreen == SCR_MEDIA)        screenMediaDynamic();
    else if (currentScreen == SCR_NEWS)         screenNewsDynamic();
    else if (currentScreen == SCR_TERMINAL)     screenTerminalDynamic();

    drawClock();
    drawStormAlertBanner();
  }

  delay(5);
}
