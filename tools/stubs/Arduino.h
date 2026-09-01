#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <string>
#define PROGMEM
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define VSPI 3
typedef uint8_t byte;
inline uint8_t pgm_read_byte(const void*p){return *(const uint8_t*)p;}
inline uint16_t pgm_read_word(const void*p){return *(const uint16_t*)p;}
inline void pinMode(int,int){}
inline void digitalWrite(int,int){}
extern unsigned long g_millis;
inline unsigned long millis(){return g_millis;}
inline void delay(unsigned long ms){g_millis+=ms;}
template<class T,class A,class B> T constrain(T x,A a,B b){return x<(T)a?(T)a:(x>(T)b?(T)b:x);}
inline size_t strlcpy(char*d,const char*s,size_t n){size_t l=strlen(s);if(n){size_t c=l>=n?n-1:l;memcpy(d,s,c);d[c]=0;}return l;}
struct SerialC{void begin(int){} int available(){return 0;} int read(){return -1;}
  void println(const char*){}};
extern SerialC Serial;
struct SPIClass{SPIClass(int){} void begin(int,int,int,int){}};
#define INPUT_PULLUP 2
#define ESP_ARDUINO_VERSION_MAJOR 3
inline int digitalRead(int){return 1;}
inline bool ledcAttach(int,int,int){return true;}
inline void ledcWriteTone(int,int){}
inline void ledcDetach(int){}
inline long random(long howbig){ return howbig<=0?0:std::rand()%howbig; }
inline long random(long howsmall,long howbig){ return howsmall>=howbig?howsmall:howsmall+std::rand()%(howbig-howsmall); }
