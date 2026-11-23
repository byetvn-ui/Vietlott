"""Kiểm tra bộ bóc 'số người trúng giải'. Chạy: python3 tests/test_winners.py"""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import server as S


def block(kyve, date, rows):
    body = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % r for r in rows)
    return "<div>Kỳ vé #%s - %s</div><table>%s</table>" % (kyve, date, body)


R655 = [("Jackpot 1", "6 x", "0", "35.000.000.000"), ("Jackpot 2", "6 x", "2", "3.000.000.000"),
        ("Giải nhất", "6 x", "30", "40.000.000"), ("Giải nhì", "6 x", "900", "500.000"),
        ("Giải ba", "6 x", "15.000", "50.000")]
R535 = [("Độc đắc", "6 x", "0", "6.000.000.000"), ("Giải nhất", "6 x", "1", "10.000.000"),
        ("Giải nhì", "6 x", "5", "5.000.000"), ("Giải ba", "6 x", "40", "500.000"),
        ("Giải tư", "6 x", "100", "100.000"), ("Giải năm", "6 x", "2.000", "30.000"),
        ("Giải KK", "6 x", "10.000", "10.000")]


class T(unittest.TestCase):
    def test_655(self):
        r = S.parse_winners(block("01234", "21/11/2026", R655), "655")
        self.assertEqual(list(r), ["2026-11-21"])
        p = {x["p"]: x for x in r["2026-11-21"]["prizes"]}
        self.assertEqual(p["Jackpot 2"]["c"], 2)
        self.assertEqual(p["Giải ba"]["c"], 15000)
        self.assertEqual(p["Giải ba"]["v"], 50000)

    def test_535_key_has_hour(self):
        r = S.parse_winners(block("00077", "21/11/2026 - 21H", R535), "535")
        self.assertIn("2026-11-21-21", r)

    def test_too_few_prizes_ignored(self):
        self.assertEqual(S.parse_winners(block("1", "21/11/2026", R655[:2]), "655"), {})

    def test_rows_merge(self):
        wins = {"655": S.parse_winners(block("01234", "21/11/2026", R655), "655")}
        w = S.winners_for_row("655", {"d": "2026-11-21"}, wins)
        self.assertEqual(w["j2"], [2, 3000000000])
        self.assertEqual(w["m3"], [15000, 50000])
        self.assertIsNone(S.winners_for_row("655", {"d": "2026-11-22"}, wins))

    def test_legacy_entry(self):
        wins = {"645": {"2026-11-19": {"j1": [0, 1], "m5": [3, 2]}}}
        self.assertEqual(S.winners_for_row("645", {"d": "2026-11-19"}, wins)["m5"], [3, 2])


if __name__ == "__main__":
    unittest.main()
