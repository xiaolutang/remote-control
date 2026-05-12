import 'project_context_snapshot.dart';
import 'recent_launch_context.dart';
import 'shortcut_item.dart';
import 'terminal_shortcut.dart';
import '../utils/json_helpers.dart';

/// 统一超时/间隔常量，消除各服务文件中重复的 Duration 定义。
abstract final class TimingConstants {
  /// HTTP 连接超时
  static const Duration httpConnectionTimeout = Duration(seconds: 10);

  /// WebSocket 连接超时
  static const Duration wsConnectionTimeout = Duration(seconds: 30);

  /// 心跳间隔（默认值，实际由 AppConfig.heartbeatInterval 控制）
  static const Duration heartbeatInterval = Duration(seconds: 30);

  /// 重连延迟（默认值）
  static const Duration reconnectDelay = Duration(seconds: 1);

  // --- Desktop Agent ---

  /// Agent 启动超时（等待 Agent 进程上线）
  static const Duration agentStartTimeout = Duration(seconds: 12);

  /// Agent 停止超时（等待 Agent 进程退出）
  static const Duration agentStopTimeout = Duration(seconds: 8);

  /// Agent 进程终止宽限期（SIGTERM → SIGKILL）
  static const Duration agentGracePeriod = Duration(seconds: 2);

  /// Agent 上线轮询间隔
  static const Duration agentOnlinePollInterval = Duration(milliseconds: 600);

  /// Agent 停止轮询间隔
  static const Duration agentStopPollInterval = Duration(milliseconds: 400);

  /// Agent HTTP 停止后健康检查轮询间隔
  static const Duration agentHttpStopPollInterval = Duration(milliseconds: 300);

  /// Agent 进程终止轮询间隔
  static const Duration agentTerminatePollInterval = Duration(milliseconds: 150);
}

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
    final explicitExitPolicy = json['desktopExitPolicy'];
    final legacyKeepRunning =
        readBoolFromJson(json['keepAgentRunningInBackground']);
    final legacyExplicitChoice =
        readBoolFromJson(json['desktopBackgroundModeUserSet']);
    return AppConfig(
      serverUrl: serverUrl,
      token: json['token'] is String ? json['token'] as String : null,
      sessionId: readStringFromJson(json['sessionId']),
      autoReconnect: readBoolFromJson(json['autoReconnect'], defaultValue: true),
      maxRetries: readIntFromJson(json['maxRetries']) == 0
          ? 5
          : readIntFromJson(json['maxRetries']),
      reconnectDelay: Duration(
          milliseconds: readIntFromJson(json['reconnectDelayMs']) == 0
              ? 1000
              : readIntFromJson(json['reconnectDelayMs'])),
      heartbeatInterval: Duration(
          milliseconds: readIntFromJson(json['heartbeatIntervalMs']) == 0
              ? 30000
              : readIntFromJson(json['heartbeatIntervalMs'])),
      themeMode: enumFromJson(
        AppThemeMode.values,
        json['themeMode'],
        AppThemeMode.system,
      ),
      claudeNavigationMode: enumFromJson(
        ClaudeNavigationMode.values,
        json['claudeNavigationMode'],
        ClaudeNavigationMode.standard,
      ),
      desktopExitPolicy: explicitExitPolicy != null
          ? enumFromJson(
              DesktopExitPolicy.values,
              explicitExitPolicy,
              DesktopExitPolicy.stopAgentOnExit,
            )
          : _legacyDesktopExitPolicy(
              keepRunningInBackground: legacyKeepRunning,
              hadExplicitChoice: legacyExplicitChoice,
            ),
      desktopAgentWorkdir: readStringFromJson(json['desktopAgentWorkdir']),
      preferredDeviceId: readStringFromJson(json['preferredDeviceId']),
      shortcutItems: readListFromJson(
          json['shortcutItems'], ShortcutItem.fromJson),
      projectShortcutItems:
          (json['projectShortcutItems'] is Map<String, dynamic>
                  ? json['projectShortcutItems'] as Map<String, dynamic>
                  : const <String, dynamic>{})
              .map(
        (key, value) => MapEntry(
          key,
          readListFromJson(value, ShortcutItem.fromJson),
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
