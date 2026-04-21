import 'package:flutter/material.dart';

import 'app_environment.dart';

extension AppEnvironmentPresentation on AppEnvironment {
  String get label {
    switch (this) {
      case AppEnvironment.local:
        return '本地';
      case AppEnvironment.direct:
        return '直连';
      case AppEnvironment.production:
        return '线上';
    }
  }

  String get title {
    switch (this) {
      case AppEnvironment.local:
        return '本地开发环境';
      case AppEnvironment.direct:
        return '服务器直连';
      case AppEnvironment.production:
        return '线上正式环境';
    }
  }

  String get description {
    switch (this) {
      case AppEnvironment.local:
        return '适合本机开发和联调，优先用于快速验证。';
      case AppEnvironment.direct:
        return '通过服务器 IP 直连，适合绕过域名或 TLS 问题排查。';
      case AppEnvironment.production:
        return '默认正式入口，使用域名与 TLS 连接。';
    }
  }

  IconData get icon {
    switch (this) {
      case AppEnvironment.local:
        return Icons.lan_outlined;
      case AppEnvironment.direct:
        return Icons.route_outlined;
      case AppEnvironment.production:
        return Icons.cloud_outlined;
    }
  }
}
