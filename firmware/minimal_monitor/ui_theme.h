// ui_theme.h - CYD OS v5.0 Obsidian Dark Design System & Layout Constants (No-Touch Edition)
#pragma once
#include <Arduino.h>

// ---- Paleta Dinamica Obsidian Dark (RGB565), atualizada em tempo real via applyColor565() ----
extern uint16_t C_BG;          // Deep obsidian #070B14 (0x0842)
extern uint16_t C_CARD;        // Elevated dark slate #0F172A (0x08A5)
extern uint16_t C_CARD_ELEV;   // Nested pill/badge slate #162033 (0x1106)
extern uint16_t C_CARD_HI;     // Subtle hairline border (accent-harmonized)
extern uint16_t C_TRACK;       // Recessed progress track #1A2436 (0x1926)
extern uint16_t C_TEXT;        // Crisp off-white #F1F5F9 (0xF7BE)
extern uint16_t C_DIM;         // Cool slate #8A9BB5 (0x8CD6)
extern uint16_t C_MUTED;       // Subtle slate #4D5E78 (0x4AF0)
extern uint16_t C_ACCENT;      // User dynamic accent color
extern uint16_t C_ACCENT_SOFT; // Subtle tinted pill surface
extern uint16_t C_ACCENT_DK;   // Sleek dark header bar surface
extern uint16_t C_OK;          // Emerald #22C55E (0x262B)
extern uint16_t C_WARN;        // Amber #F59E0B (0xF4E1)
extern uint16_t C_HOT;         // Coral Red #EF4444 (0xEA28)
extern uint16_t C_COOL;        // Sky Cyan #38BDF8 (0x3DFF)
extern uint16_t C_PURPLE;      // Violet #A855F7 (0xAAAE)
extern uint16_t C_PINK;        // Rose #EC4899 (0xEA53)

void applyColor565(uint16_t color565);

// ---- Limites termicos e de carga ----
#define T_BUSY          55.0f    // % de uso
#define T_IDLE          12.0f    // % ocioso
#define T_TEMP_HOT      75.0f    // C -> alerta amarelo
#define T_TEMP_MAX      85.0f    // C -> alerta vermelho critico
#define T_NET_CURIOUS    8.0f    // MB/s (rx+tx)
#define T_NET_HEAVY     25.0f    // MB/s (rx+tx)

// ---- Dimensoes do Display (320x240 Landscape) & Geometria do Design System ----
#define SCR_W        320
#define SCR_H        240
#define HDR_H        24
#define TICKER_H     18
#define TICKER_Y     (SCR_H - TICKER_H)          // y = 222..239
#define CONTENT_Y    (HDR_H + 2)                 // y = 26
#define CONTENT_H    (TICKER_Y - CONTENT_Y - 2)  // h = 194 (y = 26..220)
#define CARD_R       7
#define PILL_R       4
#define GAUGE_SLOTS  4

// ---- Historico dos graficos em tempo real ----
#define HIST 140

// ---- Logs (opcional via Linux journalctl) ----
#define LOG_LINES    6
#define LOG_UNIT_MAX 11
#define LOG_MSG_MAX  37

// ---- Layouts / Telas (Controladas 100% pelo Agente Python no PC) ----
#define SCREENS          15
#define SCR_RESUMO       0   // Tela 0: Resumo Geral (Gauges de CPU & RAM + Barras Disco/Rede/Temp)
#define SCR_CPU_RAM      1   // Tela 1: Painel CPU + RAM (Barras + Graficos de CPU e RAM lado a lado)
#define SCR_CPU_RAM_DUAL 2   // Tela 2: Grafico Combinado CPU + RAM (2 curvas sobrepostas)
#define SCR_GPU_FOCUS    3   // Tela 3: GPU Focus (Carga, Temp, VRAM, Watts, FPS, Grafico GPU)
#define SCR_GRAPH        4   // Tela 4: 4 Graficos em Tempo Real (CPU, RAM, GPU, TEMP)
#define SCR_WALLPAPER    5   // Tela 5: Wallpaper Mode (Destaque para imagem de fundo SD + HUD)
#define SCR_MARKET       6   // Tela 6: Mercado Financeiro, Cambio (USD/EUR) & Criptomoedas + Bolsa
#define SCR_PORTFOLIO    7   // Tela 7: Gestao de Portfolio Pessoal (Patrimonio, PnL & Top 3 Ativos)
#define SCR_POMODORO     8   // Tela 8: Hub de Produtividade Pomodoro (Trabalho / Pausa + Buzzer)
#define SCR_MEDIA        9   // Tela 9: Hub Multimidia (Spotify & YouTube Music + Capa SD + Overlay)
#define SCR_NEWS         10  // Tela 10: Clima Regional & Feed de Noticias Customizavel (News API / RSS)
#define SCR_WEATHER_GEMS 10  // Alias de retrocompatibilidade
#define SCR_TERMINAL     11  // Tela 11: Cyber Deck Terminal (Logs, Ping, Fetch, Docker & Wi-Fi Scan)
#define SCR_WIFI_RADAR   12  // Tela 12: Radar Wi-Fi RF, Fluxo Animado de Pacotes & BLE (ESP32-32U)
#define SCR_NET_ANALYZER 13  // Tela 13: Analise de Rede Local, Roteador & Link Fibra
#define SCR_SECURITY     14  // Tela 14: Monitor de Seguranca, IDS & Logs/Erros do Sistema

// Estrutura geometrica auxiliar
struct Rect { int16_t x, y, w, h; };

// ---- Helpers Inline de Manipulacao de Cores RGB565 ----

// Escala os canais R, G, B de uma cor RGB565 por (num / den)
static inline uint16_t scale565(uint16_t c, uint8_t num, uint8_t den) {
  if (den == 0) return c;
  uint16_t r = (((c >> 11) & 0x1F) * num) / den;
  uint16_t g = (((c >> 5)  & 0x3F) * num) / den;
  uint16_t b = (( c        & 0x1F) * num) / den;
  if (r > 0x1F) r = 0x1F;
  if (g > 0x3F) g = 0x3F;
  if (b > 0x1F) b = 0x1F;
  return (uint16_t)((r << 11) | (g << 5) | b);
}

// Atenua uma cor RGB565 para 40% do brilho original
static inline uint16_t dim565(uint16_t c) {
  return scale565(c, 2, 5);
}

// Converte RGB888 (0-255) para RGB565
static inline uint16_t rgb888to565(uint8_t r, uint8_t g, uint8_t b) {
  return (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

// Mistura linearmente duas cores RGB565: alpha=0 -> 100% bg, alpha=255 -> 100% fg
static inline uint16_t blend565(uint16_t bg, uint16_t fg, uint8_t alpha) {
  uint16_t inv = 255 - alpha;
  uint16_t r = (uint16_t)((((bg >> 11) & 0x1F) * inv + ((fg >> 11) & 0x1F) * alpha) / 255);
  uint16_t g = (uint16_t)((((bg >> 5)  & 0x3F) * inv + ((fg >> 5)  & 0x3F) * alpha) / 255);
  uint16_t b = (uint16_t)((( bg        & 0x1F) * inv + ( fg        & 0x1F) * alpha) / 255);
  return (uint16_t)((r << 11) | (g << 5) | b);
}

// Devolve a cor semantica (OK / WARN / HOT) conforme os limites definidos
static inline uint16_t levelColor(float v, float warn, float hot) {
  if (v >= hot)  return C_HOT;
  if (v >= warn) return C_WARN;
  return C_OK;
}
