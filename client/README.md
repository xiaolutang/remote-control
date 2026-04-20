# rc_client

## Production Network E2E

Use the standalone runner for stable production network verification:

```bash
cd client
dart run tool/production_network_e2e.dart --server-ip YOUR_SERVER_IP
```

Optional parameters:

```bash
dart run tool/production_network_e2e.dart \
  --server-ip YOUR_SERVER_IP \
  --host rc.xiaolutang.top \
  --username prod_test \
  --password test123456
```

Environment variables are also supported:

```bash
RC_TEST_SERVER_IP=YOUR_SERVER_IP \
RC_TEST_USERNAME=prod_test \
RC_TEST_PASSWORD=test123456 \
dart run tool/production_network_e2e.dart
```

`integration_test/production_network_probe_test.dart` is kept only as an
explicit opt-in harness entry. It is not the default gate because Flutter
`integration_test` currently reports post-test TLS socket noise across macOS,
iOS, and Android even after the probe itself succeeds.
