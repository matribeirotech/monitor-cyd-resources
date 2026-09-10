/*
 * ============================================================================
 *  PC MONITOR  -  monitor de PC com o gato Mike
 *  Placa: ESP32-2432S028R "CYD" versao 2 USB (micro USB + USB-C), display ST7789
 *
 *  Recebe telemetria do PC (Linux) em JSON pela serial USB, 115200 baud.
 *  Toque na tela para trocar entre as 5 telas.
 *  Tela 5 = pomodoro (25 min de foco, pausa de 5 ou 15).
 *
 *  Bibliotecas necessarias (Library Manager do Arduino IDE):
 *    - TFT_eSPI            (Bodmer)   -> use o User_Setup.h que veio no projeto
 *    - ArduinoJson         (Benoit Blanchon) v7
 *    - XPT2046_Touchscreen (Paul Stoffregen)
 * ============================================================================
 */

#include <SPI.h>
#include <TFT_eSPI.h>
#include <ArduinoJson.h>

#include <SD.h>
#include <AnimatedGIF.h>

#include "ui_theme.h"

// ------------------------------------------------------------- hardware ----
// Touch XPT2046: fica num barramento SPI separado do display no CYD
#define XPT_MOSI 32
#define XPT_MISO 39
#define XPT_CLK  25
#define XPT_CS   33
#define XPT_IRQ  36

// LED RGB embutido (catodo comum invertido: LOW = aceso)
#define LED_R 4
#define LED_G 16
#define LED_B 17

// Backlight
#define PIN_BL 21

// Alto-falante embutido da CYD (bipe no fim de cada etapa do pomodoro)
#define PIN_SPK 26
#define SOUND_ENABLED 1

// Botao BOOT da placa. Plano B caso o touch nao coopere:
// clique curto = comeca/pausa o pomodoro, clique longo = zera.
#define PIN_BOOT 0
#define BOOT_LONG_MS 900

// Se a imagem aparecer de cabeca para baixo, troque 1 por 3.
#define SCREEN_ROTATION 1

// ---------------------------------------------------------------- toque ----
// TOUCH_ENABLED 0 desliga o toque e faz as telas girarem sozinhas.
#define TOUCH_ENABLED   1
#define AUTO_ROTATE_MS  0      // 0 = desligado. Ex: 10000 troca de tela a cada 10 s.

// Pressao minima para valer como toque. Se a tela ainda trocar sozinha,
// aumente (900, 1500...). Ligue TOUCH_DEBUG para ver o valor real na tela.
#define TOUCH_Z_MIN     600
#define TOUCH_STABLE    3      // leituras seguidas com toque para aceitar
#define TOUCH_RELEASE   6      // leituras seguidas sem toque para rearmar
#define TOUCH_DEBUG     0      // 1 = mostra z / raw / x,y no rodape (calibracao)

// Calibracao: valores CRUS do XPT2046 nos cantos da tela. Os padroes abaixo
// servem para a maioria das CYD. Se os botoes do pomodoro errarem o alvo,
// ligue TOUCH_DEBUG, encoste nos quatro cantos e ajuste estes numeros.
#define TOUCH_RAW_X_MIN  200
#define TOUCH_RAW_X_MAX 3700
#define TOUCH_RAW_Y_MIN  240
#define TOUCH_RAW_Y_MAX 3800
#define TOUCH_FLIP_X     0     // 1 inverte o eixo X
#define TOUCH_FLIP_Y     0     // 1 inverte o eixo Y

TFT_eSPI tft = TFT_eSPI();

struct TS_Point { int16_t x, y, z; };
class TouchBB {
public:
  void begin() {
    pinMode(XPT_CS, OUTPUT); digitalWrite(XPT_CS, HIGH);
    pinMode(XPT_CLK, OUTPUT); digitalWrite(XPT_CLK, LOW);
    pinMode(XPT_MOSI, OUTPUT); digitalWrite(XPT_MOSI, LOW);
    pinMode(XPT_MISO, INPUT);
    pinMode(XPT_IRQ, INPUT);
  }
  bool touched() { return digitalRead(XPT_IRQ) == LOW; }
  uint16_t transfer(uint8_t cmd) {
    uint16_t result = 0;
    for(int i=7; i>=0; i--) {
      digitalWrite(XPT_CLK, LOW);
      digitalWrite(XPT_MOSI, (cmd >> i) & 1);
      digitalWrite(XPT_CLK, HIGH);
    }
    digitalWrite(XPT_CLK, LOW); digitalWrite(XPT_CLK, HIGH);
    for(int i=11; i>=0; i--) {
      digitalWrite(XPT_CLK, LOW);
      digitalWrite(XPT_CLK, HIGH);
      if(digitalRead(XPT_MISO)) result |= (1 << i);
    }
    digitalWrite(XPT_CLK, LOW); digitalWrite(XPT_CLK, HIGH);
    digitalWrite(XPT_CLK, LOW); digitalWrite(XPT_CLK, HIGH);
    digitalWrite(XPT_CLK, LOW); digitalWrite(XPT_CLK, HIGH);
    return result;
  }
  TS_Point getPoint() {
    digitalWrite(XPT_CS, LOW);
    transfer(0x90); // dummy read
    int tx = transfer(0x90);
    int ty = transfer(0xD0);
    digitalWrite(XPT_CS, HIGH);
    
    // Equivale a setRotation(1) na biblioteca original
    int16_t xRaw = tx;
    int16_t yRaw = 4095 - ty;
    
    return {xRaw, yRaw, 1000};
  }
};
TouchBB ts;

AnimatedGIF gif;
File gifFile;
bool hasSD = false;
char gifPath[64] = "/background.gif";

// -------------------------------------------------------------- estado -----

#include <Preferences.h>
Preferences prefs;

uint16_t C_BG        = 0x0000;
uint16_t C_CARD      = 0x0000;
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
uint16_t C_PINK      = 0x07E0;

uint8_t currentTheme = 0;
int currentBrightness = 128; // 0-255

void applyTheme(uint8_t t) {
  currentTheme = t;
  if (t == 0) { // Terminal Minimalista
    C_BG = 0x0000; C_CARD = 0x0000; C_CARD_HI = 0x03E0; C_TRACK = 0x0120;
    C_TEXT = 0x07E0; C_DIM = 0x03E0; C_ACCENT = 0x07E0; C_ACCENT_DK = 0x0000;
    C_OK = 0x07E0; C_WARN = 0xFFE0; C_HOT = 0xF800; C_COOL = 0x07E0; C_PINK = 0x07E0;
  } else if (t == 1) { // z1p0 (Jamaicano / Canabico)
    C_BG = 0x0000; C_CARD = 0x0000; 
    C_CARD_HI = 0xFFE0; // Amarelo (Yellow)
    C_TRACK = 0x0000;   // Fundo preto puro para a animacao brilhar mais
    C_TEXT = 0xFFFF;    // Branco para legibilidade
    C_DIM = 0xF800;     // Vermelho (Red)
    C_ACCENT = 0x07E0;  // Verde (Green)
    C_ACCENT_DK = 0x0000;
    C_OK = 0x07E0; C_WARN = 0xFFE0; C_HOT = 0xF800; C_COOL = 0x07E0; C_PINK = 0xF800;
  } else if (t == 2) { // TEMA GIF SD
    C_BG = 0x0000; C_CARD = 0x0000; C_CARD_HI = 0x03E0; C_TRACK = 0x0120;
    C_TEXT = 0x07E0; C_DIM = 0x03E0; C_ACCENT = 0x07E0; C_ACCENT_DK = 0x0000;
    C_OK = 0x07E0; C_WARN = 0xFFE0; C_HOT = 0xF800; C_COOL = 0x07E0; C_PINK = 0x07E0;
  }
}

SPIClass sdSPI(VSPI);
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
  if (isBehindUI(pDraw->iX, y)) return; // Simple row discard (not fully precise for partial row, but good enough)
  
  for (int x = 0; x < pDraw->iWidth; x++) {
    if (pDraw->ucHasTransparency && pDraw->pPixels[x] == pDraw->ucTransparent) continue;
    if (!isBehindUI(pDraw->iX + x, y)) {
      tft.drawPixel(pDraw->iX + x, y, usPalette[pDraw->pPixels[x]]);
    }
  }
}

struct Stats {
  float cpu = 0, cput = -1, cpuf = 0, load = 0;
  float gpu = -1, gput = -1, vram = -1, gpuw = -1;
  float ram = 0, ramu = 0, ramt = 0, swap = 0;
  float dsk = 0, dskf = 0, dr = 0, dw = 0;
  float rx = 0, tx = 0;
  int   cores = 0, fan = -1, gpufan = -1, fps = -1;
  int8_t hh = -1, mm = -1;    // hora de Brasilia, mandada pelo agente
  bool  game = false;         // processo de jogo/emulador rodando (modo game)
  uint32_t up = 0;
  char host[16] = "---";
  char top[16] = "";
  char gpuname[10] = "";
} st;

// ---- logs vindos do journalctl ----
struct LogLine {
  uint8_t prio = 6;
  char unit[LOG_UNIT_MAX] = "";
  char msg[LOG_MSG_MAX] = "";
};
struct LogState {
  uint32_t err = 0, warn = 0;
  float    rate = 0;             // erros por minuto
  LogLine  ring[LOG_LINES];
  uint8_t  count = 0;            // quantas posicoes do ring tem conteudo
  uint8_t  head = 0;             // proxima posicao a escrever
  bool     enabled = false;      // o agente esta mandando logs?
} lg;


// Variantes de humor pro "foco" do pomodoro, sorteadas a cada novo ciclo (ver
// pomoToggle()): a mesma cara de sempre, hacker de capuz e notebook, homem
// de negocios de terno/oculos/maletinha, ou so' sorrindo.

bool     linked      = false;      // recebendo dados?
uint32_t lastPacket  = 0;
uint32_t packets     = 0;

uint8_t  screen      = 0;          // 0 Mike, 1 graficos, 2 temperaturas, 3 logs
bool     needFullDraw = true;

// ---- reacoes com prazo de validade ----
uint32_t scareUntil   = 0;
uint32_t happyUntil   = 0;
uint32_t curiousUntil = 0;
uint32_t ledAlert     = 0;         // LED piscando vermelho ate esse millis
uint32_t idleSince    = 0;         // desde quando o PC esta ocioso (0 = nao esta)
uint32_t lastUpDays   = 0;
int16_t  gWalkX       = 0;         // posicao do Mike no passeio
int8_t   gWalkDir     = 1;



// historico para os graficos
uint8_t hCpu[HIST], hGpu[HIST], hRam[HIST], hTmp[HIST];
uint16_t hPos = 0;
bool hFilled = false;

// maior por causa das linhas de log que vem junto no pacote
char lineBuf[1024];
uint16_t lineLen = 0;

// caches de desenho (evitam redesenhar o que nao mudou).
// Precisam ser zerados sempre que a tela e redesenhada do zero.
int32_t  gGaugeEnd[2] = {-999, -999};
uint16_t gGaugeCol[2] = {0, 0};
uint8_t  gPomoBtn     = 255;   // estado desenhado dos botoes
int32_t  gPomoSecs    = -1;    // segundo ja desenhado no cronometro

void resetDrawCache() {
    gGaugeEnd[0] = gGaugeEnd[1] = -999;
  gGaugeCol[0] = gGaugeCol[1] = 0;
  }

// =========================================================== utilidades ====
static void setLed(uint8_t r, uint8_t g, uint8_t b) {
  digitalWrite(LED_R, r ? LOW : HIGH);
  digitalWrite(LED_G, g ? LOW : HIGH);
  digitalWrite(LED_B, b ? LOW : HIGH);
}

static void fmtUptime(uint32_t s, char *out, size_t n) {
  uint32_t d = s / 86400, h = (s % 86400) / 3600, m = (s % 3600) / 60;
  if (d) snprintf(out, n, "%lud %luh", (unsigned long)d, (unsigned long)h);
  else   snprintf(out, n, "%02lu:%02lu:%02lu", (unsigned long)h,
                  (unsigned long)m, (unsigned long)(s % 60));
}

static float maxTemp() {
  float t = st.cput;
  if (st.gput > t) t = st.gput;
  return t;
}

// ---------------------------------------------------------------- som ------
void beep(uint16_t freq, uint16_t ms) {
#if SOUND_ENABLED
  #if ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcAttach(PIN_SPK, freq, 8);
    ledcWriteTone(PIN_SPK, freq);
    delay(ms);
    ledcWriteTone(PIN_SPK, 0);
    ledcDetach(PIN_SPK);
  #else
    ledcSetup(0, freq, 8);
    ledcAttachPin(PIN_SPK, 0);
    ledcWriteTone(0, freq);
    delay(ms);
    ledcWriteTone(0, 0);
    ledcDetachPin(PIN_SPK);
  #endif
#else
  (void)freq; (void)ms;
#endif
}


// ============================================================= pomodoro ====





// Chamado todo loop: cuida das transicoes de etapa.


// Curto de proposito: o painel do Mike comporta ~16 caracteres na fonte 2.

// =============================================================== sprite ====
// Desenha um quadro DENTRO do sprite, em qualquer escala/posicao, opcionalmente
// espelhado. O espelhamento e de graca aqui, entao o Mike anda nos dois sentidos
// sem precisar de quadros extras na flash.




// Easter egg: todo dia as 16:20 (horario de Brasilia, mandado pelo agente --
// ver README/protocolo) o Mike fica "chapado" por um minuto. So' depende do
// relogio, entao precisa de sinal do PC pra saber a hora.
static bool isFourTwenty() {
  return linked && st.hh == 16 && st.mm == 20;
}

// ============================================================== humor ======
// A ordem aqui e a prioridade: o que vem antes ganha.




// Sorteia um gesto ocioso (espreguicar, bocejar, se limpar, espiar) por cima
// do humor calmo/dormindo, so' para o Mike parecer mais vivo quando nao ha
// nada de especial acontecendo. So' considera CALM e SLEEP -- os outros
// humores ja tem animacao propria (reacao a temperatura, erro, pomodoro...)
// e o passeio (MOOD_WALK) tem seu proprio desenho especial na tela 0.


// Quadro a desenhar: o gesto em andamento (se houver) por cima do humor real.

// ========================================================== componentes ====
void drawHeader() {
  tft.fillRect(0, 0, SCR_W, HDR_H, C_ACCENT_DK);
  tft.fillRect(0, HDR_H - 2, SCR_W, 2, C_ACCENT);

  // Hacker icon
  uint16_t hc = C_ACCENT;
  uint16_t hd = C_DIM;
  tft.fillRect(8, 4, 8, 2, hc);
  tft.fillRect(6, 6, 12, 2, hc);
  tft.fillRect(4, 8, 16, 6, hc);
  tft.fillRect(8, 8, 8, 4, C_BG); // face
  tft.fillRect(6, 14, 12, 3, hd); // laptop lid
  tft.fillRect(2, 17, 20, 2, hd); // laptop base

  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(C_ACCENT, C_ACCENT_DK);
  tft.drawString(currentTheme == 1 ? "z1p0.monitor_" : "sys.monitor_", 32, 10, 2);
  
  tft.setTextDatum(MR_DATUM);
  tft.setTextColor(linked ? C_TEXT : C_DIM, C_ACCENT_DK);
  tft.setTextPadding(100);
  tft.drawString(linked ? st.host : "sem sinal", SCR_W - 32, 10, 2);
  tft.setTextPadding(0);

  // Gear icon (Settings) - draw AFTER the host so it doesn't get erased
  tft.fillRect(SCR_W - 22, 4, 12, 12, C_DIM);
  tft.fillRect(SCR_W - 19, 7, 6, 6, C_ACCENT_DK);
}

// Relogio de Brasilia, mandado pelo agente Python (campos "hh"/"mm" do JSON,
// via zoneinfo -- ver agent.py). Fica no vao entre o titulo e o nome da
// maquina no cabecalho; chamado a cada refresh (nao so no redraw completo)
// para o minuto virar sem esperar trocar de tela.
void drawClock() {
  char buf[6];
  if (linked && st.hh >= 0 && st.mm >= 0)
    snprintf(buf, sizeof(buf), "%02d:%02d", st.hh, st.mm);
  else
    snprintf(buf, sizeof(buf), "--:--");
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(C_ACCENT, C_ACCENT_DK);
  tft.setTextPadding(40);
  tft.drawString(buf, SCR_W / 2 + 8, 10, 1);
  tft.setTextPadding(0);
}

void drawCard(int x, int y, int w, int h, const char *title) {
  tft.fillRoundRect(x, y, w, h, 4, C_CARD);
  tft.drawRoundRect(x, y, w, h, 4, C_CARD_HI);
  if (title) {
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(C_DIM, C_CARD);
    tft.drawString(title, x + 6, y + 4, 1);
  }
}

// gauge circular; so redesenha o anel e o numero (sem piscar)
void drawGauge(int cx, int cy, int r, float value, const char *label,
               bool valid, float warn, float hot, int8_t slot) {
  const int ir = r - 9;
  const int A0 = 30, A1 = 330;
  float v = valid ? constrain(value, 0.0f, 100.0f) : 0.0f;
  int aEnd = A0 + (int)((A1 - A0) * v / 100.0f);
  uint16_t col = valid ? levelColor(v, warn, hot) : C_TRACK;

  // so redesenha o anel se mudou (drawSmoothArc e caro)
  bool changed = (slot < 0) || (gGaugeEnd[slot] != aEnd) || (gGaugeCol[slot] != col);
  if (changed) {
    if (aEnd > A0 + 1) tft.drawSmoothArc(cx, cy, r, ir, A0, aEnd, col, C_CARD, true);
    if (aEnd < A1 - 1) tft.drawSmoothArc(cx, cy, r, ir, aEnd, A1, C_TRACK, C_CARD, true);
    if (slot >= 0) { gGaugeEnd[slot] = aEnd; gGaugeCol[slot] = col; }
  }

  tft.setTextDatum(MC_DATUM);
  tft.setTextPadding(r + 16);
  tft.setTextColor(valid ? C_TEXT : C_DIM, C_CARD);
  char buf[10];
  if (valid) snprintf(buf, sizeof(buf), "%d", (int)(v + 0.5f));
  else       snprintf(buf, sizeof(buf), "--");
  tft.drawString(buf, cx, cy - 4, 4);
  tft.setTextPadding(0);

  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString(label, cx, cy + 16, 2);
}

void drawBar(int x, int y, int w, int h, const char *label, float pct,
             const char *right, float warn, float hot) {
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString(label, x, y + h / 2, 2);

  const int bx = x + 34, bw = w - 34 - 58;
  tft.drawRoundRect(bx, y, bw, h, 2, C_CARD_HI);
  int fill = (int)((bw - 2) * constrain(pct, 0.0f, 100.0f) / 100.0f);
  uint16_t col = levelColor(pct, warn, hot);
  if (fill > 0) tft.fillRect(bx + 1, y + 1, fill, h - 2, col);
  if (fill < bw - 2) tft.fillRect(bx + 1 + fill, y + 1, bw - 2 - fill, h - 2, C_CARD);

  tft.setTextDatum(MR_DATUM);
  tft.setTextColor(C_TEXT, C_CARD);
  tft.setTextPadding(56);
  tft.drawString(right, x + w, y + h / 2, 2);
  tft.setTextPadding(0);
}

// Menuzinho de navegacao (setas voltar/avancar), fixo no rodape de toda
// tela -- ver handleTap(). Ficam aqui em cima (e nao la' com os botoes do
// pomodoro) porque valem em TODAS as telas, nao so' na tela 4.
#define NAV_BAR_H 18
static const Rect BTN_PREV = {0,          SCR_H - NAV_BAR_H, 54, NAV_BAR_H};
static const Rect BTN_GEAR = {SCR_W - 30, 0, 30, HDR_H};
static const Rect BTN_NEXT = {SCR_W - 54, SCR_H - NAV_BAR_H, 54, NAV_BAR_H};

void drawDots() {
  for (int i = 0; i < SCREENS; i++) {
    uint16_t c = (i == screen) ? C_ACCENT : C_CARD_HI;
    int cx = SCR_W / 2 - (SCREENS - 1) * 6 + i * 12;
    tft.fillCircle(cx, SCR_H - 7, i == screen ? 3 : 2, c);
  }
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(C_DIM, C_BG);
  tft.drawString("<", BTN_PREV.x + BTN_PREV.w / 2, BTN_PREV.y + BTN_PREV.h / 2, 2);
  tft.drawString(">", BTN_NEXT.x + BTN_NEXT.w / 2, BTN_NEXT.y + BTN_NEXT.h / 2, 2);
}

// ============================================================== tela 0 =====
#define NUM_DROPS 30
struct Drop {
  int col;
  int row;
  int len;
  int speed;
  int ticks;
} rainDrops[NUM_DROPS];

void initRain() {
  for (int i=0; i<NUM_DROPS; i++) {
    rainDrops[i].col = random(0, 53);
    rainDrops[i].row = random(-25, 0);
    rainDrops[i].len = random(6, 18);
    rainDrops[i].speed = random(1, 3);
    rainDrops[i].ticks = 0;
  }
}

const uint8_t leaf_sprite[] PROGMEM = {
  0b00100000, //   #
  0b10101000, // # # #
  0b11111000, // #####
  0b11111000, // #####
  0b01110000, //  ###
  0b00100000, //   #
  0b00100000, //   #
  0b00000000
};

bool isBehindUI(int x, int y) {
  if (screen != SCR_MAIN) return true;
  if (x >= 25 && x <= 135 && y >= 30 && y <= 135) return true;
  if (x >= 185 && x <= 295 && y >= 30 && y <= 135) return true;
  if (x >= 10 && x <= 150 && y >= 140 && y <= 210) return true;
  if (x >= 160 && x <= 310 && y >= 135 && y <= 210) return true;
  if (y < HDR_H + 2) return true;
  if (y > SCR_H - 15) return true;
  return false;
}

void drawRain() {
  if (screen != SCR_MAIN || currentTheme == 2) return;
  for (int i=0; i<NUM_DROPS; i++) {
    rainDrops[i].ticks++;
    if (rainDrops[i].ticks >= rainDrops[i].speed) {
      rainDrops[i].ticks = 0;
      
      int tailRow = rainDrops[i].row - rainDrops[i].len;
      // Erase tail
      if (tailRow >= 3 && tailRow < 30) {
         int x = rainDrops[i].col * 6;
         int y = tailRow * 8;
         if (!isBehindUI(x, y)) tft.fillRect(x, y, 6, 8, C_BG);
      }
      
      // Old head becomes trail (darker green, maybe flip character)
      if (rainDrops[i].row >= 3 && rainDrops[i].row < 30) {
         int x = rainDrops[i].col * 6;
         int y = rainDrops[i].row * 8;
         if (!isBehindUI(x, y)) {
           if (currentTheme == 1) {
             tft.fillRect(x, y, 6, 8, C_BG);
             tft.drawBitmap(x, y, leaf_sprite, 6, 8, 0x0120); // Dark green trail for leaves
           } else {
             char c = random(33, 126);
             tft.fillRect(x, y, 6, 8, C_BG);
             tft.setTextColor(0x03E0, C_BG); // Dark green
             tft.drawChar(c, x, y, 1);
           }
         }
      }
      
      rainDrops[i].row++;
      
      // New head (bright green/white)
      if (rainDrops[i].row >= 3 && rainDrops[i].row < 30) {
         int x = rainDrops[i].col * 6;
         int y = rainDrops[i].row * 8;
         if (!isBehindUI(x, y)) {
           if (currentTheme == 1) { // z1p0
             int colorPick = random(0, 3);
             uint16_t cColor = 0x07E0;
             if (colorPick == 1) cColor = 0xFFE0; // Yellow
             else if (colorPick == 2) cColor = 0xF800; // Red
             tft.fillRect(x, y, 6, 8, C_BG);
             tft.drawBitmap(x, y, leaf_sprite, 6, 8, cColor);
           } else {
             char c = random(33, 126);
             tft.fillRect(x, y, 6, 8, C_BG);
             tft.setTextColor(0xAFE5, C_BG); // Bright whitish-green
             tft.drawChar(c, x, y, 1);
           }
         }
      }
      
      if (tailRow >= 30) {
        rainDrops[i].col = random(0, 53);
        rainDrops[i].row = random(-15, 0);
        rainDrops[i].len = random(6, 18);
        rainDrops[i].speed = random(1, 3);
      }
    }
  }
}


static const Rect BTN_THEME = {20, 60, 280, 40};
static const Rect BTN_BR_DOWN = {20, 110, 80, 40};
static const Rect BTN_BR_UP = {220, 110, 80, 40};

void drawSetButton(const Rect &r, const char *lbl, uint16_t color) {
  tft.drawRoundRect(r.x, r.y, r.w, r.h, 6, color);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(color, C_BG);
  tft.drawString(lbl, r.x + r.w/2, r.y + r.h/2, 2);
}

void screenSetStatic() {
  drawHeader();
  
  const char* themeName = "TEMA: TERMINAL";
  if (currentTheme == 1) themeName = "TEMA: Z1P0";
  if (currentTheme == 2) themeName = "TEMA: GIF SD";
  
  drawSetButton(BTN_THEME, themeName, C_ACCENT);
  drawSetButton(BTN_BR_DOWN, "-", C_DIM);
  drawSetButton(BTN_BR_UP, "+", C_DIM);
  
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(C_TEXT, C_BG);
  tft.drawString("BRILHO", 160, 115, 2);
}

void screenSetDynamic() {
  char buf[16];
  snprintf(buf, sizeof(buf), "%d%%", (currentBrightness * 100) / 255);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(C_ACCENT, C_BG);
  tft.fillRect(120, 125, 80, 20, C_BG);
  tft.drawString(buf, 160, 135, 2);
}

void screenMainStatic() {
  tft.fillScreen(C_BG);
  if (currentTheme == 2 && hasSD) {
    gif.close();
    gif.open(gifPath, GIFOpenFile, GIFCloseFile, GIFReadFile, GIFSeekFile, GIFDraw);
  } else {
    initRain();
  }
  drawHeader();
  drawCard(2, HDR_H + 2, 156, 120, nullptr);      // CPU
  drawCard(162, HDR_H + 2, 156, 120, nullptr);    // RAM
  drawCard(2, HDR_H + 126, 156, 82, nullptr);     // TEMP / INFO
  drawCard(162, HDR_H + 126, 156, 82, nullptr);   // DISCO / REDE
  drawDots();
}

void screenMainDynamic() {
  char buf[40];

  // ---- CPU ----
  drawGauge(80, HDR_H + 60, 48, st.cpu, "CPU", linked, 60, 85, 0);

  // ---- RAM ----
  drawGauge(240, HDR_H + 60, 48, st.ram, "RAM", linked, 75, 90, 1);

  // ---- Info ----
  tft.setTextDatum(MC_DATUM);
  tft.setTextPadding(140);
  if (st.cput > 0) {
    snprintf(buf, sizeof(buf), "CPU: %.0f C", st.cput);
    tft.setTextColor(levelColor(st.cput, T_TEMP_HOT, T_TEMP_MAX), C_CARD);
  } else { 
    snprintf(buf, sizeof(buf), "TEMP: -- C"); 
    tft.setTextColor(C_DIM, C_CARD); 
  }
  tft.drawString(buf, 80, HDR_H + 150, 4);

  if (st.game) {
    if (st.fps >= 0) snprintf(buf, sizeof(buf), "FPS: %d", st.fps);
    else snprintf(buf, sizeof(buf), "GAME ON");
    tft.setTextColor(C_PINK, C_CARD);
  } else if (st.gput > 0) {
    snprintf(buf, sizeof(buf), "GPU: %.0f C", st.gput);
    tft.setTextColor(levelColor(st.gput, T_TEMP_HOT, T_TEMP_MAX), C_CARD);
  } else {
    snprintf(buf, sizeof(buf), " ");
  }
  tft.drawString(buf, 80, HDR_H + 180, 4);
  tft.setTextPadding(0);

  // ---- Disco/Rede ----
  snprintf(buf, sizeof(buf), "%.0fG livre", st.dskf);
  drawBar(170, HDR_H + 138, 140, 12, "DSK", st.dsk, buf, 80, 92);

  tft.setTextDatum(ML_DATUM);
  tft.setTextPadding(80);
  tft.setTextColor(C_COOL, C_CARD);
  snprintf(buf, sizeof(buf), "v %.1f MB/s", st.rx);
  tft.drawString(buf, 170, HDR_H + 168, 2);
  tft.setTextColor(C_PINK, C_CARD);
  snprintf(buf, sizeof(buf), "^ %.1f MB/s", st.tx);
  tft.drawString(buf, 170, HDR_H + 188, 2);
  tft.setTextPadding(0);
}

// ============================================================== tela 1 =====
void screenGraphStatic() {
  tft.fillScreen(C_BG);
  initRain();
  drawHeader();
  drawCard(2,   HDR_H + 2,  156, 96, "CPU %");
  drawCard(162, HDR_H + 2,  156, 96, "GPU %");
  drawCard(2,   HDR_H + 102, 156, 96, "RAM %");
  drawCard(162, HDR_H + 102, 156, 96, "TEMP C");
  drawDots();
}

// escurece uma cor RGB565 pela metade, preservando os campos
static uint16_t dim565(uint16_t c) {
  uint16_t r = (c >> 11) & 0x1F, g = (c >> 5) & 0x3F, b = c & 0x1F;
  return ((r / 3) << 11) | ((g / 3) << 5) | (b / 3);
}

void plot(int x, int y, int w, int h, uint8_t *data, uint16_t col, const char *unit) {
  tft.fillRect(x, y, w, h, C_CARD);
  const uint16_t area = dim565(col);
  // linhas de grade
  for (int i = 1; i < 4; i++)
    for (int gx = x; gx < x + w; gx += 6)
      tft.drawPixel(gx, y + h * i / 4, C_CARD_HI);

  uint16_t n = hFilled ? HIST : hPos;
  if (n < 2) return;
  int prevY = -1;
  for (int i = 0; i < w && i < n; i++) {
    uint16_t idx = (hPos - 1 - i + HIST * 2) % HIST;
    int px = x + w - 1 - i;
    int v = data[idx];
    int py = y + h - 1 - (h - 1) * v / 100;
    tft.drawFastVLine(px, py, y + h - py, area);
    if (prevY >= 0) tft.drawLine(px + 1, prevY, px, py, col);
    tft.drawPixel(px, py, col);
    prevY = py;
  }
  // valor atual
  uint16_t last = (hPos - 1 + HIST) % HIST;
  char buf[12];
  snprintf(buf, sizeof(buf), "%d%s", data[last], unit);
  tft.setTextDatum(TR_DATUM);
  tft.setTextColor(col, C_CARD);
  tft.setTextPadding(56);
  tft.drawString(buf, x + w - 2, y - 12, 2);
  tft.setTextPadding(0);
}

void screenGraphDynamic() {
  plot(8,   HDR_H + 18, 144, 74, hCpu, C_ACCENT, "%");
  plot(168, HDR_H + 18, 144, 74, hGpu, C_OK,     "%");
  plot(8,   HDR_H + 118, 144, 74, hRam, C_COOL,   "%");
  plot(168, HDR_H + 118, 144, 74, hTmp, C_HOT,    "C");
}

// ============================================================== tela 2 =====
void screenTempStatic() {
  tft.fillScreen(C_BG);
  initRain();
  drawHeader();
  drawCard(2,   HDR_H + 2,  156, 108, "CPU");
  drawCard(162, HDR_H + 2,  156, 108, "GPU");
  drawCard(2,   HDR_H + 116, 316, 72, "SISTEMA");
  drawDots();
}

void bigTemp(int cx, int cy, float t, const char *sub) {
  char buf[10];
  tft.setTextDatum(MC_DATUM);
  tft.setTextPadding(120);
  if (t > 0) {
    snprintf(buf, sizeof(buf), "%d", (int)(t + 0.5f));
    tft.setTextColor(levelColor(t, T_TEMP_HOT, T_TEMP_MAX), C_CARD);
    tft.drawString(buf, cx, cy, 7);
    tft.setTextPadding(0);
    tft.setTextDatum(ML_DATUM);
    tft.drawString("C", cx + 40, cy - 8, 4);
  } else {
    // fonte 7 (7 segmentos) so tem digitos, entao o traco vai na fonte 4
    tft.setTextColor(C_DIM, C_CARD);
    tft.fillRect(cx - 60, cy - 24, 120, 48, C_CARD);
    tft.drawString("--", cx, cy, 4);
    tft.setTextPadding(0);
  }
  tft.setTextDatum(MC_DATUM);
  tft.setTextPadding(140);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString(sub, cx, cy + 34, 2);
  tft.setTextPadding(0);
}

void screenTempDynamic() {
  char buf[40];

  snprintf(buf, sizeof(buf), "%d nucleos  %.0f MHz", st.cores, st.cpuf);
  bigTemp(78, HDR_H + 46, st.cput, buf);

  if (st.gpuw > 0) snprintf(buf, sizeof(buf), "%s  %.0f W", st.gpuname, st.gpuw);
  else             snprintf(buf, sizeof(buf), "%s", st.gpuname[0] ? st.gpuname : "sem GPU");
  bigTemp(238, HDR_H + 46, st.gput, buf);

  tft.setTextDatum(ML_DATUM);
  tft.setTextPadding(96);
  tft.setTextColor(C_TEXT, C_CARD);

  snprintf(buf, sizeof(buf), "load %.2f", st.load);
  tft.drawString(buf, 10, HDR_H + 136, 2);

  if (st.fan > 0) snprintf(buf, sizeof(buf), "fan %d rpm", st.fan);
  else            snprintf(buf, sizeof(buf), "fan --");
  tft.drawString(buf, 110, HDR_H + 136, 2);

  snprintf(buf, sizeof(buf), "swap %.0f%%", st.swap);
  tft.drawString(buf, 212, HDR_H + 136, 2);

  snprintf(buf, sizeof(buf), "disco R %.1f  W %.1f MB/s", st.dr, st.dw);
  tft.setTextPadding(200);
  tft.drawString(buf, 10, HDR_H + 160, 2);

  if (st.vram >= 0) snprintf(buf, sizeof(buf), "vram %.0f%%", st.vram);
  else              snprintf(buf, sizeof(buf), "pkts %lu", (unsigned long)packets);
  tft.setTextPadding(90);
  tft.drawString(buf, 220, HDR_H + 160, 2);
  tft.setTextPadding(0);
}

// ============================================================== tela 3 =====

// ============================================================== tela 4 =====
// struct Rect esta em ui_theme.h -- veja o comentario la sobre os prototipos.
static bool inside(const Rect &r, int x, int y) {
  return x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h;
}

// Zonas de toque da tela do pomodoro
static const Rect BTN_MAIN  = {138, 128, 174, 32};
static const Rect BTN_SHORT = {138, 166,  84, 26};
static const Rect BTN_LONG  = {228, 166,  84, 26};
static const Rect BTN_RESET = {138, 196, 174, 14};

void drawButton(const Rect &r, const char *label, uint16_t bg, uint16_t fg,
                uint8_t font) {
  tft.fillRoundRect(r.x, r.y, r.w, r.h, 4, bg);
  tft.drawRoundRect(r.x, r.y, r.w, r.h, 4, C_CARD_HI);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(fg, bg);
  tft.drawString(label, r.x + r.w / 2, r.y + r.h / 2, font);
}



// ========================================================= serial / JSON ===
void applyJson(const char *json) {
  JsonDocument doc;
  if (deserializeJson(doc, json)) return;

  // Comandos de Controle
  JsonVariant vTheme = doc["cmd_theme"];
  if (!vTheme.isNull()) {
    currentTheme = vTheme.as<uint8_t>() % 3;
    applyTheme(currentTheme);
    prefs.putUInt("theme", currentTheme);
    needFullDraw = true;
  }
  
  JsonVariant vBright = doc["cmd_bright"];
  if (!vBright.isNull()) {
    currentBrightness = vBright.as<int>();
    if (currentBrightness < 10) currentBrightness = 10;
    if (currentBrightness > 255) currentBrightness = 255;
    ledcWrite(0, currentBrightness);
    prefs.putInt("bright", currentBrightness);
    if (screen == SCR_SET) needFullDraw = true;
  }
  
  JsonVariant vGif = doc["cmd_gif"];
  if (!vGif.isNull() && hasSD) {
    strlcpy(gifPath, vGif.as<const char*>(), sizeof(gifPath));
    if (currentTheme == 2 && screen == SCR_MAIN) {
       gif.close();
       gif.open(gifPath, GIFOpenFile, GIFCloseFile, GIFReadFile, GIFSeekFile, GIFDraw);
    }
  }

  st.cpu   = doc["cpu"]   | st.cpu;
  st.cput  = doc["cput"]  | -1.0f;
  st.cpuf  = doc["cpuf"]  | 0.0f;
  st.cores = doc["cores"] | st.cores;
  st.load  = doc["load"]  | 0.0f;
  st.gpu   = doc["gpu"]   | -1.0f;
  st.gput  = doc["gput"]  | -1.0f;
  st.vram  = doc["vram"]  | -1.0f;
  st.gpuw  = doc["gpuw"]  | -1.0f;
  st.ram   = doc["ram"]   | 0.0f;
  st.ramu  = doc["ramu"]  | 0.0f;
  st.ramt  = doc["ramt"]  | 0.0f;
  st.swap  = doc["swap"]  | 0.0f;
  st.dsk   = doc["dsk"]   | 0.0f;
  st.dskf  = doc["dskf"]  | 0.0f;
  st.dr    = doc["dr"]    | 0.0f;
  st.dw    = doc["dw"]    | 0.0f;
  st.rx    = doc["rx"]    | 0.0f;
  st.tx    = doc["tx"]    | 0.0f;
  st.fan   = doc["fan"]   | -1;
  st.hh    = doc["hh"]    | -1;
  st.mm    = doc["mm"]    | -1;
  st.game  = doc["game"]  | false;
  st.fps   = doc["fps"]   | -1;
  st.up    = doc["up"]    | 0;
  strlcpy(st.host,    doc["host"]    | st.host, sizeof(st.host));
  strlcpy(st.top,     doc["top"]     | "",      sizeof(st.top));
  strlcpy(st.gpuname, doc["gpuname"] | "",      sizeof(st.gpuname));

  // historico
  hCpu[hPos] = (uint8_t)constrain(st.cpu, 0.0f, 100.0f);
  hGpu[hPos] = (uint8_t)constrain(st.gpu < 0 ? 0 : st.gpu, 0.0f, 100.0f);
  hRam[hPos] = (uint8_t)constrain(st.ram, 0.0f, 100.0f);
  float t = maxTemp();
  hTmp[hPos] = (uint8_t)constrain(t < 0 ? 0 : t, 0.0f, 100.0f);
  hPos = (hPos + 1) % HIST;
  if (hPos == 0) hFilled = true;

  // ---- logs do journalctl ----
  JsonVariant vErr = doc["le"];
  if (!vErr.isNull()) {
    lg.enabled = true;
    lg.err  = vErr | 0UL;
    lg.warn = doc["lw"] | 0UL;
    lg.rate = doc["lr"] | 0.0f;
    uint16_t nNew = doc["ln"] | 0;
    bool     crit = (doc["lc"] | 0) != 0;

    JsonArray arr = doc["lg"].as<JsonArray>();
    if (!arr.isNull()) {
      for (JsonVariant e : arr) {
        LogLine &L = lg.ring[lg.head];
        L.prio = e[0] | 6;
        strlcpy(L.unit, e[1] | "?", sizeof(L.unit));
        strlcpy(L.msg,  e[2] | "",  sizeof(L.msg));
        lg.head = (lg.head + 1) % LOG_LINES;
        if (lg.count < LOG_LINES) lg.count++;
      }
    }

    if (nNew > 0) scareUntil = millis() + REACT_SCARE;
    if (crit) {
      scareUntil = millis() + REACT_CRIT;
      ledAlert   = millis() + 8000;
      if (screen != 3) { screen = 3; needFullDraw = true; }
    }
  }

  // ---- eventos ----
  float busiest = st.cpu;
  if (st.gpu > busiest) busiest = st.gpu;
  if (st.ram > busiest) busiest = st.ram;
  if (busiest >= T_IDLE) idleSince = 0;
  else if (!idleSince)   idleSince = millis();

  if (st.rx + st.tx > T_NET_CURIOUS) curiousUntil = millis() + REACT_CURIOUS;

  uint32_t days = st.up / 86400;
  if (lastUpDays && days > lastUpDays) happyUntil = millis() + REACT_HAPPY;
  lastUpDays = days;

  packets++;
  if (packets == 1 && st.up < 180) happyUntil = millis() + REACT_HAPPY;

  lastPacket = millis();
  if (!linked) { linked = true; needFullDraw = true; }
}

void pumpSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen > 2) { lineBuf[lineLen] = 0; applyJson(lineBuf); }
      lineLen = 0;
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    } else {
      lineLen = 0;   // linha absurda, descarta
    }
  }
}

// ================================================================ touch ====
// Deteccao de BORDA: a tela so troca na transicao solto -> pressionado, e o
// toque precisa ser solto antes de valer de novo. Sem isso, se o painel
// reportar "pressionado" o tempo todo (ruido no T_IRQ, o que e comum nessas
// placas), a tela fica trocando sozinha sem parar.
uint8_t  tDown = 0, tUp = TOUCH_RELEASE;
bool     tArmed = true;
uint16_t tLastZ = 0;
int16_t  tRawX = 0, tRawY = 0;      // ultimo valor cru (para calibrar)
int16_t  tX = -1, tY = -1;          // ultimo toque em pixels

static int16_t mapClamp(int32_t v, int32_t inMin, int32_t inMax, int32_t out) {
  if (inMax == inMin) return 0;
  int32_t r = (v - inMin) * out / (inMax - inMin);
  if (r < 0) r = 0;
  if (r >= out) r = out - 1;
  return (int16_t)r;
}

// Decide o que fazer com um toque ja confirmado, em pixels.
//
// Nas telas 0-3 QUALQUER toque avanca de tela. Na tela do pomodoro isso so
// pode valer fora dos botoes -- por isso aqui a logica e invertida: primeiro
// testa os botoes, e SO SE nao acertar nenhum e' que navega. Antes disso a
// navegacao so funcionava dentro de uma faixa fina de 26px no rodape (a
// unica "excecao" ao padrao tocar-em-qualquer-lugar das outras telas), o
// que fazia o toque parecer "quebrado" bem no ponto de voltar ao menu
// principal: o resto da tela (o proprio Mike, os vaos entre os botoes) era
// zona morta. Agora, como nas outras telas, so os alvos ativos consomem o
// toque -- o resto sempre navega.
//
// As setas BTN_PREV/BTN_NEXT (menuzinho no rodape, ver drawDots()) sao o
// unico jeito de VOLTAR uma tela -- o "toque em qualquer lugar" so' avanca.
void handleTap(int16_t x, int16_t y) {
  if (inside(BTN_GEAR, x, y)) {
    if (screen != SCR_SET) {
      screen = SCR_SET;
    } else {
      screen = SCR_MAIN; // Close settings
    }
    needFullDraw = true;
    return;
  }
  
  if (inside(BTN_PREV, x, y)) { screen = (screen + SCREENS - 1) % SCREENS; needFullDraw = true; return; }
  if (inside(BTN_NEXT, x, y)) { screen = (screen + 1) % SCREENS;           needFullDraw = true; return; }
  
  if (screen == SCR_SET) {
    if (inside(BTN_THEME, x, y)) {
      currentTheme = (currentTheme + 1) % 3;
      applyTheme(currentTheme);
      prefs.putUInt("theme", currentTheme);
      needFullDraw = true;
    }
    else if (inside(BTN_BR_DOWN, x, y)) {
      currentBrightness -= 25;
      if (currentBrightness < 10) currentBrightness = 10;
      ledcWrite(0, currentBrightness);
      prefs.putInt("bright", currentBrightness);
      screenSetDynamic();
    }
    else if (inside(BTN_BR_UP, x, y)) {
      currentBrightness += 25;
      if (currentBrightness > 255) currentBrightness = 255;
      ledcWrite(0, currentBrightness);
      prefs.putInt("bright", currentBrightness);
      screenSetDynamic();
    }
    return; // NO misclick advancing on settings screen
  }

  screen = (screen + 1) % SCREENS;
  needFullDraw = true;
}

void pumpTouch() {
#if TOUCH_ENABLED
  bool down = false;
  if (ts.touched()) {
    TS_Point p = ts.getPoint();
    tLastZ = p.z;
    tRawX = p.x;
    tRawY = p.y;
    down = (p.z >= TOUCH_Z_MIN);
  } else {
    tLastZ = 0;
  }

  if (down) {
    tUp = 0;
    if (tDown < 250) tDown++;
    if (tArmed && tDown >= TOUCH_STABLE) {
      tArmed = false;                  // trava ate soltar
      tX = mapClamp(tRawX, TOUCH_RAW_X_MIN, TOUCH_RAW_X_MAX, SCR_W);
      tY = mapClamp(tRawY, TOUCH_RAW_Y_MIN, TOUCH_RAW_Y_MAX, SCR_H);
#if TOUCH_FLIP_X
      tX = SCR_W - 1 - tX;
#endif
#if TOUCH_FLIP_Y
      tY = SCR_H - 1 - tY;
#endif
      handleTap(tX, tY);
    }
  } else {
    tDown = 0;
    if (tUp < 250) tUp++;
    if (tUp >= TOUCH_RELEASE) tArmed = true;
  }
#endif

#if AUTO_ROTATE_MS > 0
  static uint32_t lastRotate = 0;
  if (millis() - lastRotate >= AUTO_ROTATE_MS) {
    lastRotate = millis();
    screen = (screen + 1) % SCREENS;
    needFullDraw = true;
  }
#endif
}

void drawTouchDebug() {
#if TOUCH_DEBUG
  // Para calibrar: encoste nos 4 cantos e anote os "raw". Esses numeros vao
  // para TOUCH_RAW_X_MIN/MAX e TOUCH_RAW_Y_MIN/MAX la em cima.
  char db[52];
  snprintf(db, sizeof(db), "z=%u raw %d,%d  px %d,%d",
           (unsigned)tLastZ, tRawX, tRawY, tX, tY);
  tft.setTextDatum(ML_DATUM);
  tft.setTextPadding(300);
  tft.setTextColor(C_ACCENT, C_BG);
  tft.drawString(db, 6, SCR_H - 8, 1);
  tft.setTextPadding(0);
#endif
}

// ---------------------------------------------------------- botao BOOT ----
// Caminho de controle que nao depende do touch.
void pumpBootButton() {
  static uint32_t bootDown = 0;
  static bool longDone = false;

  if (digitalRead(PIN_BOOT) == LOW) { // pressed
    if (bootDown == 0) {
      bootDown = millis();
      longDone = false;
    }
    if (!longDone && millis() - bootDown > BOOT_LONG_MS) {
      longDone = true;
    }
  } else { // released
    if (bootDown > 0) {
      if (!longDone) {
        screen = (screen + 1) % SCREENS;
        needFullDraw = true;
      }
      bootDown = 0;
    }
  }
}

// ================================================================ setup ====
void setup() {
  Serial.begin(115200);

  pinMode(LED_R, OUTPUT); pinMode(LED_G, OUTPUT); pinMode(LED_B, OUTPUT);
  setLed(0, 0, 0);

  pinMode(PIN_BL, OUTPUT);
  digitalWrite(PIN_BL, HIGH);

  pinMode(PIN_BOOT, INPUT_PULLUP);

  tft.init();
  tft.setRotation(SCREEN_ROTATION);
  tft.fillScreen(C_BG);
  initRain();

  ts.begin(); // Usando nosso bitbang touch!

  sdSPI.begin(18, 19, 23, 5);
  if (SD.begin(5, sdSPI, 4000000)) {
    hasSD = true;
    gif.begin(LITTLE_ENDIAN_PIXELS);
  }

  memset(hCpu, 0, sizeof(hCpu)); memset(hGpu, 0, sizeof(hGpu));
  memset(hRam, 0, sizeof(hRam)); memset(hTmp, 0, sizeof(hTmp));

  // splash
      tft.setTextDatum(MC_DATUM);
  tft.setTextColor(C_ACCENT, C_BG);
  tft.drawString("CYBER MONITOR", SCR_W / 2, 24, 4);
  tft.setTextColor(C_DIM, C_BG);
  tft.drawString("esperando o PC...", SCR_W / 2, 170, 2);
  tft.drawString("rode o agent.py no Linux", SCR_W / 2, 192, 2);
  delay(1200);

  Serial.println("MONITOR_READY");
}

// ================================================================= loop ====
void loop() {
  pumpSerial();
  pumpTouch();
  pumpBootButton();
  
  // perdeu contato com o PC?
  if (linked && millis() - lastPacket > 5000) {
    linked = false;
    needFullDraw = true;
  }

  
  // LED RGB: alerta de log critico tem prioridade, senao acompanha a temperatura
  float t = maxTemp();
  if (millis() < ledAlert)     setLed((millis() / 250) % 2, 0, 0);  // pisca
  else if (!linked)            setLed(0, 0, 1);
  else if (t >= T_TEMP_MAX)    setLed(1, 0, 0);
  else if (t >= T_TEMP_HOT)    setLed(1, 1, 0);
  else                         setLed(0, 1, 0);

  if (needFullDraw) {
    resetDrawCache();
    if      (screen == SCR_MAIN)  screenMainStatic();
    else if (screen == SCR_GRAPH) screenGraphStatic();
    else if (screen == SCR_TEMP)  screenTempStatic();
    
      else if (screen == SCR_SET)   screenSetStatic();
    
    needFullDraw = false;
  }

  static uint32_t lastRefresh = 0;
  static uint32_t lastRain = 0;
  if (millis() - lastRain >= 50) {
    lastRain = millis();
    drawRain();
  }

  if (screen == SCR_MAIN && currentTheme == 2 && hasSD) {
    if (!gif.playFrame(true, NULL)) {
      gif.reset();
    }
  }

  if (millis() - lastRefresh >= 200) {
    lastRefresh = millis();
    if      (screen == SCR_MAIN)  screenMainDynamic();
      else if (screen == SCR_GRAPH) screenGraphDynamic();
      else if (screen == SCR_TEMP)  screenTempDynamic();
      
      else if (screen == SCR_SET)   screenSetDynamic();
    
    drawClock();
    drawTouchDebug();
  }

  delay(10);
}
