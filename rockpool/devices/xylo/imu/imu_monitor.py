"""
Samna-backed bridge to Xylo dev kit for Xylo IMU
"""

# - Samna imports
import samna
from samna.xyloImu.configuration import XyloConfiguration

from . import xylo_imu_devkit_utils as hdkutils
from .xylo_imu_devkit_utils import XyloIMUHDK
from .xylo_samna import if_config_from_specification

import time
import numpy as np
from rockpool.nn.modules.module import Module
from rockpool.parameters import SimulationParameter

# - Typing
from typing import Optional, Union, Callable, List, Tuple
from warnings import warn

try:
    from tqdm.autonotebook import tqdm, trange
except ModuleNotFoundError:

    def tqdm(wrapped, *args, **kwargs):
        return wrapped

    def trange(obj, *args, **kwargs):
        return range(obj)


# - Configure exports
__all__ = ["XyloIMUMonitor"]

Default_Main_Clock_Rate = int(5e7)


class XyloIMUMonitor(Module):
    """
    A spiking neuron :py:class:`.Module` backed by the Xylo-IMU hardware, via `samna`.

    :py:class:`.XyloIMUMonitor` operates continuously in real-time, receiving and processing data from an IMU sensor with the deployed SNN. Results are continuously output from the HDK and buffered.

    On evolution, :py:class:`.XyloIMUMonitor` returns a chunk of buffered processed time of a specified duration.

    Use :py:func:`~.devices.xylo.imu.config_from_specification` to build and validate a configuration for Xylo.
    """

    def __init__(
        self,
        device: XyloIMUHDK,
        config: XyloConfiguration = None,
        output_mode: str = "Spike",
        main_clk_rate: Optional[int] = Default_Main_Clock_Rate,
        hibernation_mode: bool = False,
        interface_params: Optional[dict] = dict(),
        *args,
        **kwargs,
    ):
        """
        Instantiate a Module with Xylo dev-kit backend

        Args:
            device (XyloIMUHDK): An opened `samna` device to a Xylo dev kit
            config (XyloConfiguraration): A Xylo configuration from `samna`
            output_mode (str): The readout mode for the Xylo device. This must be one of ``["Spike", "Vmem"]``. Default: "Spike", return events from the output layer.
            main_clk_rate(int): The main clock rate of Xylo
            hibernation_mode (bool): If True, hibernation mode will be switched on, which only outputs events if it receives inputs above a threshold.
            interface_params(dict): The dictionary of Xylo interface parameters used for the `hdkutils.config_if_module` function, the keys of which must be one of "num_avg_bitshif", "select_iaf_output", "sampling_period", "filter_a1_list", "filter_a2_list", "scale_values", "Bb_list", "B_wf_list", "B_af_list", "iaf_threshold_values".
        """

        # - Check input arguments
        if device is None:
            raise ValueError("`device` must be a valid, opened Xylo HDK device.")

        # - Check output mode specification
        if output_mode not in ["Spike", "Vmem"]:
            raise ValueError(
                f'{output_mode} is not supported. Must be one of `["Spike", "Vmem"]`.'
            )
        self._output_mode = output_mode

        # - Get a default configuration
        if config is None:
            config = samna.xyloImu.configuration.XyloConfiguration()

        # - Get the network shape
        Nin, Nhidden = np.shape(config.input.weights)
        _, Nout = np.shape(config.readout.weights)

        # - Register buffers to read and write events, monitor state
        print("New read buffer")
        self._read_buffer = hdkutils.new_xylo_read_buffer(device)

        print("New write buffer")
        self._write_buffer = hdkutils.new_xylo_write_buffer(device)

        print("New state monitor buffer")
        self._state_buffer = hdkutils.new_xylo_state_monitor_buffer(device)

        # - Initialise the superclass
        super().__init__(
            shape=(Nin, Nhidden, Nout), spiking_input=True, spiking_output=True
        )

        # - Store the device
        self._device: XyloIMUHDK = device
        """ `.XyloHDK`: The Xylo HDK used by this module """

        # - Store the configuration (and apply it)
        self.config: Union[
            XyloConfiguration, SimulationParameter
        ] = SimulationParameter(shape=(), init_func=lambda _: config)
        """ `XyloConfiguration`: The HDK configuration applied to the Xylo module """

        # - Enable hibernation mode
        if hibernation_mode:
            self.config.enable_hibernation_mode = True

        # - Store the timestep
        self.dt: Union[float, SimulationParameter] = (
            1 / 200
        )  # Fixed computation step rate of 200Hz for Xylo IMU
        """ float: Simulation time-step of the module, in seconds """

        # - Store the main clock rate
        self._main_clk_rate = int(main_clk_rate)

        # - Store the io module
        self._io = self._device.get_io_module()

        # - Disable external IMU data input
        print("disable SPI slave")
        self._io.spi_slave_enable(False)

        # - Set main clock rate
        if self._main_clk_rate != Default_Main_Clock_Rate:
            print("set main clk rate")
            self._io.set_main_clk_rate(self._main_clk_rate)

        # - Configure to auto mode
        self._enable_auto_mode(interface_params)

        # - Send first trigger to start to run full auto mode
        print("advance time step")
        hdkutils.advance_time_step(self._write_buffer)

    @property
    def config(self):
        # - Return the configuration stored on Xylo HDK
        return self._device.get_model().get_configuration()

    @config.setter
    def config(self, new_config):
        # - Test for a valid configuration
        is_valid, msg = samna.xyloImu.validate_configuration(new_config)
        if not is_valid:
            raise ValueError(f"Invalid configuration for the Xylo HDK: {msg}")

        # - Write the configuration to the device
        print("apply config")
        hdkutils.apply_configuration(self._device, new_config)

        # - Store the configuration locally
        self._config = new_config

    def _enable_auto_mode(self, interface_params: dict):
        """
        Configure the Xylo HDK to use real-time mode

        Args:
            interface_params (dict): specify the interface parameters
        """

        # - Config the streaming mode
        print("configure auto mode")
        self.config = hdkutils.config_auto_mode(
            self._config, self.dt, self._main_clk_rate, self._io
        )

        # - Config the IMU interface and apply current configuration
        print("config input IF")
        self.config.input_interface = if_config_from_specification(**interface_params)

        # - Set configuration and reset state buffer
        print("set state buffer config")
        self._state_buffer.set_configuration(self._config)

        print("reset state buffer")
        self._state_buffer.reset()

    def evolve(
        self,
        input_data: np.ndarray,
        record: bool = False,
        progress: bool = False,
        timeout: Optional[float] = None,
    ) -> Tuple[np.ndarray, dict, dict]:
        """
        Evolve a network on the Xylo HDK in Real-time mode

        Args:
            input_data (np.ndarray): An array ``[T, Nin]``, specifying the number of time-steps to record.
            record (bool): A flag indicating whether a recording dictionary should be returned. Default: ``False``, do not return a recording dictionary.
            progress (bool): Display a progress bar for the read. Default: ``False``
            timeout (float): A duration in seconds for a read timeout. Default: 2x the real-time duration of the evolution

        Returns:
            Tuple[np.ndarray, dict, dict] output_events, {}, rec_dict
            output_events is an array that stores the output events of T time-steps
        """

        # - How many time-steps should we read?
        Nt = input_data.shape[0]

        # - Determine a read timeout
        timeout = 2 * Nt * self.dt if timeout is None else timeout

        out = []
        count = 0

        # - Initialise a progress bar for the read
        pbar = trange(Nt) if progress else None

        # - Start the read clock
        t_start = time.time()
        t_timeout = t_start + timeout

        while count < int(Nt):
            # - Perform a non-blocking read of either Vmem or spikes
            if self._output_mode == "Vmem":
                output = self._state_buffer.get_output_v_mem()

            elif self._output_mode == "Spike":
                output = self._state_buffer.get_output_spike()

            # - Record output if any was returned
            if output[0]:
                # - Clear the state buffer
                self._state_buffer.reset()

                # - Save the output
                output = np.array(output).T
                out.append(output)
                count += output.shape[0]

                # - Update the progress
                if progress:
                    pbar.update(output.shape[0])

            # - Check for read timeout
            if time.time() > t_timeout:
                raise TimeoutError(f"XyloIMUMonitor: Read timeout of {timeout} sec.")

        # - Concatenate and return output data
        out = np.concatenate(out, axis=0)[:Nt, :]

        return out, {}, {}
