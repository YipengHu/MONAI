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
from parameterized import parameterized

from monai.transforms import RandFlip
from tests.utils import TEST_NDARRAYS, NumpyImageTestCase2D, assert_allclose

INVALID_CASES = [("wrong_axis", ["s", 1], TypeError), ("not_numbers", "s", TypeError)]

VALID_CASES = [("no_axis", None), ("one_axis", 1), ("many_axis", [0, 1])]


class TestRandFlip(NumpyImageTestCase2D):
    @parameterized.expand(INVALID_CASES)
    def test_invalid_inputs(self, _, spatial_axis, raises):
        with self.assertRaises(raises):
            flip = RandFlip(prob=1.0, spatial_axis=spatial_axis)
            flip(self.imt[0])

    @parameterized.expand(VALID_CASES)
    def test_correct_results(self, _, spatial_axis):
        for p in TEST_NDARRAYS:
            im = p(self.imt[0])
            flip = RandFlip(prob=1.0, spatial_axis=spatial_axis)
            expected = []
            for channel in self.imt[0]:
                expected.append(np.flip(channel, spatial_axis))
            expected = np.stack(expected)
            result = flip(im)
            assert_allclose(expected, result)


if __name__ == "__main__":
    unittest.main()
