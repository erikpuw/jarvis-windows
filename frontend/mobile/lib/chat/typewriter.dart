/// main.ts typeStep: how many characters of the streamed text the reader has been shown. One step turns elapsed time into
/// characters (the fractional rest is carried over) at [baseCps], faster when the backlog is large so it never falls far behind
/// the model: the backlog is drained in about [catchUpS] seconds.
class Typewriter {
  static const baseCps =
      60.0; // STREAM_BASE_CPS: characters per second when keeping up
  static const catchUpS = 0.3; // STREAM_CATCHUP_S
  static const holdMs = 200; // STREAM_TEXT_AFTER_LOADER_MS: the loader balls shrink first, so they do not cover the first letter
  static const maxDt = 0.1; // a stalled frame counts as 100 ms

  int shown = 0;
  double _acc = 0;

  /// Advances by [dt] seconds towards [target] characters and returns the new count.
  int step(double dt, int target) {
    final backlog = target - shown;
    if (backlog <= 0) {
      _acc = 0;
      return shown;
    }
    _acc +=
        (baseCps > backlog / catchUpS ? baseCps : backlog / catchUpS) *
        (dt > maxDt ? maxDt : dt);
    final take = _acc.floor() > backlog ? backlog : _acc.floor();
    if (take > 0) {
      _acc -= take;
      shown += take;
    }
    return shown;
  }

  /// The final render (stream_end, a cancelled turn): everything at once.
  void finish(int target) {
    shown = target;
    _acc = 0;
  }
}

/// Newlines at the very end of the streamed text are not shown yet: they would open blank lines under the last line before
/// the next paragraph has a single letter (main.ts withoutTrailingNewlines).
String withoutTrailingNewlines(String s) => s.replaceFirst(RegExp(r'\n+$'), '');
