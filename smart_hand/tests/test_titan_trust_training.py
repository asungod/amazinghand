import unittest

import numpy as np

try:
    from smart_hand.titan_ai.train_titan_trust import (
        normalize_features,
        train_model,
    )
except ModuleNotFoundError:
    # run_all_checks.ps1 executes unittest discovery from smart_hand/.
    from titan_ai.train_titan_trust import normalize_features, train_model


class TitanTrustTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.metrics = train_model(samples_per_class=900)

    def test_synthetic_holdout_is_reproducible_and_separable(self):
        self.assertGreaterEqual(
            self.metrics["accuracy_synthetic_holdout"], 0.90
        )
        self.assertFalse(self.metrics["field_accuracy_validated"])
        self.assertFalse(self.metrics["hardware_inference_validated"])
        self.assertFalse(self.metrics["controls_servo"])

    def test_representative_states(self):
        samples = np.asarray(
            [
                [90, 4, 3, 500, 20, 0, 0, 0, 100, 98],
                [68, 22, 18, 650, 140, 1, 0, 1, 500, 70],
                [40, 55, 50, 1500, 500, 6, 5, 6, 1200, 25],
            ],
            dtype=np.float64,
        )
        predicted = self.model.predict(normalize_features(samples)).tolist()
        self.assertEqual(predicted, [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
