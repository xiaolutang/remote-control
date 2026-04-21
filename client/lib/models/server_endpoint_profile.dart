enum ServerRouteMode {
  gateway,
  direct,
}

class ServerEndpointProfile {
  const ServerEndpointProfile._({
    required this.serverUrl,
    required this.httpBaseUrl,
    required this.host,
    required this.port,
    required this.pathPrefix,
    required this.routeMode,
    required this.usesTls,
    required this.isProductionGateway,
    required this.fallbackIp,
  });

  static const String productionRootHost = 'xiaolutang.top';
  static const String productionGatewayHost = 'rc.xiaolutang.top';
  static const String gatewayPathPrefix = '/rc';
  static const String compiledProductionFallbackIp =
      String.fromEnvironment('PRODUCTION_SERVER_IP', defaultValue: '');

  final String serverUrl;
  final String httpBaseUrl;
  final String host;
  final String port;
  final String pathPrefix;
  final ServerRouteMode routeMode;
  final bool usesTls;
  final bool isProductionGateway;
  final String fallbackIp;

  bool get hasFallbackIp => fallbackIp.isNotEmpty;
  bool get shouldTrustSelfSignedCertificates => usesTls && !isProductionGateway;

  factory ServerEndpointProfile.local({
    required String host,
    required String port,
  }) {
    if (port.isEmpty) {
      return ServerEndpointProfile.gateway(
        host: host,
        port: '',
        secure: true,
        pathPrefix: gatewayPathPrefix,
      );
    }

    return ServerEndpointProfile.direct(
      host: host,
      port: port,
      secure: false,
    );
  }

  factory ServerEndpointProfile.direct({
    required String host,
    required String port,
    required bool secure,
    String pathPrefix = '',
    bool isProductionGateway = false,
    String fallbackIp = '',
  }) {
    final normalizedPath = _normalizePathPrefix(pathPrefix);
    final serverUrl = _buildBaseUrl(
      scheme: secure ? 'wss' : 'ws',
      host: host,
      port: port,
      pathPrefix: normalizedPath,
    );
    final httpBaseUrl = _buildBaseUrl(
      scheme: secure ? 'https' : 'http',
      host: host,
      port: port,
      pathPrefix: normalizedPath,
    );
    return ServerEndpointProfile._(
      serverUrl: serverUrl,
      httpBaseUrl: httpBaseUrl,
      host: host,
      port: port,
      pathPrefix: normalizedPath,
      routeMode: ServerRouteMode.direct,
      usesTls: secure,
      isProductionGateway: isProductionGateway,
      fallbackIp: fallbackIp.trim(),
    );
  }

  factory ServerEndpointProfile.gateway({
    required String host,
    required String port,
    required bool secure,
    required String pathPrefix,
    bool isProductionGateway = false,
    String fallbackIp = '',
  }) {
    final normalizedPath = _normalizePathPrefix(pathPrefix);
    final serverUrl = _buildBaseUrl(
      scheme: secure ? 'wss' : 'ws',
      host: host,
      port: port,
      pathPrefix: normalizedPath,
    );
    final httpBaseUrl = _buildBaseUrl(
      scheme: secure ? 'https' : 'http',
      host: host,
      port: port,
      pathPrefix: normalizedPath,
    );
    return ServerEndpointProfile._(
      serverUrl: serverUrl,
      httpBaseUrl: httpBaseUrl,
      host: host,
      port: port,
      pathPrefix: normalizedPath,
      routeMode: ServerRouteMode.gateway,
      usesTls: secure,
      isProductionGateway: isProductionGateway,
      fallbackIp: fallbackIp.trim(),
    );
  }

  factory ServerEndpointProfile.production({
    String fallbackIp = compiledProductionFallbackIp,
  }) {
    return ServerEndpointProfile.gateway(
      host: productionGatewayHost,
      port: '',
      secure: true,
      pathPrefix: gatewayPathPrefix,
      isProductionGateway: true,
      fallbackIp: fallbackIp,
    );
  }

  factory ServerEndpointProfile.fromServerUrl(
    String serverUrl, {
    String fallbackIp = compiledProductionFallbackIp,
  }) {
    final uri = Uri.parse(serverUrl);
    final normalizedPath = _normalizePathPrefix(uri.path);
    final secure = uri.scheme == 'wss' || uri.scheme == 'https';
    final isProductionGateway =
        uri.host == productionRootHost || uri.host == productionGatewayHost;
    final routeMode = normalizedPath.isEmpty
        ? ServerRouteMode.direct
        : ServerRouteMode.gateway;
    final httpBaseUrl = _buildBaseUrl(
      scheme: secure ? 'https' : 'http',
      host: uri.host,
      port: uri.hasPort ? '${uri.port}' : '',
      pathPrefix: normalizedPath,
    );
    return ServerEndpointProfile._(
      serverUrl: serverUrl,
      httpBaseUrl: httpBaseUrl,
      host: uri.host,
      port: uri.hasPort ? '${uri.port}' : '',
      pathPrefix: normalizedPath,
      routeMode: routeMode,
      usesTls: secure,
      isProductionGateway: isProductionGateway,
      fallbackIp: isProductionGateway ? fallbackIp.trim() : '',
    );
  }

  Uri healthUri() => uriFor('health');

  Uri loginUri() => uriFor('api/login');

  Uri publicKeyUri() => uriFor('api/public-key');

  Uri uriFor(String relativePath) {
    final normalizedRelative =
        relativePath.startsWith('/') ? relativePath.substring(1) : relativePath;
    final fullPath = _joinPath(pathPrefix, normalizedRelative);
    return Uri.parse(httpBaseUrl).replace(path: fullPath);
  }

  Uri? ipFallbackUriFor(String relativePath) {
    if (!hasFallbackIp) {
      return null;
    }
    final normalizedRelative =
        relativePath.startsWith('/') ? relativePath.substring(1) : relativePath;
    final fullPath = _joinPath(pathPrefix, normalizedRelative);
    return Uri(
      scheme: usesTls ? 'https' : 'http',
      host: fallbackIp,
      path: fullPath,
    );
  }

  static String _buildBaseUrl({
    required String scheme,
    required String host,
    required String port,
    required String pathPrefix,
  }) {
    final uri = Uri(
      scheme: scheme,
      host: host,
      port: port.isEmpty ? null : int.parse(port),
      path: pathPrefix,
    );
    return uri.toString();
  }

  static String _normalizePathPrefix(String pathPrefix) {
    final trimmed = pathPrefix.trim();
    if (trimmed.isEmpty || trimmed == '/') {
      return '';
    }
    final withLeadingSlash = trimmed.startsWith('/') ? trimmed : '/$trimmed';
    return withLeadingSlash.endsWith('/')
        ? withLeadingSlash.substring(0, withLeadingSlash.length - 1)
        : withLeadingSlash;
  }

  static String _joinPath(String prefix, String relativePath) {
    final normalizedPrefix = _normalizePathPrefix(prefix);
    if (normalizedPrefix.isEmpty) {
      return '/$relativePath';
    }
    return '$normalizedPrefix/$relativePath';
  }
}
