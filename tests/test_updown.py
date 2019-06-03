"""
Test FFUpDown layer in updown.py
"""

import numpy as np


def test_imports():
    from NetworksPython.layers import FFUpDown


def test_updown():
    """ Test FFUpDown """
    from NetworksPython import TSContinuous
    from NetworksPython.layers import FFUpDown

    # - Generic parameters
    weights = np.random.rand(2, 4)

    # - Layer generation
    fl0 = FFUpDown(weights=weights, dt=0.01, vfThrDown=0.02, vfThrUp=0.01, vtTauDecay=0.1)

    # - Check layer properties
    assert fl0.size == 4, "Problem with size"
    assert fl0.size_in == 2, "Problem with size_in"
    assert (fl0.vfThrDown == np.array([0.02, 0.02])).all(), "Problem with vfThrDown"
    assert (fl0.vfThrUp == np.array([0.01, 0.01])).all(), "Problem with vfThrUp"

    # - Input signal
    tsInCont = TSContinuous(
        times=np.arange(15) * 0.01,
        samples=np.vstack(
            (np.sin(np.linspace(0, 1, 15)), np.cos(np.linspace(0, 1, 15)))
        ).T,
    )

    # - Compare states and time before and after evolution
    vStateBefore = np.copy(fl0.state)
    fl0.evolve(tsInCont, duration=0.1)
    assert fl0.t == 0.1
    assert (vStateBefore != fl0.state).any()

    fl0.reset_all()
    assert fl0.t == 0
    assert (vStateBefore == fl0.state).all()


def test_updown_in_net():
    """ Test RecRateEuler """
    from NetworksPython import TSContinuous
    from NetworksPython.networks import Network
    from NetworksPython.layers import FFUpDown
    from NetworksPython.layers import RecDIAF

    # - Generic parameters
    weights = np.random.rand(2, 4)

    # - Layer generation
    fl0 = FFUpDown(weights=weights)
    fl1 = RecDIAF(np.zeros((4, 2)), np.zeros((2, 2)), dt=0.002)
    # - Generate network
    net = Network(fl0, fl1)

    # - Input signal
    tsInCont = TSContinuous(
        times=np.arange(15) * 0.01,
        samples=np.vstack(
            (np.sin(np.linspace(0, 1, 15)), np.cos(np.linspace(0, 1, 15)))
        ).T,
    )

    # - Compare states and time before and after evolution
    vStateBefore = np.copy(fl1.state)
    net.evolve(tsInCont, duration=0.1)
    assert net.t == 0.1
    assert (vStateBefore != fl1.state).any()
