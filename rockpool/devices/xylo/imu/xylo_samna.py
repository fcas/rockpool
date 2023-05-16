"""
Utilities for producing a samna HW configuration for Xylo IMU devices
"""


import numpy as np
import samna

from samna.xyloImu.configuration import XyloConfiguration, InputInterfaceConfig

from rockpool.nn.modules.module import Module
from rockpool.parameters import SimulationParameter
from . import xylo_imu_devkit_utils as hdkutils
from .xylo_imu_devkit_utils import XyloIMUHDK

# - Typing
from typing import Optional, Union, Callable, List
from warnings import warn


# - Configure exports
__all__ = [
    "config_from_specification",
    "if_config_from_specification",
    "save_config",
    "load_config",
    "XyloSamna",
]


def config_from_specification(
    weights_in: np.ndarray,
    weights_out: np.ndarray,
    weights_rec: Optional[np.ndarray] = None,
    dash_mem: Optional[np.ndarray] = None,
    dash_mem_out: Optional[np.ndarray] = None,
    dash_syn: Optional[np.ndarray] = None,
    dash_syn_out: Optional[np.ndarray] = None,
    threshold: Optional[np.ndarray] = None,
    threshold_out: Optional[np.ndarray] = None,
    bias_hidden: Optional[np.ndarray] = None,
    bias_out: Optional[np.ndarray] = None,
    weight_shift_in: int = 0,
    weight_shift_rec: int = 0,
    weight_shift_out: int = 0,
    aliases: Optional[List[List[int]]] = None,
    *args,
    **kwargs,
) -> XyloConfiguration:
    """
    Convert a full network specification to a xylo config and validate it

    See Also:
        For detailed information about the networks supported on Xylo, see :ref:`/devices/xylo-overview.ipynb`

    Args:
        weights_in (np.ndarray): A quantised 8-bit input weight matrix ``(Nin, Nin_res, 1)``. The third dimension specifies connections onto the second input synapse for each neuron. ``Nin_res`` indicates the number of hidden-layer neurons that receive input from the input channels.
        weights_out (np.ndarray): A quantised 8-bit output weight matrix ``(Nhidden, Nout)``.
        weights_rec (np.ndarray): A quantised 8-bit recurrent weight matrix ``(Nhidden, Nhidden, 1)``. The third dimension specified connections onto the second input synapse for each neuron. Default: ``0``
        dash_mem (np.ndarray): A vector or list ``(Nhidden,)`` specifing decay bitshift for neuron state for each hidden layer neuron. Default: ``1``
        dash_mem_out (np.ndarray): A vector or list ``(Nout,)`` specifing decay bitshift for neuron state for each output neuron. Default: ``1``
        dash_syn (np.ndarray): A vector or list ``(Nhidden,)`` specifing decay bitshift for synapse 1 state for each hidden layer neuron. Default: ``1``
        dash_syn_out (np.ndarray): A vector or list ``(Nout,)`` specifing decay bitshift for synapse state for each output layer neuron. Default: ``1``
        threshold (np.ndarray): A vector or list ``(Nhidden,)`` specifing the firing threshold for each hidden layer neuron. Default: ``0``
        threshold_out (np.ndarray): A vector or list ``(Nout,)`` specifing the firing threshold for each output layer neuron. Default: ``0``
        bias_hidden (np.ndarray): A vector or list ``(Nhidden,)`` specifing the bias for each hidden layer neuron. Default: ``0``
        bias_out (np.ndarray): A vector or list ``(Nout,)`` specifing the bias for each output layer neuron. Default: ``0``
        weight_shift_in (int): The number of bits to left-shift each input weight. Default: ``0``
        weight_shift_rec (int): The number of bits to left-shift each recurrent weight. Default: ``0``
        weight_shift_out (int): The number of bits to left-shift each output layer weight. Default: ``0``
        aliases (Optional[List[List[int]]]): For each neuron in the hidden population, a list containing the alias targets for that neuron

    Returns: (:py:class:`.samna.xyloImu.XyloConfiguration`, bool, str): config, is_valid, message
        ``config`` will be a `XyloConfiguration`.
        ``is_valid`` will be a boolean flag ``True`` iff the configuration is valid.
        ``message`` will be an empty string if the configuration is valid, or a message indicating why the configuration is invalid.
    """
    # - Check input weights
    if weights_in.ndim < 2:
        raise ValueError(
            f"Input weights must be at least 2 dimensional `(Nin, Nin_res [, 1])`. Found {weights_in.shape}"
        )

    # - Check output weights
    if weights_out.ndim != 2:
        raise ValueError("Output weights must be 2 dimensional `(Nhidden, Nout)`")

    # - Get network shape
    Nin, Nin_res, Nsyn = weights_in.shape
    Nhidden, Nout = weights_out.shape

    # - Check number of input synapses
    if Nsyn > 1:
        raise ValueError(
            f"Only 1 input synapse is supported on Xylo-IMU. Found {Nsyn}."
        )

    # - Check input and hidden weight sizes
    if Nin_res > Nhidden:
        raise ValueError("Input weight dimension `Nin_res` must be <= `Nhidden`")

    # - Provide default `weights_rec`
    weights_rec = (
        np.zeros((Nhidden, Nhidden, 1), "int") if weights_rec is None else weights_rec
    )

    # - Check `weights_rec`
    if weights_rec.ndim != 3 or weights_rec.shape[0] != weights_rec.shape[1]:
        raise ValueError(
            "Recurrent weights must be of shape `(Nhidden, Nhidden [, 1])`"
        )

    if Nhidden != weights_rec.shape[0]:
        raise ValueError(
            "Input weights must be consistent with recurrent weights.\n"
            f"`weights_in`: {weights_in.shape}; `weights_rec`: {weights_rec.shape}"
        )

    # - Check aliases
    if aliases is not None and len(aliases) != Nhidden:
        raise ValueError(
            f"Aliases list must have `Nhidden` entries (`Nhidden` = {Nhidden})"
        )

    # - Check bitshift TCs, assign defaults
    dash_mem = np.ones(Nhidden, "int") if dash_mem is None else np.array(dash_mem)
    dash_syn = np.ones(Nhidden, "int") if dash_syn is None else np.array(dash_syn)
    if bias_hidden is not None:
        bias_hidden = np.round(np.array(bias_hidden)).astype("int")
    if bias_out is not None:
        bias_out = np.round(np.array(bias_out)).astype("int")

    if np.size(dash_mem) != Nhidden or np.size(dash_syn) != Nhidden:
        raise ValueError(
            f"`dash_mem`, `dash_syn` need `Nhidden` entries (`Nhidden` = {Nhidden})"
            + f" found {np.size(dash_mem)}, {np.size(dash_syn)}"
        )

    dash_mem_out = (
        np.ones(Nout, "int") if dash_mem_out is None else np.array(dash_mem_out)
    )
    dash_syn_out = (
        np.ones(Nout, "int") if dash_syn_out is None else np.array(dash_syn_out)
    )

    if np.size(dash_mem_out) != Nout or np.size(dash_syn_out) != Nout:
        raise ValueError(
            f"`dash_mem_out` and `dash_syn_out` need `Nout` entries (`Nout` = {Nout})"
        )

    # - Check thresholds, assign defaults
    threshold = np.zeros(Nhidden, "int") if threshold is None else np.array(threshold)
    threshold_out = (
        np.zeros(Nout, "int") if threshold_out is None else np.array(threshold_out)
    )

    if threshold.size != Nhidden:
        raise ValueError(
            f"`thresholds` needs `Nhidden` entries (`Nhidden` = {Nhidden})"
        )

    if threshold_out.size != Nout:
        raise ValueError(f"`thresholds_out` needs `Nout` entries (`Nout` = {Nout})")

    # - Check data types
    if (
        weights_in.dtype.kind not in "ui"
        or weights_rec.dtype.kind not in "ui"
        or weights_out.dtype.kind not in "ui"
    ):
        warn(
            "`weights...` arguments should be provided as `int` data types. I am rounding and casting these to `int`."
        )

    if (
        threshold.dtype.kind not in "ui"
        or dash_syn.dtype.kind not in "ui"
        or dash_syn_out.dtype.kind not in "ui"
        or dash_mem.dtype.kind not in "ui"
        or dash_mem_out.dtype.kind not in "ui"
    ):
        warn(
            "Neuron and synapse parameter arguments should be provided as `int` data types. I am rounding and casting these to `int`."
        )

    # - Round and cast all parameters to integer
    weights_in = np.round(weights_in).astype("int8")
    weights_out = np.round(weights_out).astype("int8")
    weights_rec = np.round(weights_rec).astype("int8")
    dash_mem = np.round(dash_mem).astype("int8")
    dash_mem_out = np.round(dash_mem_out).astype("int8")
    dash_syn = np.round(dash_syn).astype("int8")
    dash_syn_out = np.round(dash_syn_out).astype("int8")
    threshold = np.round(threshold).astype("int")
    threshold_out = np.round(threshold_out).astype("int")
    weight_shift_in = np.round(weight_shift_in).astype("int8")
    weight_shift_rec = np.round(weight_shift_rec).astype("int8")
    weight_shift_out = np.round(weight_shift_out).astype("int8")
    if aliases is not None:
        aliases = [np.round(a).astype("int") for a in aliases]

    # - Build the configuration
    config = samna.xyloImu.configuration.XyloConfiguration()

    # general
    config.imu_if_input_enable = False
    config.debug.always_update_omp_stat = True

    if bias_hidden is not None or bias_out is not None:
        config.bias_enable = True

    config.hidden.aliasing = aliases is not None
    config.input.weight_bit_shift = weight_shift_in
    config.hidden.weight_bit_shift = weight_shift_rec
    config.readout.weight_bit_shift = weight_shift_out
    if weights_in.shape[1] > 128:
        warn(
            "More than 128 input expantion neurons (IEN) detected. Only the first 128 will be used."
        )
        config.input.weights = weights_in[:, :128, 0]
    else:
        config.input.weights = weights_in[:, :, 0]
    config.hidden.weights = weights_rec[:, :, 0]
    if weights_out.shape[1] > 128:
        warn(
            "More than 128 output expantion neurons (OEN) detected. Only the last 128 will be used."
        )
        config.readout.weights = weights_out[-128:, :]
    else:
        config.readout.weights = weights_out

    hidden_neurons = []
    for i in range(len(weights_rec)):
        neuron = samna.xyloImu.configuration.HiddenNeuron()
        if aliases is not None and len(aliases[i]) > 0:
            neuron.alias_target = aliases[i][0]

        neuron.i_syn_decay = dash_syn[i]
        neuron.v_mem_decay = dash_mem[i]
        neuron.threshold = threshold[i]
        if bias_hidden is not None:
            neuron.v_mem_bias = bias_hidden[i]
        hidden_neurons.append(neuron)

    config.hidden.neurons = hidden_neurons

    readout_neurons = []
    for i in range(np.shape(weights_out)[1]):
        neuron = samna.xyloImu.configuration.OutputNeuron()
        neuron.i_syn_decay = dash_syn_out[i]
        neuron.v_mem_decay = dash_mem_out[i]
        neuron.threshold = threshold_out[i]
        if bias_out is not None:
            neuron.v_mem_bias = bias_out[i]
        readout_neurons.append(neuron)

    config.readout.neurons = readout_neurons

    # - Validate the configuration and return
    is_valid, message = samna.xyloImu.validate_configuration(config)
    return config, is_valid, message


def if_config_from_specification(
    num_avg_bitshift: int = 6,
    select_iaf_output: bool = False,
    sampling_period: int = 256,
    filter_a1_list: list = [
        -64700,
        -64458,
        -64330,
        -64138,
        -63884,
        -63566,
        -63185,
        -62743,
        -62238,
        -61672,
        -61045,
        -60357,
        -59611,
        -58805,
        -57941,
    ],
    filter_a2_list: list = [0x00007CBF] + [0x00007C0A] * 14,
    scale_values: list = [8] * 15,
    Bb_list: list = [6] * 15,
    B_wf_list: list = [8] * 15,
    B_af_list: list = [9] * 15,
    iaf_threshold_values: list = [0x000007D0] * 15,
    *args,
    **kwargs,
) -> InputInterfaceConfig:
    """
    Configure the imu interface module

    Args:
        config (XyloConfiguration): a configuration for Xylo IMU
        num_avg_bitshift (int): number of bitshifts used in the low-pass filter implementation
        select_iaf_output (bool): if True, select the IAF neuron spike encoder; else, select the scale spike encoder
        sampling_period (int): sampling period
        filter_a1_list (list): list of a1 tap values
        filter_a2_list (list): list of a2 tap values
        scale_values (list): list of number of right-bit-shifts needed for down-scaling the input signal
        Bb_list (list): list of bits needed for scaling b0
        B_wf_list (list): list of bits needed for fractional part of the filter output
        B_af_list (list): list of bits needed for encoding the fractional parts of taps
        iaf_threshold_values (list): list of threshold values of IAF neurons

    Return:
        updated Xylo configuration
    """

    if_config = samna.xyloImu.configuration.InputInterfaceConfig()

    # IMU interface hyperparameters
    if_config.enable = True
    if_config.estimator_k_setting = num_avg_bitshift  # num_avg_bitshift
    if_config.select_iaf_output = select_iaf_output  # True if use IAF encoding
    if_config.update_matrix_threshold = sampling_period - 1  # sampling_period
    if_config.delay_threshold = 1
    if_config.bpf_bb_values = Bb_list
    if_config.bpf_bwf_values = B_wf_list
    if_config.bpf_baf_values = B_af_list
    if_config.bpf_a1_values = [i & 0x1FFFF for i in filter_a1_list]
    if_config.bpf_a2_values = filter_a2_list
    if_config.scale_values = scale_values  # num_scale_bits
    if_config.iaf_threshold_values = iaf_threshold_values

    return if_config


def save_config(config: XyloConfiguration, filename: str) -> None:
    """
    Save a Xylo configuration to disk in JSON format

    Args:
        config (XyloConfiguration): The configuration to write
        filename (str): The filename to write to
    """
    with open(filename, "w") as f:
        f.write(config.to_json())


def load_config(filename: str) -> XyloConfiguration:
    """
    Read a Xylo configuration from disk in JSON format

    Args:
        filename (str): The filename to read from

    Returns:
        `.XyloConfiguration`: The configuration loaded from disk
    """
    # - Create a new config object
    conf = XyloConfiguration()

    # - Read the configuration from file
    with open(filename) as f:
        conf.from_json(f.read())

    # - Return the configuration
    return conf


class XyloSamna(Module):
    """
    A spiking neuron :py:class:`.Module` backed by the Xylo hardware, via `samna`.

    Use :py:func:`.config_from_specification` to build and validate a configuration for Xylo.

    See Also:

        See the tutorials :ref:`/devices/xylo-overview.ipynb` and :ref:`/devices/torch-training-spiking-for-xylo.ipynb` for a high-level overview of building and deploying networks for Xylo.

    """

    def __init__(
        self,
        device: XyloIMUHDK,
        config: XyloConfiguration = None,
        dt: float = 1e-3,
        output_mode: str = "Spike",
        power_frequency: Optional[float] = 5.0,
        *args,
        **kwargs,
    ):
        """
        Instantiate a Module with Xylo dev-kit backend

        Args:
            device (XyloA2HDK): An opened `samna` device to a Xylo dev kit
            config (XyloConfiguration): A Xylo configuration from `samna`
            dt (float): The simulation time-step to use for this Module
            output_mode (str): The readout mode for the Xylo device. This must be one of ``["Spike", "Isyn", "Vmem"]``. Default: "Spike", return events from the output layer.
            power_frequency (float): The frequency of power measurement. Default: 5.0
        """

        # - Check input arguments
        if device is None:
            raise ValueError("`device` must be a valid, opened Xylo HDK device.")

        # - Check output mode specification
        if output_mode not in ["Spike", "Vmem", "Isyn"]:
            raise ValueError(
                f'{output_mode} is not supported. Must be one of `["Spike", "Vmem", "Isyn"]`.'
            )
        self._output_mode = output_mode

        # - Get a default configuration
        if config is None:
            config = samna.xyloImu.configuration.XyloConfiguration()

        # - Get the network shape
        Nin, Nhidden = np.shape(config.input.weights)
        _, Nout = np.shape(config.readout.weights)

        # - Initialise the superclass
        super().__init__(
            shape=(Nin, Nhidden, Nout), spiking_input=True, spiking_output=True
        )

        # - Store the device
        self._device: XyloIMUHDK = device
        """ `.XyloHDK`: The Xylo HDK used by this module """

        # - Register buffers to read and write events, monitor state
        self._read_buffer = hdkutils.new_xylo_read_buffer(device)
        self._write_buffer = hdkutils.new_xylo_write_buffer(device)
        self._state_buffer = hdkutils.new_xylo_state_monitor_buffer(device)

        # - Store the io module
        self._io = device.get_io_module()

        # - Store the timestep
        self.dt: Union[float, SimulationParameter] = dt
        """ float: Simulation time-step of the module, in seconds """

        # - Store the configuration (and apply it)
        self.config: Union[
            XyloConfiguration, SimulationParameter
        ] = SimulationParameter(shape=(), init_func=lambda _: config)
        """ `.XyloConfiguration`: The HDK configuration applied to the Xylo module """

        # - Keep a registry of the current recording mode, to save unnecessary reconfiguration
        self._last_record_mode: Optional[bool] = None
        """ bool: The most recent (and assumed still valid) recording mode """

        # - Store the timestep
        self.dt: Union[float, SimulationParameter] = dt
        """ float: Simulation time-step of the module, in seconds """

        # - Set power measurement module
        self._power_buf, self.power = hdkutils.set_power_measure(
            self._device, power_frequency
        )

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
        hdkutils.apply_configuration(self._device, new_config)
        self._state_buffer.set_configuration(new_config)
        self._config = new_config

    def _configure_accel_time_mode(
        self, Nhidden: int, Nout: int, record: bool = False
    ) -> None:
        """
        Configure the Xylo HDK to use accelerated-time mode, with optional state recording

        Args:
            Nhidden (int): Number of hidden neurons from which to record state. Default: ``0``; do not record state from any neurons. If non-zero, state from neurons with ID 0..(Nhidden-1) inclusive will be recorded during evolution.
            Nout (int): Number of output layer neurons from which to record state. Default: ``0``; do not record state from any output neurons.
            record (bool): Iff ``True``, record state during evolution. Default: ``False``, do not record state.
        """
        if record != self._last_record_mode:
            # - Keep a registry of the last recording mode
            self._last_record_mode = record

            self.config, state_buffer = hdkutils.configure_accel_time_mode(
                self._device,
                self._config,
                self._state_buffer,
                Nhidden,
                Nout,
                readout=self._output_mode,
                record=record,
            )

    def _config_hibernation_mode(self):
        """
        Configure the Xylo HDK to use hibernation mode
        """
        self.config = hdkutils.config_hibernation_mode(self._config, True)

    def evolve(
        self,
        input: np.ndarray,
        record: bool = False,
        record_power: bool = False,
        *args,
        **kwargs,
    ) -> Tuple[np.ndarray, dict, dict]:
        """
        Evolve a network on the Xylo HDK in accelerated-time mode

        Sends a series of events to the Xylo HDK, evolves the network over the input events, and returns the output events produced during the input period. Optionally record internal state of the network, selectable with the ``record`` flag.

        Args:
            input (np.ndarray): A raster ``(T, Nin)`` specifying for each bin the number of input events sent to the corresponding input channel on Xylo, at the corresponding time point. Up to 15 input events can be sent per bin.
            record (bool): Iff ``True``, record and return all internal state of the neurons and synapses on Xylo. Default: ``False``, do not record internal state.
            record_power (bool): Iff ``True``, record the power consumption during each evolve.

        Returns:
            (np.ndarray, dict, dict): ``output``, ``new_state``, ``record_dict``.
            ``output`` is a raster ``(T, Nout)``, containing events for each channel in each time bin. Time bins in ``output`` correspond to the time bins in ``input``.
            ``new_state`` is an empty dictiionary. The Xylo HDK does not permit querying or setting state.
            ``record_dict`` is a dictionary containing recorded internal state of Xylo during evolution, if the ``record`` argument is ``True``. Otherwise this is an empty dictionary.
        """

        # - Get the network size
        Nin, Nhidden, Nout = self.shape[:]

        # - Configure the recording mode
        self._configure_accel_time_mode(Nhidden, Nout, record)

        start_timestep = hdkutils.get_current_timestamp(
            self._read_buffer, self._write_buffer
        )
        final_timestamp = start_timestep + len(input) - 1

        # -- Encode input events
        input_events_list = []

        # - Locate input events
        spikes = np.argwhere(input)
        counts = input[np.nonzero(input)]

        # - Generate input events
        for timestep, channel, count in zip(spikes[:, 0], spikes[:, 1], counts):
            for _ in range(count):
                event = samna.xyloImu.event.Spike()
                event.neuron_id = channel
                event.timestamp = start_timestep + timestep
                input_events_list.append(event)

        # - Add an extra event to ensure readout for entire input extent
        event = samna.xyloImu.event.Spike()
        event.timestamp = final_timestamp + 1
        input_events_list.append(event)

        # - Clear the input registers to ensure the dummy event has no effect
        input_events_list.extend(hdkutils.gen_clear_input_registers_events())

        # - Clear the read and state buffers
        self._state_buffer.reset()

        # - Write the events and trigger the simulation
        self._write_buffer.write(input_events_list)

        # - Read the simulation output data
        xylo_data = hdkutils.read_accel_mode_data(
            self._state_buffer, Nin, Nhidden, Nout, len(input)
        )

        if record_power:
            # - Get all recent power events from the power measurement
            ps = self._power_buf.get_events()

            # - Separate out power meaurement events by channel
            channels = samna.xyloImuBoards.MeasurementChannels
            io_power = np.array([e.value for e in ps if e.channel == int(channels.Io)])
            core_power = np.array(
                [e.value for e in ps if e.channel == int(channels.Core)]
            )

        if record:
            rec_dict = {
                "Vmem": np.array(xylo_data.V_mem_hid),
                "Isyn": np.array(xylo_data.I_syn_hid),
                "Spikes": np.array(xylo_data.Spikes_hid),
                "Vmem_out": np.array(xylo_data.V_mem_out),
                "Isyn_out": np.array(xylo_data.I_syn_out),
                "times": np.arange(start_timestep, final_timestamp + 1),
            }
        else:
            rec_dict = {}

        # - Return power recordings if requested
        if record_power:
            rec_dict.update(
                {
                    "io_power": io_power,
                    "core_power": core_power,
                }
            )

        # - This module holds no state
        new_state = {}

        # - Return spike output, new state and record dictionary
        if self._output_mode == "Spike":
            return xylo_data.Spikes_out, new_state, rec_dict
        elif self._output_mode == "Isyn":
            return xylo_data.I_syn_out, new_state, rec_dict
        elif self._output_mode == "Vmem":
            return xylo_data.V_mem_out, new_state, rec_dict
