import 'package:mockito/annotations.dart';
import 'package:mockito/mockito.dart';
import 'package:test/test.dart';
import 'package:xterm/xterm.dart';

@GenerateNiceMocks([MockSpec<EscapeHandler>()])
import 'parser_test.mocks.dart';

void main() {
  group('EscapeParser', () {
    test('can parse window manipulation', () {
      final parser = EscapeParser(MockEscapeHandler());
      parser.write('\x1b[8;24;80t');
      verify(parser.handler.resize(80, 24));
    });

    test('enters alternate buffer with 1049h in the expected order', () {
      final handler = MockEscapeHandler();
      final parser = EscapeParser(handler);

      parser.write('\x1b[?1049h');

      verifyInOrder([
        handler.saveCursor(),
        handler.clearAltBuffer(),
        handler.useAltBuffer(),
      ]);
      verifyNever(handler.restoreCursor());
    });

    test('leaves alternate buffer with 1049l in the expected order', () {
      final handler = MockEscapeHandler();
      final parser = EscapeParser(handler);

      parser.write('\x1b[?1049l');

      verifyInOrder([
        handler.useMainBuffer(),
        handler.restoreCursor(),
      ]);
      verifyNever(handler.clearAltBuffer());
    });
  });
}
