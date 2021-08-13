"""
Utility functions for Dynap-SE1/SE2 simulator

Project Owner : Dylan Muir, SynSense AG
Author : Ugurcan Cakal
E-mail : ugurcan.cakal@gmail.com
23/07/2021
"""

import numpy as np
from rockpool import TSEvent, TSContinuous

from typing import (
    Callable,
    Optional,
    Union,
    Tuple,
    Generator,
    List,
)

NoneType = type(None)
ArrayLike = Union[np.ndarray, List, Tuple]

import numpy as np


def spike_to_pulse(
    input_spike: Union[TSEvent, np.ndarray],
    dt: float,
    pulse_width: float,
    amplitude: float,
    name: Optional[str] = "$V_{in}$",
) -> TSContinuous:
    """
    spike_to_pulse converts a discrete multi-channel spike train to continuous multi-channel pulse train signal.
    The function both accepts a `TSEvent` object or simple numpy array as input and produce a `TSContinuos` object.

    :param input_spike: multi-channel spike train with shape `TxN`
    :type input_spike: Union[TSEvent, np.ndarray]
    :param dt: duration of single time step in seconds
    :type dt: float
    :param pulse_width: width of a single pulse in seconds
    :type pulse_width: float
    :param amplitude: the amplitude of the pulse in volts
    :type amplitude: float
    :param name: the name of the multichannel pulse train, defaults to "$V_{in}$"
    :type name: Optional[str], optional
    :return: multi-channel pulse train, with shape `TxN`
    :rtype: TSContinuous
    """

    def channel_iterator() -> Tuple[Generator, int]:
        """
        channel_iterator implements an iterator to go over channels of
        given TSEvent object or the np.ndarray. In this contex, channel
        means a neuron firing and/or the second dimension of the array.

        :raises TypeError: Input spike is neither a TSEvent nor a np.ndarray instance
        :return: channel, steps
            channel: generator object to traverse single neuron spike trains
            steps: number of discrete timesteps
        :rtype: Tuple[Generator, int]
        """

        # TSEvent and np.ndarray are both accepted, actions are different
        if isinstance(input_spike, TSEvent):

            def event_channel() -> np.ndarray:
                """
                event_channel [summary]

                :yield: one dimensional boolean matrix with ``True`` indicating presence of events for each channel.
                :rtype: np.ndarray
                """
                event_raster = input_spike.raster(dt)
                yield from event_raster.T

            steps = int(np.round(input_spike.duration / dt))
            return event_channel(), steps

        elif isinstance(input_spike, np.ndarray):

            def array_channel() -> np.ndarray:
                """
                array_channel [summary]

                :yield: one dimensional boolean matrix with ``True`` indicating presence of events for each channel.
                :rtype: np.ndarray
                """
                yield from input_spike.T

            steps = input_spike.shape[0]
            return array_channel(), steps

        else:
            raise TypeError(
                "Input spike can be either a TSEvent or a numpy array instance!"
            )

    if pulse_width < dt:
        raise ValueError(
            f"Pulse width:{pulse_width:.1e} must be greater than or equal to dt:{dt:.1e}"
        )

    # Get the channel iterator and number of timesteps represented in one channel
    channels, signal_steps = channel_iterator()
    pulse_signal = np.empty((signal_steps, 0))
    pulse_steps = int(np.round(pulse_width / dt))

    # 1D convolution kernel
    kernel = amplitude * np.ones(pulse_steps)

    for spike_train in channels:
        pulse_train = np.convolve(spike_train, kernel, mode="full")
        pulse_train = pulse_train[:signal_steps]
        pulse_train = np.expand_dims(pulse_train, 1)
        pulse_signal = np.hstack((pulse_signal, pulse_train))

    pulse_signal = np.clip(pulse_signal, 0, amplitude)
    pulse_signal = TSContinuous.from_clocked(pulse_signal, dt=dt, name=name)

    return pulse_signal


def custom_spike_train(
    times: ArrayLike,
    channels: Union[ArrayLike, NoneType],
    duration: float,
    name: Optional[str] = "Input Spikes",
) -> TSEvent:
    """
    custom_spike_train Generate a custom spike train given exact spike times

    :param times: ``Tx1`` vector of exact spike times
    :type times: ArrayLike
    :param channels: ``Tx1`` vector of spike channels. All events belongs to channels 0 if None
    :type channels: Union[ArrayLike, NoneType]
    :param duration: The simulation duration in seconds
    :type duration: float
    :param name: The name of the resulting TSEvent object, defaults to "Input Spikes"
    :type name: Optional[str], optional
    :return: custom generated discrete spike train
    :rtype: TSEvent
    """

    input_sp_ts = TSEvent(
        times=times, channels=channels, t_start=0, t_stop=duration, name=name
    )
    return input_sp_ts


def random_spike_train(
    duration: float,
    n_channels: int,
    rate: float,
    dt: float = 1e-3,
    name: Optional[str] = "Input Spikes",
) -> TSEvent:
    """
    random_spike_train Generate a Poisson frozen random spike train

    :param duration: The simulation duration in seconds
    :type duration: float
    :param channels: Number of channels, or number of neurons
    :type channels: int
    :param rate: The spiking rate in Hertz(1/s)
    :type rate: float
    :param dt: The time step for the forward-Euler ODE solver, defaults to 1e-3
    :type dt: float, optional
    :param name: The name of the resulting TSEvent object, defaults to "Input Spikes"
    :type name: Optional[str], optional
    :raises ValueError: No spike generated due to low firing rate or very short simulation time
    :return: randomly generated discrete spike train
    :rtype: TSEvent
    """
    steps = int(np.round(duration / dt))
    spiking_prob = rate * dt
    input_sp_raster = np.random.rand(steps, n_channels) < spiking_prob
    if not any(input_sp_raster.flatten()):
        raise ValueError(
            "No spike generated at all due to low firing rate or short simulation time duration!"
        )
    input_sp_ts = TSEvent.from_raster(input_sp_raster, name=name, periodic=True, dt=dt)
    return input_sp_ts


def calculate_tau(
    c: float,
    itau: float,
    ut: float = 25e-3,
    kappa_n: float = 0.75,
    kappa_p: float = 0.66,
) -> float:
    """
    calculate_tau calculates the time constant using the leakage current

    .. math ::
        \\tau = \\dfrac{C U_{T}}{\\kappa I_{\\tau}}

    :param c: capacitor value in farads
    :type c: float
    :param itau: leakage current in amperes
    :type itau: float
    :param ut: termal voltage in volts, defaults to 25e-3
    :type ut: float, optional
    :param kappa_n: Subthreshold slope factor (n-type transistor), defaults to 0.75
    :type kappa_n: float, optional
    :param kappa_p: Subthreshold slope factor (p-type transistor), defaults to 0.66
    :type kappa_p: float, optional
    :return: time constant in seconds
    :rtype: float
    """
    kappa = (kappa_n + kappa_p) / 2
    tau = (c * ut) / (kappa * itau)
    return tau


def calculate_Isyn_inf(
    Ith: float,
    Itau: float,
    Iw: float,
) -> float:
    """
    calculate_Isyn_inf calculates the steady state DPI current

    .. math ::
        I_{syn_{\\infty}} = \\dfrac{I_{th}}{I_{\\tau}}I_{w}

    :param Ith: threshold current, a.k.a gain current in amperes
    :type Ith: float
    :param Itau: leakage current in amperes
    :type Itau: float
    :param Iw: weight current in amperes
    :type Iw: float
    :return: steady state current in amperes
    :rtype: float
    """
    Iss = (Ith / Itau) * Iw
    return Iss


def pulse_width_increment(
    method: str, base_width: float, dt: float
) -> Callable[[int], float]:
    """
    pulse_width_increment defines a method for pulse width increment
    in the case that pulses are merged together as one.
    It can be a logarithic increase which can manage infinite amount of spikes
    or can be a linear increase which is computationally lighter.

    :param method: The increment merhod: "lin" or "log".
    :type method: str
    :param base_width: the unit pulse width to be increased
    :type base_width: float
    :param dt: the simulation timestep
    :type dt: float
    :return: a function to calculate the effective pulse width
    :rtype: Callable[[int], float]
    """
    if method == "log":

        def log_incr(num_spikes: Union[int, np.ndarray]):

            """
            log_incr decreases the increment amount exponentially at each time
            so that the infinite amount of spikes can increase the pulse width
            up to the simulation timestep

            :param num_spikes: number of spikes within one simulation timestep
            :type num_spikes: Union[int, np.ndarray]
            :return: the upgraded pulsewidth
            :rtype: float
            """
            return dt * (1 - np.exp(-num_spikes * base_width / dt))

        return log_incr

    if method == "lin":

        def lin_incr(num_spikes: Union[int, np.ndarray]):
            """
            lin_incr Implements the simplest possible approach. Multiply the
            number of spikes with the unit pulse width

            :param num_spikes: [description]
            :type num_spikes: Union[int, np.ndarray]
            :return: the upgraded pulse width
            :rtype: float
            """
            pulse_width = num_spikes * base_width
            pulse_width = np.clip(pulse_width, 0, dt)
            return pulse_width

        return lin_incr


def pulse_placement(method: str, dt: float) -> Callable[[np.ndarray], float]:
    """
    pulse_placement defines a method to place a pulse inside a larger timebin

    :param method: The method of placement. It can be "middle", "start", "end", or "random"
    :type method: str
    :param dt: the timebin to place the pulse
    :type dt: float
    :return: a function to calculate the time left after the pulse ends
    :rtype: Callable[[np.ndarray],float]
    """
    if method == "middle":

        def _middle(t_pulse: np.ndarray):
            """
            _middle places the pulse right in the middle of the timebin
            .___|-|___.

            :param t_pulse: an array of durations of the pulses
            :type t_pulse: np.ndarray
            :return: the time left after the pulse ends.
            :rtype: float
            """
            t_dis = (dt - t_pulse) / 2.0
            return t_dis

        return _middle

    if method == "start":

        def _start(t_pulse: np.ndarray):
            """
            _start places the pulse at the beginning of the timebin
            .|-|______.

            :param t_pulse: an array of durations of the pulses
            :type t_pulse: np.ndarray
            :return: the time left after the pulse ends.
            :rtype: float
            """
            t_dis = dt - t_pulse
            return t_dis

        return _start

    if method == "end":

        def _end(t_pulse: np.ndarray):
            """
            _end places the pulse at the end of the timebin
            .______|-|.
            Note that it's the most advantageous one becasue
            placing the pulse at the end, one exponential term in the DPI update
            equation can be omitted.

            :param t_pulse: an array of durations of the pulses
            :type t_pulse: np.ndarray
            :return: the time left after the pulse ends.
            :rtype: float
            """
            t_dis = 0
            return t_dis

        return _end

    if method == "random":

        def _random(t_pulse: np.ndarray):
            """
            _random places the pulse to a random place inside the timebin
            .__|-|____.
            ._____|-|_.
            ._|-|_____.

            Note that it's the most expensive one among the other placement methods
            since that there is a random number generation overhead at each time.

            :param t_pulse: an array of durations of the pulses
            :type t_pulse: np.ndarray
            :return: the time left after the pulse ends.
            :rtype: float
            """

            t_pulse_start = (dt - t_pulse) * np.random.random_sample()
            t_dis = dt - t_pulse_start - t_pulse
            return t_dis

        return _random
