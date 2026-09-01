#pragma once
#include "Arduino.h"
class TS_Point { public: int16_t x=0,y=0; uint16_t z=0; };
struct XPT2046_Touchscreen {
  XPT2046_Touchscreen(int,int){}
  void begin(SPIClass&){} void setRotation(int){}
  bool tirqTouched(){return false;} bool touched(){return false;}
  TS_Point getPoint(){return TS_Point();}
};
