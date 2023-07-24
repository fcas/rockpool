from typing import Optional, Tuple
import samna
import time
import math
import numpy as np


from rockpool.nn.modules.module import Module
from . import xylo_imu_devkit_utils as hdkutils
from .xylo_imu_devkit_utils import XyloIMUHDK


__all__ = ["XyloIMUData"]


class XyloIMUData(Module):
    """
    Interface to the IMU sensor on a Xylo-Imu HDK

    This module uses ``samna`` to interface to the IMU hardware on a Xylo-IMU HDK. It permits recording from the IMU sensor.

    To record from the module, use the :py:meth:`~.XyloImuData.evolve` method. You need to pass this method an empty matrix, with the desired number of time-steps. The time-step ``dt`` is specified at module instantiation.
    """

    def __init__(
        self,
        device: XyloIMUHDK,
        frequency: float = 20.0,
        *args,
        **kwargs,
    ):
        """
        Instantiate a XyloIMUData Module, via a samna backend

        Args:
            device (XyloIMUHDK): A connected XyloIMUHDK device.
            frequency (float): The frequency to read data from IMU sensor. Default: 20.0
        """

        # - Check device validation
        if device is None:
            raise ValueError("`device` must be a valid, opened Xylo IMU HDK device.")

        # - Store the device
        self._device: XyloIMUHDK = device
        """ `.XyloHDK`: The Xylo HDK used by this module """

        # - Register buffers to read and write events
        self._read_buffer, self._write_buffer, mc = hdkutils.initialise_imu_sensor(
            device
        )

        # - Store the IMU sensor
        self._mc = mc

        # - Store the dt
        self.dt = 1 / frequency

        # - Set the frequency and config the IMU sensor to ready for data reading
        hdkutils.config_imu_sensor(self._mc, frequency)

    def evolve(
        self,
        input_data,
        timeout: Optional[float] = None,
    ) -> Tuple[np.ndarray, dict, dict]:
        """
        Use the IMU sensor to record live IMU data and return

        Args:
            input_data (np.ndarray): An array ``[T, 3]``, specifying the number of time-steps to record.

        Returns:
            (np.ndarray, dict, dict) output_events, {}, {}
        """

        # - Ensure data is a float tensor
        data = np.array(input_data, "float")

        # - Verify input data shape
        if len(data.shape) == 1:
            data = np.expand_dims(data, 0)
            data = np.expand_dims(data, 2)
        elif len(data.shape) == 2:
            data = np.expand_dims(data, 0)

        # - Get the shape of the output data
        Nb, Nt, Nc = data.shape

        # - Check batch size
        if Nb > 1:
            raise ValueError(
                f"Batched data are not supported by IMUData. Got batched input data with shape {[Nb, Nt, Nc]}."
            )

        out = []
        count = 0

        # - Determine a read timeout
        timeout = 2 * Nt * self.dt if timeout is None else timeout

        # - Clear the read buffer to ensure no previous events influence
        self._read_buffer.get_events()

        # - Start recording time
        t_start = time.time()
        t_timeout = t_start + timeout

        while count < int(Nt):
            evts = self._read_buffer.get_events()
            for e in evts:
                if isinstance(e, samna.events.Acceleration) and count < int(Nt):
                    count += 1
                    x = e.x * 4 / math.pow(2, 14)
                    y = e.y * 4 / math.pow(2, 14)
                    z = e.z * 4 / math.pow(2, 14)
                    out.append([x, y, z])

                # - Check for read timeout
                if time.time() > t_timeout:
                    raise TimeoutError(f"IMUSensor: Read timeout of {timeout} sec.")

        out = np.array(out)

        return out, {}, {}
