"""
Dynap-SE samna backend bridge
Handles the low-level hardware configuration under the hood and provide easy-to-use access to the user

Note : Existing modules are reconstructed considering consistency with Xylo support.

Project Owner : Dylan Muir, SynSense AG
Author : Ugurcan Cakal
E-mail : ugurcan.cakal@gmail.com

15/09/2022
[] TODO : configure FPGA inside ?
[] TODO : It's done when it's done
[] TODO : Implement read timeout in evolve
"""

from __future__ import annotations

from typing import Any, Dict, Optional, List, Tuple
import time

import numpy as np
from rockpool.devices.dynapse.interface.utils import (
    aer_to_raster,
    event_generator,
    raster_to_aer,
    capture_events_from_device,
)


# - Rockpool imports
from rockpool.nn.modules.module import Module
from rockpool.devices.dynapse.samna_alias.dynapse2 import (
    Dynapse2Destination,
    Dynapse2Interface,
)

# Try to import samna for device interfacing
try:
    import samna
    import samna.dynapse2 as se2
except:
    samna = Any
    se2 = Any
    print(
        "Device interface requires `samna` package which is not installed on the system"
    )

# - Configure exports
__all__ = ["DynapseSamna"]
DT_FPGA = 1e-6


class DynapseSamna(Module):
    """
    DynapSim solves dynamical chip equations for the DPI neuron and synapse models.
    Receives configuration as bias currents and solves membrane and synapse dynamics using ``jax`` backend.

    :Parameters:

    :param shape: Two dimensions ``(Nin, Nout)``, which defines a input and output conections of DynapSE neurons.
    :type shape: Tuple[int]
    :param board: the Dynan-SE2 interface node. (Like a file) It should be opened beforehand.
    :type board: Dynapse2Interface
    :param dt: the simulation timestep resolution, defaults to 1e-3
    :type dt: float, optional

    """

    def __init__(
        self,
        shape: Tuple[int],
        board: Dynapse2Interface,
        dt: float = 1e-3,
    ):

        if np.size(shape) != 2:
            raise ValueError("`shape` must be a two-element tuple `(Nin, Nout)`.")

        if board is None:
            raise ValueError("`device` must be a valid, opened Dynap-SE2 HDK device.")

        # - Initialise the superclass
        super().__init__(shape=shape, spiking_input=True, spiking_output=True)

        self.board = board
        self.dt = dt
        self.dt_fpga = DT_FPGA

    def evolve(
        self,
        input_data: np.ndarray,
        channel_map: Optional[Dict[int, Dynapse2Destination]] = None,
        read_timeout: float = 5.0,
        offset_fpga: bool = True,
        offset: float = 100e-3,
        record: bool = False,
    ) -> Tuple[np.ndarray, Dict, Dict]:
        """
        evolve simulates the network on Dynap-SE2 HDK in real-time
        The function first converts raster plot to a sequence of AER packages and dispatches to the device.
        Then reads the output buffers

        :param input_data: A raster ``(T, Nin)`` specifying for each bin the number of input events sent to the corresponding input channel on Dynap-SE2, at the corresponding time point.
        :type input_data: np.ndarray
        :param channel_map: the mapping between input timeseries channels and the destinations
        :type channel_map: Optional[Dict[int, Dynapse2Destination]]
        :param read_timeout: the maximum time to wait until reading finishes, defaults to None
        :type read_timeout: float, optional
        :param offset_fpga: offset the timeseries depending on the current FPGA clock, defaults to True
        :type offset_fpga: bool, optional
        :param offset: user defined offset in seconds, defaults to True
        :type offset: float, optional
        :param record: record the states in each timestep of evolution or not, defaults to False
        :type record: bool, optional
        :return: spikes_ts, states, record_dict
            :spikes_ts: is an array with shape ``(T, Nrec)`` containing the output data(spike raster) produced by the module.
            :states: is a dictionary containing the updated module state following evolution.
            :record_dict: is a dictionary containing the recorded state variables during the evolution at each time step, if the ``record`` argument is ``True`` else empty dictionary {}
        :rtype: Tuple[np.ndarray, Dict, Dict]
        """

        # Read Current FPGA timestamp, offset the events accordingly
        if offset_fpga:
            offset += self.current_timestamp()

        # Convert the input data to aer sequence
        event_sequence = raster_to_aer(
            input_data,
            start_time=offset,
            channel_map=channel_map,
            return_samna=True,
            dt=self.dt,
            dt_fpga=self.dt_fpga,
        )

        # Write AER packages to the bus
        self.board.grid_bus_write_events(event_sequence)
        output_events = capture_events_from_device(self.board, read_timeout)

        # Return
        spikes_ts, channel_map = aer_to_raster(output_events)
        states = {}
        record_dict = {}

        if record is True:
            record_dict = {"channel_map": channel_map}

        return spikes_ts, states, record_dict

    def reset_time(self) -> bool:
        """
        reset_time reset the FPGA counters

        :return: success flag, True if FPGA is resetted
        :rtype: bool
        """
        return self.board.reset_fpga()

    def current_timestamp(
        self,
        reading_interval: float = 10e-3,
        number_of_events: int = 10,
        retry: int = 20,
    ) -> float:
        """
        current_timestamp bounces a dummy event from FPGA to get the exact FPGA time at that moment.

        :param reading_interval: minimum time to wait for the event to bounce back, defaults to 10e-3
        :type reading_interval: float, optional
        :param number_of_events: the number of dummy events to bounce to dispatch, defaults to 10
        :type number_of_events: int, optional
        :param retry: number of retrials in the case that event is not returned back. Each time double the reading interval, defaults to 20
        :type retry: int, optional
        :raises TimeoutError: "FPGA could not respond, increase number of trials or reading interval!"
        :return: the current FPGA time in seconds
        :rtype: float
        """

        # Flush the buffers
        self.board.output_read()

        # Generate dummy events
        events = [
            event_generator(ts, dt_fpga=self.dt_fpga)
            for ts in np.arange(
                0, reading_interval, reading_interval / number_of_events
            )
        ]

        # Send dummy event sequence to the device
        self.board.input_interface_write_events(0, events)
        time.sleep(reading_interval)

        # Try to catch them and read the last timestamp
        for __break in range(retry):
            evs = self.board.output_read()
            if len(evs) > 0:
                return evs[-1] * self.dt_fpga
            else:
                time.sleep(reading_interval)
                reading_interval *= 2

        raise TimeoutError(
            f"FPGA could not respond, increase number of trials or reading interval!"
        )
