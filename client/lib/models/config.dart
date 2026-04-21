import 'shortcut_item.dart';
import 'terminal_shortcut.dart';

enum AppThemeMode {
  system,
  light,
  dark,
}

enum DesktopExitPolicy {
  stopAgentOnExit,
  keepAgentRunningInBackground,
}

/// 配置模型
class AppConfig {
  /// serverUrl 由 EnvironmentService 动态提供，不参与持久化
  final String serverUrl;
  final String? token;
  final String sessionId;
  final bool autoReconnect;
  final int maxRetries;
  final Duration reconnectDelay;
  final Duration heartbeatInterval;
  final AppThemeMode themeMode;
  final ClaudeNavigationMode claudeNavigationMode;
  final DesktopExitPolicy desktopExitPolicy;
  final String desktopAgentWorkdir;
  final String preferredDeviceId;
  final List<ShortcutItem> shortcutItems;
  final Map<String, List<ShortcutItem>> projectShortcutItems;

  bool get keepAgentRunningInBackground =>
      desktopExitPolicy == DesktopExitPolicy.keepAgentRunningInBackground;

  const AppConfig({
    this.serverUrl = '',
    this.token,
    this.sessionId = '',
    this.autoReconnect = true,
    this.maxRetries = 5,
    this.reconnectDelay = const Duration(seconds: 1),
    this.heartbeatInterval = const Duration(seconds: 30),
    this.themeMode = AppThemeMode.system,
    this.claudeNavigationMode = ClaudeNavigationMode.standard,
    DesktopExitPolicy? desktopExitPolicy,
    bool? keepAgentRunningInBackground,
    this.desktopAgentWorkdir = '',
    this.preferredDeviceId = '',
    this.shortcutItems = const [],
    this.projectShortcutItems = const {},
  }) : desktopExitPolicy = desktopExitPolicy ??
            (keepAgentRunningInBackground == true
                ? DesktopExitPolicy.keepAgentRunningInBackground
                : DesktopExitPolicy.stopAgentOnExit);

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
    DesktopExitPolicy? desktopExitPolicy,
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
      claudeNavigationMode: claudeNavigationMode ?? this.claudeNavigationMode,
      desktopExitPolicy: desktopExitPolicy ?? this.desktopExitPolicy,
      desktopAgentWorkdir: desktopAgentWorkdir ?? this.desktopAgentWorkdir,
      preferredDeviceId: preferredDeviceId ?? this.preferredDeviceId,
      shortcutItems: shortcutItems ?? this.shortcutItems,
      projectShortcutItems: projectShortcutItems ?? this.projectShortcutItems,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'token': token,
      'sessionId': sessionId,
      'autoReconnect': autoReconnect,
      'maxRetries': maxRetries,
      'reconnectDelayMs': reconnectDelay.inMilliseconds,
      'heartbeatIntervalMs': heartbeatInterval.inMilliseconds,
      'themeMode': themeMode.name,
      'claudeNavigationMode': claudeNavigationMode.name,
      'desktopExitPolicy': desktopExitPolicy.name,
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

  factory AppConfig.fromJson(Map<String, dynamic> json,
      {String serverUrl = ''}) {
    final explicitExitPolicy = json['desktopExitPolicy'] as String?;
    final legacyKeepRunning =
        json['keepAgentRunningInBackground'] as bool? ?? false;
    final legacyExplicitChoice =
        json['desktopBackgroundModeUserSet'] as bool? ?? false;
    return AppConfig(
      serverUrl: serverUrl,
      token: json['token'] as String?,
      sessionId: json['sessionId'] as String? ?? '',
      autoReconnect: json['autoReconnect'] as bool? ?? true,
      maxRetries: json['maxRetries'] as int? ?? 5,
      reconnectDelay:
          Duration(milliseconds: json['reconnectDelayMs'] as int? ?? 1000),
      heartbeatInterval:
          Duration(milliseconds: json['heartbeatIntervalMs'] as int? ?? 30000),
      themeMode: AppThemeMode.values.byName(
        json['themeMode'] as String? ?? AppThemeMode.system.name,
      ),
      claudeNavigationMode: ClaudeNavigationMode.values.byName(
        json['claudeNavigationMode'] as String? ??
            ClaudeNavigationMode.standard.name,
      ),
      desktopExitPolicy: explicitExitPolicy != null
          ? DesktopExitPolicy.values.byName(explicitExitPolicy)
          : _legacyDesktopExitPolicy(
              keepRunningInBackground: legacyKeepRunning,
              hadExplicitChoice: legacyExplicitChoice,
            ),
      desktopAgentWorkdir: json['desktopAgentWorkdir'] as String? ?? '',
      preferredDeviceId: json['preferredDeviceId'] as String? ?? '',
      shortcutItems: ((json['shortcutItems'] as List<dynamic>?) ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(ShortcutItem.fromJson)
          .toList(growable: false),
      projectShortcutItems:
          (((json['projectShortcutItems'] as Map<String, dynamic>?) ??
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

  static DesktopExitPolicy _legacyDesktopExitPolicy({
    required bool keepRunningInBackground,
    required bool hadExplicitChoice,
  }) {
    if (keepRunningInBackground && hadExplicitChoice) {
      return DesktopExitPolicy.keepAgentRunningInBackground;
    }
    return DesktopExitPolicy.stopAgentOnExit;
  }
}
