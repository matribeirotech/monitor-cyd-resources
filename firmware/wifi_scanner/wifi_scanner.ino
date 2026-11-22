/*
 * ============================================================================
 *  CYD CYBER DECK — ESP32-WROOM-32U WI-FI RADAR + LONG-RANGE BLE BRIDGE (v2.0)
 *  Placa: ESP32-WROOM-32U (Antena Externa 2.4 GHz • Wi-Fi + Bluetooth +9 dBm)
 *
 *  Operacao 100% sem fio (cabo micro-USB apenas para energia):
 *    1) WI-FI RADAR / RF TELEMETRY (Tela 12):
 *       - Anuncia hostname mDNS `cyd-radar.local` na rede local.
 *       - Executa varreduras passivas periodicas das redes Wi-Fi 2.4 GHz proximas.
 *       - Transmite telemetria JSON via Wi-Fi UDP (:8889 PC Agent e :8888 CYD).
 *
 *    2) LONG-RANGE BLUETOOTH LOW ENERGY (BLE +9 dBm + Antena Externa):
 *       - Dispositivo BLE anunciando como: "CYD-RADAR-32U"
 *       - Servico Nordic UART Service (NUS) — compativel com Web Bluetooth (PWA
 *         Mobile :8088/:8443), ble_monitor.html, Flutter e apps BLE Terminal:
 *           * Service UUID : 6e400001-b5a3-f393-e0a9-e50e24dcca9e
 *           * RX (Write)   : 6e400002-b5a3-f393-e0a9-e50e24dcca9e
 *           * TX (Notify)  : 6e400003-b5a3-f393-e0a9-e50e24dcca9e
 *       - Recebe snapshot ao vivo do PC Agent via UDP :8890 ({"cmd":"ble_push","snap":{...}})
 *         contendo Hardware, Rede/Fibra, Seguranca/IDS (Tela 14) e Mercado, e transmite
 *         em tempo real para o smartphone conectado via BLE!
 *       - Encaminha comandos recebidos do smartphone via BLE (troca de tela, scan RF,
 *         ack/sim de seguranca, speedtest, brilho) de volta ao PC Agent via UDP :8889!
 *
 *    3) Provisionamento via Serial USB (115200 bps) gravado em NVS:
 *       - wifi <SSID>|<SENHA> | interval <seg> | scan | status | reboot | help
 * ============================================================================
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <ArduinoJson.h>

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <esp_bt.h>

#ifndef WIFI_SSID_DEFAULT
#define WIFI_SSID_DEFAULT ""
#endif
#ifndef WIFI_PASS_DEFAULT
#define WIFI_PASS_DEFAULT ""
#endif

#define UDP_AGENT_PORT   8889   // Porta escutada pelo Agente PC (wifi_scanner.py)
#define UDP_CYD_PORT     8888   // Porta escutada diretamente pela placa CYD
#define UDP_CMD_PORT     8890   // Porta de comando/inscricao/ble_push UDP
#define LED_BUILTIN_PIN  2
#define MAX_APS_CYD      6
#define MAX_APS_FULL     16
#define MAX_SUBS         4
#define SUB_TTL_MS       60000UL

// Nordic UART Service (NUS) UUIDs — padrao universal Web Bluetooth + Mobile
#define BLE_DEVICE_NAME  "CYD-RADAR-32U"
#define NUS_SERVICE_UUID "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#define NUS_RX_CHAR_UUID "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
#define NUS_TX_CHAR_UUID "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
#define BLE_CHUNK_SIZE   180

Preferences prefs;
WiFiUDP udpCmd;

char     wifiSsid[64]     = WIFI_SSID_DEFAULT;
char     wifiPass[64]     = WIFI_PASS_DEFAULT;
uint16_t scanIntervalSec  = 8;
uint32_t scanCount        = 0;
uint32_t lastScanMs       = 0;
bool     forceScanFlag    = true;
bool     udpStarted       = false;
bool     mdnsStarted      = false;

String   lastJsonCyd      = "";
String   lastJsonFull     = "";
String   lastHostSnap     = "";
uint32_t lastHostSnapMs   = 0;

// ---- Estado BLE (Longo Alcance +9 dBm c/ Antena Externa) ----
BLEServer*         pBleServer   = nullptr;
BLECharacteristic* pBleTxChar   = nullptr;
BLECharacteristic* pBleRxChar   = nullptr;
volatile bool      bleConnected = false;
volatile bool      bleOldConn   = false;
volatile uint8_t   bleClients   = 0;
volatile bool      bleCmdReady  = false;
String             bleCmdPending = "";
uint32_t           lastBleSendMs = 0;
uint32_t           bleTxPackets  = 0;
bool               bleReady      = false;

struct UdpSub {
  IPAddress ip;
  uint16_t  port;
  uint32_t  lastSeenMs;
  bool      active;
};
UdpSub subs[MAX_SUBS];

char     serialBuf[192];
uint16_t serialLen        = 0;

struct ScannedNet {
  char    ssid[25];
  int16_t rssi;
  uint8_t ch;
  char    bssid[18];
  char    enc[6];
  bool    isOpen;
};

// Prototipos antecipados
static void sendBleChunkedLine(const String& line);
static void forwardBleCmdToAgent(const String& cmdLine);

class CydBleServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) override {
    bleConnected = true;
    bleClients = (uint8_t)max((int)pServer->getConnectedCount(), 1);
    esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_CONN_HDL0, ESP_PWR_LVL_P9);
    Serial.printf("[BLE] Dispositivo movel conectado! Clientes: %u (TX +9 dBm Antena Externa)\n", (unsigned)bleClients);
  }
  void onDisconnect(BLEServer* pServer) override {
    int cnt = pServer->getConnectedCount();
    bleClients = (uint8_t)max(cnt - 1, 0);
    if (bleClients == 0) {
      bleConnected = false;
    }
    Serial.println("[BLE] Dispositivo movel desconectado. Reiniciando advertising...");
  }
};

class CydBleRxCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* pChar) override {
    String val = pChar->getValue();
    if (val.length() == 0) return;
    val.trim();
    if (val.length() > 0 && val.length() < 240) {
      bleCmdPending = val;
      bleCmdReady = true;
    }
  }
};

static void initBleLongRange() {
  BLEDevice::init(BLE_DEVICE_NAME);
  BLEDevice::setMTU(512);

  // Potencia maxima de transmissao BLE (+9 dBm) aproveitando a antena externa 2.4 GHz
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_DEFAULT, ESP_PWR_LVL_P9);
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_ADV,     ESP_PWR_LVL_P9);
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_SCAN,    ESP_PWR_LVL_P9);

  pBleServer = BLEDevice::createServer();
  pBleServer->setCallbacks(new CydBleServerCallbacks());

  BLEService* pService = pBleServer->createService(NUS_SERVICE_UUID);

  pBleTxChar = pService->createCharacteristic(
    NUS_TX_CHAR_UUID,
    BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ
  );
  pBleTxChar->addDescriptor(new BLE2902());

  pBleRxChar = pService->createCharacteristic(
    NUS_RX_CHAR_UUID,
    BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR
  );
  pBleRxChar->setCallbacks(new CydBleRxCallbacks());

  pService->start();

  BLEAdvertising* pAdv = BLEDevice::getAdvertising();
  pAdv->addServiceUUID(NUS_SERVICE_UUID);
  pAdv->setScanResponse(true);
  pAdv->setMinPreferred(0x06);  // melhora compatibilidade iOS/Android
  pAdv->setMaxPreferred(0x12);
  BLEDevice::startAdvertising();

  bleReady = true;
  Serial.println("[BLE] GATT Server 'CYD-RADAR-32U' ativo (NUS +9 dBm Long-Range)!");
}

static void sendBleChunkedLine(const String& line) {
  if (!bleReady || !bleConnected || pBleTxChar == nullptr || line.length() == 0) return;
  String framed = line;
  if (!framed.endsWith("\n")) framed += "\n";

  const size_t total = framed.length();
  size_t offset = 0;
  while (offset < total && bleConnected) {
    size_t chunkLen = min((size_t)BLE_CHUNK_SIZE, total - offset);
    pBleTxChar->setValue((uint8_t*)(framed.c_str() + offset), chunkLen);
    pBleTxChar->notify();
    offset += chunkLen;
    if (offset < total) delay(8);
  }
  bleTxPackets++;
  lastBleSendMs = millis();
}

static void sanitizeAscii(char* dst, const char* src, size_t maxLen) {
  if (!dst || maxLen == 0) return;
  if (!src) { dst[0] = '\0'; return; }
  size_t j = 0;
  for (size_t i = 0; src[i] != '\0' && j < maxLen - 1; i++) {
    uint8_t c = (uint8_t)src[i];
    if (c >= 0x20 && c <= 0x7E) {
      dst[j++] = (char)c;
    } else if (c == 0xC3 && src[i + 1] != '\0') {
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

static const char* authToShort(wifi_auth_mode_t m) {
  switch (m) {
    case WIFI_AUTH_OPEN:            return "OPEN";
    case WIFI_AUTH_WEP:             return "WEP";
    case WIFI_AUTH_WPA_PSK:         return "WPA";
    case WIFI_AUTH_WPA2_PSK:        return "WPA2";
    case WIFI_AUTH_WPA_WPA2_PSK:    return "WPA2";
    case WIFI_AUTH_WPA2_ENTERPRISE: return "ENT";
    case WIFI_AUTH_WPA3_PSK:        return "WPA3";
    case WIFI_AUTH_WPA2_WPA3_PSK:   return "WPA3";
    default:                        return "WPA";
  }
}

static IPAddress getBroadcastIP() {
  if (WiFi.status() == WL_CONNECTED) {
    IPAddress ip   = WiFi.localIP();
    IPAddress mask = WiFi.subnetMask();
    return IPAddress(
      ip[0] | (~mask[0] & 0xFF),
      ip[1] | (~mask[1] & 0xFF),
      ip[2] | (~mask[2] & 0xFF),
      ip[3] | (~mask[3] & 0xFF)
    );
  }
  return IPAddress(255, 255, 255, 255);
}

static void blinkLed(uint8_t times, uint16_t ms = 55) {
  for (uint8_t i = 0; i < times; i++) {
    digitalWrite(LED_BUILTIN_PIN, HIGH);
    delay(ms);
    digitalWrite(LED_BUILTIN_PIN, LOW);
    if (i + 1 < times) delay(ms);
  }
}

static void sendUdpTo(IPAddress ip, uint16_t port, const String& payload) {
  if (WiFi.status() != WL_CONNECTED || !udpStarted || payload.length() == 0) return;
  udpCmd.beginPacket(ip, port);
  udpCmd.write((const uint8_t*)payload.c_str(), payload.length());
  udpCmd.endPacket();
}

static void registerSubscriber(IPAddress ip, uint16_t port) {
  if (port == 0) port = UDP_AGENT_PORT;
  uint32_t now = millis();
  int freeIdx = -1;
  int oldestIdx = 0;
  uint32_t oldestAge = 0;

  for (int i = 0; i < MAX_SUBS; i++) {
    if (subs[i].active && subs[i].ip == ip && subs[i].port == port) {
      subs[i].lastSeenMs = now;
      return;
    }
    if (!subs[i].active && freeIdx < 0) freeIdx = i;
    uint32_t age = now - subs[i].lastSeenMs;
    if (age >= oldestAge) {
      oldestAge = age;
      oldestIdx = i;
    }
  }
  int slot = (freeIdx >= 0) ? freeIdx : oldestIdx;
  subs[slot].ip = ip;
  subs[slot].port = port;
  subs[slot].lastSeenMs = now;
  subs[slot].active = true;
}

static void dispatchPayloadToAgents(const String& payload) {
  if (WiFi.status() != WL_CONNECTED || !udpStarted || payload.length() == 0) return;
  uint32_t now = millis();
  bool sentUnicast = false;
  for (int i = 0; i < MAX_SUBS; i++) {
    if (!subs[i].active) continue;
    if ((now - subs[i].lastSeenMs) > SUB_TTL_MS) {
      subs[i].active = false;
      continue;
    }
    sendUdpTo(subs[i].ip, subs[i].port, payload);
    sentUnicast = true;
    delay(4);
  }
  if (!sentUnicast) {
    sendUdpTo(getBroadcastIP(), UDP_AGENT_PORT, payload);
  }
}

static void dispatchToSubscribersAndBroadcast() {
  if (WiFi.status() != WL_CONNECTED || !udpStarted) return;
  const String& agentPkt = (lastJsonFull.length() > 0 && lastJsonFull.length() <= 1380) ? lastJsonFull : lastJsonCyd;

  uint32_t now = millis();
  for (int i = 0; i < MAX_SUBS; i++) {
    if (!subs[i].active) continue;
    if ((now - subs[i].lastSeenMs) > SUB_TTL_MS) {
      subs[i].active = false;
      continue;
    }
    sendUdpTo(subs[i].ip, subs[i].port, agentPkt);
    delay(6);
  }

  IPAddress bcast = getBroadcastIP();
  if (lastJsonCyd.length() > 0) {
    sendUdpTo(bcast, UDP_CYD_PORT, lastJsonCyd);
    delay(10);
  }
  if (agentPkt.length() > 0) {
    sendUdpTo(bcast, UDP_AGENT_PORT, agentPkt);
  }
}

static bool ensureWiFiConnected(uint32_t timeoutMs = 8000) {
  if (wifiSsid[0] == '\0') return false;
  if (WiFi.status() == WL_CONNECTED) {
    if (!udpStarted) udpStarted = udpCmd.begin(UDP_CMD_PORT);
    if (!mdnsStarted) mdnsStarted = MDNS.begin("cyd-radar");
    return true;
  }

  WiFi.mode(WIFI_STA);
  // Nota: com BLE + Wi-Fi coexistindo no ESP32, modem-sleep e gerenciado pelo driver
  WiFi.begin(wifiSsid, wifiPass);

  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - t0) < timeoutMs) {
    delay(150);
  }

  if (WiFi.status() == WL_CONNECTED) {
    if (!udpStarted) udpStarted = udpCmd.begin(UDP_CMD_PORT);
    if (!mdnsStarted) mdnsStarted = MDNS.begin("cyd-radar");
    Serial.printf("[WIFI] Conectado em '%s' | IP: %s | mDNS: cyd-radar.local | RSSI: %d dBm\n",
                  wifiSsid, WiFi.localIP().toString().c_str(), WiFi.RSSI());
    return true;
  }
  Serial.printf("[WIFI] Falha ao conectar em '%s' (status=%d)\n", wifiSsid, (int)WiFi.status());
  return false;
}

static uint8_t pickBestNonOverlappingChannel(const uint8_t chCounts[13]) {
  const uint8_t cands[3] = {1, 6, 11};
  uint8_t bestCh = 1;
  int bestScore = 99999;

  for (int i = 0; i < 3; i++) {
    uint8_t c = cands[i];
    int direct = chCounts[c - 1];
    int adj = 0;
    for (int k = max(1, (int)c - 2); k <= min(13, (int)c + 2); k++) {
      if (k != c) adj += chCounts[k - 1];
    }
    int score = direct * 3 + adj;
    if (score < bestScore) {
      bestScore = score;
      bestCh = c;
    }
  }
  return bestCh;
}

static void runScanAndBroadcast() {
  digitalWrite(LED_BUILTIN_PIN, HIGH);

  WiFi.mode(WIFI_STA);
  int n = WiFi.scanNetworks(false, true);
  if (n < 0) n = 0;

  const int maxStore = min(n, 32);
  ScannedNet nets[32];
  uint8_t chCounts[13] = {0};
  int32_t rssiSum = 0;
  uint8_t openCnt = 0;

  for (int i = 0; i < maxStore; i++) {
    String s = WiFi.SSID(i);
    sanitizeAscii(nets[i].ssid, s.c_str(), sizeof(nets[i].ssid));
    if (nets[i].ssid[0] == '\0') strlcpy(nets[i].ssid, "<OCULTA>", sizeof(nets[i].ssid));
    nets[i].rssi = (int16_t)WiFi.RSSI(i);
    nets[i].ch   = (uint8_t)constrain((int)WiFi.channel(i), 0, 14);
    strlcpy(nets[i].bssid, WiFi.BSSIDstr(i).c_str(), sizeof(nets[i].bssid));
    wifi_auth_mode_t auth = WiFi.encryptionType(i);
    strlcpy(nets[i].enc, authToShort(auth), sizeof(nets[i].enc));
    nets[i].isOpen = (auth == WIFI_AUTH_OPEN);
    if (nets[i].isOpen) openCnt++;
    rssiSum += nets[i].rssi;
    if (nets[i].ch >= 1 && nets[i].ch <= 13) {
      chCounts[nets[i].ch - 1]++;
    }
  }

  for (int i = 1; i < maxStore; i++) {
    ScannedNet key = nets[i];
    int j = i - 1;
    while (j >= 0 && nets[j].rssi < key.rssi) {
      nets[j + 1] = nets[j];
      j--;
    }
    nets[j + 1] = key;
  }

  WiFi.scanDelete();
  scanCount++;

  uint8_t busiestCh = 0;
  uint8_t maxChCnt = 0;
  for (int c = 0; c < 13; c++) {
    if (chCounts[c] > maxChCnt) {
      maxChCnt = chCounts[c];
      busiestCh = c + 1;
    }
  }
  uint8_t freeCh   = pickBestNonOverlappingChannel(chCounts);
  int16_t bestRssi = (maxStore > 0) ? nets[0].rssi : 0;
  int16_t avgRssi  = (maxStore > 0) ? (int16_t)(rssiSum / maxStore) : 0;

  bool wifiOk = ensureWiFiConnected(5000);
  String myIp = wifiOk ? WiFi.localIP().toString() : "";

  JsonDocument docCyd;
  JsonObject w = docCyd["wrad"].to<JsonObject>();
  w["on"]   = true;
  w["scan"] = false;
  w["port"] = wifiOk ? ("UDP:" + myIp) : "BLE_ONLY";
  w["tot"]  = n;
  w["open"] = openCnt;
  w["best"] = bestRssi;
  w["avg"]  = avgRssi;
  w["bch"]  = busiestCh;
  w["fch"]  = freeCh;
  w["age"]  = 0;
  w["sc"]   = scanCount;
  w["ble"]  = bleConnected ? 1 : 0;
  w["bcli"] = (uint8_t)bleClients;
  w["bpwr"] = 9;

  JsonArray chArr = w["ch"].to<JsonArray>();
  for (int c = 0; c < 13; c++) chArr.add(chCounts[c]);

  JsonArray apsArr = w["aps"].to<JsonArray>();
  int topN = min(maxStore, MAX_APS_CYD);
  for (int i = 0; i < topN; i++) {
    JsonArray row = apsArr.add<JsonArray>();
    char shortSsid[17];
    strlcpy(shortSsid, nets[i].ssid, sizeof(shortSsid));
    row.add(shortSsid);
    row.add(nets[i].rssi);
    row.add(nets[i].ch);
    row.add(nets[i].bssid);
    row.add(nets[i].enc);
  }

  lastJsonCyd = "";
  serializeJson(docCyd, lastJsonCyd);

  JsonDocument docFull;
  JsonObject wf = docFull["wrad_full"].to<JsonObject>();
  wf["ip"]   = myIp;
  wf["tot"]  = n;
  wf["open"] = openCnt;
  wf["best"] = bestRssi;
  wf["avg"]  = avgRssi;
  wf["bch"]  = busiestCh;
  wf["fch"]  = freeCh;
  wf["sc"]   = scanCount;
  wf["ble"]  = bleConnected ? 1 : 0;
  wf["bcli"] = (uint8_t)bleClients;
  wf["bpwr"] = 9;
  wf["bnam"] = BLE_DEVICE_NAME;

  JsonArray chFull = wf["ch"].to<JsonArray>();
  for (int c = 0; c < 13; c++) chFull.add(chCounts[c]);

  JsonArray apsFull = wf["aps"].to<JsonArray>();
  int fullN = min(maxStore, MAX_APS_FULL);
  for (int i = 0; i < fullN; i++) {
    JsonArray row = apsFull.add<JsonArray>();
    row.add(nets[i].ssid);
    row.add(nets[i].rssi);
    row.add(nets[i].ch);
    row.add(nets[i].bssid);
    row.add(nets[i].enc);
  }

  lastJsonFull = "";
  serializeJson(docFull, lastJsonFull);

  if (wifiOk) {
    dispatchToSubscribersAndBroadcast();
  }

  // Se houver celular conectado via BLE, tambem envia o radar local imediatamente!
  if (bleConnected && lastJsonCyd.length() > 0) {
    sendBleChunkedLine(lastJsonCyd);
  }

  Serial.print("WRAD_JSON:");
  Serial.println(lastJsonCyd);

  digitalWrite(LED_BUILTIN_PIN, LOW);
}

static void forwardBleCmdToAgent(const String& cmdLine) {
  JsonDocument doc;
  JsonObject bc = doc["ble_cmd"].to<JsonObject>();
  bc["raw"] = cmdLine;
  bc["src"] = BLE_DEVICE_NAME;

  // Se ja for JSON valido do app mobile, aninha os campos
  JsonDocument parsed;
  if (cmdLine.startsWith("{") && deserializeJson(parsed, cmdLine) == DeserializationError::Ok) {
    bc["json"] = parsed.as<JsonVariant>();
  }

  String out;
  serializeJson(doc, out);
  dispatchPayloadToAgents(out);
  Serial.printf("[BLE->AGENT] Encaminhado: %s\n", cmdLine.c_str());
}

static void processBleCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;
  Serial.printf("[BLE RX] %s\n", cmd.c_str());

  if (cmd.equalsIgnoreCase("scan") || cmd.indexOf("\"scan_now\"") >= 0) {
    forceScanFlag = true;
    sendBleChunkedLine("{\"ble_ack\":\"scan_started\"}");
    return;
  }
  if (cmd.equalsIgnoreCase("status") || cmd.equalsIgnoreCase("ping")) {
    char stBuf[192];
    snprintf(stBuf, sizeof(stBuf),
             "{\"ble_status\":{\"name\":\"%s\",\"ip\":\"%s\",\"rssi\":%d,\"pwr\":9,\"scans\":%lu,\"tx\":%lu}}",
             BLE_DEVICE_NAME,
             (WiFi.status() == WL_CONNECTED) ? WiFi.localIP().toString().c_str() : "OFFLINE",
             (WiFi.status() == WL_CONNECTED) ? WiFi.RSSI() : 0,
             (unsigned long)scanCount,
             (unsigned long)bleTxPackets);
    sendBleChunkedLine(String(stBuf));
    if (lastHostSnap.length() > 0) {
      sendBleChunkedLine(lastHostSnap);
    }
    return;
  }
  if (cmd.equalsIgnoreCase("help")) {
    sendBleChunkedLine("{\"ble_help\":\"Comandos: screen 0..14 | scan | sec_ack | sec_sim | speed | status\"}");
    return;
  }

  // Encaminha comando para o PC Agent (troca de tela CYD, ACK seguranca, speedtest, brilho, etc.)
  forwardBleCmdToAgent(cmd);
  sendBleChunkedLine("{\"ble_ack\":\"forwarded\"}");
}

static void printHelp() {
  Serial.println("============================================================");
  Serial.println("  ESP32-WROOM-32U WI-FI RADAR + LONG-RANGE BLE BRIDGE v2.0");
  Serial.println("============================================================");
  Serial.println("Comandos Serial (115200 bps):");
  Serial.println("  wifi <SSID>|<SENHA>  - Salva Wi-Fi na NVS e conecta");
  Serial.println("  interval <seg>       - Intervalo entre scans (4..60s)");
  Serial.println("  scan                 - Executa scan RF e transmite UDP/BLE");
  Serial.println("  status               - Mostra Wi-Fi, BLE (+9dBm), RSSI e subs");
  Serial.println("  reboot               - Reinicia a placa");
  Serial.println("  help                 - Exibe esta ajuda");
}

static void printStatus() {
  int subCnt = 0;
  for (int i = 0; i < MAX_SUBS; i++) if (subs[i].active) subCnt++;
  Serial.printf("RADAR_STATUS: wifi=%s ssid='%s' ip=%s mdns=cyd-radar.local rssi=%d ble=%s(%u) pwr=+9dBm interval=%us scans=%lu subs=%d heap=%lu\n",
                (WiFi.status() == WL_CONNECTED) ? "CONNECTED" : "OFFLINE",
                wifiSsid,
                (WiFi.status() == WL_CONNECTED) ? WiFi.localIP().toString().c_str() : "0.0.0.0",
                (WiFi.status() == WL_CONNECTED) ? WiFi.RSSI() : 0,
                bleConnected ? "CONNECTED" : "ADV",
                (unsigned)bleClients,
                (unsigned)scanIntervalSec,
                (unsigned long)scanCount,
                subCnt,
                (unsigned long)ESP.getFreeHeap());
}

static void handleSerialCommand(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line.equalsIgnoreCase("help")) {
    printHelp();
  } else if (line.equalsIgnoreCase("status")) {
    printStatus();
  } else if (line.equalsIgnoreCase("scan")) {
    forceScanFlag = true;
  } else if (line.equalsIgnoreCase("reboot")) {
    Serial.println("[SYS] Reiniciando...");
    delay(200);
    ESP.restart();
  } else if (line.startsWith("wifi ")) {
    String rest = line.substring(5);
    int sep = rest.indexOf('|');
    if (sep <= 0) {
      Serial.println("[ERR] Uso correto: wifi <SSID>|<SENHA>");
      return;
    }
    String s = rest.substring(0, sep);
    String p = rest.substring(sep + 1);
    s.trim();
    strlcpy(wifiSsid, s.c_str(), sizeof(wifiSsid));
    strlcpy(wifiPass, p.c_str(), sizeof(wifiPass));
    prefs.putString("ssid", wifiSsid);
    prefs.putString("pass", wifiPass);
    Serial.printf("[WIFI] Credenciais salvas na NVS para '%s'. Conectando...\n", wifiSsid);
    WiFi.disconnect(true);
    udpStarted = false;
    mdnsStarted = false;
    delay(150);
    ensureWiFiConnected(10000);
    printStatus();
    forceScanFlag = true;
  } else if (line.startsWith("interval ")) {
    int v = line.substring(9).toInt();
    scanIntervalSec = (uint16_t)constrain(v, 4, 60);
    prefs.putUShort("interval", scanIntervalSec);
    Serial.printf("[CFG] Intervalo de scan ajustado para %us\n", (unsigned)scanIntervalSec);
  } else {
    Serial.printf("[WARN] Comando desconhecido: '%s' (digite 'help')\n", line.c_str());
  }
}

static void pumpSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (serialLen > 0) {
        serialBuf[serialLen] = '\0';
        handleSerialCommand(String(serialBuf));
        serialLen = 0;
      }
    } else if (serialLen < sizeof(serialBuf) - 1) {
      serialBuf[serialLen++] = c;
    }
  }
}

static void pumpUdpCommands() {
  if (!udpStarted || WiFi.status() != WL_CONNECTED) return;
  int pktSize = udpCmd.parsePacket();
  while (pktSize > 0) {
    IPAddress rIp   = udpCmd.remoteIP();
    uint16_t  rPort = udpCmd.remotePort();
    static char buf[1460];
    int len = udpCmd.read(buf, sizeof(buf) - 1);
    if (len > 0) {
      buf[len] = '\0';
      registerSubscriber(rIp, rPort);

      // Push de telemetria completa do PC Agent para streaming BLE em tempo real!
      if (strstr(buf, "\"ble_push\"") != nullptr) {
        lastHostSnap = String(buf);
        lastHostSnap.trim();
        lastHostSnapMs = millis();
        if (bleConnected) {
          sendBleChunkedLine(lastHostSnap);
        }
      } else {
        // Inscricao ou comando padrao ("sub" / "scan_now")
        const String& replyPkt = (lastJsonFull.length() > 0 && lastJsonFull.length() <= 1380) ? lastJsonFull : lastJsonCyd;
        if (replyPkt.length() > 0) {
          sendUdpTo(rIp, rPort, replyPkt);
        }
        if (strstr(buf, "scan_now") != nullptr) {
          forceScanFlag = true;
        }
      }
    }
    pktSize = udpCmd.parsePacket();
  }
}

static void pumpBleMaintenance() {
  if (!bleReady) return;

  // Processa comando recebido via BLE
  if (bleCmdReady) {
    String cmd = bleCmdPending;
    bleCmdPending = "";
    bleCmdReady = false;
    processBleCommand(cmd);
  }

  // Transicao de conexao/desconexao BLE
  if (bleConnected && !bleOldConn) {
    bleOldConn = true;
    // Ao conectar, envia imediatamente o ultimo snapshot do PC + radar RF
    if (lastHostSnap.length() > 0) {
      sendBleChunkedLine(lastHostSnap);
    }
    if (lastJsonCyd.length() > 0) {
      delay(15);
      sendBleChunkedLine(lastJsonCyd);
    }
    // Avisa o PC Agent imediatamente que ha um celular conectado via BLE
    dispatchToSubscribersAndBroadcast();
  } else if (!bleConnected && bleOldConn) {
    bleOldConn = false;
    delay(250);
    if (pBleServer != nullptr) {
      pBleServer->startAdvertising();
    }
    dispatchToSubscribersAndBroadcast();
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN_PIN, OUTPUT);
  digitalWrite(LED_BUILTIN_PIN, LOW);

  for (int i = 0; i < MAX_SUBS; i++) subs[i].active = false;

  prefs.begin("wrad_node", false);
  String sSaved = prefs.getString("ssid", WIFI_SSID_DEFAULT);
  String pSaved = prefs.getString("pass", WIFI_PASS_DEFAULT);
  scanIntervalSec = (uint16_t)constrain((int)prefs.getUShort("interval", 8), 4, 60);

  if (sSaved.length() > 0) {
    strlcpy(wifiSsid, sSaved.c_str(), sizeof(wifiSsid));
    strlcpy(wifiPass, pSaved.c_str(), sizeof(wifiPass));
  }

  delay(350);
  blinkLed(2, 60);
  printHelp();

  // Inicializa BLE Long-Range (+9 dBm) antes/em conjunto com Wi-Fi
  initBleLongRange();

  if (wifiSsid[0] != '\0') {
    ensureWiFiConnected(8000);
  } else {
    Serial.println("[WIFI] Nenhum SSID configurado. Use: wifi <SSID>|<SENHA>");
  }
  printStatus();
}

void loop() {
  pumpSerial();
  pumpUdpCommands();
  pumpBleMaintenance();

  uint32_t now = millis();
  if (forceScanFlag || (now - lastScanMs) >= ((uint32_t)scanIntervalSec * 1000UL)) {
    forceScanFlag = false;
    lastScanMs = now;
    runScanAndBroadcast();
  }

  delay(15);
}
