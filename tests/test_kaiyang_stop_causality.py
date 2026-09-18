"""Run the actual Rust holding-extreme blocks on adversarial entry-bar OHLC.

No market database or Tauri runtime is required; rustc compiles the source blocks.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


class KaiyangStopCausality(unittest.TestCase):
    def test_current_bar_cannot_raise_its_own_protective_stop(self):
        source = (Path(__file__).resolve().parents[1] / 'desktop/src-tauri/src/backtest.rs').read_text()
        strategy = source.split('"adaptive_regime_evolution" => {', 1)[1].split('// 💎', 1)[0]
        blocks = []
        for side in ('highest', 'lowest'):
            # Include any local bounds calculation preceding the actual fold.
            pattern = rf'(?:let prev_idx =[^;]+;\s*)?let {side}_hold =[^;]+;'
            match = re.search(pattern, strategy)
            self.assertIsNotNone(match, f'{side} holding-extreme calculation missing')
            blocks.append(match.group())
        program = '''fn main() {
            let highs = vec![150.0, 103.0, 110.0];
            let lows = vec![50.0, 99.5, 90.0];
            let buy_price: f64 = 100.0;
            for (i, bars_held, expected_high, expected_low) in [
                (1_usize, 0_usize, 100.0, 100.0),
                (2_usize, 1_usize, 103.0, 99.5),
            ] {
        ''' + '\n'.join(blocks) + '''
                assert_eq!(highest_hold, expected_high, "current/pre-entry high leaked");
                assert_eq!(lowest_hold, expected_low, "current/pre-entry low leaked");
            }
        }'''
        with tempfile.TemporaryDirectory() as directory:
            rust_file = Path(directory) / 'check.rs'
            rust_file.write_text(program)
            executable = Path(directory) / 'check'
            subprocess.run(['rustc', str(rust_file), '-o', str(executable)], check=True, capture_output=True, text=True)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
