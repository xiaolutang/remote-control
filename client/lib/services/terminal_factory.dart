import 'package:xterm/xterm.dart';

/// App-wide terminal factory.
///
/// We intentionally disable xterm reflow on resize. Desktop layout changes
/// (for example the sidebar width transition) can trigger buffer reflow on
/// terminals that contain complex Claude/Codex alt-buffer content. In
/// practice, preserving the existing buffer is safer than re-wrapping it.
Terminal buildAppTerminal({
  int maxLines = 10000,
}) {
  return Terminal(
    maxLines: maxLines,
    reflowEnabled: false,
  );
}
