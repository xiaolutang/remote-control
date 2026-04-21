import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/server_endpoint_profile.dart';

void main() {
  group('ServerEndpointProfile', () {
    test('local default uses gateway /rc path', () {
      final profile = ServerEndpointProfile.local(
        host: 'localhost',
        port: '',
      );

      expect(profile.serverUrl, 'wss://localhost/rc');
      expect(profile.httpBaseUrl, 'https://localhost/rc');
      expect(profile.routeMode, ServerRouteMode.gateway);
      expect(profile.healthUri().toString(), 'https://localhost/rc/health');
      expect(profile.shouldTrustSelfSignedCertificates, isTrue);
    });

    test('local custom port uses direct route', () {
      final profile = ServerEndpointProfile.local(
        host: '127.0.0.1',
        port: '8080',
      );

      expect(profile.serverUrl, 'ws://127.0.0.1:8080');
      expect(profile.httpBaseUrl, 'http://127.0.0.1:8080');
      expect(profile.routeMode, ServerRouteMode.direct);
      expect(profile.healthUri().toString(), 'http://127.0.0.1:8080/health');
    });

    test('production uses TLS gateway and fallback ip when provided', () {
      final profile = ServerEndpointProfile.production(fallbackIp: '1.2.3.4');

      expect(profile.serverUrl, 'wss://rc.xiaolutang.top/rc');
      expect(profile.httpBaseUrl, 'https://rc.xiaolutang.top/rc');
      expect(profile.usesTls, isTrue);
      expect(profile.isProductionGateway, isTrue);
      expect(
        profile.ipFallbackUriFor('health')?.toString(),
        'https://1.2.3.4/rc/health',
      );
    });

    test('fromServerUrl preserves path-based gateway semantics', () {
      final profile =
          ServerEndpointProfile.fromServerUrl('wss://rc.xiaolutang.top/rc');

      expect(profile.routeMode, ServerRouteMode.gateway);
      expect(profile.isProductionGateway, isTrue);
      expect(profile.loginUri().toString(),
          'https://rc.xiaolutang.top/rc/api/login');
    });
  });
}
