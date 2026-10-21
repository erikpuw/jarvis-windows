/// settings/api.ts formatNumber: `toLocaleString("vi-VN")` - dots between thousands, a comma before decimals; "--" when missing.
String formatNumber(num? n) {
  if (n == null || n.isNaN) return '--';
  final neg = n < 0;
  final fixed = n.abs().toStringAsFixed(3);
  var whole = fixed.split('.').first;
  var frac = fixed.split('.').last.replaceFirst(RegExp(r'0+$'), '');
  whole = whole.replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => '.');
  return '${neg ? '-' : ''}$whole${frac.isEmpty ? '' : ',$frac'}';
}

/// settings/api.ts formatUptime: "1d 2h 3m", "1h 2m 3s", "2m 3s", "3s"; "--" when 0 or missing.
String formatUptime(num? seconds) {
  if (seconds == null || seconds <= 0) return '--';
  final d = seconds ~/ 86400;
  final h = (seconds % 86400) ~/ 3600;
  final m = (seconds % 3600) ~/ 60;
  final s = (seconds % 60).floor();
  if (d > 0) return '${d}d ${h}h ${m}m';
  if (h > 0) return '${h}h ${m}m ${s}s';
  if (m > 0) return '${m}m ${s}s';
  return '${s}s';
}

/// A number as JS prints it into a template string: `12.0` is "12", `12.5` stays "12.5" (the status probes send floats).
String jsNum(num? n) {
  if (n == null) return '0';
  return n == n.truncate() ? '${n.truncate()}' : '$n';
}
