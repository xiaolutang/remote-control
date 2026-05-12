import 'package:flutter_test/flutter_test.dart';
import '../../test_support/integration_env.dart';

void main() {
  group('isPrivateIp', () {
    test('loopback addresses are local', () {
      expect(isPrivateIp('localhost'), isTrue);
      expect(isPrivateIp('127.0.0.1'), isTrue);
    });

    test('RFC1918 private addresses are local', () {
      expect(isPrivateIp('192.168.1.100'), isTrue);
      expect(isPrivateIp('192.168.0.1'), isTrue);
      expect(isPrivateIp('10.0.0.1'), isTrue);
      expect(isPrivateIp('10.255.255.255'), isTrue);
      expect(isPrivateIp('172.16.0.1'), isTrue);
      expect(isPrivateIp('172.31.255.255'), isTrue);
    });

    test('public IPs are not local', () {
      expect(isPrivateIp('8.8.8.8'), isFalse);
      expect(isPrivateIp('1.2.3.4'), isFalse);
      expect(isPrivateIp('172.15.0.1'), isFalse);
      expect(isPrivateIp('172.32.0.1'), isFalse);
    });
  });
}
