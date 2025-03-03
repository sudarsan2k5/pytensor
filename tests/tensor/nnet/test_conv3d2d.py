import numpy as np
import pytest

import pytensor


try:
    from scipy import ndimage
except ImportError:
    ndimage = None

import tests.unittest_tools as utt
from pytensor.compile.sharedvalue import shared
from pytensor.graph.rewriting.basic import check_stack_trace
from pytensor.tensor.nnet.conv3d2d import (
    DiagonalSubtensor,
    IncDiagonalSubtensor,
    conv3d,
    get_diagonal_subtensor_view,
)


def test_get_diagonal_subtensor_view(wrap=lambda a: a):
    x = np.arange(20).reshape(5, 4).astype("float32")
    x = wrap(x)
    xv01 = get_diagonal_subtensor_view(x, 0, 1)

    # test that it works in 2d
    assert np.array_equal(np.asarray(xv01), [[12, 9, 6, 3], [16, 13, 10, 7]])

    x = np.arange(24).reshape(4, 3, 2)
    xv01 = get_diagonal_subtensor_view(x, 0, 1)
    xv02 = get_diagonal_subtensor_view(x, 0, 2)
    xv12 = get_diagonal_subtensor_view(x, 1, 2)

    # print 'x', x
    # print 'xv01', xv01
    # print 'xv02', xv02
    assert np.array_equal(
        np.asarray(xv01), [[[12, 13], [8, 9], [4, 5]], [[18, 19], [14, 15], [10, 11]]]
    )

    assert np.array_equal(
        np.asarray(xv02),
        [
            [[6, 1], [8, 3], [10, 5]],
            [[12, 7], [14, 9], [16, 11]],
            [[18, 13], [20, 15], [22, 17]],
        ],
    )

    # diagonal views of each leading matrix is the same
    # as the slices out of the diagonal view of the entire 3d tensor
    for xi, xvi in zip(x, xv12):
        assert np.array_equal(xvi, get_diagonal_subtensor_view(xi, 0, 1))


def pyconv3d(signals, filters, border_mode="valid"):
    Ns, Ts, C, Hs, Ws = signals.shape
    Nf, Tf, C, Hf, Wf = filters.shape

    # if border_mode is not 'valid', the signals need zero-padding
    if border_mode == "full":
        Tpad = Tf - 1
        Hpad = Hf - 1
        Wpad = Wf - 1
    elif border_mode == "half":
        Tpad = Tf // 2
        Hpad = Hf // 2
        Wpad = Wf // 2
    else:
        Tpad = 0
        Hpad = 0
        Wpad = 0

    if Tpad > 0 or Hpad > 0 or Wpad > 0:
        # zero-pad signals
        signals_padded = np.zeros(
            (Ns, Ts + 2 * Tpad, C, Hs + 2 * Hpad, Ws + 2 * Wpad), "float32"
        )
        signals_padded[
            :, Tpad : (Ts + Tpad), :, Hpad : (Hs + Hpad), Wpad : (Ws + Wpad)
        ] = signals
        Ns, Ts, C, Hs, Ws = signals_padded.shape
        signals = signals_padded

    Tf2 = Tf // 2
    Hf2 = Hf // 2
    Wf2 = Wf // 2

    rval = np.zeros((Ns, Ts - Tf + 1, Nf, Hs - Hf + 1, Ws - Wf + 1))
    for ns in range(Ns):
        for nf in range(Nf):
            for c in range(C):
                s_i = signals[ns, :, c, :, :]
                f_i = filters[nf, :, c, :, :]
                r_i = rval[ns, :, nf, :, :]
                o_i = ndimage.convolve(s_i, f_i, mode="constant", cval=1)
                o_i_sh0 = o_i.shape[0]
                # print s_i.shape, f_i.shape, r_i.shape, o_i.shape
                r_i += o_i[Tf2 : o_i_sh0 - Tf2, Hf2:-Hf2, Wf2:-Wf2]
    return rval


def check_diagonal_subtensor_view_traces(fn):
    assert check_stack_trace(fn, ops_to_check=(DiagonalSubtensor, IncDiagonalSubtensor))


@pytest.mark.skipif(
    ndimage is None or not pytensor.config.cxx,
    reason="conv3d2d tests need SciPy and a c++ compiler",
)
@pytest.mark.parametrize("border_mode", ("valid", "full", "half"))
def test_conv3d(border_mode):
    if pytensor.config.mode == "FAST_COMPILE":
        mode = pytensor.compile.mode.get_mode("FAST_RUN")
    else:
        mode = pytensor.compile.mode.get_default_mode()

    Ns, Ts, C, Hs, Ws = 3, 10, 3, 32, 32
    Nf, Tf, C, Hf, Wf = 32, 5, 3, 5, 5

    signals = (
        np.arange(Ns * Ts * C * Hs * Ws).reshape(Ns, Ts, C, Hs, Ws).astype("float32")
    )
    filters = (
        np.arange(Nf * Tf * C * Hf * Wf).reshape(Nf, Tf, C, Hf, Wf).astype("float32")
    )

    # t0 = time.perf_counter()
    pyres = pyconv3d(signals, filters, border_mode)
    # print(time.perf_counter() - t0)

    s_signals = shared(signals)
    s_filters = shared(filters)
    s_output = shared(signals * 0)

    out = conv3d(
        s_signals,
        s_filters,
        signals_shape=signals.shape,
        filters_shape=filters.shape,
        border_mode=border_mode,
    )

    newconv3d = pytensor.function([], [], updates={s_output: out}, mode=mode)

    check_diagonal_subtensor_view_traces(newconv3d)
    # t0 = time.perf_counter()
    newconv3d()
    # print(time.perf_counter() - t0)
    utt.assert_allclose(pyres, s_output.get_value(borrow=True))
    gsignals, gfilters = pytensor.grad(out.sum(), [s_signals, s_filters])
    gnewconv3d = pytensor.function(
        [],
        [],
        updates=[(s_filters, gfilters), (s_signals, gsignals)],
        mode=mode,
        name="grad",
    )
    check_diagonal_subtensor_view_traces(gnewconv3d)

    # t0 = time.perf_counter()
    gnewconv3d()
    # print("grad", time.perf_counter() - t0)

    Ns, Ts, C, Hs, Ws = 3, 3, 3, 5, 5
    Nf, Tf, C, Hf, Wf = 4, 2, 3, 2, 2

    rng = np.random.default_rng(280284)

    signals = rng.random((Ns, Ts, C, Hs, Ws)).astype("float32")
    filters = rng.random((Nf, Tf, C, Hf, Wf)).astype("float32")
    utt.verify_grad(
        lambda s, f: conv3d(s, f, border_mode=border_mode),
        [signals, filters],
        eps=1e-1,
        mode=mode,
    )

    # Additional Test that covers the case of patched implementation for filter with Tf=1
    Ns, Ts, C, Hs, Ws = 3, 10, 3, 32, 32
    Nf, Tf, C, Hf, Wf = 32, 1, 3, 5, 5

    signals = (
        np.arange(Ns * Ts * C * Hs * Ws).reshape(Ns, Ts, C, Hs, Ws).astype("float32")
    )
    filters = (
        np.arange(Nf * Tf * C * Hf * Wf).reshape(Nf, Tf, C, Hf, Wf).astype("float32")
    )

    # t0 = time.perf_counter()
    pyres = pyconv3d(signals, filters, border_mode)
    # print(time.perf_counter() - t0)

    s_signals = shared(signals)
    s_filters = shared(filters)
    s_output = shared(signals * 0)

    out = conv3d(
        s_signals,
        s_filters,
        signals_shape=signals.shape,
        filters_shape=filters.shape,
        border_mode=border_mode,
    )

    newconv3d = pytensor.function([], [], updates={s_output: out}, mode=mode)

    # t0 = time.perf_counter()
    newconv3d()
    # print(time.perf_counter() - t0)
    utt.assert_allclose(pyres, s_output.get_value(borrow=True))
    gsignals, gfilters = pytensor.grad(out.sum(), [s_signals, s_filters])
    gnewconv3d = pytensor.function(
        [],
        [],
        updates=[(s_filters, gfilters), (s_signals, gsignals)],
        mode=mode,
        name="grad",
    )

    # t0 = time.perf_counter()
    gnewconv3d()
    # print("grad", time.perf_counter() - t0)

    Ns, Ts, C, Hs, Ws = 3, 3, 3, 5, 5
    Nf, Tf, C, Hf, Wf = 4, 1, 3, 2, 2

    signals = rng.random((Ns, Ts, C, Hs, Ws)).astype("float32")
    filters = rng.random((Nf, Tf, C, Hf, Wf)).astype("float32")
    utt.verify_grad(
        lambda s, f: conv3d(s, f, border_mode=border_mode),
        [signals, filters],
        eps=1e-1,
        mode=mode,
    )
