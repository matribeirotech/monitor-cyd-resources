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
// CYD OS v5.0 Obsidian Dark Palette (atualizada em tempo real via applyColor565)
uint16_t C_BG          = 0x0842; // Deep obsidian #070B14
uint16_t C_CARD        = 0x08A5; // Elevated dark slate #0F172A
uint16_t C_CARD_ELEV   = 0x1106; // Nested pill/badge slate #162033
uint16_t C_CARD_HI     = 0x2189; // Subtle hairline border
uint16_t C_TRACK       = 0x1926; // Recessed progress track #1A2436
uint16_t C_TEXT        = 0xF7BE; // Crisp off-white #F1F5F9
uint16_t C_DIM         = 0x8CD6; // Cool slate #8A9BB5
uint16_t C_MUTED       = 0x4AF0; // Subtle slate #4D5E78
uint16_t C_ACCENT      = 0x07E0; // Dynamic user accent color
uint16_t C_ACCENT_SOFT = 0x09C5; // Subtle tinted pill surface
uint16_t C_ACCENT_DK   = 0x08E3; // Sleek dark header bar surface
uint16_t C_OK          = 0x262B; // Emerald #22C55E
uint16_t C_WARN        = 0xF4E1; // Amber #F59E0B
uint16_t C_HOT         = 0xEA28; // Coral Red #EF4444
uint16_t C_COOL        = 0x3DFF; // Sky Cyan #38BDF8
uint16_t C_PURPLE      = 0xAAAE; // Violet #A855F7
uint16_t C_PINK        = 0xEA53; // Rose #EC4899

uint8_t  currentScreen     = SCR_RESUMO;
uint16_t currentColor565   = 0x07E0; // Accent padrao (harmonizado no tema v5.0)
int      currentBrightness = 200;    // 0-255
char     bgImage[64]       = "none"; // Ex: "cyberpunk.jpg", "terminal", "z1p0", "none"
bool     hasBgBitmap       = false;  // true quando ha um JPG/BMP desenhado no fundo
bool     alarmEnabled      = false;

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
int      targetBrightness = 200;
uint32_t lastFadeMs       = 0;

static void writeBacklightHw(int brt) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(PIN_BL, brt);
#else
  ledcWrite(BL_PWM_CH, brt);
#endif
}

void initBacklight(int brt) {
  currentBrightness = constrain(brt, 5, 255);
  targetBrightness  = currentBrightness;
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
  targetBrightness = targetBrt;
  if (!smooth || targetBrt == currentBrightness) {
    currentBrightness = targetBrt;
    writeBacklightHw(currentBrightness);
    return;
  }
  // Transicao suave 100% nao-bloqueante executada por pumpBacklight() no loop()
  // (evita travar pumpSerial() por 300-500ms durante mudancas de brilho / sleep!)
  lastFadeMs = millis();
}

void pumpBacklight() {
  if (currentBrightness == targetBrightness) return;
  uint32_t now = millis();
  if (now - lastFadeMs < 4) return;
  lastFadeMs = now;
  int diff = targetBrightness - currentBrightness;
  int step = (abs(diff) > 16) ? 4 : ((abs(diff) > 6) ? 2 : 1);
  if (diff > 0) currentBrightness = min(targetBrightness, currentBrightness + step);
  else          currentBrightness = max(targetBrightness, currentBrightness - step);
  writeBacklightHw(currentBrightness);
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

// ======================================= Modulo 3: Radar Wi-Fi RF (SCR_WIFI_RADAR / Tela 12)
#define WRAD_MAX_APS 6

struct WifiRadarAp {
  char    ssid[18];
  int16_t rssi;
  uint8_t ch;
  char    bssid[18];
};

struct WifiRadarState {
  bool        valid      = false;
  bool        online     = false;
  bool        scanning   = false;
  char        port[16]   = "";
  uint8_t     total      = 0;
  uint8_t     newCount   = 0;
  int16_t     bestRssi   = 0;
  int16_t     avgRssi    = 0;
  uint8_t     busiestCh  = 0;
  uint8_t     freeCh     = 1;
  uint16_t    ageSec     = 999;
  uint16_t    scanCount  = 0;
  bool        bleConn    = false;
  uint8_t     bleClients = 0;
  int8_t      blePwr     = 9;
  uint8_t     chCounts[13] = {0};
  WifiRadarAp aps[WRAD_MAX_APS];
  uint8_t     apCount    = 0;
  bool        dirty      = true;
} wrad;

// Animacao de Fluxo de Dados & Pacotes na Rede (Tela 12 - Sprite 8-bit flicker-free)
#define NETFLOW_W         304
#define NETFLOW_H         48
#define NETFLOW_MAX_PKTS  14

struct FlowPacket {
  float   x;
  float   speed;
  int8_t  dir;    // +1 (esq->dir) ou -1 (dir->esq)
  uint8_t lane;   // 0=RX (topo), 1=TX (baixo), 2=RF/BLE (direita)
  uint8_t type;   // 0=RX cyan/green, 1=TX orange, 2=RF/BLE magenta, 3=CRIT red
  bool    active;
};

TFT_eSprite netFlowSpr      = TFT_eSprite(&tft);
bool        netFlowSprReady = false;
FlowPacket  flowPkts[NETFLOW_MAX_PKTS];
uint16_t    flowAnimTick    = 0;

// ======================================= Modulo 4: Analise de Rede & Roteador (Tela 13)
struct NetAnalyzerState {
  bool     valid     = false;
  char     gw[20]    = "---";
  char     iface[12] = "eth0";
  char     localIp[20] = "---";
  bool     gwUp      = false;
  float    gwMs      = 0.0f;
  float    gwJit     = 0.0f;
  uint8_t  loss      = 0;
  uint16_t gwHttp    = 0;
  bool     wanUp     = false;
  float    wanMs     = 0.0f;
  int16_t  dnsMs     = 0;
  float    rxMbps    = 0.0f;
  float    txMbps    = 0.0f;
  uint16_t planMbps  = 700;
  uint8_t  lanCount  = 0;
  char     isp[20]   = "ISP";
  bool     spdRun    = false;
  float    spdDl     = 0.0f;
  float    spdUl     = 0.0f;
  char     spdTm[10] = "--:--";
  bool     dirty     = true;
} neta;

// ======================================= Modulo 5: Seguranca, IDS & Logs (Tela 14)
#define SEC_MAX_LOGS 6

struct SecLogEntry {
  uint8_t sev;      // 0=INFO, 1=WARN/ERR, 2=CRIT/INVASAO
  char    hm[7];    // "HH:MM"
  char    msg[40];  // mensagem sanitizada
};

struct SecurityState {
  bool        valid       = false;
  uint8_t     level       = 0; // 0=SEGURO, 1=ATENCAO, 2=INVASAO!
  char        status[14]  = "SEGURO";
  uint16_t    authFails   = 0;
  uint16_t    sysErrors   = 0;
  uint16_t    portScans   = 0;
  uint16_t    unknownLan  = 0;
  uint16_t    openPorts   = 0;
  uint16_t    extConns    = 0;
  char        lastIp[20]  = "---";
  char        lastAlert[46] = "";
  char        lastTime[10]  = "--:--";
  SecLogEntry logs[SEC_MAX_LOGS];
  uint8_t     logCount    = 0;
  bool        dirty       = true;
} sec;

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

#define LINK_TIMEOUT_MS 8000UL
#define SERIAL_RX_BUF_SZ 8192

bool     linked       = false;
uint32_t lastPacket   = 0;
uint32_t packets      = 0;
bool     needFullDraw = true;

// Historico para os graficos de hardware
uint8_t  hCpu[HIST], hGpu[HIST], hRam[HIST], hTmp[HIST];
uint16_t hPos    = 0;
bool     hFilled = false;

char     lineBuf[4096];
uint16_t lineLen      = 0;
bool     lineOverflow = false;

// Caches de desenho dos gauges circulares e boxes dinamicos (evita flicker)
int32_t  gGaugeEnd[GAUGE_SLOTS] = {-999, -999, -999, -999};
uint16_t gGaugeCol[GAUGE_SLOTS] = {0, 0, 0, 0};
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
bool     gLastSecAlert   = false;
uint8_t  gLastSecFlash   = 255;

void resetDrawCache() {
  for (int i = 0; i < GAUGE_SLOTS; i++) {
    gGaugeEnd[i] = -999;
    gGaugeCol[i] = 0;
  }
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
  gLastSecFlash = 255;
  termSt.dirty = true;
  wrad.dirty = true;
  neta.dirty = true;
  sec.dirty = true;
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
    // Micro-dot obsidian canvas sutil (estilo moderno, zero poluicao visual)
    uint16_t dotCol = blend565(C_BG, C_MUTED, 40);
    for (int y = HDR_H + 12; y < TICKER_Y; y += 20) {
      for (int x = 12; x < SCR_W; x += 20) {
        tft.drawPixel(x, y, dotCol);
      }
    }
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

// ======================================= CYD OS v5.0 Modular UI Engine =====
#include "ui_components.h"
#include "ui_screens_sys.h"
#include "ui_screens_life.h"
#include "ui_screens_cyber.h"

// ================================================= Serial & UDP / Protocolo JSON =
void applyJson(const char *json) {
  JsonDocument doc;
  if (deserializeJson(doc, json)) return;

  // 00) Heartbeat Serial/UDP do agente: responde uptime + IP (mantem link vivo se ja conectado)
  if (doc["cmd"] == "ser_ping") {
    if (linked) lastPacket = millis();
    char pong[64];
    snprintf(pong, sizeof(pong), "SER_PONG:%lu:%s:%lu",
             (unsigned long)(millis() / 1000UL),
             (WiFi.status() == WL_CONNECTED) ? WiFi.localIP().toString().c_str() : "",
             (unsigned long)ESP.getFreeHeap());
    sendReplyLine(pong);
    return;
  }
  if (doc["cmd"] == "udp_ping") {
    if (linked) lastPacket = millis();
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
    // Mantem o link vivo durante uploads longos para o Cartao SD (evita falso OFFLINE!)
    if (linked) lastPacket = millis();
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
      if (s.indexOf("sec") >= 0 || s.indexOf("seg") >= 0 || s.indexOf("ids") >= 0 || s.indexOf("inv") >= 0) newScr = SCR_SECURITY;
      else if (s.indexOf("net") >= 0 || s.indexOf("rout") >= 0 || s.indexOf("vivo") >= 0 || s.indexOf("spd") >= 0) newScr = SCR_NET_ANALYZER;
      else if (s.indexOf("radar") >= 0 || s.indexOf("wifi") >= 0 || s.indexOf("rf") >= 0) newScr = SCR_WIFI_RADAR;
      else if (s.indexOf("term") >= 0 || s.indexOf("deck") >= 0 || s.indexOf("cmd") >= 0 || s.indexOf("sh") >= 0) newScr = SCR_TERMINAL;
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

  // 7.8) Processa Modulo 3: Radar Wi-Fi Externo ("wrad") - ESP32-WROOM-32U
  JsonVariant jwr = root["wrad"];
  if (!jwr.isNull()) {
    wrad.online    = jwr["on"]   | false;
    wrad.scanning  = jwr["scan"] | false;
    if (!jwr["port"].isNull()) sanitizeAscii(wrad.port, jwr["port"] | "", sizeof(wrad.port));
    wrad.total     = (uint8_t)constrain((int)(jwr["tot"]  | 0), 0, 255);
    wrad.newCount  = (uint8_t)constrain((int)(jwr["new"]  | 0), 0, 255);
    wrad.bestRssi  = (int16_t)(jwr["best"] | 0);
    wrad.avgRssi   = (int16_t)(jwr["avg"]  | 0);
    wrad.busiestCh = (uint8_t)constrain((int)(jwr["bch"]  | 0), 0, 13);
    wrad.freeCh    = (uint8_t)constrain((int)(jwr["fch"]  | 1), 1, 13);
    wrad.ageSec    = (uint16_t)constrain((int)(jwr["age"] | 0), 0, 999);
    wrad.scanCount = (uint16_t)(jwr["sc"]  | wrad.scanCount);
    if (!jwr["ble"].isNull())  wrad.bleConn    = (jwr["ble"].as<int>() != 0);
    if (!jwr["bcli"].isNull()) wrad.bleClients = (uint8_t)constrain(jwr["bcli"].as<int>(), 0, 10);
    if (!jwr["bpwr"].isNull()) wrad.blePwr     = (int8_t)constrain(jwr["bpwr"].as<int>(), -12, 12);

    if (jwr["ch"].is<JsonArray>()) {
      JsonArray chArr = jwr["ch"].as<JsonArray>();
      uint8_t idx = 0;
      for (JsonVariant v : chArr) {
        if (idx >= 13) break;
        wrad.chCounts[idx++] = (uint8_t)constrain(v.as<int>(), 0, 99);
      }
    }

    if (jwr["aps"].is<JsonArray>()) {
      JsonArray apsArr = jwr["aps"].as<JsonArray>();
      uint8_t idx = 0;
      for (JsonVariant v : apsArr) {
        if (idx >= WRAD_MAX_APS) break;
        if (v.is<JsonArray>()) {
          JsonArray row = v.as<JsonArray>();
          const char* ss = row[0] | "<OCULTA>";
          sanitizeAscii(wrad.aps[idx].ssid, ss, sizeof(wrad.aps[idx].ssid));
          if (!wrad.aps[idx].ssid[0]) strlcpy(wrad.aps[idx].ssid, "<OCULTA>", sizeof(wrad.aps[idx].ssid));
          wrad.aps[idx].rssi = (int16_t)(row[1] | -100);
          wrad.aps[idx].ch   = (uint8_t)constrain((int)(row[2] | 0), 0, 14);
          const char* bs = row[3] | "";
          strlcpy(wrad.aps[idx].bssid, bs, sizeof(wrad.aps[idx].bssid));
          idx++;
        }
      }
      wrad.apCount = idx;
    }

    wrad.valid = true;
    wrad.dirty = true;
  }

  // 7.9) Processa Modulo 4: Analise de Rede, Roteador & Fibra ("neta")
  JsonVariant jna = root["neta"];
  if (!jna.isNull()) {
    if (!jna["gw"].isNull())  sanitizeAscii(neta.gw,      jna["gw"]  | "---", sizeof(neta.gw));
    if (!jna["if"].isNull())  sanitizeAscii(neta.iface,   jna["if"]  | "eth0", sizeof(neta.iface));
    if (!jna["ip"].isNull())  sanitizeAscii(neta.localIp, jna["ip"]  | "---", sizeof(neta.localIp));
    if (!jna["isp"].isNull()) sanitizeAscii(neta.isp,     jna["isp"] | "ISP", sizeof(neta.isp));
    if (!jna["stm"].isNull()) sanitizeAscii(neta.spdTm,   jna["stm"] | "--:--", sizeof(neta.spdTm));
    neta.gwUp     = jna["gwup"]  | neta.gwUp;
    neta.gwMs     = jna["gwms"]  | neta.gwMs;
    neta.gwJit    = jna["gwjit"] | neta.gwJit;
    neta.loss     = (uint8_t)constrain((int)(jna["loss"] | neta.loss), 0, 100);
    neta.gwHttp   = (uint16_t)(jna["gwh"] | neta.gwHttp);
    neta.wanUp    = jna["wanup"] | neta.wanUp;
    neta.wanMs    = jna["wanms"] | neta.wanMs;
    neta.dnsMs    = (int16_t)(jna["dnsms"] | neta.dnsMs);
    neta.rxMbps   = jna["rx"]    | neta.rxMbps;
    neta.txMbps   = jna["tx"]    | neta.txMbps;
    neta.planMbps = (uint16_t)constrain((int)(jna["plan"] | neta.planMbps), 10, 10000);
    neta.lanCount = (uint8_t)constrain((int)(jna["lan"] | neta.lanCount), 0, 255);
    neta.spdRun   = jna["srun"]  | false;
    neta.spdDl    = jna["sdl"]   | neta.spdDl;
    neta.spdUl    = jna["sul"]   | neta.spdUl;
    neta.valid    = true;
    neta.dirty    = true;
  }

  // 7.10) Processa Modulo 5: Seguranca, IDS & Logs de Erro ("sec") - Tela 14
  JsonVariant jsec = root["sec"];
  if (!jsec.isNull()) {
    uint8_t prevLvl = sec.level;
    sec.level      = (uint8_t)constrain((int)(jsec["lvl"] | 0), 0, 2);
    if (!jsec["st"].isNull()) sanitizeAscii(sec.status,    jsec["st"] | "SEGURO", sizeof(sec.status));
    if (!jsec["ip"].isNull()) sanitizeAscii(sec.lastIp,    jsec["ip"] | "---",    sizeof(sec.lastIp));
    if (!jsec["al"].isNull()) sanitizeAscii(sec.lastAlert, jsec["al"] | "",       sizeof(sec.lastAlert));
    if (!jsec["tm"].isNull()) sanitizeAscii(sec.lastTime,  jsec["tm"] | "--:--",  sizeof(sec.lastTime));
    sec.authFails  = (uint16_t)(jsec["af"] | 0);
    sec.sysErrors  = (uint16_t)(jsec["er"] | 0);
    sec.portScans  = (uint16_t)(jsec["ps"] | 0);
    sec.unknownLan = (uint16_t)(jsec["un"] | 0);
    sec.openPorts  = (uint16_t)(jsec["op"] | 0);
    sec.extConns   = (uint16_t)(jsec["ex"] | 0);

    if (jsec["logs"].is<JsonArray>()) {
      JsonArray lArr = jsec["logs"].as<JsonArray>();
      uint8_t idx = 0;
      for (JsonVariant v : lArr) {
        if (idx >= SEC_MAX_LOGS) break;
        if (v.is<JsonArray>()) {
          JsonArray row = v.as<JsonArray>();
          sec.logs[idx].sev = (uint8_t)constrain((int)(row[0] | 0), 0, 2);
          sanitizeAscii(sec.logs[idx].hm,  row[1] | "--:--", sizeof(sec.logs[idx].hm));
          sanitizeAscii(sec.logs[idx].msg, row[2] | "",      sizeof(sec.logs[idx].msg));
          idx++;
        }
      }
      sec.logCount = idx;
    }

    if (sec.level >= 2 && prevLvl < 2) {
      triggerAlert(true, 0xF800, 3);
    }
    sec.valid = true;
    sec.dirty = true;
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

  // Qualquer pacote JSON de dados/controle valido renova lastPacket (suporte a envio diferencial/fragmentado)
  if (!root["ui"].isNull() || !jm.isNull() || !pm.isNull() || !md.isNull() ||
      !jw.isNull() || !jn.isNull() || !jt.isNull() || !jwr.isNull() ||
      !jna.isNull() || !jsec.isNull() || !alrt.isNull()) {
    lastPacket = millis();
    if (!linked) {
      linked = true;
      needFullDraw = true;
    }
  }
}

void pumpSerial() {
  uint8_t linesProcessed = 0;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (!lineOverflow && lineLen > 2) {
        lineBuf[lineLen] = '\0';
        applyJson(lineBuf);
        linesProcessed++;
      }
      lineLen = 0;
      lineOverflow = false;
      if (linesProcessed >= 6) break; // Evita monopolizar o loop() em rajadas, drenando o restante na proxima iteracao
    } else if (!lineOverflow) {
      if (lineLen < sizeof(lineBuf) - 1) {
        lineBuf[lineLen++] = c;
      } else {
        // Linha excedeu lineBuf: descarta o restante ate '\n' em vez de embrulhar e corromper JSON
        lineOverflow = true;
        lineLen = 0;
      }
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
    // Aguarda ate ~3.0s na tela de boot (em passos curtos de 15ms drenando a Serial)
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - t0) < 3000) {
      pumpSerial();
      delay(15);
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
      IPAddress srcIP   = udp.remoteIP();
      uint16_t  srcPort = udp.remotePort();
      int len = udp.read(udpBuf, sizeof(udpBuf) - 1);
      if (len > 2) {
        udpBuf[len] = '\0';
        // Remove quebras de linha finais opcionais e roteia para o mesmo parser da Serial
        while (len > 0 && (udpBuf[len - 1] == '\n' || udpBuf[len - 1] == '\r')) {
          udpBuf[--len] = '\0';
        }
        // Broadcast puro da ESP32-WROOM-32U ("wrad") nao deve sobrescrever o IP do Agente PC
        bool isExternalRadarOnly = (strstr(udpBuf, "\"wrad\"") != nullptr) &&
                                   (strstr(udpBuf, "\"sys\"")  == nullptr) &&
                                   (strstr(udpBuf, "\"cmd\"")  == nullptr);
        if (!isExternalRadarOnly) {
          lastUdpRemoteIP   = srcIP;
          lastUdpRemotePort = srcPort;
          replyViaUdp       = true;
        } else {
          replyViaUdp       = false;
        }
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
  // Expande o ring-buffer de RX da UART0 de 256 B (padrao Arduino-ESP32) para 8 KB
  // ANTES de Serial.begin(): elimina perda de bytes durante redesenhos TFT / SD!
  Serial.setRxBufferSize(SERIAL_RX_BUF_SZ);
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

  // Inicializa Sprite 8-bit (14.5 KB) para a Ilustracao Animada de Pacotes na Rede (Tela 12)
  netFlowSpr.setColorDepth(8);
  if (netFlowSpr.createSprite(NETFLOW_W, NETFLOW_H) != nullptr) {
    netFlowSprReady = true;
    netFlowSpr.setTextWrap(false, false);
  }
  resetFlowPackets();

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

  // Splash Screen CYD OS v5.0 + Inicializacao Wi-Fi UDP (Porta 8888)
  drawBootSplash(hasSD);

  initWiFiAndUDP();

  if (WiFi.status() == WL_CONNECTED) {
    String ipStr = WiFi.localIP().toString();
    drawBootSplashWifiStatus(true, ipStr.c_str());
  } else {
    drawBootSplashWifiStatus(false, nullptr);
  }
  uint32_t splashT0 = millis();
  while (millis() - splashT0 < 450) {
    pumpSerial();
    delay(10);
  }

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
  pumpBacklight(); // Transicao suave de brilho 100% nao-bloqueante
  pumpAlerts();    // Execucao de bipes e flashes do alerta sem bloquear a CPU

  // Perdeu sinal do PC apos LINK_TIMEOUT_MS (8s)?
  if (linked && millis() - lastPacket > LINK_TIMEOUT_MS) {
    linked = false;
    needFullDraw = true;
  }

  // LED RGB traseiro: so aplica status termico se nao houver alerta ativo!
  if (!alertEngine.active) {
    float t = maxTemp();
    if (sec.level >= 2) {
      // Pisca LED vermelho em caso de invasao / alerta critico IDS!
      bool blinkOn = ((millis() / 320) % 2) == 0;
      setLed(blinkOn ? 1 : 0, 0, 0);
    } else if (!linked)        setLed(0, 0, 1); // Azul aguardando conexao
    else if (t >= T_TEMP_MAX)  setLed(1, 0, 0); // Vermelho critico
    else if (t >= T_TEMP_HOT)  setLed(1, 1, 0); // Amarelo atencao
    else if (sec.level == 1)   setLed(1, 1, 0); // Amarelo atencao IDS
    else                       setLed(0, 1, 0); // Verde normal
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
    else if (currentScreen == SCR_WIFI_RADAR)   screenWifiRadarStatic();
    else if (currentScreen == SCR_NET_ANALYZER) screenNetAnalyzerStatic();
    else if (currentScreen == SCR_SECURITY)     screenSecurityStatic();
    needFullDraw = false;
    pumpSerial(); // Drena imediatamente qualquer pacote chegado durante o redesenho completo
  }

  // Se o usuario escolheu um GIF animado no SD, avanca o frame
  if (isGifPlaying && hasSD) {
    if (!gif.playFrame(true, NULL)) {
      gif.reset();
    }
    pumpSerial();
  }

  // Atualizacao fluida do Letreiro Infinito da Bolsa, Sprite de Noticias e Fluxo de Pacotes (~28 FPS)
  static uint32_t lastTicker = 0;
  if (millis() - lastTicker >= 35) {
    lastTicker = millis();
    updateTickerTape();
    if (currentScreen == SCR_NEWS) {
      updateNewsHeadlineSprite();
    } else if (currentScreen == SCR_WIFI_RADAR) {
      updateNetFlowAnimation();
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
    else if (currentScreen == SCR_WIFI_RADAR)   screenWifiRadarDynamic();
    else if (currentScreen == SCR_NET_ANALYZER) screenNetAnalyzerDynamic();
    else if (currentScreen == SCR_SECURITY)     screenSecurityDynamic();

    drawClock();
    drawStormAlertBanner();
    drawSecurityAlertBanner();
    pumpSerial();
  }

  delay(1);
}
