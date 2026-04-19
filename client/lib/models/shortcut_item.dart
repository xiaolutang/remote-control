import 'terminal_shortcut.dart';

enum ShortcutItemSource {
  builtin,
  user,
  project,
}

enum ShortcutItemSection {
  core,
  smart,
}

enum ShortcutItemScope {
  global,
  project,
}

class ShortcutItem {
  const ShortcutItem({
    required this.id,
    required this.label,
    required this.source,
    required this.section,
    required this.action,
    this.enabled = true,
    this.pinned = false,
    this.order = 0,
    this.useCount = 0,
    this.lastUsedAt,
    this.scope = ShortcutItemScope.global,
    this.description,
  });

  final String id;
  final String label;
  final ShortcutItemSource source;
  final ShortcutItemSection section;
  final TerminalShortcutAction action;
  final bool enabled;
  final bool pinned;
  final int order;
  final int useCount;
  final DateTime? lastUsedAt;
  final ShortcutItemScope scope;
  final String? description;

  bool get isCore => section == ShortcutItemSection.core;

  ShortcutItem copyWith({
    String? id,
    String? label,
    ShortcutItemSource? source,
    ShortcutItemSection? section,
    TerminalShortcutAction? action,
    bool? enabled,
    bool? pinned,
    int? order,
    int? useCount,
    DateTime? lastUsedAt,
    bool clearLastUsedAt = false,
    ShortcutItemScope? scope,
    String? description,
    bool clearDescription = false,
  }) {
    return ShortcutItem(
      id: id ?? this.id,
      label: label ?? this.label,
      source: source ?? this.source,
      section: section ?? this.section,
      action: action ?? this.action,
      enabled: enabled ?? this.enabled,
      pinned: pinned ?? this.pinned,
      order: order ?? this.order,
      useCount: useCount ?? this.useCount,
      lastUsedAt: clearLastUsedAt ? null : (lastUsedAt ?? this.lastUsedAt),
      scope: scope ?? this.scope,
      description: clearDescription ? null : (description ?? this.description),
    );
  }

  ShortcutItem markUsed([DateTime? usedAt]) {
    return copyWith(
      useCount: useCount + 1,
      lastUsedAt: usedAt ?? DateTime.now().toUtc(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'label': label,
      'source': source.name,
      'section': section.name,
      'action': action.toJson(),
      'enabled': enabled,
      'pinned': pinned,
      'order': order,
      'useCount': useCount,
      'lastUsedAt': lastUsedAt?.toUtc().toIso8601String(),
      'scope': scope.name,
      if (description != null) 'description': description,
    };
  }

  factory ShortcutItem.fromJson(Map<String, dynamic> json) {
    return ShortcutItem(
      id: json['id'] as String,
      label: json['label'] as String,
      source: ShortcutItemSource.values.byName(
        json['source'] as String? ?? ShortcutItemSource.builtin.name,
      ),
      section: ShortcutItemSection.values.byName(
        json['section'] as String? ?? ShortcutItemSection.smart.name,
      ),
      action: TerminalShortcutAction.fromJson(
        json['action'] as Map<String, dynamic>? ?? const {},
      ),
      enabled: json['enabled'] as bool? ?? true,
      pinned: json['pinned'] as bool? ?? false,
      order: json['order'] as int? ?? 0,
      useCount: json['useCount'] as int? ?? 0,
      lastUsedAt: json['lastUsedAt'] == null
          ? null
          : DateTime.parse(json['lastUsedAt'] as String).toUtc(),
      scope: ShortcutItemScope.values.byName(
        json['scope'] as String? ?? ShortcutItemScope.global.name,
      ),
      description: json['description'] as String?,
    );
  }

  factory ShortcutItem.fromTerminalShortcut(
    TerminalShortcut shortcut, {
    ShortcutItemSource source = ShortcutItemSource.builtin,
    ShortcutItemSection section = ShortcutItemSection.core,
    int order = 0,
    ShortcutItemScope scope = ShortcutItemScope.global,
  }) {
    return ShortcutItem(
      id: shortcut.id,
      label: shortcut.label,
      source: source,
      section: section,
      action: shortcut.action,
      order: order,
      scope: scope,
    );
  }
}

class ShortcutLayout {
  const ShortcutLayout({
    required this.coreItems,
    required this.smartItems,
  });

  final List<ShortcutItem> coreItems;
  final List<ShortcutItem> smartItems;
}

class ShortcutItemSorter {
  const ShortcutItemSorter._();

  static ShortcutLayout partitionAndSort(Iterable<ShortcutItem> items) {
    final enabledItems = items.where((item) => item.enabled);
    final coreItems = enabledItems
        .where((item) => item.section == ShortcutItemSection.core)
        .toList()
      ..sort(_compareCore);
    final smartItems = enabledItems
        .where((item) => item.section == ShortcutItemSection.smart)
        .toList()
      ..sort(_compareSmart);

    return ShortcutLayout(coreItems: coreItems, smartItems: smartItems);
  }

  static int _compareCore(ShortcutItem a, ShortcutItem b) {
    final byOrder = a.order.compareTo(b.order);
    if (byOrder != 0) return byOrder;
    return a.label.compareTo(b.label);
  }

  static int _compareSmart(ShortcutItem a, ShortcutItem b) {
    if (a.pinned != b.pinned) {
      return a.pinned ? -1 : 1;
    }

    final aLast = a.lastUsedAt;
    final bLast = b.lastUsedAt;
    if (aLast != null && bLast != null) {
      final byRecent = bLast.compareTo(aLast);
      if (byRecent != 0) return byRecent;
    } else if (aLast != null || bLast != null) {
      return aLast != null ? -1 : 1;
    }

    final byOrder = a.order.compareTo(b.order);
    if (byOrder != 0) return byOrder;

    return a.label.compareTo(b.label);
  }
}
