import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shorebird_code_push/shorebird_code_push.dart';

import '../theme/tokens.dart';

/// Vercel / Linear-inspired mandatory update dialog.
/// Displays an update prompt with a percentage progress bar and a restart action.
class UpdateDialog extends StatefulWidget {
  const UpdateDialog({
    super.key,
    this.updater,
    this.onRestart,
  });

  /// Injected for testing. Defaults to ShorebirdUpdater().
  final ShorebirdUpdater? updater;

  /// Injected for testing. Defaults to Restart.restartApp().
  final VoidCallback? onRestart;

  @override
  State<UpdateDialog> createState() => _UpdateDialogState();
}

class _UpdateDialogState extends State<UpdateDialog> {
  late final ShorebirdUpdater _updater = widget.updater ?? ShorebirdUpdater();
  bool _downloading = false;
  bool _complete = false;
  double _progress = 0;
  Timer? _ticker;
  String? _error;

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  void _startUpdate() async {
    setState(() {
      _downloading = true;
      _error = null;
      _progress = 12;
    });

    // Smoothly animate progress counter to 90% while patch downloads
    _ticker = Timer.periodic(const Duration(milliseconds: 60), (t) {
      if (!mounted) return;
      setState(() {
        if (_progress < 90) {
          _progress += (90 - _progress) * 0.08 + 0.5;
          if (_progress > 90) _progress = 90;
        }
      });
    });

    try {
      await _updater.update();
      _ticker?.cancel();
      if (!mounted) return;
      setState(() {
        _progress = 100;
        _downloading = false;
        _complete = true;
      });
    } catch (e) {
      _ticker?.cancel();
      if (!mounted) return;
      setState(() {
        _downloading = false;
        _error = 'Không thể tải bản cập nhật: $e';
      });
    }
  }

  void _handleRestart() {
    if (widget.onRestart != null) {
      widget.onRestart!();
      return;
    }
    // Cleanly terminate the app process so next launch loads the patch
    SystemNavigator.pop();
    Future<void>.delayed(const Duration(milliseconds: 150), () {
      exit(0);
    });
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      child: Dialog(
        backgroundColor: Colors.transparent,
        elevation: 0,
        insetPadding: const EdgeInsets.symmetric(horizontal: 20),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 380),
          child: Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: JTokens.surface, // #0D1117 Linear surface
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: JTokens.border), // 1px hairline border
              boxShadow: const [
                BoxShadow(
                  color: Color(0x99000000),
                  blurRadius: 32,
                  offset: Offset(0, 12),
                ),
              ],
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Top Tag Badge
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: JTokens.accentSoft,
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(color: const Color(0x330EA5E9)),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 6,
                        height: 6,
                        decoration: const BoxDecoration(
                          color: JTokens.accent,
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: 6),
                      const Text(
                        'BẢN CẬP NHẬT MỚI',
                        style: TextStyle(
                          color: JTokens.accent,
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 0.5,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),

                // Title
                const Text(
                  'Cập nhật hệ thống JARVIS',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                    color: Colors.white,
                    letterSpacing: -0.2,
                  ),
                ),
                const SizedBox(height: 8),

                // Description
                const Text(
                  'Hệ thống đã có bản vá sửa lỗi mới qua mạng OTA. Vui lòng cập nhật để tiếp tục sử dụng ứng dụng.',
                  style: TextStyle(
                    fontSize: 13,
                    height: 1.5,
                    color: JTokens.muted,
                  ),
                ),
                const SizedBox(height: 20),

                // Progress Bar (when downloading or complete)
                if (_downloading || _complete) ...[
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        _complete ? 'Đã tải hoàn tất' : 'Đang tải bản vá...',
                        style: const TextStyle(fontSize: 12, color: JTokens.muted),
                      ),
                      Text(
                        '${_progress.toInt()}%',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: _complete ? JTokens.ok : JTokens.text,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(2),
                    child: LinearProgressIndicator(
                      value: _progress / 100.0,
                      minHeight: 4,
                      backgroundColor: const Color(0x1AFFFFFF),
                      valueColor: AlwaysStoppedAnimation<Color>(
                        _complete ? JTokens.ok : JTokens.accent,
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),
                ],

                // Error text if any
                if (_error != null) ...[
                  Text(
                    _error!,
                    style: const TextStyle(color: JTokens.err, fontSize: 12),
                  ),
                  const SizedBox(height: 14),
                ],

                // Action Button (no cancel/skip button)
                SizedBox(
                  width: double.infinity,
                  height: 42,
                  child: _complete
                      ? TextButton(
                          key: const Key('update-restart-btn'),
                          onPressed: _handleRestart,
                          style: TextButton.styleFrom(
                            backgroundColor: JTokens.ok,
                            foregroundColor: const Color(0xFF050508),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(8),
                            ),
                          ),
                          child: const Text(
                            'Khởi động lại ngay',
                            style: TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        )
                      : TextButton(
                          key: const Key('update-download-btn'),
                          style: TextButton.styleFrom(
                            backgroundColor: JTokens.accent,
                            foregroundColor: Colors.white,
                            disabledBackgroundColor: JTokens.accent.withValues(alpha: 0.5),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(8),
                            ),
                          ),
                          onPressed: _downloading ? null : _startUpdate,
                          child: Text(
                            _downloading ? 'Đang cập nhật...' : 'Cập nhật ngay',
                            style: const TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Checks and displays the update dialog on startup or resume.
class UpdateChecker {
  static final ShorebirdUpdater _updater = ShorebirdUpdater();
  static bool _isChecking = false;

  static Future<void> check(BuildContext context) async {
    if (_isChecking) return;
    _isChecking = true;

    try {
      if (!_updater.isAvailable) return;
      final status = await _updater.checkForUpdate();
      if (status == UpdateStatus.outdated && context.mounted) {
        await showDialog<void>(
          context: context,
          barrierDismissible: false,
          builder: (_) => const UpdateDialog(),
        );
      }
    } catch (e) {
      debugPrint('[update_checker] $e');
    } finally {
      _isChecking = false;
    }
  }
}
