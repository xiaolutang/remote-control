/// 安全地将动态 JSON 值转为 int。
///
/// 处理 int、num、String 三种 JSON 数值类型，解析失败返回 0。
int readIntFromJson(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  if (value is String) return int.tryParse(value) ?? 0;
  return 0;
}

/// 安全地将动态 JSON 值转为 trimmed String，null/缺失返回空串。
///
/// 非字符串输入在 debug 模式下会 assert，release 模式静默返回空串。
String readStringFromJson(Object? value) {
  assert(value == null || value is String,
      'readStringFromJson: expected String but got ${value.runtimeType}');
  if (value is String) return value.trim();
  return '';
}

/// 安全地将动态 JSON 值转为 trimmed String?，null/缺失返回 null。
///
/// 用于 nullable 字段（如 `final String? conversationId`）。
String? readOptionalStringFromJson(Object? value) {
  if (value is String) return value.trim();
  return null;
}

/// 安全地将动态 JSON 值转为 String（不 trim），null/缺失/非字符串返回空串。
///
/// 用于控制字符有语义的场景（终端 payload 中的 \\r、\\t、\\x1b 等）。
String readRawStringFromJson(Object? value) {
  if (value is String) return value;
  return '';
}

/// 安全地将动态 JSON 值转为 bool，null/缺失返回 [defaultValue]。
bool readBoolFromJson(Object? value, {bool defaultValue = false}) {
  if (value is bool) return value;
  return defaultValue;
}

/// 安全地将动态 JSON 值转为 List<T>，逐元素通过 [fromJson] 转换。
///
/// null 或非 List 输入返回空列表。
List<T> readListFromJson<T>(
  Object? value,
  T Function(Map<String, dynamic>) fromJson,
) {
  if (value is List) {
    return value
        .whereType<Map<String, dynamic>>()
        .map(fromJson)
        .toList(growable: false);
  }
  return const [];
}

/// 安全地将枚举名称映射为枚举值，未知名称返回 [fallback]。
///
/// 替代 `values.byName(name)` —— byName 遇到未知值会抛 ArgumentError。
T enumFromJson<T extends Enum>(
  List<T> values,
  String? name,
  T fallback,
) {
  if (name == null) return fallback;
  for (final v in values) {
    if (v.name == name) return v;
  }
  return fallback;
}

/// 安全地将 Map<String, dynamic> 的 value 转为 int。
///
/// 兼容 int、num（double → toInt）、String 三种 JSON 数值类型。
int safeIntFromMapValue(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return 0;
}
