import '../models/claude_command_pack.dart';
import '../models/shortcut_item.dart';
import '../models/terminal_shortcut.dart';
import 'config_service.dart';

class ShortcutConfigService {
  ShortcutConfigService({ConfigService? configService})
      : _configService = configService ?? ConfigService();

  final ConfigService _configService;

  Future<List<ShortcutItem>> loadShortcutItems() async {
    final config = await _configService.loadConfig();
    return _mergeWithDefaults(config.shortcutItems);
  }

  Future<ClaudeNavigationMode> loadClaudeNavigationMode() async {
    final config = await _configService.loadConfig();
    return config.claudeNavigationMode;
  }

  Future<void> saveClaudeNavigationMode(ClaudeNavigationMode mode) async {
    final config = await _configService.loadConfig();
    await _configService.saveConfig(config.copyWith(claudeNavigationMode: mode));
  }

  Future<void> saveShortcutItems(List<ShortcutItem> items) async {
    final config = await _configService.loadConfig();
    await _configService.saveConfig(config.copyWith(shortcutItems: items));
  }

  Future<List<ShortcutItem>> restoreDefaultShortcutItems() async {
    final defaults = ClaudeCommandPack.cloneDefaults();
    await saveShortcutItems(defaults);
    return defaults;
  }

  List<ShortcutItem> _mergeWithDefaults(List<ShortcutItem> savedItems) {
    final defaults = ClaudeCommandPack.cloneDefaults();
    if (savedItems.isEmpty) {
      return defaults;
    }

    final merged = <ShortcutItem>[
      for (final defaultItem in defaults)
        savedItems.firstWhere(
          (item) => item.id == defaultItem.id,
          orElse: () => defaultItem,
        ),
    ];

    final defaultIds = defaults.map((item) => item.id).toSet();
    for (final item in savedItems) {
      if (!defaultIds.contains(item.id)) {
        merged.add(item);
      }
    }

    merged.sort((a, b) {
      final byOrder = a.order.compareTo(b.order);
      if (byOrder != 0) return byOrder;
      return a.label.compareTo(b.label);
    });

    return merged;
  }

  Future<void> updateShortcutItem(ShortcutItem item) async {
    final items = List<ShortcutItem>.from(await loadShortcutItems());
    final index = items.indexWhere((candidate) => candidate.id == item.id);
    if (index >= 0) {
      items[index] = item;
    } else {
      items.add(item);
    }
    await saveShortcutItems(items);
  }

  Future<void> reorderShortcutItems(List<String> orderedIds) async {
    final items = List<ShortcutItem>.from(await loadShortcutItems());
    final byId = {for (final item in items) item.id: item};
    final reordered = <ShortcutItem>[];

    for (var i = 0; i < orderedIds.length; i++) {
      final item = byId.remove(orderedIds[i]);
      if (item != null) {
        reordered.add(item.copyWith(order: i + 1));
      }
    }

    final remaining = byId.values.toList()
      ..sort((a, b) => a.order.compareTo(b.order));
    for (final item in remaining) {
      reordered.add(item.copyWith(order: reordered.length + 1));
    }

    await saveShortcutItems(reordered);
  }

  Future<void> toggleShortcutItem(String id, bool enabled) async {
    final items = List<ShortcutItem>.from(await loadShortcutItems());
    final updated = items
        .map((item) => item.id == id ? item.copyWith(enabled: enabled) : item)
        .toList(growable: false);
    await saveShortcutItems(updated);
  }

  Future<List<ShortcutItem>> loadProjectShortcutItems(String projectId) async {
    final config = await _configService.loadConfig();
    return config.projectShortcutItems[projectId] ?? const [];
  }

  Future<void> saveProjectShortcutItems(
    String projectId,
    List<ShortcutItem> items,
  ) async {
    final config = await _configService.loadConfig();
    final updatedProjectItems = Map<String, List<ShortcutItem>>.from(
      config.projectShortcutItems,
    )..[projectId] = items;
    await _configService.saveConfig(
      config.copyWith(projectShortcutItems: updatedProjectItems),
    );
  }

  Future<void> addProjectShortcutItem(
    String projectId,
    ShortcutItem item,
  ) async {
    final items = List<ShortcutItem>.from(await loadProjectShortcutItems(projectId))
      ..add(item.copyWith(
        source: ShortcutItemSource.project,
        scope: ShortcutItemScope.project,
      ));
    await saveProjectShortcutItems(projectId, items);
  }

  Future<void> updateProjectShortcutItem(
    String projectId,
    ShortcutItem item,
  ) async {
    final items = List<ShortcutItem>.from(await loadProjectShortcutItems(projectId));
    final index = items.indexWhere((candidate) => candidate.id == item.id);
    if (index >= 0) {
      items[index] = item.copyWith(
        source: ShortcutItemSource.project,
        scope: ShortcutItemScope.project,
      );
    } else {
      items.add(item.copyWith(
        source: ShortcutItemSource.project,
        scope: ShortcutItemScope.project,
      ));
    }
    await saveProjectShortcutItems(projectId, items);
  }

  Future<List<ShortcutItem>> loadCombinedShortcutItems({
    String? projectId,
  }) async {
    final items = List<ShortcutItem>.from(await loadShortcutItems());
    if (projectId != null && projectId.isNotEmpty) {
      items.addAll(await loadProjectShortcutItems(projectId));
    }
    return items;
  }
}
