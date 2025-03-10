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

from monai.transforms import RandAxisFlipd
from tests.utils import TEST_NDARRAYS, NumpyImageTestCase3D, assert_allclose


class TestRandAxisFlip(NumpyImageTestCase3D):
    def test_correct_results(self):
        for p in TEST_NDARRAYS:
            flip = RandAxisFlipd(keys="img", prob=1.0)
            result = flip({"img": p(self.imt[0])})["img"]

            expected = []
            for channel in self.imt[0]:
                expected.append(np.flip(channel, flip._axis))
            assert_allclose(np.stack(expected), result)


if __name__ == "__main__":
    unittest.main()
