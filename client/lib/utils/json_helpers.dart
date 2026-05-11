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
