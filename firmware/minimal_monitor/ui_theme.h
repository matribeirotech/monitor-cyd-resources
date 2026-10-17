// ui_theme.h - Paleta dinamica e constantes de layout do CYD Hardware Monitor (No-Touch Edition)
#pragma once
#include <Arduino.h>

// ---- Cores (RGB565), atualizadas em tempo real pelo PC (Color Picker / HEX / RGB565) ----
extern uint16_t C_BG;
extern uint16_t C_CARD;
extern uint16_t C_CARD_HI;
extern uint16_t C_TRACK;
extern uint16_t C_TEXT;
extern uint16_t C_DIM;
extern uint16_t C_ACCENT;
extern uint16_t C_ACCENT_DK;
extern uint16_t C_OK;
extern uint16_t C_WARN;
extern uint16_t C_HOT;
extern uint16_t C_COOL;
extern uint16_t C_PINK;

void applyColor565(uint16_t color565);

// ---- Limites termicos e de carga ----
#define T_BUSY          55.0f    // % de uso
#define T_IDLE          12.0f    // % ocioso
#define T_TEMP_HOT      75.0f    // C -> alerta amarelo
#define T_TEMP_MAX      85.0f    // C -> alerta vermelho critico
#define T_NET_CURIOUS    8.0f    // MB/s (rx+tx)
#define T_NET_HEAVY     25.0f    // MB/s (rx+tx)

// ---- Dimensoes do Display (320x240 Landscape) ----
#define SCR_W 320
#define SCR_H 240
#define HDR_H 24

// ---- Historico dos graficos em tempo real ----
#define HIST 140

// ---- Logs (opcional via Linux journalctl) ----
#define LOG_LINES    6
#define LOG_UNIT_MAX 11
#define LOG_MSG_MAX  37

// ---- Layouts / Telas (Controladas 100% pelo Agente Python no PC) ----
#define SCREENS          7
#define SCR_RESUMO       0   // Tela 0: Resumo Geral (Gauges de CPU & RAM + Barras Disco/Rede/Temp)
#define SCR_CPU_RAM      1   // Tela 1: Painel CPU + RAM (Barras + Graficos de CPU e RAM lado a lado, estilo sys.monitor_)
#define SCR_CPU_RAM_DUAL 2   // Tela 2: Grafico Combinado CPU + RAM (2 curvas sobrepostas no mesmo grafico grande)
#define SCR_GPU_FOCUS    3   // Tela 3: GPU Focus (Carga, Temp, VRAM, Watts, FPS, Grafico GPU)
#define SCR_GRAPH        4   // Tela 4: 4 Graficos em Tempo Real (CPU, RAM, GPU, TEMP)
#define SCR_WALLPAPER    5   // Tela 5: Wallpaper Mode (Destaque para a imagem de fundo do SD + HUD CPU/RAM)
#define SCR_MARKET       6   // Tela 6: Mercado Financeiro, Cambio (USD/EUR) & Criptomoedas + Bolsa

// Estrutura geometrica auxiliar
struct Rect { int16_t x, y, w, h; };

// Devolve a cor (OK / WARN / HOT) conforme os limites definidos
static inline uint16_t levelColor(float v, float warn, float hot) {
  if (v >= hot)  return C_HOT;
  if (v >= warn) return C_WARN;
  return C_OK;
}
