import importlib.util
import unittest


class FeaturePolicyTests(unittest.TestCase):
    def policy(self):
        self.assertIsNotNone(importlib.util.find_spec('feature_policy'), 'Pickup policy is not implemented')
        import feature_policy
        return feature_policy

    def test_marker_coordinates_follow_slot_and_window_dimensions(self):
        policy = self.policy()
        grid = [.1, .2, .5, .6]
        self.assertEqual(policy.slot_rect(0, grid, 1000, 600), (100, 120, 150, 180))
        self.assertEqual(policy.slot_rect(39, grid, 1000, 600), (550, 300, 600, 360))
        self.assertEqual(policy.slot_rect(39, grid, 2000, 1200), (1100, 600, 1200, 720))
        self.assertIsNone(policy.slot_rect(60, grid, 1000, 600))
        self.assertIsNone(policy.slot_rect(1, None, 1000, 600))


if __name__ == '__main__':
    unittest.main()
