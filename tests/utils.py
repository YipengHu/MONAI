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

import copy
import datetime
import functools
import importlib
import os
import queue
import sys
import tempfile
import time
import traceback
import unittest
import warnings
from functools import partial
from io import BytesIO
from subprocess import PIPE, Popen
from typing import Callable, Optional, Tuple
from urllib.error import ContentTooShortError, HTTPError, URLError

import numpy as np
import torch
import torch.distributed as dist

from monai.config import NdarrayTensor
from monai.config.deviceconfig import USE_COMPILED
from monai.config.type_definitions import NdarrayOrTensor
from monai.data import create_test_image_2d, create_test_image_3d
from monai.utils import ensure_tuple, optional_import, set_determinism
from monai.utils.module import version_leq

nib, _ = optional_import("nibabel")

quick_test_var = "QUICKTEST"


def clone(data: NdarrayTensor) -> NdarrayTensor:
    """
    Clone data independent of type.

    Args:
        data (NdarrayTensor): This can be a Pytorch Tensor or numpy array.

    Returns:
        Any: Cloned data object
    """
    return copy.deepcopy(data)


def assert_allclose(a: NdarrayOrTensor, b: NdarrayOrTensor, *args, **kwargs):
    """
    Assert that all values of two data objects are close.

    Args:
        a (NdarrayOrTensor): Pytorch Tensor or numpy array for comparison
        b (NdarrayOrTensor): Pytorch Tensor or numpy array to compare against
    """
    a = a.cpu() if isinstance(a, torch.Tensor) else a
    b = b.cpu() if isinstance(b, torch.Tensor) else b
    np.testing.assert_allclose(a, b, *args, **kwargs)


def test_pretrained_networks(network, input_param, device):
    try:
        net = network(**input_param).to(device)
    except (URLError, HTTPError, ContentTooShortError) as e:
        raise unittest.SkipTest(e)
    return net


def test_is_quick():
    return os.environ.get(quick_test_var, "").lower() == "true"


def skip_if_quick(obj):
    """
    Skip the unit tests if environment variable `quick_test_var=true`.
    For example, the user can skip the relevant tests by setting ``export QUICKTEST=true``.
    """
    is_quick = test_is_quick()

    return unittest.skipIf(is_quick, "Skipping slow tests")(obj)


class SkipIfNoModule:
    """Decorator to be used if test should be skipped
    when optional module is not present."""

    def __init__(self, module_name):
        self.module_name = module_name
        self.module_missing = not optional_import(self.module_name)[1]

    def __call__(self, obj):
        return unittest.skipIf(self.module_missing, f"optional module not present: {self.module_name}")(obj)


class SkipIfModule:
    """Decorator to be used if test should be skipped
    when optional module is present."""

    def __init__(self, module_name):
        self.module_name = module_name
        self.module_avail = optional_import(self.module_name)[1]

    def __call__(self, obj):
        return unittest.skipIf(self.module_avail, f"Skipping because optional module present: {self.module_name}")(obj)


def skip_if_no_cpp_extension(obj):
    """
    Skip the unit tests if the cpp extension is not available
    """
    return unittest.skipUnless(USE_COMPILED, "Skipping cpp extension tests")(obj)


def skip_if_no_cuda(obj):
    """
    Skip the unit tests if torch.cuda.is_available is False
    """
    return unittest.skipUnless(torch.cuda.is_available(), "Skipping CUDA-based tests")(obj)


def skip_if_windows(obj):
    """
    Skip the unit tests if platform is win32
    """
    return unittest.skipIf(sys.platform == "win32", "Skipping tests on Windows")(obj)


class SkipIfBeforePyTorchVersion:
    """Decorator to be used if test should be skipped
    with PyTorch versions older than that given."""

    def __init__(self, pytorch_version_tuple):
        self.min_version = pytorch_version_tuple
        test_ver = ".".join(map(str, self.min_version))
        self.version_too_old = torch.__version__ != test_ver and version_leq(torch.__version__, test_ver)

    def __call__(self, obj):
        return unittest.skipIf(
            self.version_too_old, f"Skipping tests that fail on PyTorch versions before: {self.min_version}"
        )(obj)


class SkipIfAtLeastPyTorchVersion:
    """Decorator to be used if test should be skipped
    with PyTorch versions newer than or equal to that given."""

    def __init__(self, pytorch_version_tuple):
        self.max_version = pytorch_version_tuple
        test_ver = ".".join(map(str, self.max_version))
        self.version_too_new = version_leq(test_ver, torch.__version__)

    def __call__(self, obj):
        return unittest.skipIf(
            self.version_too_new, f"Skipping tests that fail on PyTorch versions at least: {self.max_version}"
        )(obj)


def make_nifti_image(array, affine=None):
    """
    Create a temporary nifti image on the disk and return the image name.
    User is responsible for deleting the temporary file when done with it.
    """
    if affine is None:
        affine = np.eye(4)
    test_image = nib.Nifti1Image(array, affine)

    temp_f, image_name = tempfile.mkstemp(suffix=".nii.gz")
    nib.save(test_image, image_name)
    os.close(temp_f)
    return image_name


def make_rand_affine(ndim: int = 3, random_state: Optional[np.random.RandomState] = None):
    """Create random affine transformation (with values == -1, 0 or 1)."""
    rs = np.random.random.__self__ if random_state is None else random_state  # type: ignore

    vals = rs.choice([-1, 1], size=ndim)
    positions = rs.choice(range(ndim), size=ndim, replace=False)
    af = np.zeros([ndim + 1, ndim + 1])
    af[ndim, ndim] = 1
    for i, (v, p) in enumerate(zip(vals, positions)):
        af[i, p] = v
    return af


class DistTestCase(unittest.TestCase):
    """
    testcase without _outcome, so that it's picklable.
    """

    def __getstate__(self):
        self_dict = self.__dict__.copy()
        del self_dict["_outcome"]
        return self_dict

    def __setstate__(self, data_dict):
        self.__dict__.update(data_dict)


class DistCall:
    """
    Wrap a test case so that it will run in multiple processes on a single machine using `torch.distributed`.
    It is designed to be used with `tests.utils.DistTestCase`.

    Usage:

        decorate a unittest testcase method with a `DistCall` instance::

            class MyTests(unittest.TestCase):
                @DistCall(nnodes=1, nproc_per_node=3, master_addr="localhost")
                def test_compute(self):
                ...

        the `test_compute` method should trigger different worker logic according to `dist.get_rank()`.

    Multi-node tests require a fixed master_addr:master_port, with node_rank set manually in multiple scripts
    or from environment variable "NODE_RANK".
    """

    def __init__(
        self,
        nnodes: int = 1,
        nproc_per_node: int = 1,
        master_addr: str = "localhost",
        master_port: Optional[int] = None,
        node_rank: Optional[int] = None,
        timeout=60,
        init_method=None,
        backend: Optional[str] = None,
        daemon: Optional[bool] = None,
        method: Optional[str] = "spawn",
        verbose: bool = False,
    ):
        """

        Args:
            nnodes: The number of nodes to use for distributed call.
            nproc_per_node: The number of processes to call on each node.
            master_addr: Master node (rank 0)'s address, should be either the IP address or the hostname of node 0.
            master_port: Master node (rank 0)'s free port.
            node_rank: The rank of the node, this could be set via environment variable "NODE_RANK".
            timeout: Timeout for operations executed against the process group.
            init_method: URL specifying how to initialize the process group.
                Default is "env://" or "file:///d:/a_temp" (windows) if unspecified.
            backend: The backend to use. Depending on build-time configurations,
                valid values include ``mpi``, ``gloo``, and ``nccl``.
            daemon: the process’s daemon flag.
                When daemon=None, the initial value is inherited from the creating process.
            method: set the method which should be used to start a child process.
                method can be 'fork', 'spawn' or 'forkserver'.
            verbose: whether to print NCCL debug info.
        """
        self.nnodes = int(nnodes)
        self.nproc_per_node = int(nproc_per_node)
        if self.nnodes < 1 or self.nproc_per_node < 1:
            raise ValueError(
                f"number of nodes and processes per node must be >= 1, got {self.nnodes} and {self.nproc_per_node}"
            )
        self.node_rank = int(os.environ.get("NODE_RANK", "0")) if node_rank is None else int(node_rank)
        self.master_addr = master_addr
        self.master_port = np.random.randint(10000, 20000) if master_port is None else master_port

        if backend is None:
            self.backend = "nccl" if torch.distributed.is_nccl_available() and torch.cuda.is_available() else "gloo"
        else:
            self.backend = backend
        self.init_method = init_method
        if self.init_method is None and sys.platform == "win32":
            self.init_method = "file:///d:/a_temp"
        self.timeout = datetime.timedelta(0, timeout)
        self.daemon = daemon
        self.method = method
        self.verbose = verbose

    def run_process(self, func, local_rank, args, kwargs, results):
        _env = os.environ.copy()  # keep the original system env
        try:
            os.environ["MASTER_ADDR"] = self.master_addr
            os.environ["MASTER_PORT"] = str(self.master_port)
            os.environ["LOCAL_RANK"] = str(local_rank)
            if self.verbose:
                os.environ["NCCL_DEBUG"] = "INFO"
                os.environ["NCCL_DEBUG_SUBSYS"] = "ALL"
            os.environ["NCCL_BLOCKING_WAIT"] = str(1)
            os.environ["OMP_NUM_THREADS"] = str(1)
            os.environ["WORLD_SIZE"] = str(self.nproc_per_node * self.nnodes)
            os.environ["RANK"] = str(self.nproc_per_node * self.node_rank + local_rank)

            if torch.cuda.is_available():
                os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
                torch.cuda.set_device(int(local_rank))

            dist.init_process_group(
                backend=self.backend,
                init_method=self.init_method,
                timeout=self.timeout,
                world_size=int(os.environ["WORLD_SIZE"]),
                rank=int(os.environ["RANK"]),
            )
            func(*args, **kwargs)
            # the primary node lives longer to
            # avoid _store_based_barrier, RuntimeError: Broken pipe
            # as the TCP store daemon is on the rank 0
            if int(os.environ["RANK"]) == 0:
                time.sleep(0.1)
            results.put(True)
        except Exception as e:
            results.put(False)
            raise e
        finally:
            os.environ.clear()
            os.environ.update(_env)
            try:
                dist.destroy_process_group()
            except RuntimeError as e:
                warnings.warn(f"While closing process group: {e}.")

    def __call__(self, obj):
        if not torch.distributed.is_available():
            return unittest.skipIf(True, "Skipping distributed tests because not torch.distributed.is_available()")(obj)
        if torch.cuda.is_available() and torch.cuda.device_count() < self.nproc_per_node:
            return unittest.skipIf(
                True,
                f"Skipping distributed tests because it requires {self.nnodes} devices "
                f"but got {torch.cuda.device_count()}",
            )(obj)

        _cache_original_func(obj)

        @functools.wraps(obj)
        def _wrapper(*args, **kwargs):
            tmp = torch.multiprocessing.get_context(self.method)
            processes = []
            results = tmp.Queue()
            func = _call_original_func
            args = [obj.__name__, obj.__module__] + list(args)
            for proc_rank in range(self.nproc_per_node):
                p = tmp.Process(
                    target=self.run_process, args=(func, proc_rank, args, kwargs, results), daemon=self.daemon
                )
                p.start()
                processes.append(p)
            for p in processes:
                p.join()
                assert results.get(), "Distributed call failed."

        return _wrapper


class TimedCall:
    """
    Wrap a test case so that it will run in a new process, raises a TimeoutError if the decorated method takes
    more than `seconds` to finish. It is designed to be used with `tests.utils.DistTestCase`.
    """

    def __init__(
        self,
        seconds: float = 60.0,
        daemon: Optional[bool] = None,
        method: Optional[str] = "spawn",
        force_quit: bool = True,
        skip_timing=False,
    ):
        """

        Args:
            seconds: timeout seconds.
            daemon: the process’s daemon flag.
                When daemon=None, the initial value is inherited from the creating process.
            method: set the method which should be used to start a child process.
                method can be 'fork', 'spawn' or 'forkserver'.
            force_quit: whether to terminate the child process when `seconds` elapsed.
            skip_timing: whether to skip the timing constraint.
                this is useful to include some system conditions such as
                `torch.cuda.is_available()`.
        """
        self.timeout_seconds = seconds
        self.daemon = daemon
        self.force_quit = force_quit
        self.skip_timing = skip_timing
        self.method = method

    @staticmethod
    def run_process(func, args, kwargs, results):
        try:
            output = func(*args, **kwargs)
            results.put(output)
        except Exception as e:
            e.traceback = traceback.format_exc()
            results.put(e)

    def __call__(self, obj):

        if self.skip_timing:
            return obj

        _cache_original_func(obj)

        @functools.wraps(obj)
        def _wrapper(*args, **kwargs):
            tmp = torch.multiprocessing.get_context(self.method)
            func = _call_original_func
            args = [obj.__name__, obj.__module__] + list(args)
            results = tmp.Queue()
            p = tmp.Process(target=TimedCall.run_process, args=(func, args, kwargs, results), daemon=self.daemon)
            p.start()

            p.join(timeout=self.timeout_seconds)

            timeout_error = None
            try:
                if p.is_alive():
                    # create an Exception
                    timeout_error = torch.multiprocessing.TimeoutError(
                        f"'{obj.__name__}' in '{obj.__module__}' did not finish in {self.timeout_seconds}s."
                    )
                    if self.force_quit:
                        p.terminate()
                    else:
                        warnings.warn(
                            f"TimedCall: deadline ({self.timeout_seconds}s) "
                            f"reached but waiting for {obj.__name__} to finish."
                        )
            finally:
                p.join()

            res = None
            try:
                res = results.get(block=False)
            except queue.Empty:  # no result returned, took too long
                pass
            if isinstance(res, Exception):  # other errors from obj
                if hasattr(res, "traceback"):
                    raise RuntimeError(res.traceback) from res
                raise res
            if timeout_error:  # no force_quit finished
                raise timeout_error
            return res

        return _wrapper


_original_funcs = {}


def _cache_original_func(obj) -> None:
    """cache the original function by name, so that the decorator doesn't shadow it."""
    global _original_funcs
    _original_funcs[obj.__name__] = obj


def _call_original_func(name, module, *args, **kwargs):
    if name not in _original_funcs:
        _original_module = importlib.import_module(module)  # reimport, refresh _original_funcs
        if not hasattr(_original_module, name):
            # refresh module doesn't work
            raise RuntimeError(f"Could not recover the original {name} from {module}: {_original_funcs}.")
    f = _original_funcs[name]
    return f(*args, **kwargs)


class NumpyImageTestCase2D(unittest.TestCase):
    im_shape = (128, 64)
    input_channels = 1
    output_channels = 4
    num_classes = 3

    def setUp(self):
        im, msk = create_test_image_2d(
            self.im_shape[0], self.im_shape[1], num_objs=4, rad_max=20, noise_max=0.0, num_seg_classes=self.num_classes
        )

        self.imt = im[None, None]
        self.seg1 = (msk[None, None] > 0).astype(np.float32)
        self.segn = msk[None, None]


class TorchImageTestCase2D(NumpyImageTestCase2D):
    def setUp(self):
        NumpyImageTestCase2D.setUp(self)
        self.imt = torch.tensor(self.imt)
        self.seg1 = torch.tensor(self.seg1)
        self.segn = torch.tensor(self.segn)


class NumpyImageTestCase3D(unittest.TestCase):
    im_shape = (64, 48, 80)
    input_channels = 1
    output_channels = 4
    num_classes = 3

    def setUp(self):
        im, msk = create_test_image_3d(
            self.im_shape[0],
            self.im_shape[1],
            self.im_shape[2],
            num_objs=4,
            rad_max=20,
            noise_max=0.0,
            num_seg_classes=self.num_classes,
        )

        self.imt = im[None, None]
        self.seg1 = (msk[None, None] > 0).astype(np.float32)
        self.segn = msk[None, None]


class TorchImageTestCase3D(NumpyImageTestCase3D):
    def setUp(self):
        NumpyImageTestCase3D.setUp(self)
        self.imt = torch.tensor(self.imt)
        self.seg1 = torch.tensor(self.seg1)
        self.segn = torch.tensor(self.segn)


def test_script_save(net, *inputs, eval_nets=True, device=None, rtol=1e-4):
    """
    Test the ability to save `net` as a Torchscript object, reload it, and apply inference. The value `inputs` is
    forward-passed through the original and loaded copy of the network and their results returned. Both `net` and its
    reloaded copy are set to evaluation mode if `eval_nets` is True. The forward pass for both is done without
    gradient accumulation.

    The test will be performed with CUDA if available, else CPU.
    """
    if True:
        device = "cpu"
    else:
        # TODO: It would be nice to be able to use GPU if
        # available, but this currently causes CI failures.
        if not device:
            device = "cuda" if torch.cuda.is_available() else "cpu"

    # Convert to device
    inputs = [i.to(device) for i in inputs]

    scripted = torch.jit.script(net.cpu())
    buffer = scripted.save_to_buffer()
    reloaded_net = torch.jit.load(BytesIO(buffer)).to(device)
    net.to(device)

    if eval_nets:
        net.eval()
        reloaded_net.eval()

    with torch.no_grad():
        set_determinism(seed=0)
        result1 = net(*inputs)
        result2 = reloaded_net(*inputs)
        set_determinism(seed=None)

    # convert results to tuples if needed to allow iterating over pairs of outputs
    result1 = ensure_tuple(result1)
    result2 = ensure_tuple(result2)

    for i, (r1, r2) in enumerate(zip(result1, result2)):
        if None not in (r1, r2):  # might be None
            np.testing.assert_allclose(
                r1.detach().cpu().numpy(),
                r2.detach().cpu().numpy(),
                rtol=rtol,
                atol=0,
                err_msg=f"failed on comparison number: {i}",
            )


def query_memory(n=2):
    """
    Find best n idle devices and return a string of device ids.
    """
    bash_string = "nvidia-smi --query-gpu=power.draw,temperature.gpu,memory.used --format=csv,noheader,nounits"

    try:
        p1 = Popen(bash_string.split(), stdout=PIPE)
        output, error = p1.communicate()
        free_memory = [x.split(",") for x in output.decode("utf-8").split("\n")[:-1]]
        free_memory = np.asarray(free_memory, dtype=float).T
        free_memory[1] += free_memory[0]  # combine 0/1 column measures
        ids = np.lexsort(free_memory)[:n]
    except (FileNotFoundError, TypeError, IndexError):
        ids = range(n) if isinstance(n, int) else []
    return ",".join(f"{int(x)}" for x in ids)


TEST_NDARRAYS: Tuple[Callable] = (np.array, torch.as_tensor)  # type: ignore
if torch.cuda.is_available():
    gpu_tensor: Callable = partial(torch.as_tensor, device="cuda")
    TEST_NDARRAYS = TEST_NDARRAYS + (gpu_tensor,)  # type: ignore


if __name__ == "__main__":
    print(query_memory())
