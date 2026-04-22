import 'project_context_snapshot.dart';
import 'recent_launch_context.dart';
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
  final Map<String, RecentLaunchContext> recentLaunchContexts;
  final Map<String, DeviceProjectContextSnapshot> projectContextSnapshots;

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
    this.recentLaunchContexts = const {},
    this.projectContextSnapshots = const {},
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
    Map<String, RecentLaunchContext>? recentLaunchContexts,
    Map<String, DeviceProjectContextSnapshot>? projectContextSnapshots,
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
      recentLaunchContexts: recentLaunchContexts ?? this.recentLaunchContexts,
      projectContextSnapshots:
          projectContextSnapshots ?? this.projectContextSnapshots,
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
      'recentLaunchContexts': recentLaunchContexts.map(
        (key, value) => MapEntry(key, value.toJson()),
      ),
      'projectContextSnapshots': projectContextSnapshots.map(
        (key, value) => MapEntry(key, value.toJson()),
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
      recentLaunchContexts: _parseRecentLaunchContexts(
        json['recentLaunchContexts'],
      ),
      projectContextSnapshots: _parseProjectContextSnapshots(
        json['projectContextSnapshots'],
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

  static Map<String, RecentLaunchContext> _parseRecentLaunchContexts(
    Object? rawValue,
  ) {
    if (rawValue is! Map) {
      return const {};
    }

    final contexts = <String, RecentLaunchContext>{};
    for (final entry in rawValue.entries) {
      final key = entry.key.toString();
      final value = entry.value;
      if (value is! Map) {
        continue;
      }
      final context = RecentLaunchContext.tryFromJson(
        Map<String, dynamic>.from(value),
        fallbackDeviceId: key,
      );
      if (context != null) {
        contexts[key] = context;
      }
    }
    return contexts;
  }

  static Map<String, DeviceProjectContextSnapshot>
      _parseProjectContextSnapshots(
    Object? rawValue,
  ) {
    if (rawValue is! Map) {
      return const {};
    }

    final snapshots = <String, DeviceProjectContextSnapshot>{};
    for (final entry in rawValue.entries) {
      final key = entry.key.toString();
      final value = entry.value;
      if (value is! Map) {
        continue;
      }
      final snapshot = DeviceProjectContextSnapshot.fromJson(
        Map<String, dynamic>.from(value),
      );
      if (snapshot.deviceId.isNotEmpty) {
        snapshots[key] = snapshot;
      }
    }
    return snapshots;
  }
}
