import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rc_client/services/runtime_device_service.dart';

void main() {
  group('RuntimeDeviceService', () {
    test('lists runtime devices', () async {
      final client = MockClient((request) async {
        expect(request.url.toString(), 'http://localhost:8888/api/runtime/devices');
        return http.Response(
          jsonEncode({
            'devices': [
              {
                'device_id': 'mbp-01',
                'name': 'MacBook Pro',
                'owner': 'user1',
                'agent_online': true,
                'max_terminals': 3,
                'active_terminals': 1,
              },
            ],
          }),
          200,
        );
      });
      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final devices = await service.listDevices('token');

      expect(devices.single.deviceId, 'mbp-01');
      expect(devices.single.canCreateTerminal, isTrue);
    });

    test('creates runtime terminal', () async {
      final client = MockClient((request) async {
        expect(request.method, 'POST');
        return http.Response(
          jsonEncode({
            'terminal_id': 'term-1',
            'title': 'Claude',
            'cwd': '/tmp',
            'command': '/bin/bash',
            'status': 'detached',
            'views': {'mobile': 0, 'desktop': 0},
          }),
          200,
        );
      });
      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final terminal = await service.createTerminal(
        'token',
        'mbp-01',
        title: 'Claude',
        cwd: '/tmp',
        command: '/bin/bash',
        terminalId: 'term-1',
      );

      expect(terminal.terminalId, 'term-1');
      expect(terminal.status, 'detached');
    });

    test('gets runtime terminal snapshot from backend list', () async {
      final client = MockClient((request) async {
        expect(request.method, 'GET');
        expect(
          request.url.toString(),
          'http://localhost:8888/api/runtime/devices/mbp-01/terminals',
        );
        return http.Response(
          jsonEncode({
            'device_id': 'mbp-01',
            'device_online': true,
            'terminals': [
              {
                'terminal_id': 'term-1',
                'title': 'Claude',
                'cwd': '/tmp',
                'command': '/bin/bash',
                'status': 'attached',
                'views': {'mobile': 1, 'desktop': 1},
              },
            ],
          }),
          200,
        );
      });
      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final terminal = await service.getTerminal('token', 'mbp-01', 'term-1');

      expect(terminal, isNotNull);
      expect(terminal!.views['mobile'], 1);
      expect(terminal.views['desktop'], 1);
    });

    test('closes runtime terminal', () async {
      final client = MockClient((request) async {
        expect(request.method, 'DELETE');
        expect(
          request.url.toString(),
          'http://localhost:8888/api/runtime/devices/mbp-01/terminals/term-1',
        );
        return http.Response(
          jsonEncode({
            'terminal_id': 'term-1',
            'title': 'Claude',
            'cwd': '/tmp',
            'command': '/bin/bash',
            'status': 'closed',
            'disconnect_reason': 'server_forced_close',
            'updated_at': '2026-03-29T02:00:00Z',
            'views': {'mobile': 0, 'desktop': 0},
          }),
          200,
        );
      });
      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final terminal = await service.closeTerminal('token', 'mbp-01', 'term-1');

      expect(terminal.terminalId, 'term-1');
      expect(terminal.status, 'closed');
      expect(terminal.disconnectReason, 'server_forced_close');
    });

    test('updates device settings', () async {
      final client = MockClient((request) async {
        expect(request.method, 'PATCH');
        expect(
          request.url.toString(),
          'http://localhost:8888/api/runtime/devices/mbp-01',
        );
        expect(
          jsonDecode(request.body),
          {'name': 'New Name'},
        );
        return http.Response(
          jsonEncode({
            'device_id': 'mbp-01',
            'name': 'New Name',
            'owner': 'user1',
            'agent_online': true,
            'max_terminals': 3,
            'active_terminals': 1,
          }),
          200,
        );
      });
      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final device = await service.updateDevice(
        'token',
        'mbp-01',
        name: 'New Name',
      );

      expect(device.deviceId, 'mbp-01');
      expect(device.name, 'New Name');
      expect(device.maxTerminals, 3);
    });

    test('updates terminal title', () async {
      final client = MockClient((request) async {
        expect(request.method, 'PATCH');
        expect(
          request.url.toString(),
          'http://localhost:8888/api/runtime/devices/mbp-01/terminals/term-1',
        );
        return http.Response(
          jsonEncode({
            'terminal_id': 'term-1',
            'title': 'New Title',
            'cwd': '/tmp',
            'command': '/bin/bash',
            'status': 'detached',
            'updated_at': '2026-03-29T02:00:00Z',
            'views': {'mobile': 0, 'desktop': 0},
          }),
          200,
        );
      });
      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final terminal = await service.updateTerminalTitle(
        'token',
        'mbp-01',
        'term-1',
        'New Title',
      );

      expect(terminal.terminalId, 'term-1');
      expect(terminal.title, 'New Title');
    });
  });
}
