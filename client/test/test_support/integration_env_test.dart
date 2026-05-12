import 'package:flutter_test/flutter_test.dart';
import '../../test_support/integration_env.dart';

void main() {
  group('isLocalTestEnv', () {
    test('loopback addresses are local', () {
      expect(isLocalTestEnv('localhost'), isTrue);
      expect(isLocalTestEnv('127.0.0.1'), isTrue);
    });

    test('RFC1918 private addresses are local', () {
      expect(isLocalTestEnv('192.168.1.100'), isTrue);
      expect(isLocalTestEnv('192.168.0.1'), isTrue);
      expect(isLocalTestEnv('10.0.0.1'), isTrue);
      expect(isLocalTestEnv('10.255.255.255'), isTrue);
      expect(isLocalTestEnv('172.16.0.1'), isTrue);
      expect(isLocalTestEnv('172.31.255.255'), isTrue);
    });

    test('public IPs are not local', () {
      expect(isLocalTestEnv('8.8.8.8'), isFalse);
      expect(isLocalTestEnv('1.2.3.4'), isFalse);
      expect(isLocalTestEnv('172.15.0.1'), isFalse);
      expect(isLocalTestEnv('172.32.0.1'), isFalse);
    });
  });
}
