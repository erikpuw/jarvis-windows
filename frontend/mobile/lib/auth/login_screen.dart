import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../theme/tokens.dart';
import 'auth_controller.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  var _mode = 'member'; // 'member' | 'admin'
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  void _submit() {
    final auth = context.read<AuthController>();
    if (_mode == 'admin') {
      auth.loginAdmin(_passwordController.text);
    } else {
      auth.loginMember(_usernameController.text);
    }
  }

  /// auth-gate.css .auth-input: #18181b, 1px white 12%, radius 10; focus: white 35%; placeholder #52525b.
  static InputDecoration _input(String hint) {
    OutlineInputBorder edge(Color c) => OutlineInputBorder(
      borderRadius: BorderRadius.circular(10),
      borderSide: BorderSide(color: c),
    );
    return InputDecoration(
      hintText: hint,
      hintStyle: const TextStyle(color: Color(0xFF52525B), fontSize: 14),
      filled: true,
      fillColor: JTokens.surface2,
      counterText: '',
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: edge(const Color(0x1FFFFFFF)),
      enabledBorder: edge(const Color(0x1FFFFFFF)),
      focusedBorder: edge(const Color(0x59FFFFFF)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();

    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Container(
                padding: const EdgeInsets.all(24),
                // auth-gate.css .auth-card (phone radius 18)
                decoration: BoxDecoration(
                  color: JTokens.surface,
                  borderRadius: BorderRadius.circular(18),
                  border: Border.all(color: JTokens.border),
                  boxShadow: const [
                    BoxShadow(
                      color: Color(0xB3000000),
                      blurRadius: 48,
                      spreadRadius: -12,
                      offset: Offset(0, 24),
                    ),
                  ],
                ),
                child: Form(
                  key: _formKey,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      // Header
                      const Text(
                        'Đăng nhập JARVIS',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 22,
                          fontWeight: FontWeight.bold,
                          color: Colors.white,
                          letterSpacing: -0.3,
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'Chọn loại tài khoản và nhập thông tin để truy cập.',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 13,
                          color: JTokens.muted,
                        ),
                      ),
                      const SizedBox(height: 20),

                      // Tabs
                      Container(
                        padding: const EdgeInsets.all(4),
                        decoration: BoxDecoration(
                          color: const Color(0xFF0D0D0F),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: const Color(0x0FFFFFFF)),
                        ),
                        child: Row(
                          children: [
                            Expanded(
                              child: _TabButton(
                                label: 'Thành viên',
                                active: _mode == 'member',
                                onTap: () => setState(() => _mode = 'member'),
                              ),
                            ),
                            Expanded(
                              child: _TabButton(
                                label: 'Quản trị',
                                active: _mode == 'admin',
                                onTap: () => setState(() => _mode = 'admin'),
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 20),

                      // Fields
                      if (_mode == 'member') ...[
                        const Text(
                          'Tên hiển thị',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w500,
                            color: JTokens.text,
                          ),
                        ),
                        const SizedBox(height: 8),
                        TextFormField(
                          controller: _usernameController,
                          maxLength: 40,
                          style: const TextStyle(color: Colors.white, fontSize: 14),
                          decoration: _input('Nhập tên của bạn...'),
                          onFieldSubmitted: (_) => _submit(),
                        ),
                      ] else ...[
                        const Text(
                          'Mật khẩu quản trị',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w500,
                            color: JTokens.text,
                          ),
                        ),
                        const SizedBox(height: 8),
                        TextFormField(
                          controller: _passwordController,
                          obscureText: true,
                          style: const TextStyle(color: Colors.white, fontSize: 14),
                          decoration: _input('Nhập mật khẩu quản trị...'),
                          onFieldSubmitted: (_) => _submit(),
                        ),
                      ],

                      // Error box
                      if (auth.error != null) ...[
                        const SizedBox(height: 14),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                          decoration: BoxDecoration(
                            color: const Color(0x14EF4444),
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(color: const Color(0x38EF4444)),
                          ),
                          child: Text(
                            auth.error == 'Failed to fetch'
                                ? 'Vui lòng kiểm tra lại kết nối mạng hoặc Tailscale.'
                                : auth.error!,
                            style: const TextStyle(color: Color(0xFFF87171), fontSize: 13),
                          ),
                        ),
                      ],

                      const SizedBox(height: 20),

                      // Submit button
                      ElevatedButton(
                        onPressed: auth.isLoading ? null : _submit,
                        // .auth-submit-btn: white pill, near-black text
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.white,
                          foregroundColor: const Color(0xFF09090B),
                          disabledBackgroundColor: const Color(0x99FFFFFF),
                          disabledForegroundColor: const Color(0xFF09090B),
                          padding: const EdgeInsets.symmetric(vertical: 14),
                          shape: const StadiumBorder(),
                          elevation: 0,
                        ),
                        child: Text(
                          auth.isLoading ? 'Đang xác thực...' : 'Tiếp tục',
                          style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                        ),
                      ),

                      const SizedBox(height: 18),

                      // Footnote
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const Icon(Icons.info_outline, size: 14, color: JTokens.textMuted),
                          const SizedBox(width: 6),
                          const Expanded(
                            child: Text(
                              'Dữ liệu và bộ nhớ hội thoại được cô lập riêng biệt.',
                              style: TextStyle(fontSize: 12, color: JTokens.textMuted),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _TabButton extends StatelessWidget {
  const _TabButton({
    required this.label,
    required this.active,
    required this.onTap,
  });

  final String label;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 8),
        decoration: BoxDecoration(
          color: active ? JTokens.surface3 : Colors.transparent,
          borderRadius: BorderRadius.circular(9),
          boxShadow: active
              ? const [BoxShadow(color: Color(0x33000000), blurRadius: 4, offset: Offset(0, 1))]
              : null,
        ),
        alignment: Alignment.center,
        child: Text(
          label,
          style: TextStyle(
            fontSize: 13,
            fontWeight: active ? FontWeight.w600 : FontWeight.normal,
            color: active ? Colors.white : JTokens.textMuted,
          ),
        ),
      ),
    );
  }
}
