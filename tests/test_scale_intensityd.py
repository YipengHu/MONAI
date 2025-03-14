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

from monai.transforms import ScaleIntensityd
from tests.utils import TEST_NDARRAYS, NumpyImageTestCase2D, assert_allclose


class TestScaleIntensityd(NumpyImageTestCase2D):
    def test_range_scale(self):
        for p in TEST_NDARRAYS:
            key = "img"
            scaler = ScaleIntensityd(keys=[key], minv=1.0, maxv=2.0)
            result = scaler({key: p(self.imt)})
            mina = np.min(self.imt)
            maxa = np.max(self.imt)
            norm = (self.imt - mina) / (maxa - mina)
            expected = (norm * (2.0 - 1.0)) + 1.0
            assert_allclose(result[key], expected)

    def test_factor_scale(self):
        for p in TEST_NDARRAYS:
            key = "img"
            scaler = ScaleIntensityd(keys=[key], minv=None, maxv=None, factor=0.1)
            result = scaler({key: p(self.imt)})
            expected = (self.imt * (1 + 0.1)).astype(np.float32)
            assert_allclose(result[key], expected)


if __name__ == "__main__":
    unittest.main()
