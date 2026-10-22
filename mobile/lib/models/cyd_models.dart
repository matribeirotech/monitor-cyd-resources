// lib/models/cyd_models.dart
class SysTelemetry {
  final double cpu;
  final double? cpuTemp;
  final int cpuFreq;
  final double ram;
  final double ramUsed;
  final double ramTotal;
  final double gpu;
  final double? gpuTemp;
  final String gpuName;
  final double disk;
  final double rxMb;
  final double txMb;

  SysTelemetry({
    this.cpu = 0.0,
    this.cpuTemp,
    this.cpuFreq = 0,
    this.ram = 0.0,
    this.ramUsed = 0.0,
    this.ramTotal = 0.0,
    this.gpu = 0.0,
    this.gpuTemp,
    this.gpuName = 'GPU',
    this.disk = 0.0,
    this.rxMb = 0.0,
    this.txMb = 0.0,
  });

  factory SysTelemetry.fromJson(Map<String, dynamic>? json) {
    if (json == null) return SysTelemetry();
    return SysTelemetry(
      cpu: (json['cpu'] as num?)?.toDouble() ?? 0.0,
      cpuTemp: (json['cput'] as num?)?.toDouble(),
      cpuFreq: (json['cpuf'] as num?)?.toInt() ?? 0,
      ram: (json['ram'] as num?)?.toDouble() ?? 0.0,
      ramUsed: (json['ramu'] as num?)?.toDouble() ?? 0.0,
      ramTotal: (json['ramt'] as num?)?.toDouble() ?? 0.0,
      gpu: (json['gpu'] as num?)?.toDouble() ?? 0.0,
      gpuTemp: (json['gput'] as num?)?.toDouble(),
      gpuName: json['gpuname']?.toString() ?? 'GPU',
      disk: (json['dsk'] as num?)?.toDouble() ?? 0.0,
      rxMb: (json['rx'] as num?)?.toDouble() ?? 0.0,
      txMb: (json['tx'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class MarketData {
  final double usd;
  final double usdChg;
  final double eur;
  final double eurChg;
  final double ibov;
  final double ibovChg;
  final double btc;
  final double btcChg;
  final double eth;
  final double ethChg;
  final double sol;
  final double solChg;
  final String lastStr;

  MarketData({
    this.usd = 0.0,
    this.usdChg = 0.0,
    this.eur = 0.0,
    this.eurChg = 0.0,
    this.ibov = 0.0,
    this.ibovChg = 0.0,
    this.btc = 0.0,
    this.btcChg = 0.0,
    this.eth = 0.0,
    this.ethChg = 0.0,
    this.sol = 0.0,
    this.solChg = 0.0,
    this.lastStr = '--:--:--',
  });

  factory MarketData.fromJson(Map<String, dynamic>? json) {
    if (json == null) return MarketData();
    return MarketData(
      usd: (json['usd'] as num?)?.toDouble() ?? 0.0,
      usdChg: (json['usdc'] as num?)?.toDouble() ?? 0.0,
      eur: (json['eur'] as num?)?.toDouble() ?? 0.0,
      eurChg: (json['eurc'] as num?)?.toDouble() ?? 0.0,
      ibov: (json['ibov'] as num?)?.toDouble() ?? 0.0,
      ibovChg: (json['ibovc'] as num?)?.toDouble() ?? 0.0,
      btc: (json['btc'] as num?)?.toDouble() ?? 0.0,
      btcChg: (json['btcc'] as num?)?.toDouble() ?? 0.0,
      eth: (json['eth'] as num?)?.toDouble() ?? 0.0,
      ethChg: (json['ethc'] as num?)?.toDouble() ?? 0.0,
      sol: (json['sol'] as num?)?.toDouble() ?? 0.0,
      solChg: (json['solc'] as num?)?.toDouble() ?? 0.0,
      lastStr: json['last_str']?.toString() ?? '--:--:--',
    );
  }
}

class CydAppState {
  final int screen;
  final String hexColor;
  final String colorRgb565;
  final String bg;
  final int brt;
  final bool ticker;
  final List<String> sdFiles;
  final SysTelemetry sys;
  final MarketData mkt;
  final bool isConnected;

  CydAppState({
    this.screen = 1,
    this.hexColor = '#00FF00',
    this.colorRgb565 = '0x07E0',
    this.bg = 'none',
    this.brt = 200,
    this.ticker = true,
    this.sdFiles = const ['none', 'terminal', 'z1p0'],
    required this.sys,
    required this.mkt,
    this.isConnected = true,
  });

  factory CydAppState.fromJson(Map<String, dynamic> json) {
    return CydAppState(
      screen: (json['screen'] as num?)?.toInt() ?? 1,
      hexColor: json['hex_color']?.toString() ?? '#00FF00',
      colorRgb565: json['color']?.toString() ?? '0x07E0',
      bg: json['bg']?.toString() ?? 'none',
      brt: (json['brt'] as num?)?.toInt() ?? 200,
      ticker: json['ticker'] as bool? ?? true,
      sdFiles: (json['sd_files'] as List<dynamic>?)
              ?.map((e) => e.toString())
              .toList() ??
          const ['none', 'terminal', 'z1p0'],
      sys: SysTelemetry.fromJson(json['sys'] as Map<String, dynamic>?),
      mkt: MarketData.fromJson(json['mkt'] as Map<String, dynamic>?),
      isConnected: json['connected'] as bool? ?? true,
    );
  }
}
