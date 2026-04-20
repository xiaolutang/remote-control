import 'package:test/test.dart';
import 'package:xterm/core.dart';

import '../_fixture/_fixture.dart';

void main() {
  group('Terminal.inputHandler', () {
    test('can be set to null', () {
      final terminal = Terminal(inputHandler: null);
      expect(() => terminal.keyInput(TerminalKey.keyA), returnsNormally);
    });

    test('can be changed', () {
      final handler1 = _TestInputHandler();
      final handler2 = _TestInputHandler();
      final terminal = Terminal(inputHandler: handler1);

      terminal.keyInput(TerminalKey.keyA);
      expect(handler1.events, isNotEmpty);

      terminal.inputHandler = handler2;

      terminal.keyInput(TerminalKey.keyA);
      expect(handler2.events, isNotEmpty);
    });
  });

  group('Terminal.mouseInput', () {
    test('can handle mouse events', () {
      final output = <String>[];

      final terminal = Terminal(onOutput: output.add);

      terminal.mouseInput(
        TerminalMouseButton.left,
        TerminalMouseButtonState.down,
        CellOffset(10, 10),
      );

      expect(output, isEmpty);

      // enable mouse reporting
      terminal.write('\x1b[?1000h');

      terminal.mouseInput(
        TerminalMouseButton.left,
        TerminalMouseButtonState.down,
        CellOffset(10, 10),
      );

      expect(output, ['\x1B[M +,']);
    });
  });

  group('Terminal.sendCursorPosition', () {
    test('responds to CPR requests using ANSI 1-based origin coordinates', () {
      final output = <String>[];
      final terminal = Terminal(onOutput: output.add);

      terminal.setCursor(0, 0);
      terminal.write('\x1b[6n');

      expect(output, equals(['\x1b[1;1R']));
    });

    test('responds to CPR requests using ANSI 1-based arbitrary coordinates',
        () {
      final output = <String>[];
      final terminal = Terminal(onOutput: output.add);

      terminal.setCursor(5, 3);
      terminal.write('\x1b[6n');

      expect(output, equals(['\x1b[4;6R']));
    });
  });

  group('Terminal.reflowEnabled', () {
    test('prevents reflow when set to false', () {
      final terminal = Terminal(reflowEnabled: false);

      terminal.write('Hello World');
      terminal.resize(5, 5);

      expect(terminal.buffer.lines[0].toString(), 'Hello');
      expect(terminal.buffer.lines[1].toString(), isEmpty);
    });

    test('preserves hidden cells when reflow is disabled', () {
      final terminal = Terminal(reflowEnabled: false);

      terminal.write('Hello World');
      terminal.resize(5, 5);
      terminal.resize(20, 5);

      expect(terminal.buffer.lines[0].toString(), 'Hello World');
      expect(terminal.buffer.lines[1].toString(), isEmpty);
    });

    test('can be set at runtime', () {
      final terminal = Terminal(reflowEnabled: true);

      terminal.resize(5, 5);
      terminal.write('Hello World');
      terminal.reflowEnabled = false;
      terminal.resize(20, 5);

      expect(terminal.buffer.lines[0].toString(), 'Hello');
      expect(terminal.buffer.lines[1].toString(), ' Worl');
      expect(terminal.buffer.lines[2].toString(), 'd');
    });
  });

  group('Terminal.mouseInput', () {
    test('applys to the main buffer', () {
      final terminal = Terminal(
        wordSeparators: {
          'z'.codeUnitAt(0),
        },
      );

      expect(
        terminal.mainBuffer.wordSeparators,
        contains('z'.codeUnitAt(0)),
      );
    });

    test('applys to the alternate buffer', () {
      final terminal = Terminal(
        wordSeparators: {
          'z'.codeUnitAt(0),
        },
      );

      expect(
        terminal.altBuffer.wordSeparators,
        contains('z'.codeUnitAt(0)),
      );
    });

    test('restores main buffer cursor after exiting alt buffer with 1049', () {
      final terminal = Terminal();

      terminal.setCursor(12, 6);
      terminal.write('\x1b[?1049h');
      terminal.setCursor(1, 1);

      terminal.write('\x1b[?1049l');

      expect(terminal.buffer, same(terminal.mainBuffer));
      expect(terminal.buffer.cursorX, 12);
      expect(terminal.buffer.cursorY, 6);
    });

    test('enters alt buffer at home position after 1049 enable', () {
      final terminal = Terminal();

      terminal.setCursor(10, 8);
      terminal.write('\x1b[?1049h');

      expect(terminal.buffer, same(terminal.altBuffer));
      expect(terminal.buffer.cursorX, 0);
      expect(terminal.buffer.cursorY, 0);
    });

    test('homes cursor when setting scroll margins', () {
      final terminal = Terminal();

      terminal.setCursor(12, 9);
      terminal.write('\x1b[3;20r');

      expect(terminal.buffer.marginTop, 2);
      expect(terminal.buffer.marginBottom, 19);
      expect(terminal.buffer.cursorX, 0);
      expect(terminal.buffer.cursorY, 0);
    });

    test('homes cursor to margin top when enabling origin mode', () {
      final terminal = Terminal();

      terminal.write('\x1b[3;20r');
      terminal.setCursor(12, 9);
      terminal.write('\x1b[?6h');

      expect(terminal.originMode, isTrue);
      expect(terminal.buffer.cursorX, 0);
      expect(terminal.buffer.cursorY, 2);
    });

    test('homes cursor to screen origin when disabling origin mode', () {
      final terminal = Terminal();

      terminal.write('\x1b[3;20r');
      terminal.write('\x1b[?6h');
      terminal.setCursor(5, 5);
      terminal.write('\x1b[?6l');

      expect(terminal.originMode, isFalse);
      expect(terminal.buffer.cursorX, 0);
      expect(terminal.buffer.cursorY, 0);
    });

    test('restores cursor with ANSI CSI s/u sequences', () {
      final terminal = Terminal();

      terminal.setCursor(7, 4);
      terminal.write('\x1b[s');
      terminal.setCursor(1, 1);
      terminal.write('\x1b[u');

      expect(terminal.buffer.cursorX, 7);
      expect(terminal.buffer.cursorY, 4);
    });

    test('restores cursor to the saved buffer line after scrollback grows', () {
      final terminal = Terminal();
      terminal.resize(5, 4);

      terminal.write('a\r\nb\r\nc\r\nd');
      terminal.setCursor(0, 2);
      terminal.write('\x1b[s');
      terminal.setCursor(0, 3);

      terminal.write('\r\ne');
      terminal.write('\x1b[u');

      expect(terminal.buffer.scrollBack, 1);
      expect(terminal.buffer.absoluteCursorY, 2);
      expect(terminal.buffer.cursorX, 0);
      expect(terminal.buffer.cursorY, 1);
      expect(terminal.buffer.currentLine.toString(), 'c');
    });

    test('treats VPA as relative to top margin in origin mode', () {
      final terminal = Terminal();

      terminal.write('\x1b[3;20r');
      terminal.write('\x1b[?6h');
      terminal.setCursor(7, 10);
      terminal.write('\x1b[5d');

      expect(terminal.buffer.cursorX, 7);
      expect(terminal.buffer.cursorY, 6);
    });

    test('clamps relative vertical cursor movement to margins in origin mode',
        () {
      final terminal = Terminal();

      terminal.write('\x1b[3;20r');
      terminal.write('\x1b[?6h');
      terminal.setCursor(7, 0);
      terminal.write('\x1b[999B');

      expect(terminal.buffer.cursorX, 7);
      expect(terminal.buffer.cursorY, 19);

      terminal.write('\x1b[999A');

      expect(terminal.buffer.cursorX, 7);
      expect(terminal.buffer.cursorY, 2);
    });

    test('restores origin mode cursor relative to margins', () {
      final terminal = Terminal();

      terminal.write('\x1b[3;20r');
      terminal.write('\x1b[?6h');
      terminal.setCursor(7, 5);
      terminal.write('\x1b[s');
      terminal.write('\x1b[?6l');
      terminal.setCursor(0, 0);
      terminal.write('\x1b[u');

      expect(terminal.originMode, isTrue);
      expect(terminal.buffer.cursorX, 7);
      expect(terminal.buffer.cursorY, 7);
    });
  });

  group('Terminal.onPrivateOSC', () {
    test(r'works with \a end', () {
      String? lastCode;
      List<String>? lastData;

      final terminal = Terminal(
        onPrivateOSC: (String code, List<String> data) {
          lastCode = code;
          lastData = data;
        },
      );

      terminal.write('\x1b]6\x07');

      expect(lastCode, '6');
      expect(lastData, []);

      terminal.write('\x1b]66;hello world\x07');

      expect(lastCode, '66');
      expect(lastData, ['hello world']);

      terminal.write('\x1b]666;hello;world\x07');

      expect(lastCode, '666');
      expect(lastData, ['hello', 'world']);

      terminal.write('\x1b]hello;world\x07');

      expect(lastCode, 'hello');
      expect(lastData, ['world']);
    });

    test(r'works with \x1b\ end', () {
      String? lastCode;
      List<String>? lastData;

      final terminal = Terminal(
        onPrivateOSC: (String code, List<String> data) {
          lastCode = code;
          lastData = data;
        },
      );

      terminal.write('\x1b]6\x1b\\');

      expect(lastCode, '6');
      expect(lastData, []);

      terminal.write('\x1b]66;hello world\x1b\\');

      expect(lastCode, '66');
      expect(lastData, ['hello world']);

      terminal.write('\x1b]666;hello;world\x1b\\');

      expect(lastCode, '666');
      expect(lastData, ['hello', 'world']);

      terminal.write('\x1b]hello;world\x1b\\');

      expect(lastCode, 'hello');
      expect(lastData, ['world']);
    });

    test('do not receive common osc', () {
      String? lastCode;
      List<String>? lastData;

      final terminal = Terminal(
        onPrivateOSC: (String code, List<String> data) {
          lastCode = code;
          lastData = data;
        },
      );

      terminal.write('\x1b]0;hello world\x07');

      expect(lastCode, isNull);
      expect(lastData, isNull);
    });
  });

  group('Terminal.shellExitReplay', () {
    test('replays codex shell exit after ctrl+c back to the shell prompt', () {
      final terminal = Terminal(maxLines: 10000);
      terminal.resize(80, 24, 0, 0);

      terminal.write(TestFixtures.codexShellExitAfterCtrlC());
      final nonEmptyLines = _nonEmptyLines(terminal);

      expect(terminal.isUsingAltBuffer, isFalse);
      expect(terminal.buffer.currentLine.toString(), TestFixtures.shellPrompt);
      expect(nonEmptyLines.last, TestFixtures.shellPrompt);
      expect(nonEmptyLines.first, startsWith('To continue this session'));
      expect(
        _lastNonEmptyLineIndex(terminal),
        terminal.buffer.absoluteCursorY,
      );
    });

    test('replays claude shell exit after ctrl+c back to the shell prompt', () {
      final terminal = Terminal(maxLines: 10000);
      terminal.resize(80, 24, 0, 0);

      terminal.write(TestFixtures.claudeShellExitAfterCtrlC());
      final nonEmptyLines = _nonEmptyLines(terminal);

      expect(terminal.isUsingAltBuffer, isFalse);
      expect(terminal.buffer.currentLine.toString(), TestFixtures.shellPrompt);
      expect(nonEmptyLines.last, TestFixtures.shellPrompt);
      expect(
        _lastNonEmptyLineIndex(terminal),
        terminal.buffer.absoluteCursorY,
      );
    });

    test('replays claude slash-exit real transcript back to the shell prompt',
        () {
      final terminal = Terminal(maxLines: 10000);
      terminal.resize(80, 24, 0, 0);

      terminal.write(TestFixtures.claudeShellExitAfterSlashExitRealTranscript());
      final nonEmptyLines = _nonEmptyLines(terminal);

      expect(terminal.isUsingAltBuffer, isFalse);
      expect(terminal.buffer.currentLine.toString(), TestFixtures.shellPrompt);
      expect(nonEmptyLines.last, TestFixtures.shellPrompt);
      expect(
        _lastNonEmptyLineIndex(terminal),
        terminal.buffer.absoluteCursorY,
      );
    });
  });
}

List<String> _nonEmptyLines(Terminal terminal) {
  final lines = <String>[];
  terminal.buffer.lines.forEach((line) {
    final text = line.toString();
    if (text.trim().isNotEmpty) {
      lines.add(text);
    }
  });
  return lines;
}

int _lastNonEmptyLineIndex(Terminal terminal) {
  for (var i = terminal.buffer.lines.length - 1; i >= 0; i--) {
    if (terminal.buffer.lines[i].toString().trim().isNotEmpty) {
      return i;
    }
  }
  return -1;
}

class _TestInputHandler implements TerminalInputHandler {
  final events = <TerminalKeyboardEvent>[];

  @override
  String? call(TerminalKeyboardEvent event) {
    events.add(event);
    return null;
  }
}
