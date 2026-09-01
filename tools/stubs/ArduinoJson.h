#pragma once
#include "Arduino.h"
#include <vector>
struct JVal {
  template<class T> T operator|(T d) const {return d;}
  const char* operator|(const char* d) const {return d;}
  JVal operator[](int) const {return JVal();}
  bool isNull() const {return true;}
  template<class T> T as() const {return T();}
};
typedef JVal JsonVariant;
struct JsonArray {
  bool isNull() const {return true;}
  JVal* begin() const {return nullptr;}
  JVal* end() const {return nullptr;}
};
template<> inline JsonArray JVal::as<JsonArray>() const {return JsonArray();}
struct JsonDocument { JVal operator[](const char*) const {return JVal();} };
inline int deserializeJson(JsonDocument&, const char*){return 0;}
