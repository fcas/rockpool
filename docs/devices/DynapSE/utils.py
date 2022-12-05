"""
Dynap-SE tuturials common utility functions 

Project Owner : Dylan Muir, SynSense AG
Author : Ugurcan Cakal
E-mail : ugurcan.cakal@gmail.com

15/09/2022
"""
from typing import Dict, Optional, Tuple, Union

import matplotlib

import numpy as np
import matplotlib.pyplot as plt

from rockpool.timeseries import TSContinuous
from rockpool.devices.dynapse.typehints import NeuronKey


def poisson_spike_train(
    n_channels: int,
    duration: float,
    rate: float,
    dt: float,
    batch_size: int = 1,
    seed: Optional[int] = None,
) -> np.ndarray:
    """
    random_spike_train generates a Poisson frozen random spike train

    :param n_channels: number of channels
    :type n_channels: float
    :param duration: simulation duration in seconds
    :type duration: float
    :param rate: expected mean spiking rate in Hertz(1/s)
    :type rate: float
    :param dt: time step length
    :type dt: float, optional
    :param batch_size: number of batches in data, defaults to 1
    :type batch_size: int, optional
    :param seed: the random number seed
    :type seed: int, optional
    :raises ValueError: no spike generated due to low firing rate or very short simulation time
    :return: randomly generated discrete spike train
    :rtype: np.ndarray
    """
    np.random.seed(seed)
    steps = int(np.round(duration / dt))
    raster = np.random.poisson(rate * dt, (batch_size, steps, n_channels))

    # Check if raster has at least one spike
    if not any(raster.flatten()):
        raise ValueError(
            "No spike generated at all due to low firing rate or short simulation time duration!"
        )

    spike_tensor = np.array(raster, dtype=float)
    return spike_tensor


def plot_Ix(
    Ix_record: np.ndarray,
    Ithr: Optional[Union[float, np.ndarray]] = None,
    dt: float = 1e-3,
    name: Optional[str] = None,
    idx_map: Optional[Dict[int, NeuronKey]] = None,
    margin: Optional[float] = 0.2,
    ax: Optional[matplotlib.axes.Axes] = None,
    line_ratio: float = 0.3,
    ylabel: str = "Current (A)",
    *args,
    **kwargs,
) -> TSContinuous:
    """
    plot_Ix converts an `Ix_record` current measurements/recordings obtained from the record dictionary to a `TSContinuous` object and plot

    :param Ix_record: Membrane or synapse currents of the neurons recorded with respect to time (T,N)
    :type Ix_record: np.ndarray
    :param Ithr: Spike threshold or any other upper threshold for neurons. Both a single float number for global spike threshold and an array of numbers for neuron-specific thresholds can be provided. Plotted with dashed lines if provided, defaults to None
    :type Ithr: Optional[float], optional
    :param dt: The discrete time resolution of the recording, defaults to 1e-3
    :type dt: float, optional
    :param name: title of the figure, name of the `TSContinuous` object, defaults to None
    :type name: str, optional
    :param idx_map: a dictionary of the mapping between matrix indexes of the neurons and their global unique neuron keys, defaults to None
    :type idx_map: Optional[Dict[int, NeuronKey]], optional
    :param margin: The margin between the edges of the figure and edges of the lines, defaults to 0.2
    :type margin: Optional[float], optional
    :param ax: The sub-plot axis to plot the figure, defaults to None
    :type ax: Optional[matplotlib.axes.Axes], optional
    :param line_ratio: the ratio between Imem lines and the Ispkthr lines, defaults to 0.3
    :type line_ratio: float, optional
    :param ylabel: ylabel value to be printed
    :type ylabel: str, optional
    :return: Imem current in `TSContinuous` object format
    :rtype: TSContinuous
    """
    f_margin = 1.0 + margin if margin is not None else 1.0

    if ax is not None:
        plt.sca(ax)

    # Convert and plot
    Ix = TSContinuous.from_clocked(Ix_record, dt=dt, name=name)
    _lines = Ix.plot(stagger=np.float32(Ix.max * f_margin), *args, **kwargs)
    plt.ylabel(ylabel)

    if idx_map is not None:
        ax = plt.gca()
        handles, labels = ax.get_legend_handles_labels()
        ax.legend(
            handles[::-1],
            [f"n[{n_key}]" for n_key in idx_map.values()][::-1],
            bbox_to_anchor=(1.05, 1.05),
        )

    plt.tight_layout()

    # Upper threshold lines
    if Ithr is not None:
        linewidth = _lines[0]._linewidth * line_ratio
        Ithr = np.ones_like(Ix_record) * Ithr
        Ithr = TSContinuous.from_clocked(Ithr, dt=dt)
        Ithr.plot(
            stagger=np.float32(Ix.max * f_margin),
            linestyle="dashed",
            linewidth=linewidth,
        )

    return Ix


def split_yaxis(
    top_ax: matplotlib.axes.Axes,
    bottom_ax: matplotlib.axes.Axes,
    top_bottom_ratio: Tuple[float],
) -> None:
    """
    split_yaxis arrange ylimits such that two different plots can share the same y axis without any intersection

    :param top_ax: the axis to place on top
    :type top_ax: matplotlib.axes.Axes
    :param bottom_ax: the axis to place on bottom
    :type bottom_ax: matplotlib.axes.Axes
    :param top_bottom_ratio: the ratio between top and bottom axes
    :type top_bottom_ratio: Tuple[float]
    """

    def arrange_ylim(ax: matplotlib.axes.Axes, place_top: bool, factor: float) -> None:
        """
        arrange_ylim helper function to arrange y_limits

        :param ax: the axis to change the limits
        :type ax: matplotlib.axes.Axes
        :param place_top: place the axis of interest to top or bottom
        :type place_top: bool
        :param factor: the factor to multiply the y-range and allocate space to the other plot
        :type factor: float
        """
        bottom, top = ax.get_ylim()

        if place_top:
            bottom = bottom - factor * (top - bottom)
        else:
            top = top + factor * (top - bottom)

        ax.set_ylim(top=top, bottom=bottom)

    f_top = top_bottom_ratio[1] / top_bottom_ratio[0]
    f_bottom = top_bottom_ratio[0] / top_bottom_ratio[1]

    arrange_ylim(top_ax, 1, f_top)
    arrange_ylim(bottom_ax, 0, f_bottom)
