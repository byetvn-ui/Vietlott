"""Kiểm tra cấu trúc và tính hợp lệ của ba bộ dữ liệu ODS."""
import unittest

import server


class ODSIntegrityTests(unittest.TestCase):
    def test_all_games_have_rows_and_unique_draw_keys(self):
        for game in server.GAMES:
            with self.subTest(game=game):
                rows = server.read_ods(game)
                self.assertTrue(rows)
                keys = [server.rowkey(game, row) for row in rows]
                self.assertEqual(len(keys), len(set(keys)), "trùng mã kỳ quay")
                self.assertEqual(keys, sorted(keys, reverse=True), "dữ liệu phải mới nhất ở đầu")

    def test_main_numbers_are_unique_and_in_range(self):
        for game, cfg in server.GAMES.items():
            for row in server.read_ods(game):
                with self.subTest(game=game, draw=server.rowkey(game, row)):
                    self.assertEqual(len(row["n"]), cfg["main"])
                    self.assertEqual(len(set(row["n"])), cfg["main"])
                    self.assertTrue(all(1 <= n <= cfg["maxn"] for n in row["n"]))

    def test_bonus_number_rules(self):
        for game, cfg in server.GAMES.items():
            if not cfg["bonus"]:
                continue
            for row in server.read_ods(game):
                with self.subTest(game=game, draw=server.rowkey(game, row)):
                    self.assertIsNotNone(row["b"])
                    self.assertGreaterEqual(row["b"], 1)
                    self.assertLessEqual(row["b"], cfg.get("bmax", cfg["maxn"]))
                    # Power 6/55 lấy số phụ trong 49 số còn lại; Lotto 5/35
                    # có số đặc biệt 1–12 và theo luật có thể trùng số chính.
                    if game == "655":
                        self.assertNotIn(row["b"], row["n"])

    def test_lotto_535_has_valid_draw_hours(self):
        for row in server.read_ods("535"):
            self.assertIn(row["h"], (13, 21))


if __name__ == "__main__":
    unittest.main()
