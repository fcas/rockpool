"""
Low-level device kit utilities for the Xylo AFE2 HDK
"""

import samna, time
import numpy as np

from typing import List, Any


Xylo2ReadBuffer = samna.BasicSinkNode_xylo_core2_event_output_event
AFE2ReadBuffer = samna.BasicSinkNode_afe2_event_output_event
AFE2WriteBuffer = samna.BasicSourceNode_afe2_event_input_event
AFE2OutputEvent = samna.afe2.event.Spike
AFE2HDK = Any
Xylo2HDK = Any


def find_xylo_afe2_boards() -> List[AFE2HDK]:
    """
    Search for and return a list of Xylo AFE V2 HDKs

    Iterate over devices and search for Xylo AFE V2 HDK nodes. Return a list of available AFE HDKs, or an empty list if none are found.

    Returns:
        List[AFEHDK]: A (possibly empty) list of AFE HDK nodes.
    """
    # - Get a list of devices
    device_list = samna.device.get_all_devices()

    # - Search for a xylo dev kit
    afev2_hdk_list = [
        samna.device.open_device(d)
        for d in device_list
        if d.device_type_name == "XyloA2TestBoard"
    ]

    return afev2_hdk_list


def read_afe2_register(
        read_buffer: AFE2ReadBuffer,
        write_buffer: AFE2WriteBuffer,
        address: int,
        timeout: float = 2.0,
) -> List[int]:
    """
    Read the contents of a register

    Args:
        read_buffer (AFE2ReadBuffer): A connected read buffer to the XYlo HDK
        write_buffer (AFE2WriteBuffer): A connected write buffer to the Xylo HDK
        address (int): The register address to read
        timeout (float): A timeout in seconds

    Returns:
        List[int]: A list of events returned from the read
    """
    # - Set up a register read
    rrv_ev = samna.afe2.event.ReadRegisterValue()
    rrv_ev.address = address

    # - Request read
    write_buffer.write([rrv_ev])

    # - Wait for data and read it
    start_t = time.time()
    continue_read = True
    while continue_read:
        # - Read from the buffer
        events = read_buffer.get_events()

        # - Filter returned events for the desired address
        ev_filt = [e for e in events if hasattr(e, "address") and e.address == address]

        # - Should we continue the read?
        continue_read &= len(ev_filt) == 0
        continue_read &= (time.time() - start_t) < timeout

    # - If we didn't get the required register read, raise an error
    if len(ev_filt) == 0:
        raise TimeoutError(f"Timeout after {timeout}s when reading register {address}.")

    # - Return adta
    return [e.data for e in ev_filt]


def write_afe2_register(write_buffer: AFE2WriteBuffer, register: int, data: int = 0) -> None:
    """
    Write data to a register on a Xylo AFE2 HDK

    Args:
        write_buffer (AFE2WriteBuffer): A connected write buffer to the desintation Xylo AFE2 HDK
        register (int): The address of the register to write to
        data (int): The data to write. Default: 0x0
    """
    wwv_ev = samna.afe2.event.WriteRegisterValue()
    wwv_ev.address = register
    wwv_ev.data = data
    write_buffer.write([wwv_ev])


def read_afe2_events_blocking(afe2hdk: AFE2HDK, write_buffer: AFE2WriteBuffer, afe_read_buf: AFE2ReadBuffer,
                              duration: float) -> (np.ndarray, np.ndarray):
    """
    Perform a blocking read of AFE2 audio spike events for a desired duration

    Args:
        afe2hdk (AFE2HDK): A device node for an AFE2 HDK
        write_buffer (AFE2WriteBuffer): A connected write buffer to an AFE2 HDK
        afe_read_buf (AFE2ReadBuffer): A connected read buffer from an AFE2 HDK
        duration (float): The desired duration to record from, in seconds

    Returns:
        (np.ndarray, np.ndarray) timestamps, channels
        timestamps: A list of event timestamps, in seconds from the start of recording
        channels: A list of event channels, corresponding to the event timestamps
    """
    # - Get AFE handler
    afe_handler = afe2hdk.get_io_module().get_afe_handler()

    # - Enable AER monitor mode for AFE2
    write_afe2_register(write_buffer, 0x45, 0x30000)
    # time.sleep(0.1)

    # - Clear events buffer
    afe_read_buf.get_events()

    # - Trigger recording for desired duration
    afe2hdk.get_stop_watch().set_enable_value(True)
    afe2hdk.get_stop_watch().reset()
    afe_handler.enable_event_monitor(True)
    time.sleep(duration)
    afe_handler.enable_event_monitor(False)
    time.sleep(0.1)
    
    # write_spi(0x45,0)
    # time.sleep(0.5)

    # - Read and filter events
    events = afe_read_buf.get_events()
    events = [(e.timestamp, e.channel)
              for e in events
              if isinstance(e, samna.afe2.event.Spike) and e.timestamp <= duration * 1e6
              ]
    
    # - Sort events by time
    events = np.stack(events)
    index_array = np.argsort(events[:, 0])

    # - Convert to vectors of timestamps, channels
    timestamps = events[index_array, 0]
    channels = events[index_array, 1]
    
    # - Return timestamps in seconds and channels
    return timestamps * 1e-6, channels


def afe2_test_config_c(afe_write_buf: AFE2WriteBuffer) -> None:
    """
    Configure an AFE2 HDK for a "reasonable" performance
    """
    write_afe2_register(afe_write_buf, 0x1, 0x71317)  # all top bias enable
    write_afe2_register(afe_write_buf, 0x02, 0xffffffff)  # all-channel enable
    write_afe2_register(afe_write_buf, 0x04, 0x2100)  # lna vcm
    write_afe2_register(afe_write_buf, 0x05, 0x62000000)  # top vcm 
    write_afe2_register(afe_write_buf, 0x06, 0x20550)  # lna 0db gain
    write_afe2_register(afe_write_buf, 0x07, 0x883704)  # bpf 100-10khz q=5,space=1.35
    write_afe2_register(afe_write_buf, 0x14, 0x30000)  # disable mgm bias  
    write_afe2_register(afe_write_buf, 0x10, 0x23112400)
    write_afe2_register(afe_write_buf, 0x11, 0x15000104)
    write_afe2_register(afe_write_buf, 0xf, 0x88888f88)
