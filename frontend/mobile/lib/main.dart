import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import 'auth/auth_controller.dart';
import 'auth/login_screen.dart';
import 'chat/chat_controller.dart';
import 'chat/chat_models.dart' show AudioEvent;
import 'chat/home_screen.dart';
import 'net/api_client.dart';
import 'net/jarvis_socket.dart';
import 'updater/update_dialog.dart';
import 'net/server_config.dart';
import 'settings/settings_shell.dart';
import 'theme/app_theme.dart';
import 'voice/audio_out.dart';

Future<void> main() async {
  var started = false;
  // A start-up error must show on screen: in a release build an uncaught one leaves a blank window and nothing to read.
  await runZonedGuarded(
    () async {
      WidgetsFlutterBinding.ensureInitialized();
      ErrorWidget.builder = (d) => StartupError(d.exceptionAsString());
      // phones are portrait only (style.css: landscape on a phone is covered)
      await SystemChrome.setPreferredOrientations([
        DeviceOrientation.portraitUp,
      ]);
      final cfg = ServerConfig();
      await cfg.load();
      final tts = await ChatController.loadTtsEnabled();
      started = true;
      runApp(JarvisApp(cfg: cfg, ttsEnabled: tts));
    },
    (e, s) {
      debugPrint('[startup] $e\n$s');
      if (!started) runApp(StartupError('$e\n$s'));
    },
  );
}

/// Plain text error page (no theme, no providers) so it renders even when the app itself cannot.
class StartupError extends StatelessWidget {
  const StartupError(this.message, {super.key});
  final String message;

  @override
  Widget build(BuildContext context) => Directionality(
    textDirection: TextDirection.ltr,
    child: ColoredBox(
      color: const Color(0xFF050508),
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Text(
            'JARVIS lỗi khởi động:\n\n$message',
            style: const TextStyle(color: Color(0xFFF87171), fontSize: 13),
          ),
        ),
      ),
    ),
  );
}

class JarvisApp extends StatefulWidget {
  const JarvisApp({
    super.key,
    required this.cfg,
    @visibleForTesting this.socket,
    @visibleForTesting this.audioOut,
    @visibleForTesting this.auth,
    this.ttsEnabled = true,
  });
  final ServerConfig cfg;

  /// The stored TTS switch (loaded before runApp).
  final bool ttsEnabled;

  /// Tests pass a fake socket.
  final JarvisSocket? socket;
  final AudioOut? audioOut;
  final AuthController? auth;

  @override
  State<JarvisApp> createState() => _JarvisAppState();
}

class _JarvisAppState extends State<JarvisApp> with WidgetsBindingObserver {
  final GlobalKey<NavigatorState> _navKey = GlobalKey<NavigatorState>();
  late final ApiClient _api = ApiClient(widget.cfg);
  late final AuthController _auth =
      widget.auth ??
      (() {
        final a = AuthController(_api);
        if (widget.socket != null) {
          // Fake socket in tests without explicit auth controller defaults to authenticated
          a.setAuthenticatedForTesting();
        }
        return a;
      })();
  late final JarvisSocket _socket =
      widget.socket ??
      JarvisSocket(
        widget.cfg,
        device: Platform.isIOS ? 'ios' : 'android',
        tokenProvider: () => _api.memoryToken,
        // the server refused the token (expired / revoked): back to the login screen, as the web does
        onRejected: () => _auth.logout(),
      );
  late final ChatController _chat = ChatController(
    _socket,
    _api,
    ttsEnabled: widget.ttsEnabled,
  );
  late final AudioOut _audioOut =
      widget.audioOut ?? AudioOut(onError: _chat.reportError);
  StreamSubscription<AudioEvent>? _audioSub;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _audioSub = _chat.audio.listen(_audioOut.handle);
    _audioOut.playing.addListener(_onPlaying);
    if (widget.auth == null && widget.socket == null) {
      _auth.init();
    }
    _lastIdentity = _identity;
    _auth.addListener(_onAuthChanged);
    if (_auth.isAuthenticated) {
      _socket.connect();
    }
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final nav = _navKey.currentContext;
      if (nav != null) UpdateChecker.check(nav);
    });
  }

  void _onPlaying() => _chat.setPlaying(_audioOut.playing.value);

  /// Who is signed in (user id + token), or null when signed out.
  String? get _identity => _auth.isAuthenticated
      ? '${_auth.currentUser!.id}|${_api.memoryToken}'
      : null;
  String? _lastIdentity;

  void _onAuthChanged() {
    // Only a login, logout or user switch resets the chat and session: the controller also notifies on loading/error
    // and when the same user's profile is refreshed (saving the User page), which must keep the conversation.
    final identity = _identity;
    if (identity == _lastIdentity) return;
    _lastIdentity = identity;
    if (_auth.isAuthenticated) {
      _chat.reset();
      _socket.forceReconnect(resetSession: true);
    } else {
      _chat.reset();
      _socket.disconnect();
    }
  }

  /// Coming back to the app: the OS may have cut the socket while it was away; reconnect now instead of waiting out the backoff.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      if (_auth.isAuthenticated) {
        _socket.reconnectNow();
      }
      final nav = _navKey.currentContext;
      if (nav != null) UpdateChecker.check(nav);
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _auth.removeListener(_onAuthChanged);
    _audioOut.playing.removeListener(_onPlaying);
    _audioSub?.cancel();
    _audioOut.dispose();
    _chat.dispose();
    _socket.dispose();
    _auth.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MultiProvider(
    providers: [
      ChangeNotifierProvider.value(value: widget.cfg),
      Provider.value(value: _api),
      Provider.value(value: _socket),
      ChangeNotifierProvider.value(value: _chat),
      ChangeNotifierProvider.value(value: _auth),
    ],
    child: MaterialApp(
      navigatorKey: _navKey,
      title: 'JARVIS',
      theme: buildAppTheme(),
      builder: (context, child) {
        final mq = MediaQuery.of(context);
        final shortest = mq.size.shortestSide;
        final longest = mq.size.longestSide;
        final ratio = longest / (shortest > 0 ? shortest : 1.0);
        // Legacy 16:9 non-bezel-less screens (e.g. Galaxy J7 Pro 411x731dp, iPhone 6/7/8):
        // Aspect ratio is ~1.77 (< 1.85) and height is cramped (< 780dp).
        final isLegacy16x9 = ratio < 1.85 || longest < 780;
        final isTablet = shortest >= 600;

        // /ui-ux-pro-max adaptive mobile typography matrix:
        // 1. Foldables / Tablets (shortest >= 600): +20% optical scale (~19.2px body)
        // 2. Large modern phablets (shortest >= 410, tall longest >= 820, ratio >= 1.9: Ultra, Pro Max): +12% (~18px body)
        // 3. Legacy 16:9 non-bezel-less (e.g. Galaxy J7 Pro): 0.96x (~15.4px), safe ceiling 1.20x prevents font explosion
        // 4. Ultra compact (shortest < 360, e.g. iPhone SE 1st gen 320dp, large display zoom): 0.90x (~14.4px), ceiling 1.15x
        // 5. Standard modern phones (360 <= shortest < 410, ratio >= 1.85: iPhone Pro, Galaxy base): 1.00x (16px 1:1 Web)
        final double screenFactor;
        final double maxScale;
        if (isTablet) {
          screenFactor = 1.20;
          maxScale = 1.45;
        } else if (shortest < 360) {
          // Ultra compact screens (e.g. iPhone SE 1st gen 320dp, extreme display zoom)
          screenFactor = 0.90;
          maxScale = 1.15;
        } else if (shortest >= 410 && !isLegacy16x9 && longest >= 820) {
          // True large phablets (Galaxy Ultra, iPhone Pro Max)
          screenFactor = 1.12;
          maxScale = 1.38;
        } else if (isLegacy16x9) {
          // Legacy 16:9 non-bezel-less phones (Galaxy J7 Pro, older Androids)
          screenFactor = 0.96;
          maxScale = 1.20;
        } else {
          // Standard modern bezel-less phones (iPhone Pro, Galaxy S base)
          screenFactor = 1.00;
          maxScale = 1.30;
        }

        final userScale = mq.textScaler.scale(1.0);
        final targetScaler = TextScaler.linear(userScale * screenFactor)
            .clamp(minScaleFactor: 0.85, maxScaleFactor: maxScale);
        return MediaQuery(
          data: mq.copyWith(
            textScaler: targetScaler,
          ),
          child: child!,
        );
      },
      home: Consumer<AuthController>(
        builder: (context, auth, _) {
          if (auth.isLoading && !auth.isAuthenticated) {
            return const Scaffold(
              backgroundColor: Colors.black,
              body: Center(
                child: CircularProgressIndicator(
                  color: Color(0xFF00D2FF),
                  strokeWidth: 2,
                ),
              ),
            );
          }
          if (!auth.isAuthenticated) {
            return const LoginScreen();
          }
          return HomeScreen(onCueEnd: _audioOut.reactivate);
        },
      ),
      routes: {
        '/settings': (_) => const SettingsShell(),
      },
    ),
  );
}
