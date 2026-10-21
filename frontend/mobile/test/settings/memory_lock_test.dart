import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/settings/settings_shell.dart';
import 'package:jarvis_mobile/theme/app_theme.dart';
import 'package:provider/provider.dart';

void main() {
  testWidgets('memory and logs pages open directly without password prompt', (t) async {
    final cfg = ServerConfig();
    final mockClient = MockClient((req) async {
      return http.Response('{}', 200);
    });

    final api = ApiClient(cfg, client: mockClient)..memoryToken = 'tok_123';

    await t.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider.value(value: cfg),
          Provider<ApiClient>.value(value: api),
        ],
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const SettingsShell(initialPageId: 'memory'),
        ),
      ),
    );
    await t.pumpAndSettle();

    expect(find.text('Nhập mật khẩu để mở.'), findsNothing);
    expect(find.text('Bộ nhớ'), findsOneWidget);
  });
}
