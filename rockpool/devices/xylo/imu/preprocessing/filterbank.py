"""
Hardware butterworth filter implementation for the Xylo IMU.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from rockpool.devices.xylo.imu.preprocessing.utils import (
    type_check,
    unsigned_bit_range_check,
    signed_bit_range_check,
)
from rockpool.nn.modules.module import Module

B_IN = 16
"""Number of input bits that can be processed with the block diagram"""

B_WORST_CASE: int = 9
"""Number of additional bits devoted to storing filter taps such that no over- and under-flow can happen"""

__all__ = ["FilterBank", "BandPassFilter"]


@dataclass(eq=False, repr=False)
class BandPassFilter:
    """
    Class containing the parameters of the filter in state-space representation
    This is the block-diagram structure proposed for implementation.
    """

    B_b: int = 6
    """Bits needed for scaling b0"""

    B_wf: int = 8
    """Bits needed for fractional part of the filter output"""

    B_af: int = 9
    """Bits needed for encoding the fractional parts of taps"""

    a1: int = 73131
    """Integer representation of a1 tap"""

    a2: int = 31754
    """Integer representation of a2 tap"""

    def __post_init__(self) -> None:
        """
        Check the validity of the parameters.
        """
        self.B_w = B_IN + B_WORST_CASE + self.B_wf
        """Total number of bits devoted to storing the values computed by the AR-filter."""

        self.B_out = B_IN + B_WORST_CASE
        """Total number of bits needed for storing the values computed by the WHOLE filter."""

        unsigned_bit_range_check(self.B_b, n_bits=4)
        unsigned_bit_range_check(self.B_wf, n_bits=4)
        unsigned_bit_range_check(self.B_af, n_bits=4)
        signed_bit_range_check(self.a1, n_bits=17)
        signed_bit_range_check(self.a2, n_bits=17)

    @type_check
    def compute_AR(self, signal: np.ndarray) -> np.ndarray:
        """
        Compute the AR part of the filter in the block-diagram with the given parameters.

        Args:
            signal (np.ndarray): the quantized input signal in python-object integer format.

        Raises:
            OverflowError: if any overflow happens during the filter computation.

        Returns:
            np.ndarray: the output signal of the AR filter.
        """

        # check that the input is within the valid range of block-diagram

        unsigned_bit_range_check(np.max(np.abs(signal)), n_bits=B_IN - 1)

        output = []

        # w[n], w[n-1], w[n-2]
        w = [0, 0, 0]

        for val in signal:
            # Computation after the clock edge
            w_new = (val << self.B_wf) + (
                (-self.a2 * w[2] - self.a1 * w[1]) >> self.B_af
            )
            w_new = w_new >> self.B_b

            w[0] = w_new

            # register shift at the rising edge of the clock
            w[1], w[2] = w[0], w[1]

            output.append(w[0])

            # check the overflow: here we have the integer version

        unsigned_bit_range_check(np.max(np.abs(output)), n_bits=self.B_w - 1)
        # convert into numpy
        return np.asarray(output, dtype=object)

    @type_check
    def compute_MA(self, signal: np.ndarray) -> np.ndarray:
        """
        Compute the MA part of the filter in the block-diagram representation.

        Args:
            signal (np.ndarray): input signal (in this case output of AR part) of datatype `pyton.object`.

        Raises:
            OverflowError: if any overflow happens during the filter computation.

        Returns:
            np.ndarray: quantized filtered output signal.
        """

        # check dimension
        if signal.ndim > 1:
            raise ValueError("input signal should be 1-dim.")

        sig_out = np.copy(signal)
        sig_out[2:] = sig_out[2:] - signal[:-2]

        # apply the last B_wf bitshift to get rid of additional scaling needed to avoid dead-zone in the AR part
        sig_out = sig_out >> self.B_wf

        # check the validity of the computed output
        unsigned_bit_range_check(np.max(np.abs(sig_out)), n_bits=self.B_out - 1)
        return sig_out

    @type_check
    def __call__(self, signal: np.ndarray):
        """
        Combine the filtering done in the AR and MA part of the block-diagram representation.

        Args:
            sig_in (np.ndarray): quantized input signal of python.object integer type.

        Raises:
            OverflowError: if any overflow happens during the filter computation.

        Returns:
            np.nadarray: quantized filtered output signal.
        """
        signal = self.compute_AR(signal)
        signal = self.compute_MA(signal)
        return signal


class FilterBank(Module):
    """
    This class builds the block-diagram version of the filters, which is exactly as it is done in FPGA.

    NOTE: Here we have considered a collection of `candidate` band-pass filters that have the potential to be chosen and implemented by the algorithm team.
    Here we make sure that all those filters work properly.
    """

    def __init__(
        self,
        shape: Optional[Union[Tuple, int]] = (3, 15),
        B_b_list: List[int] = [6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6],
        B_wf_list: List[int] = [8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8],
        B_af_list: List[int] = [9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9],
        a1_list: List[int] = [
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
        a2_list: List[int] = [
            31935,
            31754,
            31754,
            31754,
            31754,
            31754,
            31754,
            31754,
            31754,
            31754,
            31754,
            31754,
            31754,
            31754,
            31754,
        ],
    ) -> None:
        """Object Constructor

        Args:
            shape (Optional[Union[Tuple, int]], optional): The number of input and output channels. Defaults to (3,15).
            B_b_list (List[int], optional): The list of the B_b parameters of each filter. B_b stands for bits needed for scaling b0. Defaults to [6,6,6,6,6,6,6,6,6,6,6,6,6,6,6].
            B_wf_list (List[int], optional): The list of the B_wf parameters of each filter. B_wf stands for bits needed for fractional part of the filter output. Defaults to [8,8,8,8,8,8,8,8,8,8,8,8,8,8,8].
            B_af_list (List[int], optional): The list of the B_af parameters of each filter. B_af stands for bits needed for encoding the fractional parts of taps. Defaults to [9,9,9,9,9,9,9,9,9,9,9,9,9,9,9].
            a1_list (List[int], optional): The list of the a1 tap parameters of each filter. Defaults to [-64700,-64458,-64330,-64138,-63884,-63566,-63185,-62743,-62238,-61672,-61045,-60357,-59611,-58805,-57941].
            a2_list (List[int], optional): The list of the a2 tap parameters of each filter. Defaults to [31935,31754,31754,31754,31754,31754,31754,31754,31754,31754,31754,31754,31754,31754,31754].
        """

        if shape[1] // shape[0] != shape[1] / shape[0]:
            raise ValueError(
                f"The number of output channels should be a multiple of the number of input channels."
            )

        def __check_list_shape(list: List[int], name: str) -> None:
            if len(list) != shape[1]:
                raise ValueError(
                    f"The number of {name} should be equal to the number of filters. Expected {shape[1]} Got {len(list)}"
                )

        __check_list_shape(B_b_list, "B_b")
        __check_list_shape(B_wf_list, "B_wf")
        __check_list_shape(B_af_list, "B_af")
        __check_list_shape(a1_list, "a1")
        __check_list_shape(a2_list, "a2")

        self.filter_list = []
        for B_b, B_wf, B_af, a1, a2 in zip(
            B_b_list, B_wf_list, B_af_list, a1_list, a2_list
        ):
            self.filter_list.append(
                BandPassFilter(B_b=B_b, B_wf=B_wf, B_af=B_af, a1=a1, a2=a2)
            )

        if shape[1] != len(self.filter_list):
            raise ValueError(
                f"The output size should be {len(self.filter_list)} to compute filtered output!"
            )

        super().__init__(shape=shape, spiking_input=False, spiking_output=False)

        self.channel_mapping = np.sort([i % self.size_in for i in range(self.size_out)])
        """Mapping from IMU channels to filter channels. [0,0,0,0,0,1,1,1,1,1,2,2,2,2,2] by default"""

    @type_check
    def evolve(
        self, input_data: np.ndarray, record: bool = False
    ) -> Tuple[np.ndarray, Dict[str, Any], Dict[str, Any]]:
        """
        Compute the output of all filters for an input signal.
        Combine the filtering done in the `AR` and `MA` part of the block-diagram representation.

        Args:
            input_data (np.ndarray): the quantized input signal of datatype python.object integer. (BxTxC)

        Returns:
            Tuple[np.ndarray, Dict[str, Any], Dict[str, Any]]:
                np.ndarray: the filtered output signal of all filters (BxTxC)
                dict: empty record dictionary.
                dict: empty state dictionary.
        """

        # -- Batch processing
        input_data, _ = self._auto_batch(input_data)
        input_data = np.array(input_data, dtype=np.int64).astype(object)

        # -- Filter
        data_out = []

        # iterate over batch
        for signal in input_data:
            channel_out = []
            for __filter, __ch in zip(self.filter_list, self.channel_mapping):
                out = __filter(signal.T[__ch])
                channel_out.append(out)

            data_out.append(channel_out)

        # convert into numpy
        data_out = np.asarray(data_out, dtype=object)
        data_out = data_out.transpose(0, 2, 1)  # BxTxC

        return data_out, {}, {}
