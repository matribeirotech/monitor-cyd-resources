#pragma once
#include "Arduino.h"
#define ML_DATUM 0
#define MR_DATUM 1
#define MC_DATUM 2
#define TL_DATUM 3
#define TR_DATUM 4
struct TFT_eSPI {
  void init(){} void setRotation(int){} void fillScreen(uint16_t){}
  void fillRect(int,int,int,int,uint16_t){}
  void fillRoundRect(int,int,int,int,int,uint16_t){}
  void drawRoundRect(int,int,int,int,int,uint16_t){}
  void fillCircle(int,int,int,uint16_t){}
  void drawLine(int,int,int,int,uint16_t){}
  void drawPixel(int,int,uint16_t){}
  void drawFastVLine(int,int,int,uint16_t){}
  void drawSmoothArc(int,int,int,int,uint32_t,uint32_t,uint32_t,uint32_t,bool){}
  void setTextDatum(uint8_t){} void setTextPadding(uint16_t){}
  void setTextColor(uint16_t,uint16_t){}
  void drawString(const char*,int,int,uint8_t){}
};
struct TFT_eSprite {
  TFT_eSprite(TFT_eSPI*){}
  void createSprite(int,int){} void fillSprite(uint16_t){}
  void fillRect(int,int,int,int,uint16_t){}
  void pushSprite(int,int){}
};
