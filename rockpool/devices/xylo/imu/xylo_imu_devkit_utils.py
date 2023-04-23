"""
Low-level device kit utilities for the SYNS61201 Xylo-A2 HDK
"""

import enum
from ipaddress import IPv4Network
from rockpool.utilities.backend_management import backend_available

if not backend_available("samna"):
    raise ModuleNotFoundError(
        "`samna` not found. The Xylo HDK requires `samna` for interfacing."
    )

import samna
from samna.xyloImu.configuration import XyloConfiguration

# - Other imports
from warnings import warn
import time
import numpy as np
from pathlib import Path
from os import makedirs
import json
from bitstruct import pack_dict, unpack_dict


# - Typing and useful proxy types
from typing import Any, List, Iterable, Optional, NamedTuple, Union, Tuple

XyloIMUReadBuffer = samna.BasicSinkNode_xylo_imu_event_output_event
XyloIMUWriteBuffer = samna.BasicSourceNode_xylo_imu_event_input_event
XyloIMUNeuronStateBuffer = samna.xyloImu.NeuronStateSinkNode

XyloIMUHDK = Any


def find_xylo_imu_boards() -> List[XyloIMUHDK]:
    """
    Search for and return a list of Xylo AFE V2 HDKs

    Iterate over devices and search for Xylo AFE V2 HDK nodes. Return a list of available AFE HDKs, or an empty list if none are found.

    Returns:
        List[AFEHDK]: A (possibly empty) list of AFE HDK nodes.
    """

    # - Search for a xylo dev kit
    afev2_hdk_list = [samna.device.open_device("XyloImuTestBoard:0")]

    return afev2_hdk_list


def new_xylo_read_buffer(
    hdk: XyloIMUHDK,
) -> XyloIMUReadBuffer:
    """
    Create and connect a new buffer to read from a Xylo HDK

    Args:
        hdk (XyloDaughterBoard):

    Returns:
        samna.BasicSinkNode_xylo_event_output_event: Output buffer receiving events from Xylo HDK
    """
    # - Register a buffer to read events from Xylo
    buffer = XyloIMUReadBuffer()

    # - Get the device model
    model = hdk.get_model()

    # - Get Xylo output event source node
    source_node = model.get_source_node()

    # - Add the buffer as a destination for the Xylo output events
    graph = samna.graph.EventFilterGraph()
    graph.sequential([source_node, buffer])

    # - Return the buffer
    return buffer


def new_xylo_write_buffer(hdk: XyloIMUHDK) -> XyloIMUWriteBuffer:
    """
    Create a new buffer for writing events to a Xylo HDK

    Args:
        hdk (XyloDaughterBoard): A Xylo HDK to create a new buffer for

    Returns:
        XyloWriteBuffer: A connected event write buffer
    """
    buffer = XyloIMUWriteBuffer()
    sink = hdk.get_model().get_sink_node()
    graph = samna.graph.EventFilterGraph()
    graph.sequential([buffer, sink])

    return buffer


def new_xylo_state_monitor_buffer(
    hdk: XyloIMUHDK,
) -> XyloIMUNeuronStateBuffer:
    """
    Create a new buffer for monitoring neuron and synapse state and connect it

    Args:
        hdk (XyloDaughterBoard): A Xylo HDK to configure

    Returns:
        XyloNeuronStateBuffer: A connected neuron / synapse state monitor buffer
    """
    # - Register a new buffer to receive neuron and synapse state
    buffer = XyloIMUNeuronStateBuffer()

    # - Get the device model
    model = hdk.get_model()

    # - Get Xylo output event source node
    source_node = model.get_source_node()

    # - Add the buffer as a destination for the Xylo output events
    graph = samna.graph.EventFilterGraph()
    graph.sequential([source_node, buffer])

    # - Return the buffer
    return buffer


def new_xylo_source(hdk: XyloIMUHDK,):
    source = samna.graph.source_to(hdk.get_model_sink_node())
    return source


def initialise_xylo_hdk(write_buffer: XyloIMUWriteBuffer) -> None:
    """
    Initialise the Xylo HDK

    Args:
        write_buffer (XyloIMUWriteBuffer): A write buffer connected to a Xylo HDK to initialise
    """
    # - Always need to advance one time-step to initialise
    advance_time_step(write_buffer)


def advance_time_step(write_buffer: XyloIMUWriteBuffer) -> None:
    """
    Take a single manual time-step on a Xylo HDK

    Args:
        write_buffer (XyloIMUWriteBuffer): A write buffer connected to the Xylo HDK
    """
    e = samna.xyloImu.event.TriggerProcessing()
    write_buffer.write([e])


def verify_xylo_version(
    read_buffer: XyloIMUReadBuffer,
    write_buffer: XyloIMUWriteBuffer,
    timeout: float = 1.0,
) -> bool:
    """
    Verify that the provided daughterbaord returns the correct version ID for Xylo

    Args:
        read_buffer (XyloIMUReadBuffer): A read buffer connected to the Xylo HDK
        write_buffer (XyloIMUWriteBuffer): A write buffer connected to the Xylo HDK
        timeout (float): Timeout for checking in seconds

    Returns:
        bool: ``True`` iff the version ID is correct for Xylo V2
    """
    # - Clear the read buffer
    read_buffer.get_events()

    # - Read the version register
    write_buffer.write([samna.xyloImu.event.ReadVersion()])

    # - Read events until timeout
    filtered_events = []
    t_end = time.time() + timeout
    while len(filtered_events) == 0:
        events = read_buffer.get_events()
        filtered_events = [
            e for e in events if isinstance(e, samna.xyloImu.event.Version)
        ]

        # - Check timeout
        if time.time() > t_end:
            raise TimeoutError(f"Checking version timed out after {timeout}s.")

    return (
        (len(filtered_events) > 0)
        and (filtered_events[0].major == 1)
        and (filtered_events[0].minor == 1)
    )


def set_power_measure(
    hdk: XyloIMUHDK,
    frequency: Optional[float] = 5.0,
) -> Tuple[
    samna.BasicSinkNode_unifirm_modules_events_measurement,
    samna.boards.common.power.PowerMonitor,
]:
    """
    Initialize power consumption measure on a hdk

    Args:
        hdk (XyloHDK): The Xylo HDK to be measured
        frequency (float): The frequency of power measurement. Default: 5.0

    Returns:
        power_buf: Event buffer to read power monitoring events from
        power_monitor: The power monitoring object
    """
    power_monitor = hdk.get_power_monitor()
    power_buf = samna.BasicSinkNode_unifirm_modules_events_measurement()
    graph = samna.graph.EventFilterGraph()
    graph.sequential([power_monitor.get_source_node(), power_buf])
    power_monitor.start_auto_power_measurement(frequency)
    return power_buf, power_monitor


def reset_neuron_synapse_state(
    hdk: XyloIMUHDK,
    read_buffer: XyloIMUReadBuffer,
    write_buffer: XyloIMUWriteBuffer,
) -> None:
    """
    Reset the neuron and synapse state on a Xylo HDK

    Args:
        hdk (XyloIMUHDK): The Xylo HDK hdk to reset
        read_buffer (XyloIMUReadBuffer): A read buffer connected to the Xylo HDK to reset
        write_buffer (XyloIMUWriteBuffer): A write buffer connected to the Xylo HDK to reset
    """
    # - Get the current configuration
    config = hdk.get_model().get_configuration()

    # - Reset via configuration
    config.clear_network_state = True
    apply_configuration(hdk, config, read_buffer, write_buffer)


def apply_configuration(
    hdk: XyloIMUHDK,
    config: XyloConfiguration,
    *_,
    **__,
) -> None:
    """
    Apply a configuration to the Xylo HDK

    Args:
        hdk (XyloHDK): The Xylo HDK to write the configuration to
        config (XyloConfiguration): A configuration for Xylo
    """
    # - Ideal -- just write the configuration using samna
    hdk.get_model().apply_configuration(config)


def configure_accel_time_mode(
    config: XyloConfiguration,
    state_monitor_buffer: XyloIMUNeuronStateBuffer,
    monitor_Nhidden: Optional[int] = 0,
    monitor_Noutput: Optional[int] = 0,
    readout="Spike",
    record=False,
) -> Tuple[XyloConfiguration, XyloIMUNeuronStateBuffer]:
    """
    Switch on accelerated-time mode on a Xylo hdk, and configure network monitoring

    Notes:
        Use :py:func:`new_xylo_state_monitor_buffer` to generate a buffer to monitor neuron and synapse state.

    Args:
        config (XyloConfiguration): The desired Xylo configuration to use
        state_monitor_buffer (XyloIMUNeuronStateBuffer): A connected neuron state monitor buffer
        monitor_Nhidden (Optional[int]): The number of hidden neurons for which to monitor state during evolution. Default: ``0``, don't monitor any hidden neurons.
        monitor_Noutput (Optional[int]): The number of output neurons for which to monitor state during evolution. Default: ``0``, don't monitor any output neurons.
        readout: The readout out mode for which to output neuron states. Default: ``Spike''. Must be one of ``['Vmem', 'Spike']``.
        record (bool): Iff ``True``, record state during evolution. Default: ``False``, do not record state.

    Returns:
        (XyloConfiguration, XyloIMUNeuronStateBuffer): `config` and `monitor_buffer`
    """
    assert readout in ["Vmem", "Spike"], f"{readout} is not supported."

    # - Select accelerated time mode
    config.operation_mode = samna.xyloImu.OperationMode.AcceleratedTime

    config.debug.monitor_neuron_spike = None
    config.debug.monitor_neuron_v_mem = None

    if record:
        config.debug.monitor_neuron_spike = samna.xyloImu.configuration.NeuronRange(
            0, monitor_Nhidden
        )
        config.debug.monitor_neuron_v_mem = samna.xyloImu.configuration.NeuronRange(
            0, monitor_Nhidden + monitor_Noutput
        )

    else:
        config.debug.monitor_neuron_v_mem = samna.xyloImu.configuration.NeuronRange(
            monitor_Nhidden, monitor_Nhidden + monitor_Noutput
        )

    # - Configure the monitor buffer
    state_monitor_buffer.set_configuration(config)

    # - Return the configuration and buffer
    return config, state_monitor_buffer


def config_hibernation_mode(
    config: XyloConfiguration, hibernation_mode: bool
) -> XyloConfiguration:
    """
    Switch on hibernaton mode on a Xylo hdk

    Args:
        config (XyloConfiguration): The desired Xylo configuration to use
    """
    config.enable_hibernation_mode = hibernation_mode
    return config


def config_auto_mode(
    config: XyloConfiguration,
    dt: float,
    main_clk_rate: int,
    io,
) -> XyloConfiguration:
    """
    Set the Xylo HDK to manual mode before configure to real-time mode

    Args:
        config (XyloConfiguration): A configuration for Xylo

    Return:
        updated Xylo configuration
    """
    io.write_config(0x11, 0)
    config.operation_mode = samna.xyloImu.OperationMode.RealTime
    config.bias_enable = True
    config.hidden.aliasing = True
    config.debug.always_update_omp_stat = True
    config.imu_if_input_enable = True
    config.debug.imu_if_clk_enable = True
    config.time_resolution_wrap = int(dt * main_clk_rate)
    config.debug.imu_if_clock_freq_div = 0x169

    return config


def config_if_module(
    config: XyloConfiguration,
    num_avg_bitshift=6,
    select_iaf_output=False,
    sampling_period=256,
    filter_a1_list=[
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
    filter_a2_list=[0x00007CBF] + [0x00007C0A] * 14,
    scale_values=[8] * 15,
    Bb_list=[6] * 15,
    B_wf_list=[8] * 15,
    B_af_list=[9] * 15,
    iaf_threshold_values=[0x000007D0] * 15,
    *args,
    **kwargs,
):
    # Preprocessing hyperparameters
    config.input_interface.enable = True
    config.input_interface.estimator_k_setting = num_avg_bitshift  # num_avg_bitshift
    config.input_interface.select_iaf_output = (
        select_iaf_output  # True if use IAF encoding
    )
    config.input_interface.update_matrix_threshold = (
        sampling_period - 1
    )  # sampling_period
    config.input_interface.delay_threshold = 1
    config.input_interface.bpf_bb_values = Bb_list
    config.input_interface.bpf_bwf_values = B_wf_list
    config.input_interface.bpf_baf_values = B_af_list
    config.input_interface.bpf_a1_values = [i & 0x1FFFF for i in filter_a1_list]
    config.input_interface.bpf_a2_values = filter_a2_list
    config.input_interface.scale_values = scale_values  # num_scale_bits
    config.input_interface.iaf_threshold_values = iaf_threshold_values

    return config
