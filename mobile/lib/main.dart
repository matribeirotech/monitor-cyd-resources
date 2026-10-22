// lib/main.dart
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'models/cyd_models.dart';
import 'services/cyd_api_service.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
    systemNavigationBarColor: Color(0xFF07090E),
  ));
  runApp(const CydMobileApp());
}

class CydMobileApp extends StatelessWidget {
  const CydMobileApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'CYD Mobile Controller',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: const Color(0xFF07090E),
        primaryColor: const Color(0xFF00FF00),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF00FF00),
          surface: Color(0xFF0F141F),
        ),
      ),
      home: const CydHomeScreen(),
    );
  }
}

class CydHomeScreen extends StatefulWidget {
  const CydHomeScreen({super.key});

  @override
  State<CydHomeScreen> createState() => _CydHomeScreenState();
}

class _CydHomeScreenState extends State<CydHomeScreen> {
  final CydApiService api = CydApiService();
  CydAppState? state;
  int currentTab = 0;
  Timer? pollTimer;
  bool isConnected = false;
  String hostUrl = 'http://192.168.0.109:8088';

  @override
  void initState() {
    super.initState();
    _startSync();
  }

  @override
  void dispose() {
    pollTimer?.cancel();
    super.dispose();
  }

  void _startSync() {
    _syncOnce();
    pollTimer?.cancel();
    pollTimer = Timer.periodic(const Duration(milliseconds: 1200), (_) => _syncOnce());
  }

  Future<void> _syncOnce() async {
    final s = await api.fetchStatus();
    if (mounted) {
      setState(() {
        if (s != null) {
          state = s;
          isConnected = true;
        } else {
          isConnected = false;
        }
      });
    }
  }

  Color _parseHex(String? hex) {
    if (hex == null || hex.isEmpty) return const Color(0xFF00FF00);
    final clean = hex.replaceAll('#', '');
    if (clean.length == 6) {
      return Color(int.parse('FF$clean', radix: 16));
    }
    return const Color(0xFF00FF00);
  }

  void _showHostDialog() {
    final controller = TextEditingController(text: hostUrl);
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0F141F),
        title: const Text('Endereço IP do PC Agente', style: TextStyle(color: Colors.white)),
        content: TextField(
          controller: controller,
          style: const TextStyle(color: Colors.white, fontFamily: 'monospace'),
          decoration: const InputDecoration(
            hintText: 'http://192.168.0.109:8088',
            hintStyle: TextStyle(color: Colors.grey),
            border: OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancelar'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF00FF00)),
            onPressed: () {
              setState(() {
                hostUrl = controller.text.trim();
                api.updateHost(hostUrl);
              });
              Navigator.pop(ctx);
              _syncOnce();
            },
            child: const Text('Salvar', style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final accentColor = _parseHex(state?.hexColor);

    return Scaffold(
      appBar: AppBar(
        backgroundColor: const Color(0xFF07090E),
        elevation: 0,
        title: Row(
          children: [
            const Text('⚡ ', style: TextStyle(fontSize: 20)),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'CYD CONTROLLER',
                  style: TextStyle(
                    color: accentColor,
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 0.5,
                  ),
                ),
                const Text(
                  'ESP32-2432S028R • Wi-Fi Remote',
                  style: TextStyle(color: Color(0xFF8B95A8), fontSize: 10),
                ),
              ],
            ),
          ],
        ),
        actions: [
          GestureDetector(
            onTap: _showHostDialog,
            child: Container(
              margin: const EdgeInsets.only(right: 14),
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: const Color(0xFF111622),
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: const Color(0xFF1E2738)),
              ),
              child: Row(
                children: [
                  Container(
                    width: 8,
                    height: 8,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: isConnected ? const Color(0xFF22C55E) : const Color(0xFFEF4444),
                    ),
                  ),
                  const SizedBox(width: 6),
                  Text(
                    isConnected ? 'CONECTADO' : 'OFFLINE',
                    style: const TextStyle(fontSize: 10, fontWeight: FontWeight.bold, fontFamily: 'monospace'),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
      body: IndexedStack(
        index: currentTab,
        children: [
          _buildScreensTab(accentColor),
          _buildColorsTab(accentColor),
          _buildMetricsTab(accentColor),
          _buildSdTab(accentColor),
        ],
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: currentTab,
        backgroundColor: const Color(0xFF0A0E16),
        selectedItemColor: accentColor,
        unselectedItemColor: const Color(0xFF64748B),
        type: BottomNavigationBarType.fixed,
        onTap: (idx) {
          HapticFeedback.lightImpact();
          setState(() => currentTab = idx);
        },
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.tv), label: 'Telas'),
          BottomNavigationBarItem(icon: Icon(Icons.palette), label: 'Cores'),
          BottomNavigationBarItem(icon: Icon(Icons.bar_chart), label: 'Métricas'),
          BottomNavigationBarItem(icon: Icon(Icons.sd_card), label: 'SD & Brilho'),
        ],
      ),
    );
  }

  // --- TAB 1: TELAS (SCREENS) ---
  Widget _buildScreensTab(Color accent) {
    final curScreen = state?.screen ?? 0;
    final screenItems = [
      (0, '⚡', 'Tela 0: Resumo Gauges', 'Gauges circulares de CPU & RAM + Disco/Rede + Letreiro'),
      (1, '🖥️', 'Tela 1: CPU + RAM Principal', 'Barras duplas + Gráficos de histórico lado a lado'),
      (2, '📈', 'Tela 2: Gráfico Duplo', 'Curvas de Uso de CPU % e RAM % sobrepostas'),
      (3, '🎮', 'Tela 3: GPU Focus', 'Gauge grande de GPU + VRAM + Watts/FPS + Letreiro'),
      (4, '📊', 'Tela 4: 4x Gráficos', 'Grid em tempo real: CPU %, RAM %, GPU % e TEMP °C'),
      (5, '🖼️', 'Tela 5: Wallpaper HUD', 'Destaque total para imagem do Cartão SD + Dock'),
      (6, '💰', 'Tela 6: Mercado Financeiro', 'Dólar, Euro, B3, Top 5 Criptos + Gráfico Bitcoin 24h'),
    ];

    return ListView(
      padding: const EdgeInsets.all(14),
      children: [
        const Text(
          'SELECIONE A TELA DA CYD (0 A 6)',
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Color(0xFF8B95A8), letterSpacing: 0.8),
        ),
        const SizedBox(height: 10),
        ...screenItems.map((item) {
          final idx = item.$1;
          final icon = item.$2;
          final title = item.$3;
          final desc = item.$4;
          final active = idx == curScreen;

          return Container(
            margin: const EdgeInsets.only(bottom: 10),
            decoration: BoxDecoration(
              color: active ? const Color(0xFF162032) : const Color(0xFF0F141F),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: active ? accent : const Color(0xFF1E2738), width: active ? 2 : 1),
            ),
            child: ListTile(
              contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
              leading: Text(icon, style: const TextStyle(fontSize: 26)),
              title: Text(
                title,
                style: TextStyle(
                  color: active ? accent : Colors.white,
                  fontWeight: FontWeight.bold,
                  fontSize: 14,
                ),
              ),
              subtitle: Text(
                desc,
                style: const TextStyle(color: Color(0xFF8B95A8), fontSize: 11),
              ),
              trailing: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: active ? accent : const Color(0xFF1A2234),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  active ? 'ATIVO' : 'ATIVAR',
                  style: TextStyle(
                    color: active ? Colors.black : const Color(0xFF8B95A8),
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              onTap: () {
                HapticFeedback.mediumImpact();
                api.setScreen(idx);
                setState(() {
                  state = state != null
                      ? CydAppState(
                          screen: idx,
                          hexColor: state!.hexColor,
                          colorRgb565: state!.colorRgb565,
                          bg: state!.bg,
                          brt: state!.brt,
                          ticker: state!.ticker,
                          sdFiles: state!.sdFiles,
                          sys: state!.sys,
                          mkt: state!.mkt,
                        )
                      : null;
                });
              },
            ),
          );
        }),
      ],
    );
  }

  // --- TAB 2: CORES RGB565 ---
  Widget _buildColorsTab(Color accent) {
    final presets = [
      ('#00FF00', 'Matrix', const Color(0xFF00FF00)),
      ('#00F0FF', 'Neon', const Color(0xFF00F0FF)),
      ('#FF5500', 'Chama', const Color(0xFFFF5500)),
      ('#FF007F', 'Cyber', const Color(0xFFFF007F)),
      ('#9D00FF', 'Synth', const Color(0xFF9D00FF)),
      ('#0088FF', 'Elétrico', const Color(0xFF0088FF)),
      ('#FFD700', 'Ouro', const Color(0xFFFFD700)),
      ('#FFFFFF', 'Neve', const Color(0xFFFFFFFF)),
    ];

    final r = accent.red;
    final g = accent.green;
    final b = accent.blue;

    return ListView(
      padding: const EdgeInsets.all(14),
      children: [
        const Text(
          'ESTÚDIO DE CORES EM TEMPO REAL',
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Color(0xFF8B95A8), letterSpacing: 0.8),
        ),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: const Color(0xFF0F141F),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: const Color(0xFF1E2738)),
          ),
          child: Row(
            children: [
              Container(
                width: 50,
                height: 50,
                decoration: BoxDecoration(
                  color: accent,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.white24),
                ),
              ),
              const SizedBox(width: 14),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    state?.hexColor.toUpperCase() ?? '#00FF00',
                    style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, fontFamily: 'monospace'),
                  ),
                  Text(
                    'RGB565: ${state?.colorRgb565 ?? '0x07E0'}',
                    style: const TextStyle(color: Color(0xFF8B95A8), fontSize: 12, fontFamily: 'monospace'),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        const Text(
          'PALETAS PRONTAS (1-TOQUE)',
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Color(0xFF8B95A8), letterSpacing: 0.8),
        ),
        const SizedBox(height: 10),
        GridView.count(
          crossAxisCount: 4,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 8,
          crossAxisSpacing: 8,
          children: presets.map((p) {
            return GestureDetector(
              onTap: () {
                HapticFeedback.lightImpact();
                api.setColor(p.$1);
              },
              child: Container(
                decoration: BoxDecoration(
                  color: const Color(0xFF0F141F),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: const Color(0xFF1E2738)),
                ),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Container(
                      width: 22,
                      height: 22,
                      decoration: BoxDecoration(
                        color: p.$3,
                        shape: BoxShape.circle,
                        border: Border.all(color: Colors.white24),
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(p.$2, style: const TextStyle(fontSize: 10, color: Color(0xFF8B95A8))),
                  ],
                ),
              ),
            );
          }).toList(),
        ),
        const SizedBox(height: 16),
        const Text(
          'AJUSTE FINO (R / G / B)',
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Color(0xFF8B95A8), letterSpacing: 0.8),
        ),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: const Color(0xFF0F141F),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: const Color(0xFF1E2738)),
          ),
          child: Column(
            children: [
              _buildRgbSlider('R', r, const Color(0xFFEF4444), (val) {
                final hex = '#${val.toRadixString(16).padLeft(2, '0')}${g.toRadixString(16).padLeft(2, '0')}${b.toRadixString(16).padLeft(2, '0')}';
                api.setColor(hex);
              }),
              _buildRgbSlider('G', g, const Color(0xFF22C55E), (val) {
                final hex = '#${r.toRadixString(16).padLeft(2, '0')}${val.toRadixString(16).padLeft(2, '0')}${b.toRadixString(16).padLeft(2, '0')}';
                api.setColor(hex);
              }),
              _buildRgbSlider('B', b, const Color(0xFF3B82F6), (val) {
                final hex = '#${r.toRadixString(16).padLeft(2, '0')}${g.toRadixString(16).padLeft(2, '0')}${val.toRadixString(16).padLeft(2, '0')}';
                api.setColor(hex);
              }),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildRgbSlider(String label, int value, Color color, ValueChanged<int> onChanged) {
    return Row(
      children: [
        Text(label, style: TextStyle(color: color, fontWeight: FontWeight.bold, fontFamily: 'monospace')),
        Expanded(
          child: Slider(
            value: value.toDouble(),
            min: 0,
            max: 255,
            activeColor: color,
            onChanged: (v) => onChanged(v.toInt()),
          ),
        ),
        SizedBox(
          width: 32,
          child: Text(
            value.toString(),
            textAlign: TextAlign.right,
            style: const TextStyle(fontSize: 11, color: Color(0xFF8B95A8), fontFamily: 'monospace'),
          ),
        ),
      ],
    );
  }

  // --- TAB 3: MÉTRICAS & MERCADO ---
  Widget _buildMetricsTab(Color accent) {
    final sys = state?.sys ?? SysTelemetry();
    final mkt = state?.mkt ?? MarketData();

    return ListView(
      padding: const EdgeInsets.all(14),
      children: [
        const Text(
          'TELEMETRIA DO COMPUTADOR AO VIVO',
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Color(0xFF8B95A8), letterSpacing: 0.8),
        ),
        const SizedBox(height: 10),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 8,
          crossAxisSpacing: 8,
          childAspectRatio: 1.6,
          children: [
            _buildMetricTile('CPU', '${sys.cpu.toStringAsFixed(1)}%', sys.cpuTemp != null ? '${sys.cpuTemp!.toStringAsFixed(0)} °C' : '${sys.cpuFreq} MHz', sys.cpu / 100.0, accent),
            _buildMetricTile('RAM', '${sys.ram.toStringAsFixed(1)}%', '${sys.ramUsed.toStringAsFixed(1)} / ${sys.ramTotal.toStringAsFixed(0)} GB', sys.ram / 100.0, accent),
            _buildMetricTile('GPU', '${sys.gpu.toStringAsFixed(1)}%', sys.gpuTemp != null ? '${sys.gpuTemp!.toStringAsFixed(0)} °C' : sys.gpuName, sys.gpu / 100.0, accent),
            _buildMetricTile('DISCO & REDE', '${sys.disk.toStringAsFixed(0)}%', '↓${sys.rxMb.toStringAsFixed(1)} ↑${sys.txMb.toStringAsFixed(1)} MB/s', sys.disk / 100.0, accent),
          ],
        ),
        const SizedBox(height: 16),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              'MERCADO FINANCEIRO & CRIPTO',
              style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Color(0xFF8B95A8), letterSpacing: 0.8),
            ),
            Text(
              mkt.lastStr,
              style: const TextStyle(fontSize: 10, color: Color(0xFF64748B), fontFamily: 'monospace'),
            ),
          ],
        ),
        const SizedBox(height: 10),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 8,
          crossAxisSpacing: 8,
          childAspectRatio: 2.1,
          children: [
            _buildMarketTile('USD / BRL', 'R\$ ${mkt.usd.toStringAsFixed(2)}', mkt.usdChg),
            _buildMarketTile('EUR / BRL', 'R\$ ${mkt.eur.toStringAsFixed(2)}', mkt.eurChg),
            _buildMarketTile('IBOVESPA', '${(mkt.ibov / 1000).toStringAsFixed(1)}k pts', mkt.ibovChg),
            _buildMarketTile('BITCOIN (BTC)', '\$ ${mkt.btc.toStringAsFixed(0)}', mkt.btcChg),
            _buildMarketTile('ETHEREUM (ETH)', '\$ ${mkt.eth.toStringAsFixed(0)}', mkt.ethChg),
            _buildMarketTile('SOLANA (SOL)', '\$ ${mkt.sol.toStringAsFixed(2)}', mkt.solChg),
          ],
        ),
        const SizedBox(height: 12),
        ElevatedButton(
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFF1A2234),
            padding: const EdgeInsets.symmetric(vertical: 12),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          ),
          onPressed: () {
            HapticFeedback.lightImpact();
            api.toggleTicker();
          },
          child: Text(
            'Ticker da Bolsa na CYD: ${state?.ticker == true ? "LIGADO" : "DESLIGADO"}',
            style: const TextStyle(color: Colors.white, fontSize: 12),
          ),
        ),
      ],
    );
  }

  Widget _buildMetricTile(String title, String val, String sub, double pct, Color accent) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFF0F141F),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF1E2738)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(title, style: const TextStyle(color: Color(0xFF64748B), fontSize: 10, fontWeight: FontWeight.bold)),
          Text(val, style: TextStyle(color: accent, fontSize: 18, fontWeight: FontWeight.bold, fontFamily: 'monospace')),
          Text(sub, style: const TextStyle(color: Color(0xFF8B95A8), fontSize: 10)),
          ClipRRect(
            borderRadius: BorderRadius.circular(2),
            child: LinearProgressIndicator(
              value: pct.clamp(0.0, 1.0),
              backgroundColor: const Color(0xFF1A2234),
              color: accent,
              minHeight: 3,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMarketTile(String sym, String price, double chg) {
    final isPos = chg >= 0;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: const Color(0xFF0F141F),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFF1E2738)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(sym, style: const TextStyle(color: Color(0xFF64748B), fontSize: 10, fontWeight: FontWeight.bold)),
          const SizedBox(height: 2),
          Text(price, style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.bold, fontFamily: 'monospace')),
          Text(
            '${isPos ? "+" : ""}${chg.toStringAsFixed(2)}%',
            style: TextStyle(
              color: isPos ? const Color(0xFF22C55E) : const Color(0xFFEF4444),
              fontSize: 10,
              fontFamily: 'monospace',
              fontWeight: FontWeight.bold,
            ),
          ),
        ],
      ),
    );
  }

  // --- TAB 4: SD CARD & BRILHO ---
  Widget _buildSdTab(Color accent) {
    final curBg = state?.bg ?? 'none';
    final sdList = state?.sdFiles ?? ['none', 'terminal', 'z1p0'];
    final brt = state?.brt ?? 200;
    final brtPct = (brt / 255.0 * 100).round();

    return ListView(
      padding: const EdgeInsets.all(14),
      children: [
        const Text(
          'FUNDO DE TELA (CARTÃO MICROSD)',
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Color(0xFF8B95A8), letterSpacing: 0.8),
        ),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: const Color(0xFF0F141F),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: const Color(0xFF1E2738)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              DropdownButtonFormField<String>(
                value: sdList.contains(curBg) ? curBg : sdList.first,
                dropdownColor: const Color(0xFF0F141F),
                style: const TextStyle(color: Colors.white, fontFamily: 'monospace'),
                decoration: const InputDecoration(
                  border: OutlineInputBorder(),
                  contentPadding: EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                ),
                items: sdList.map((f) => DropdownMenuItem(value: f, child: Text(f))).toList(),
                onChanged: (v) {
                  if (v != null) api.setBackground(v);
                },
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: ElevatedButton(
                      style: ElevatedButton.styleFrom(backgroundColor: accent),
                      onPressed: () {
                        HapticFeedback.lightImpact();
                        api.setBackground(curBg);
                      },
                      child: const Text('Aplicar Fundo', style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
                    ),
                  ),
                  const SizedBox(width: 8),
                  OutlinedButton(
                    onPressed: () {
                      HapticFeedback.lightImpact();
                      api.refreshSd();
                    },
                    child: const Text('Ler SD', style: TextStyle(color: Colors.white)),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        const Text(
          'BRILHO DO DISPLAY (PWM - PINO 21)',
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Color(0xFF8B95A8), letterSpacing: 0.8),
        ),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: const Color(0xFF0F141F),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: const Color(0xFF1E2738)),
          ),
          child: Column(
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text('Ajuste Backlight:', style: TextStyle(color: Color(0xFF8B95A8), fontSize: 12)),
                  Text('$brtPct% ($brt/255)', style: TextStyle(color: accent, fontWeight: FontWeight.bold, fontFamily: 'monospace')),
                ],
              ),
              Slider(
                value: brt.toDouble(),
                min: 10,
                max: 255,
                activeColor: accent,
                onChanged: (v) => api.setBrightness(v.toInt()),
              ),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceAround,
                children: [
                  _buildBrtPreset('25%', 64),
                  _buildBrtPreset('50%', 128),
                  _buildBrtPreset('80%', 204),
                  _buildBrtPreset('100%', 255),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildBrtPreset(String label, int val) {
    return OutlinedButton(
      style: OutlinedButton.styleFrom(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      ),
      onPressed: () => api.setBrightness(val),
      child: Text(label, style: const TextStyle(color: Colors.white, fontSize: 11)),
    );
  }
}
