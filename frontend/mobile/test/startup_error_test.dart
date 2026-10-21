import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/main.dart';

void main() {
  testWidgets('a start-up error is shown as text, not a blank window', (
    t,
  ) async {
    await t.pumpWidget(const StartupError('MissingPluginException(x)'));
    expect(find.textContaining('JARVIS lỗi khởi động'), findsOneWidget);
    expect(find.textContaining('MissingPluginException(x)'), findsOneWidget);
  });
}
