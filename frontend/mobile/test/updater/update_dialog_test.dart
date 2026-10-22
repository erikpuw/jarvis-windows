import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/updater/update_dialog.dart';
import 'package:shorebird_code_push/shorebird_code_push.dart';

class FakeShorebirdUpdater implements ShorebirdUpdater {
  bool updateCalled = false;
  Completer<void> updateCompleter = Completer<void>();

  @override
  bool get isAvailable => true;

  @override
  Future<UpdateStatus> checkForUpdate({UpdateTrack? track}) async => UpdateStatus.outdated;

  @override
  Future<void> update({UpdateTrack? track}) async {
    updateCalled = true;
    await updateCompleter.future;
  }

  @override
  Future<Patch?> readCurrentPatch() async => null;

  @override
  Future<Patch?> readNextPatch() async => null;
}

void main() {
  testWidgets('UpdateDialog shows prompt and updates with progress and restart', (t) async {
    final fakeUpdater = FakeShorebirdUpdater();
    bool restarted = false;

    await t.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: UpdateDialog(
            updater: fakeUpdater,
            onRestart: () => restarted = true,
          ),
        ),
      ),
    );

    // Initial state: Title and Cập nhật ngay button
    expect(find.text('BẢN CẬP NHẬT MỚI'), findsOneWidget);
    expect(find.text('Cập nhật hệ thống JARVIS'), findsOneWidget);
    expect(find.byKey(const Key('update-download-btn')), findsOneWidget);
    expect(find.text('Cập nhật ngay'), findsOneWidget);

    // Click Cập nhật ngay
    await t.tap(find.byKey(const Key('update-download-btn')));
    await t.pump();

    // Now downloading: progress shows up
    expect(fakeUpdater.updateCalled, isTrue);
    expect(find.text('Đang cập nhật...'), findsOneWidget);
    expect(find.text('Đang tải bản vá...'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);

    // Complete the update
    fakeUpdater.updateCompleter.complete();
    await t.pump();
    await t.pump(const Duration(milliseconds: 100));

    // Completed state: 100% and restart button
    expect(find.text('100%'), findsOneWidget);
    expect(find.text('Đã tải hoàn tất'), findsOneWidget);
    expect(find.byKey(const Key('update-restart-btn')), findsOneWidget);
    expect(find.text('Khởi động lại ngay'), findsOneWidget);

    // Click restart
    await t.tap(find.byKey(const Key('update-restart-btn')));
    await t.pump();
    expect(restarted, isTrue);
  });
}
