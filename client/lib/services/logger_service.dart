import 'dart:async';
import 'dart:convert';
import 'dart:collection';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// 日志级别
enum LogLevel {
  debug,
  info,
  warn,
  error,
  fatal,
}

/// 日志记录
class LogRecord {
  final LogLevel level;
  final String message;
  final DateTime timestamp;
  final Map<String, dynamic>? metadata;

  LogRecord({
    required this.level,
    required this.message,
    DateTime? timestamp,
    this.metadata,
  }) : timestamp = timestamp ?? DateTime.now().toUtc();

  Map<String, dynamic> toJson() => {
        'level': level.name,
        'message': message,
        'timestamp': timestamp.toIso8601String(),
        'metadata': metadata ?? {},
      };
}

/// 日志上报服务
///
/// 功能：
/// - 收集客户端日志
/// - 批量上报（10 条或 5 秒触发）
/// - 网络失败时本地缓存
/// - 重试机制
class LoggerService extends ChangeNotifier {
  final String serverUrl;
  final String sessionId;
  final String token;

  // 配置
  static const int _batchSize = 10;
  static const Duration _flushInterval = Duration(seconds: 5);
  static const int _maxCacheSize = 1000;

  // 状态
  final Queue<LogRecord> _queue = Queue();
  final Queue<LogRecord> _cache = Queue();
  Timer? _flushTimer;
  bool _isUploading = false;
  String _uid = ''; // 缓存 uid，start() 时读取一次

  LoggerService({
    required this.serverUrl,
    required this.sessionId,
    required this.token,
  });

  int get pendingCount => _queue.length + _cache.length;
  bool get isUploading => _isUploading;

  /// 启动服务
  void start() {
    _startFlushTimer();
    _loadCache();
    _loadUid();
    debugPrint('[Logger] Service started for session: $sessionId');
  }

  /// 停止服务
  Future<void> stop() async {
    _flushTimer?.cancel();
    _flushTimer = null;
    await flush();
    debugPrint('[Logger] Service stopped');
  }

  /// 记录 debug 日志
  void debug(String message, {Map<String, dynamic>? metadata}) {
    _log(LogLevel.debug, message, metadata);
  }

  /// 记录 info 日志
  void info(String message, {Map<String, dynamic>? metadata}) {
    _log(LogLevel.info, message, metadata);
  }

  /// 记录 warn 日志
  void warn(String message, {Map<String, dynamic>? metadata}) {
    _log(LogLevel.warn, message, metadata);
  }

  /// 记录 error 日志
  void error(String message, {Map<String, dynamic>? metadata}) {
    _log(LogLevel.error, message, metadata);
  }

  /// 记录 fatal 日志
  void fatal(String message, {Map<String, dynamic>? metadata}) {
    _log(LogLevel.fatal, message, metadata);
  }

  /// 记录日志
  void _log(LogLevel level, String message, Map<String, dynamic>? metadata) {
    final record = LogRecord(
      level: level,
      message: message,
      metadata: metadata,
    );

    _queue.add(record);
    notifyListeners();

    // 达到批量大小立即刷新
    if (_queue.length >= _batchSize) {
      flush();
    }

    // 控制台输出（调试用）
    if (kDebugMode) {
      final levelStr = level.name.toUpperCase().padRight(5);
      debugPrint('[$levelStr] $message');
    }
  }

  /// 启动定时刷新
  void _startFlushTimer() {
    _flushTimer?.cancel();
    _flushTimer = Timer.periodic(_flushInterval, (_) {
      if (_queue.isNotEmpty) {
        flush();
      }
    });
  }

  /// 刷新队列（立即上报）
  Future<void> flush() async {
    if (_queue.isEmpty && _cache.isEmpty) return;
    if (_isUploading) return;

    _isUploading = true;
    notifyListeners();

    try {
      // 合并队列和缓存的日志
      final logs = <LogRecord>[..._cache, ..._queue];
      _cache.clear();
      _queue.clear();

      if (logs.isEmpty) {
        _isUploading = false;
        notifyListeners();
        return;
      }

      // 上报
      final success = await _uploadLogs(logs);

      if (success) {
        await _clearCache();
        debugPrint('[Logger] Uploaded ${logs.length} logs');
      } else {
        // 上传失败，存入缓存
        _addToCache(logs);
        debugPrint('[Logger] Upload failed, cached ${logs.length} logs');
      }
    } finally {
      _isUploading = false;
      notifyListeners();
    }
  }

  /// 上报日志到服务器
  Future<bool> _uploadLogs(List<LogRecord> logs) async {
    try {
      final httpUrl = _getHttpUrl();

      final response = await http.post(
        Uri.parse('$httpUrl/api/logs'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode({
          'session_id': sessionId,
          'uid': _uid,
          'logs': logs.map((l) => l.toJson()).toList(),
        }),
      );

      return response.statusCode == 200;
    } catch (e) {
      debugPrint('[Logger] Upload error: $e');
      return false;
    }
  }

  /// 转换 WebSocket URL 为 HTTP URL
  String _getHttpUrl() {
    if (serverUrl.startsWith('ws://')) {
      return serverUrl.replaceFirst('ws://', 'http://');
    } else if (serverUrl.startsWith('wss://')) {
      return serverUrl.replaceFirst('wss://', 'https://');
    }
    return serverUrl;
  }

  /// 添加到缓存（失败重试用）
  void _addToCache(List<LogRecord> logs) {
    for (final log in logs) {
      _cache.add(log);
    }

    // 限制缓存大小
    while (_cache.length > _maxCacheSize) {
      _cache.removeFirst();
    }

    _saveCache();
  }

  /// 保存缓存到本地
  Future<void> _saveCache() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final cacheData = _cache.map((l) => jsonEncode(l.toJson())).toList();
      await prefs.setStringList('rc_log_cache_$sessionId', cacheData);
    } catch (e) {
      debugPrint('[Logger] Save cache error: $e');
    }
  }

  /// 从 SharedPreferences 读取 uid（username），缓存到内存
  Future<void> _loadUid() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      _uid = prefs.getString('rc_username') ?? '';
    } catch (_) {}
  }

  /// 从本地加载缓存
  Future<void> _loadCache() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final cacheData = prefs.getStringList('rc_log_cache_$sessionId');

      if (cacheData != null) {
        for (final jsonStr in cacheData) {
          try {
            final data = jsonDecode(jsonStr) as Map<String, dynamic>;
            _cache.add(LogRecord(
              level: LogLevel.values.firstWhere(
                (l) => l.name == data['level'],
                orElse: () => LogLevel.info,
              ),
              message: data['message'] ?? '',
              timestamp: DateTime.parse(data['timestamp']),
              metadata: data['metadata'],
            ));
          } catch (_) {}
        }

        if (_cache.isNotEmpty) {
          debugPrint('[Logger] Loaded ${_cache.length} cached logs');
        }
      }
    } catch (e) {
      debugPrint('[Logger] Load cache error: $e');
    }
  }

  /// 清除本地缓存
  Future<void> _clearCache() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove('rc_log_cache_$sessionId');
    } catch (e) {
      debugPrint('[Logger] Clear cache error: $e');
    }
  }

  /// 释放资源
  @override
  void dispose() {
    stop();
    super.dispose();
  }
}
