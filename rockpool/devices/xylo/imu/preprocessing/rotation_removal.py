"""
Rotation-Removal module for removing the rotation from the IMU input signal.
"""
from typing import Any, Dict, Tuple, Optional, Union

import numpy as np

from rockpool.devices.xylo.imu.preprocessing.jsvd import JSVD
from rockpool.devices.xylo.imu.preprocessing.sample_hold import SampleAndHold
from rockpool.devices.xylo.imu.preprocessing.subspace import SubSpace
from rockpool.devices.xylo.imu.preprocessing.utils import type_check
from rockpool.nn.combinators import Sequential

from rockpool.nn.modules.module import Module
from rockpool.parameters import SimulationParameter

__all__ = ["RotationRemoval"]


class RotationRemoval(Module):
    """
    1. Takes the T x 3 input data received from an IMU sensor,
    2. Computes the 3 x 3 sample covariance using subspace estimation module,
    3. Applies a sample-and-hold module to compute SVD only at specific periods
    4. Computes the SVD of the resulting covariance matrix to find the rotation matrix,
    5. Applies the rotation matrix to the input data to compute the rotation-removed version of the input data

    The resulting signal is then forwarded to the filterbank module.
    In this version, we are using `object` rather than `np.int64` so that our simulation works for arbitrary number of quantization bit size for the parameters.
    """

    def __init__(
        self,
        num_bits_in: int,
        num_bits_out: int,
        num_bits_highprec_filter: int,
        num_bits_multiplier: int,
        num_avg_bitshift: int,
        sampling_period: int,
        num_angles: int,
        num_bits_lookup: int,
        num_bits_covariance: int,
        num_bits_rotation: int,
        nround: int = 4,
        shape: Optional[Union[Tuple, int]] = (3, 3),
    ) -> None:
        """Object constructor.

        Args:
            num_bits_in (int): number of bits in the input data. We assume a sign magnitude format.
            num_bits_out (int): number of bits in the final signal (obtained after rotation removal).
            num_bits_highprec_filter (int) : number of bits devoted to computing the high-precision filter (to avoid dead-zone effect)
            num_bits_multiplier (int): number of bits devoted to computing [x(t) x(t)^T]_{ij}. If less then needed, the LSB values are removed.
            num_avg_bitshift (int): number of bitshifts used in the low-pass filter implementation.
                The effective window length of the low-pass filter will be `2**num_avg_bitshift`
            sampling_period (int): Sampling period that the signal is sampled and held
            num_angles (int): number of angles in lookup table.
            num_bits_lookup (int): number of bits used for quantizing the lookup table.
            num_bits_covariance (int): number of bits used for the covariance matrix.
            num_bits_rotation (int): number of bits devoted for implementing rotation matrix.
            nround (int): number of round rotation computation and update is done over all 3 axes/dims.

        """
        super().__init__(shape=shape, spiking_input=False, spiking_output=False)

        self.sub_estimate = Sequential(
            SubSpace(
                num_bits_in=num_bits_in,
                num_bits_highprec_filter=num_bits_highprec_filter,
                num_bits_multiplier=num_bits_multiplier,
                num_avg_bitshift=num_avg_bitshift,
                shape=(self.size_in, self.size_in**2),
            ),
            SampleAndHold(
                sampling_period=sampling_period,
                shape=(self.size_in**2, self.size_in**2),
            ),
        )

        self.jsvd = JSVD(
            num_angles=num_angles,
            num_bits_lookup=num_bits_lookup,
            num_bits_covariance=num_bits_covariance,
            num_bits_rotation=num_bits_rotation,
            nround=nround,
        )

        self.num_bits_in = SimulationParameter(num_bits_in, shape=(1,), cast_fn=int)
        """number of bits in the input data. We assume a sign magnitude format."""

        self.num_bits_out = SimulationParameter(num_bits_out, shape=(1,), cast_fn=int)
        """number of round rotation computation and update is done over all 3 axes/dims."""

        self.num_bits_rotation = SimulationParameter(
            num_bits_rotation, shape=(1,), cast_fn=int
        )
        """number of bits devoted for implementing rotation matrix"""

    @type_check
    def evolve(
        self, input_data: np.ndarray, record: bool = False
    ) -> Tuple[np.ndarray, Dict[str, Any], Dict[str, Any]]:
        """Take the BxTx3 raw analog IMU signal and processes it to produce the BxTx3 rotation-removed signal.

        Args:
            input_data (np.ndarray): the input signal (BxTx3)
            record (bool, optional): record flag to match with the other rockpool modules. Practically useless. Defaults to False.

        Raises:
            ValueError: if the dimensions do not match.

        Returns:
            np.ndarray: Output signal after rotation removal (BxTx3)
            Dict[str, Any]: empty dictionary
            Dict[str, Any]: empty dictionary
        """

        # Input handling (BxTx3)
        input_data, _ = self._auto_batch(input_data)
        input_data = np.array(input_data, dtype=np.int64).astype(object)
        __B, __T, __C = input_data.shape
        if __C != self.size_in:
            raise ValueError(f"The input data should have {self.size_in} channels!")

        # compute the covariances using subspace estimation: do not save the high-precision ones
        # B x T x 3 x 3
        batch_cov_SH, _, _ = self.sub_estimate(input_data)
        batch_cov_SH = batch_cov_SH.reshape((__B, __T, __C, __C))

        # feed the computed covariance matrices into a JSVD module and compute the rotation and diagonal matrix
        covariance_old = -np.ones((3, 3), dtype=object)
        rotation_old = np.eye(3).astype(np.int64).astype(object)

        signal_out = []
        data_out = []

        # loop over the batch
        for cov_SH, signal in zip(batch_cov_SH, input_data):
            # loop over the time dimension
            for cov_new, sample in zip(cov_SH, signal):
                # check if the covariance matrix is repeated
                if np.linalg.norm(covariance_old - cov_new) == 0:
                    # output signal sample after rotation removal
                    sample_out = self.rotate(rotation_old.T, sample)
                    signal_out.append(sample_out)

                # if not, compute the JSVD
                else:
                    rotation_new, diagonal_new = self.jsvd(cov_new)

                    # correct the sign of rotation to keep the consistency with the previous rotations
                    # no need to change the diagonal matrix
                    sign_new_old = (
                        np.sign(np.diag(rotation_new.T @ rotation_old))
                        .astype(np.int8)
                        .astype(object)
                    )
                    rotation_new = rotation_new @ np.diag(sign_new_old)

                    # output signal sample after rotation removal
                    sample_out = self.rotate(rotation_new.T, sample)
                    signal_out.append(sample_out)

                    # update the covariance matrix
                    covariance_old = cov_new
                    rotation_old = rotation_new

            # convert into array and return
            signal_out = np.array(signal_out, dtype=object).T

        data_out.append(signal_out)
        data_out = np.array(data_out, dtype=object)

        return data_out, {}, {}


    # utility modules
    @type_check
    def rotate(self, rotation_matrix: np.ndarray, sig_sample: np.ndarray) -> np.ndarray:
        """this module takes a rotation matrix and also a 3 x 1 signal sample and rotates it.

        Args:
            rotation_matrix (np.ndarray): 3 x 3 input rotation matrix.
            sig_sample (np.ndarray): 3 x 1 input signal sample.

        Returns:
            np.ndarray: 3 x 1 input signal after being multiplied with transpose of rotation matrix (rotation removal).
        """
        # number of bits used in rotation removal
        num_bits_rotation = self.jsvd.num_bits_rotation

        # number of bits used in the input signal
        num_bits_in = self.num_bits_in

        # number of bitshifts needed to fit the multiplication into the buffer
        # NOTE: the amplitude amplification due to multiplication with a rotation matrix
        # is already taken into account by right-bit-shift of 1
        num_right_bit_shifts = num_bits_rotation + num_bits_in - self.num_bits_out

        sig_out = []

        for row_vec in rotation_matrix:
            buffer = 0

            for val_rotation, val_sig_in in zip(row_vec, sig_sample):
                update = (val_rotation * val_sig_in) >> num_right_bit_shifts

                if abs(update) >= 2 ** (self.num_bits_out - 1):
                    raise ValueError(
                        f"The update value {update} encountered in rotation-input signal multiplication is beyond the range [-{2**(self.num_bits_out-1)}, +{2**(self.num_bits_out-1)}]!"
                    )

                buffer += update

                if abs(buffer) >= 2 ** (self.num_bits_out - 1):
                    raise ValueError(
                        f"The beffer value {buffer} encountered in rotation-input signal multiplication is beyond the range [-{2**(self.num_bits_out-1)}, +{2**(self.num_bits_out-1)}]!"
                    )

            # add this component
            sig_out.append(buffer)

        sig_out = np.asarray(sig_out, dtype=object)

        return sig_out
