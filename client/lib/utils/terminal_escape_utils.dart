// Terminal escape-sequence utilities shared between
// TerminalScreen and TerminalSessionManager.
//
// Centralises the regex patterns, formatting helpers, and
// auto-response classification logic that were previously
// duplicated in both files.

/// Matches common terminal transition sequences:
/// - alternate screen buffer switch  ESC[?1049h/l
/// - cursor save/restore             ESC[?1048h/l
/// - origin mode                     `\x1B[?6h/l`
/// - set scrolling region            `\x1B[...r`
final RegExp terminalTransitionPattern = RegExp(
  '\x1B\\[(?:\\?1049[hl]|\\?1048[hl]|\\?6[hl]|[0-9;]*r)',
);

/// Matches alternate-buffer transition sequences specifically.
final RegExp alternateBufferTransitionPattern = RegExp(
  '\x1B\\[\\?(?:1049|1047|47)[hl]',
);

/// Summarises terminal transition escape sequences found in [data].
///
/// Returns a string like `[ESC[?1049h, ESC[?1049l]` (with ESC
/// rendered literally).  At most 8 sequences are listed; excess ones
/// are represented by ` ...`.
String summarizeTerminalSequences(String data) {
  final matches = terminalTransitionPattern.allMatches(data).toList();
  if (matches.isEmpty) return '[]';

  final sequences = matches
      .map((m) => formatEscapeSequence(m.group(0)!))
      .take(8)
      .toList();
  final suffix = matches.length > sequences.length ? ' ...' : '';
  return '[${sequences.join(', ')}$suffix]';
}

/// Formats an escape-sequence string for human-readable logging.
///
/// Replaces `\x1B` with `<ESC>`, newlines and carriage returns with
/// their escaped representations.
String formatEscapeSequence(String value) {
  return value
      .replaceAll('\x1B', '<ESC>')
      .replaceAll('\n', r'\n')
      .replaceAll('\r', r'\r');
}

// ---------------------------------------------------------------------------
// Auto-response classification
// ---------------------------------------------------------------------------

/// Kinds of terminal auto-responses that the session manager may need to
/// suppress or handle specially.
enum TerminalAutoResponseKind {
  deviceAttributes,
  statusReport,
  cursorReport,
  deviceControlString,
}

/// Classifies [data] as a terminal auto-response, or returns `null` if
/// it does not look like one.
TerminalAutoResponseKind? classifyTerminalAutoResponse(String data) {
  if (data.isEmpty || !data.startsWith('\x1b')) return null;

  if (data == '\x1b[?1;2c' || data.startsWith('\x1b[>')) {
    return TerminalAutoResponseKind.deviceAttributes;
  }
  if (data == '\x1b[0n') {
    return TerminalAutoResponseKind.statusReport;
  }
  if (data.startsWith('\x1bP!|')) {
    return TerminalAutoResponseKind.deviceControlString;
  }
  final cursorReport = RegExp(r'^\x1b\[\d+;\d+R$');
  if (cursorReport.hasMatch(data)) {
    return TerminalAutoResponseKind.cursorReport;
  }
  return null;
}
