def test_XyloMonitor():
    import pytest

    pytest.importorskip("samna")

    from rockpool.devices.xylo.syns63300 import (
        XyloIMUMonitor,
        config_from_specification,
    )
    import rockpool.devices.xylo.syns63300.xylo_imu_devkit_utils as putils
    import numpy as np

    xylo_hdk_nodes = putils.find_xylo_imu_boards()

    if len(xylo_hdk_nodes) == 0:
        pytest.skip("A connected Xylo IMU HDK is required to run this test")

    daughterboard = xylo_hdk_nodes[0]

    # - Make a Xylo configuration
    Nin = 3
    Nhidden = 5
    Nout = 2
    dt = 1e-3

    config, valid, msg = config_from_specification(
        weights_in=np.random.uniform(-127, 127, size=(Nin, Nhidden, 1)),
        weights_out=np.random.uniform(-127, 127, size=(Nhidden, Nout)),
        weights_rec=np.random.uniform(-127, 127, size=(Nhidden, Nhidden, 1)),
        dash_mem=2 * np.ones(Nhidden),
        dash_mem_out=3 * np.ones(Nout),
        dash_syn=4 * np.ones(Nhidden),
        dash_syn_out=3 * np.ones(Nout),
        threshold=128 * np.ones(Nhidden),
        threshold_out=256 * np.ones(Nout),
        weight_shift_in=1,
        weight_shift_rec=1,
        weight_shift_out=1,
        aliases=None,
    )

    # - Make a XyloMonitor module
    mod_xylo = XyloIMUMonitor(
        device=daughterboard, config=config, dt=dt, output_mode="Vmem"
    )

    # - Simulate with random input
    T = 10
    input_ts = np.random.rand(T, Nin)
    # mod_xylo.reset_state()
    output_ts, _, _ = mod_xylo(input_ts)
    print(output_ts)


def test_config_from_specification():
    import pytest

    pytest.importorskip("samna")

    from rockpool.devices.xylo.syns63300 import config_from_specification, mapper
    from rockpool.transform import quantize_methods as q
    from rockpool.nn.modules import LIFTorch, LinearTorch
    from rockpool.nn.combinators import Sequential, Residual

    Nin = 2
    Nhidden = 4
    Nout = 2
    dt = 1e-2

    net = Sequential(
        LinearTorch((Nin, Nhidden), has_bias=False),
        LIFTorch(Nhidden, dt=dt),
        Residual(
            LinearTorch((Nhidden, Nhidden), has_bias=False),
            LIFTorch(Nhidden, has_rec=True, threshold=1.0, dt=dt),
        ),
        LinearTorch((Nhidden, Nout), has_bias=False),
        LIFTorch(Nout, dt=dt),
    )

    spec = mapper(
        net.as_graph(),
        weight_dtype="float",
        threshold_dtype="float",
        dash_dtype="float",
    )
    spec.update(q.global_quantize(**spec))

    config, is_valid, msg = config_from_specification(**spec)
    if not is_valid:
        print(msg)


def test_external_input():
    import pytest

    pytest.importorskip("samna")

    from rockpool.devices.xylo.syns63300 import (
        XyloIMUMonitor,
        config_from_specification,
    )
    import rockpool.devices.xylo.syns63300.xylo_imu_devkit_utils as putils
    import numpy as np

    xylo_hdk_nodes = putils.find_xylo_imu_boards()

    if len(xylo_hdk_nodes) == 0:
        pytest.skip("A connected Xylo IMU HDK is required to run this test")

    daughterboard = xylo_hdk_nodes[0]

    # - Make a Xylo configuration
    Nin = 3
    Nhidden = 5
    Nout = 2

    config, valid, msg = config_from_specification(
        weights_in=np.random.uniform(-127, 127, size=(Nin, Nhidden, 1)),
        weights_out=np.random.uniform(-127, 127, size=(Nhidden, Nout)),
        weights_rec=np.random.uniform(-127, 127, size=(Nhidden, Nhidden, 1)),
        dash_mem=2 * np.ones(Nhidden),
        dash_mem_out=3 * np.ones(Nout),
        dash_syn=4 * np.ones(Nhidden),
        dash_syn_out=3 * np.ones(Nout),
        threshold=128 * np.ones(Nhidden),
        threshold_out=256 * np.ones(Nout),
        weight_shift_in=1,
        weight_shift_rec=1,
        weight_shift_out=1,
        aliases=None,
    )

    # - Make a XyloMonitor module
    mod_xylo = XyloIMUMonitor(
        device=daughterboard,
        config=config,
        output_mode="Vmem",
        prerecorded_imu_input=True,
    )

    # - Simulate with random input
    T = 10
    input_ts = 2**12 * np.random.rand(T, 3).astype(int)
    output_ts, _, _ = mod_xylo(input_ts)
    print(output_ts)
