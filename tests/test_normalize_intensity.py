# Copyright 2020 - 2021 MONAI Consortium
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest

import numpy as np
import torch
from parameterized import parameterized

from monai.transforms import NormalizeIntensity
from tests.utils import TEST_NDARRAYS, NumpyImageTestCase2D, assert_allclose

TESTS = []
for p in TEST_NDARRAYS:
    TESTS.append([p, {"nonzero": True}, np.array([0.0, 3.0, 0.0, 4.0]), np.array([0.0, -1.0, 0.0, 1.0])])
    for q in TEST_NDARRAYS:
        for u in TEST_NDARRAYS:
            TESTS.append(
                [
                    p,
                    {
                        "subtrahend": q(np.array([3.5, 3.5, 3.5, 3.5])),
                        "divisor": u(np.array([0.5, 0.5, 0.5, 0.5])),
                        "nonzero": True,
                    },
                    np.array([0.0, 3.0, 0.0, 4.0]),
                    np.array([0.0, -1.0, 0.0, 1.0]),
                ]
            )
    TESTS.append([p, {"nonzero": True}, np.array([0.0, 0.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.0, 0.0])])
    TESTS.append([p, {"nonzero": False}, np.array([0.0, 0.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.0, 0.0])])
    TESTS.append([p, {"nonzero": False}, np.array([1, 1, 1, 1]), np.array([0.0, 0.0, 0.0, 0.0])])
    TESTS.append(
        [
            p,
            {"nonzero": False, "channel_wise": True, "subtrahend": [1, 2, 3]},
            np.ones((3, 2, 2)),
            np.array([[[0.0, 0.0], [0.0, 0.0]], [[-1.0, -1.0], [-1.0, -1.0]], [[-2.0, -2.0], [-2.0, -2.0]]]),
        ]
    )
    TESTS.append(
        [
            p,
            {"nonzero": True, "channel_wise": True, "subtrahend": [1, 2, 3], "divisor": [0, 0, 2]},
            np.ones((3, 2, 2)),
            np.array([[[0.0, 0.0], [0.0, 0.0]], [[-1.0, -1.0], [-1.0, -1.0]], [[-1.0, -1.0], [-1.0, -1.0]]]),
        ]
    )
    TESTS.append(
        [
            p,
            {"nonzero": True, "channel_wise": False, "subtrahend": 2, "divisor": 0},
            np.ones((3, 2, 2)),
            np.ones((3, 2, 2)) * -1.0,
        ]
    )
    TESTS.append(
        [
            p,
            {"nonzero": True, "channel_wise": False, "subtrahend": np.ones((3, 2, 2)) * 0.5, "divisor": 0},
            np.ones((3, 2, 2)),
            np.ones((3, 2, 2)) * 0.5,
        ]
    )
    TESTS.append(
        [
            p,
            {"nonzero": True, "channel_wise": True, "subtrahend": np.ones((3, 2, 2)) * 0.5, "divisor": [0, 1, 0]},
            np.ones((3, 2, 2)),
            np.ones((3, 2, 2)) * 0.5,
        ]
    )


class TestNormalizeIntensity(NumpyImageTestCase2D):
    @parameterized.expand([[p] for p in TEST_NDARRAYS])
    def test_default(self, im_type):
        im = im_type(self.imt.copy())
        normalizer = NormalizeIntensity()
        normalized = normalizer(im)
        self.assertEqual(type(im), type(normalized))
        if isinstance(normalized, torch.Tensor):
            self.assertEqual(im.device, normalized.device)
        self.assertTrue(normalized.dtype in (np.float32, torch.float32))
        expected = (self.imt - np.mean(self.imt)) / np.std(self.imt)
        assert_allclose(expected, normalized, rtol=1e-3)

    @parameterized.expand(TESTS)
    def test_nonzero(self, in_type, input_param, input_data, expected_data):
        normalizer = NormalizeIntensity(**input_param)
        im = in_type(input_data)
        normalized = normalizer(im)
        self.assertEqual(type(im), type(normalized))
        if isinstance(normalized, torch.Tensor):
            self.assertEqual(im.device, normalized.device)
        assert_allclose(expected_data, normalized)

    @parameterized.expand([[p] for p in TEST_NDARRAYS])
    def test_channel_wise(self, im_type):
        normalizer = NormalizeIntensity(nonzero=True, channel_wise=True)
        input_data = im_type(np.array([[0.0, 3.0, 0.0, 4.0], [0.0, 4.0, 0.0, 5.0]]))
        expected = np.array([[0.0, -1.0, 0.0, 1.0], [0.0, -1.0, 0.0, 1.0]])
        normalized = normalizer(input_data)
        self.assertEqual(type(input_data), type(normalized))
        if isinstance(normalized, torch.Tensor):
            self.assertEqual(input_data.device, normalized.device)
        assert_allclose(expected, normalized)

    @parameterized.expand([[p] for p in TEST_NDARRAYS])
    def test_value_errors(self, im_type):
        input_data = im_type(np.array([[0.0, 3.0, 0.0, 4.0], [0.0, 4.0, 0.0, 5.0]]))
        normalizer = NormalizeIntensity(nonzero=True, channel_wise=True, subtrahend=[1])
        with self.assertRaises(ValueError):
            normalizer(input_data)
        normalizer = NormalizeIntensity(nonzero=True, channel_wise=True, subtrahend=[1, 2], divisor=[1])
        with self.assertRaises(ValueError):
            normalizer(input_data)


if __name__ == "__main__":
    unittest.main()
