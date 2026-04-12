import 'shortcut_item.dart';
import 'terminal_shortcut.dart';

enum AppThemeMode {
  system,
  light,
  dark,
}

/// 配置模型
class AppConfig {
  static const String defaultServerUrl = 'ws://localhost/rc';
  final String serverUrl;
  final String? token;
  final String sessionId;
  final bool autoReconnect;
  final int maxRetries;
  final Duration reconnectDelay;
  final Duration heartbeatInterval;
  final AppThemeMode themeMode;
  final ClaudeNavigationMode claudeNavigationMode;
  final bool keepAgentRunningInBackground;
  final String desktopAgentWorkdir;
  final String preferredDeviceId;
  final List<ShortcutItem> shortcutItems;
  final Map<String, List<ShortcutItem>> projectShortcutItems;

  const AppConfig({
    this.serverUrl = defaultServerUrl,
    this.token,
    this.sessionId = '',
    this.autoReconnect = true,
    this.maxRetries = 5,
    this.reconnectDelay = const Duration(seconds: 1),
    this.heartbeatInterval = const Duration(seconds: 30),
    this.themeMode = AppThemeMode.system,
    this.claudeNavigationMode = ClaudeNavigationMode.standard,
    this.keepAgentRunningInBackground = true,
    this.desktopAgentWorkdir = '',
    this.preferredDeviceId = '',
    this.shortcutItems = const [],
    this.projectShortcutItems = const {},
  });

  AppConfig copyWith({
    String? serverUrl,
    String? token,
    String? sessionId,
    bool? autoReconnect,
    int? maxRetries,
    Duration? reconnectDelay,
    Duration? heartbeatInterval,
    AppThemeMode? themeMode,
    ClaudeNavigationMode? claudeNavigationMode,
    bool? keepAgentRunningInBackground,
    String? desktopAgentWorkdir,
    String? preferredDeviceId,
    List<ShortcutItem>? shortcutItems,
    Map<String, List<ShortcutItem>>? projectShortcutItems,
  }) {
    return AppConfig(
      serverUrl: serverUrl ?? this.serverUrl,
      token: token ?? this.token,
      sessionId: sessionId ?? this.sessionId,
      autoReconnect: autoReconnect ?? this.autoReconnect,
      maxRetries: maxRetries ?? this.maxRetries,
      reconnectDelay: reconnectDelay ?? this.reconnectDelay,
      heartbeatInterval: heartbeatInterval ?? this.heartbeatInterval,
      themeMode: themeMode ?? this.themeMode,
      claudeNavigationMode:
          claudeNavigationMode ?? this.claudeNavigationMode,
      keepAgentRunningInBackground:
          keepAgentRunningInBackground ?? this.keepAgentRunningInBackground,
      desktopAgentWorkdir: desktopAgentWorkdir ?? this.desktopAgentWorkdir,
      preferredDeviceId: preferredDeviceId ?? this.preferredDeviceId,
      shortcutItems: shortcutItems ?? this.shortcutItems,
      projectShortcutItems: projectShortcutItems ?? this.projectShortcutItems,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'serverUrl': serverUrl,
      'token': token,
      'sessionId': sessionId,
      'autoReconnect': autoReconnect,
      'maxRetries': maxRetries,
      'reconnectDelayMs': reconnectDelay.inMilliseconds,
      'heartbeatIntervalMs': heartbeatInterval.inMilliseconds,
      'themeMode': themeMode.name,
      'claudeNavigationMode': claudeNavigationMode.name,
      'keepAgentRunningInBackground': keepAgentRunningInBackground,
      'desktopAgentWorkdir': desktopAgentWorkdir,
      'preferredDeviceId': preferredDeviceId,
      'shortcutItems': shortcutItems.map((item) => item.toJson()).toList(),
      'projectShortcutItems': projectShortcutItems.map(
        (key, value) => MapEntry(
          key,
          value.map((item) => item.toJson()).toList(),
        ),
      ),
    };
  }

  factory AppConfig.fromJson(Map<String, dynamic> json) {
    return AppConfig(
      serverUrl: json['serverUrl'] as String? ?? defaultServerUrl,
      token: json['token'] as String?,
      sessionId: json['sessionId'] as String? ?? '',
      autoReconnect: json['autoReconnect'] as bool? ?? true,
      maxRetries: json['maxRetries'] as int? ?? 5,
      reconnectDelay: Duration(milliseconds: json['reconnectDelayMs'] as int? ?? 1000),
      heartbeatInterval: Duration(milliseconds: json['heartbeatIntervalMs'] as int? ?? 30000),
      themeMode: AppThemeMode.values.byName(
        json['themeMode'] as String? ?? AppThemeMode.system.name,
      ),
      claudeNavigationMode: ClaudeNavigationMode.values.byName(
        json['claudeNavigationMode'] as String? ??
            ClaudeNavigationMode.standard.name,
      ),
      keepAgentRunningInBackground:
          json['keepAgentRunningInBackground'] as bool? ?? true,
      desktopAgentWorkdir: json['desktopAgentWorkdir'] as String? ?? '',
      preferredDeviceId: json['preferredDeviceId'] as String? ?? '',
      shortcutItems: ((json['shortcutItems'] as List<dynamic>?) ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(ShortcutItem.fromJson)
          .toList(growable: false),
      projectShortcutItems: (((json['projectShortcutItems'] as Map<String, dynamic>?) ??
                  const <String, dynamic>{}))
              .map(
        (key, value) => MapEntry(
          key,
          ((value as List<dynamic>?) ?? const [])
              .whereType<Map<String, dynamic>>()
              .map(ShortcutItem.fromJson)
              .toList(growable: false),
        ),
      ),
    );
  }
}
