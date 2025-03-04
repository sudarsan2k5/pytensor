"""
Provides Ops for FFT and DCT.

"""


# This module will soon be deprecated.
import warnings

import numpy as np
import numpy.fft

from pytensor.graph.basic import Apply
from pytensor.graph.op import Op
from pytensor.link.c.type import generic
from pytensor.tensor.basic import as_tensor
from pytensor.tensor.type import zmatrix


message = (
    "The module pytensor.sandbox.fourier will soon be deprecated."
    " Please use pytensor.tensor.fft, which supports gradients."
)
warnings.warn(message)


class GradTodo(Op):
    # TODO : need description for class
    __props__ = ()

    def make_node(self, x):
        return Apply(self, [x], [x.type()])

    def perform(self, node, inputs, outputs):
        raise NotImplementedError("TODO")


grad_todo = GradTodo()


class FFT(Op):
    # TODO : need description for parameters
    """
    Fast Fourier Transform.

    .. TODO:
        The current implementation just works for matrix inputs, and permits
        taking a 1D FFT over either rows or columns. Add support for N-D FFTs
        as provided by either numpy or FFTW directly.

    .. TODO:
        Give the C code that uses FFTW.

    .. TODO:
        Unit tests.

    """

    default_output = 0
    # don't return the plan object in the 'buf' output

    half = False
    """Only return the first half (positive-valued) of the frequency
    components."""
    __props__ = ("half", "inverse")

    def __init__(self, half=False, inverse=False):
        self.half = half
        self.inverse = inverse

    def make_node(self, frames, n, axis):
        """
        Compute an n-point fft of frames along given axis.

        """
        _frames = as_tensor(frames, ndim=2)
        _n = as_tensor(n, ndim=0)
        _axis = as_tensor(axis, ndim=0)
        if self.half and _frames.type.dtype.startswith("complex"):
            raise TypeError("Argument to HalfFFT must not be complex", frames)
        spectrogram = zmatrix()
        buf = generic()
        # The `buf` output is present for future work
        # when we call FFTW directly and re-use the 'plan' that FFTW creates.
        # In that case, buf would store a CObject encapsulating the plan.
        rval = Apply(self, [_frames, _n, _axis], [spectrogram, buf])
        return rval

    def perform(self, node, inp, out):
        frames, n, axis = inp
        spectrogram, buf = out
        if self.inverse:
            fft_fn = numpy.fft.ifft
        else:
            fft_fn = numpy.fft.fft

        fft = fft_fn(frames, int(n), int(axis))
        if self.half:
            M, N = fft.shape
            if axis == 0:
                if M % 2:
                    raise ValueError("halfFFT on odd-length vectors is undefined")
                spectrogram[0] = fft[0 : M / 2, :]
            elif axis == 1:
                if N % 2:
                    raise ValueError("halfFFT on odd-length vectors is undefined")
                spectrogram[0] = fft[:, 0 : N / 2]
            else:
                raise NotImplementedError()
        else:
            spectrogram[0] = fft

    def grad(self, inp, out):
        frames, n, axis = inp
        g_spectrogram, g_buf = out
        return [grad_todo(frames), None, None]


fft = FFT(half=False, inverse=False)
half_fft = FFT(half=True, inverse=False)
ifft = FFT(half=False, inverse=True)
half_ifft = FFT(half=True, inverse=True)


def dct_matrix(rows, cols, unitary=True):
    # TODO : need description for parameters
    """
    Return a (rows x cols) matrix implementing a discrete cosine transform.

    This algorithm is adapted from Dan Ellis' Rastmat spec2cep.m, lines 15-20.

    """
    rval = np.zeros((rows, cols))
    col_range = np.arange(cols)
    scale = np.sqrt(2.0 / cols)
    for i in range(rows):
        rval[i] = np.cos(i * (col_range * 2 + 1) / (2.0 * cols) * np.pi) * scale

    if unitary:
        rval[0] *= np.sqrt(0.5)
    return rval
