enum TerminalLaunchTool {
  claudeCode,
  codex,
  shell,
  custom,
}

enum TerminalEntryStrategy {
  directExec,
  shellBootstrap,
}

enum TerminalLaunchPlanSource {
  recommended,
  intent,
  custom,
}

enum TerminalLaunchConfidence {
  high,
  medium,
  low,
}

class TerminalLaunchPlan {
  const TerminalLaunchPlan({
    required this.tool,
    required this.title,
    required this.cwd,
    required this.command,
    required this.entryStrategy,
    required this.postCreateInput,
    required this.source,
    this.intent,
    this.confidence = TerminalLaunchConfidence.high,
    this.requiresManualConfirmation = false,
  });

  final TerminalLaunchTool tool;
  final String title;
  final String cwd;
  final String command;
  final TerminalEntryStrategy entryStrategy;
  final String postCreateInput;
  final TerminalLaunchPlanSource source;
  final String? intent;
  final TerminalLaunchConfidence confidence;
  final bool requiresManualConfirmation;

  TerminalLaunchPlan copyWith({
    TerminalLaunchTool? tool,
    String? title,
    String? cwd,
    String? command,
    TerminalEntryStrategy? entryStrategy,
    String? postCreateInput,
    TerminalLaunchPlanSource? source,
    String? intent,
    bool clearIntent = false,
    TerminalLaunchConfidence? confidence,
    bool? requiresManualConfirmation,
  }) {
    return TerminalLaunchPlan(
      tool: tool ?? this.tool,
      title: title ?? this.title,
      cwd: cwd ?? this.cwd,
      command: command ?? this.command,
      entryStrategy: entryStrategy ?? this.entryStrategy,
      postCreateInput: postCreateInput ?? this.postCreateInput,
      source: source ?? this.source,
      intent: clearIntent ? null : (intent ?? this.intent),
      confidence: confidence ?? this.confidence,
      requiresManualConfirmation:
          requiresManualConfirmation ?? this.requiresManualConfirmation,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'tool': TerminalLaunchToolCodec.toJson(tool),
      'title': title,
      'cwd': cwd,
      'command': command,
      'entry_strategy': TerminalEntryStrategyCodec.toJson(entryStrategy),
      'post_create_input': postCreateInput,
      'source': TerminalLaunchPlanSourceCodec.toJson(source),
      'intent': intent,
      'confidence': TerminalLaunchConfidenceCodec.toJson(confidence),
      'requires_manual_confirmation': requiresManualConfirmation,
    };
  }

  factory TerminalLaunchPlan.fromJson(Map<String, dynamic> json) {
    final tool = TerminalLaunchToolCodec.fromJson(json['tool'] as String?) ??
        TerminalLaunchTool.shell;
    final cwd = _normalizedString(json['cwd']) ?? '~';
    final defaults = TerminalLaunchPlanDefaults.forTool(tool);
    return TerminalLaunchPlan(
      tool: tool,
      title: _normalizedString(json['title']) ??
          TerminalLaunchPlanDefaults.titleFor(tool, cwd),
      cwd: cwd,
      command: _normalizedString(json['command']) ?? defaults.command,
      entryStrategy: TerminalEntryStrategyCodec.fromJson(
              json['entry_strategy'] as String?) ??
          defaults.entryStrategy,
      postCreateInput:
          (json['post_create_input'] as String?) ?? defaults.postCreateInput,
      source: TerminalLaunchPlanSourceCodec.fromJson(
            json['source'] as String?,
          ) ??
          TerminalLaunchPlanSource.recommended,
      intent: _normalizedString(json['intent']),
      confidence: TerminalLaunchConfidenceCodec.fromJson(
            json['confidence'] as String?,
          ) ??
          TerminalLaunchConfidence.high,
      requiresManualConfirmation:
          json['requires_manual_confirmation'] as bool? ?? false,
    );
  }

  static String? _normalizedString(Object? value) {
    final trimmed = (value as String?)?.trim();
    if (trimmed == null || trimmed.isEmpty) {
      return null;
    }
    return trimmed;
  }
}

class TerminalLaunchPlanDefaults {
  const TerminalLaunchPlanDefaults._({
    required this.command,
    required this.entryStrategy,
    required this.postCreateInput,
  });

  final String command;
  final TerminalEntryStrategy entryStrategy;
  final String postCreateInput;

  static TerminalLaunchPlanDefaults forTool(TerminalLaunchTool tool) {
    switch (tool) {
      case TerminalLaunchTool.claudeCode:
        return const TerminalLaunchPlanDefaults._(
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.shellBootstrap,
          postCreateInput: 'claude\n',
        );
      case TerminalLaunchTool.codex:
        return const TerminalLaunchPlanDefaults._(
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.shellBootstrap,
          postCreateInput: 'codex\n',
        );
      case TerminalLaunchTool.shell:
      case TerminalLaunchTool.custom:
        return const TerminalLaunchPlanDefaults._(
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.directExec,
          postCreateInput: '',
        );
    }
  }

  static String titleFor(TerminalLaunchTool tool, String cwd) {
    final prefix = switch (tool) {
      TerminalLaunchTool.claudeCode => 'Claude',
      TerminalLaunchTool.codex => 'Codex',
      TerminalLaunchTool.shell => 'Shell',
      TerminalLaunchTool.custom => 'Custom',
    };
    final segment = _basename(cwd);
    if (segment == null) {
      return prefix;
    }
    return '$prefix / $segment';
  }

  static String? _basename(String cwd) {
    final normalized = cwd.trim();
    if (normalized.isEmpty || normalized == '~' || normalized == '/') {
      return null;
    }
    final stripped = normalized.endsWith('/')
        ? normalized.substring(0, normalized.length - 1)
        : normalized;
    final parts = stripped.split('/');
    for (var index = parts.length - 1; index >= 0; index--) {
      final candidate = parts[index].trim();
      if (candidate.isNotEmpty && candidate != '~') {
        return candidate;
      }
    }
    return null;
  }
}

class TerminalLaunchToolCodec {
  static String toJson(TerminalLaunchTool tool) {
    switch (tool) {
      case TerminalLaunchTool.claudeCode:
        return 'claude_code';
      case TerminalLaunchTool.codex:
        return 'codex';
      case TerminalLaunchTool.shell:
        return 'shell';
      case TerminalLaunchTool.custom:
        return 'custom';
    }
  }

  static TerminalLaunchTool? fromJson(String? value) {
    switch (value) {
      case 'claude_code':
        return TerminalLaunchTool.claudeCode;
      case 'codex':
        return TerminalLaunchTool.codex;
      case 'shell':
        return TerminalLaunchTool.shell;
      case 'custom':
        return TerminalLaunchTool.custom;
      default:
        return null;
    }
  }
}

class TerminalEntryStrategyCodec {
  static String toJson(TerminalEntryStrategy strategy) {
    switch (strategy) {
      case TerminalEntryStrategy.directExec:
        return 'direct_exec';
      case TerminalEntryStrategy.shellBootstrap:
        return 'shell_bootstrap';
    }
  }

  static TerminalEntryStrategy? fromJson(String? value) {
    switch (value) {
      case 'direct_exec':
        return TerminalEntryStrategy.directExec;
      case 'shell_bootstrap':
        return TerminalEntryStrategy.shellBootstrap;
      default:
        return null;
    }
  }
}

class TerminalLaunchPlanSourceCodec {
  static String toJson(TerminalLaunchPlanSource source) {
    switch (source) {
      case TerminalLaunchPlanSource.recommended:
        return 'recommended';
      case TerminalLaunchPlanSource.intent:
        return 'intent';
      case TerminalLaunchPlanSource.custom:
        return 'custom';
    }
  }

  static TerminalLaunchPlanSource? fromJson(String? value) {
    switch (value) {
      case 'recommended':
        return TerminalLaunchPlanSource.recommended;
      case 'intent':
        return TerminalLaunchPlanSource.intent;
      case 'custom':
        return TerminalLaunchPlanSource.custom;
      default:
        return null;
    }
  }
}

class TerminalLaunchConfidenceCodec {
  static String toJson(TerminalLaunchConfidence confidence) {
    switch (confidence) {
      case TerminalLaunchConfidence.high:
        return 'high';
      case TerminalLaunchConfidence.medium:
        return 'medium';
      case TerminalLaunchConfidence.low:
        return 'low';
    }
  }

  static TerminalLaunchConfidence? fromJson(String? value) {
    switch (value) {
      case 'high':
        return TerminalLaunchConfidence.high;
      case 'medium':
        return TerminalLaunchConfidence.medium;
      case 'low':
        return TerminalLaunchConfidence.low;
      default:
        return null;
    }
  }
}
