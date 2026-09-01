// ui_theme.h - paleta e constantes de layout do Mike Monitor
#pragma once
#include <Arduino.h>

// ---- cores (RGB565), variaveis para suportar multiplos temas ----
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

extern uint8_t currentTheme;
void applyTheme(uint8_t t);


// ---- limites que definem o humor do Mike ----
#define T_BUSY      55.0f    // % de uso -> "trabalhando"
#define T_IDLE      12.0f    // abaixo disso -> "dormindo"
#define T_TEMP_HOT  75.0f    // C -> "ta quente"
#define T_TEMP_MAX  85.0f    // C -> "SOCORRO"
#define T_NET_CURIOUS  8.0f   // MB/s (rx+tx) -> pico rapido, "curioso"
#define T_NET_HEAVY   25.0f   // MB/s (rx+tx) sustentado -> rede pesada, escalado

// ---- layout ----
#define SCR_W 320
#define SCR_H 240
#define HDR_H 22

// ---- historico dos graficos ----
#define HIST 140

// ---- logs ----
#define LOG_LINES    6     // linhas guardadas/exibidas na tela de logs
#define LOG_UNIT_MAX 11    // +1 para o terminador
#define LOG_MSG_MAX  37
#define LOG_RATE_ANGRY 3.0f   // erros/min acima disso o Mike fica bravo
#define LOG_RATE_WARN  1.0f

// ---- tempos das reacoes (ms) ----
#define REACT_SCARE   4000    // susto ao chegar erro novo
#define REACT_CRIT    7000    // susto maior em erro critico
#define REACT_HAPPY   6000    // comemoracao (boot, uptime redondo)
#define REACT_CURIOUS 3000    // curiosidade (pico de rede)
#define IDLE_WALK_MS  20000   // ocioso por tanto tempo -> Mike passeia

// ---- numero de telas ----
#define SCREENS 3
#define SCR_MAIN  0
#define SCR_GRAPH 1
#define SCR_TEMP  2
#define SCR_SET   3

// ---- pomodoro ----
#define POMO_WORK_MIN   25    // duracao do ciclo de foco
#define POMO_SHORT_MIN   5    // pausa curta
#define POMO_LONG_MIN   15    // pausa longa
#define POMO_CELEBRATE 8000   // quanto tempo o Mike comemora no fim do ciclo (ms)

// Retangulo de toque.
// MORA AQUI DE PROPOSITO: o Arduino/PlatformIO gera prototipos de todas as
// funcoes do .ino e os injeta no topo do arquivo. Como drawButton() e inside()
// recebem um "const Rect&", o tipo precisa existir antes desses prototipos --
// ou seja, tem que vir de um header, nao do meio do .ino.
struct Rect { int16_t x, y, w, h; };

// devolve verde/laranja/vermelho conforme o valor
static inline uint16_t levelColor(float v, float warn, float hot) {
  if (v >= hot) return C_HOT;
  if (v >= warn) return C_WARN;
  return C_OK;
}
