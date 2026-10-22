// lib/services/cyd_api_service.dart
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/cyd_models.dart';

class CydApiService {
  String baseUrl;

  CydApiService({this.baseUrl = 'http://192.168.0.109:8088'});

  void updateHost(String newBaseUrl) {
    baseUrl = newBaseUrl.replaceAll(RegExp(r'/+$'), '');
  }

  Future<CydAppState?> fetchStatus() async {
    try {
      final res = await http
          .get(Uri.parse('$baseUrl/api/status'))
          .timeout(const Duration(seconds: 3));
      if (res.statusCode == 200) {
        final data = json.decode(utf8.decode(res.bodyBytes));
        return CydAppState.fromJson(data);
      }
    } catch (_) {}
    return null;
  }

  Future<bool> setScreen(int screen) async {
    try {
      final res = await http.post(
        Uri.parse('$baseUrl/api/screen'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({'screen': screen}),
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<bool> setColor(String hex) async {
    try {
      final res = await http.post(
        Uri.parse('$baseUrl/api/color'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({'hex': hex}),
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<bool> setBrightness(int brt) async {
    try {
      final res = await http.post(
        Uri.parse('$baseUrl/api/brightness'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({'brt': brt}),
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<bool> setBackground(String bg) async {
    try {
      final res = await http.post(
        Uri.parse('$baseUrl/api/bg'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({'bg': bg}),
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<bool> toggleTicker({bool? ticker}) async {
    try {
      final body = ticker != null ? json.encode({'ticker': ticker}) : '{}';
      final res = await http.post(
        Uri.parse('$baseUrl/api/ticker'),
        headers: {'Content-Type': 'application/json'},
        body: body,
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<bool> refreshSd() async {
    try {
      final res = await http.post(Uri.parse('$baseUrl/api/refresh_sd'));
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<bool> uploadImage(String filename, List<int> bytes) async {
    try {
      final b64 = base64Encode(bytes);
      final res = await http.post(
        Uri.parse('$baseUrl/api/upload'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({'filename': filename, 'data': b64}),
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }
}
