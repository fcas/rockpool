"""
Simulation of an analog IMU signal filtering front-end

Defines :py:class:`.IMUIFSim` module.

See Also:
    For example usage of the :py:class:`.IMUIFSim` Module, see :ref:`/devices/xylo-imu/imu-if.ipynb`
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union
from warnings import warn

import numpy as np

from rockpool.devices.xylo.imu.preprocessing.filterbank import FilterBank
from rockpool.devices.xylo.imu.preprocessing.rotation_removal import RotationRemoval
from rockpool.devices.xylo.imu.preprocessing.spike_encoder import (
    IAFSpikeEncoder,
    ScaleSpikeEncoder,
)
from rockpool.devices.xylo.imu.preprocessing.utils import type_check
from rockpool.nn.combinators import Sequential
from rockpool.nn.modules.module import Module
from rockpool.utilities.backend_management import backend_available

if backend_available("samna"):
    from samna.xyloImu.configuration import InputInterfaceConfig
else:
    InputInterfaceConfig = Any

__all__ = ["IMUIFSim"]


class IMUIFSim(Module):
    """
    A :py:class:`.Module` that simulates analog IMU signal preprocessing into spikes.

    This module simulates the Xylo IMU front-end stage. This is a signal-to-event core that consists of rotation removal units, low-pass filters, and a spike generator. The module takes in a 3D IMU signal and outputs a spike train.

    See Also:
        For example usage of the :py:class:`.IMUIFSim` Module, see :ref:`/devices/xylo-imu/imu-if.ipynb`
    """

    def __init__(
        self,
        shape: Optional[Union[Tuple, int]] = (3, 15),
        select_iaf_output: bool = False,
        bypass_jsvd: bool = False,
        B_b_list: Union[List[int], int] = 6,
        B_wf_list: Union[List[int], int] = 8,
        B_af_list: Union[List[int], int] = 9,
        a1_list: Union[List[int], int] = [
            64700,
            64458,
            64330,
            64138,
            63884,
            63566,
            63185,
            62743,
            62238,
            61672,
            61045,
            60357,
            59611,
            58805,
            57941,
        ],
        a2_list: Union[List[int], int] = [
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
        scale_values: Union[List[int], int] = 5,
        iaf_threshold_values: Union[List[int], int] = 1024,
        num_avg_bitshift: int = 4,
        sampling_period: int = 10,
    ):
        """ """
        super().__init__(shape=shape, spiking_input=False, spiking_output=True)

        filter_bank = FilterBank(
            shape=shape,
            B_b_list=B_b_list,
            B_wf_list=B_wf_list,
            B_af_list=B_af_list,
            a1_list=a1_list,
            a2_list=a2_list,
        )

        if select_iaf_output:
            spike_encoder = IAFSpikeEncoder(
                shape=(self.size_out, self.size_out), threshold=iaf_threshold_values
            )
        else:
            spike_encoder = ScaleSpikeEncoder(
                shape=(self.size_out, self.size_out), num_scale_bits=scale_values
            )

        if bypass_jsvd:
            mod_IMUIF = Sequential(filter_bank, spike_encoder)
        else:
            rotation_removal = RotationRemoval(
                shape=(self.size_in, self.size_in),
                num_avg_bitshift=num_avg_bitshift,
                sampling_period=sampling_period,
            )
            mod_IMUIF = Sequential(rotation_removal, filter_bank, spike_encoder)

        self.mod_IMUIF = mod_IMUIF

    @type_check
    def evolve(
        self, input_data: np.ndarray, record: bool = False
    ) -> Tuple[np.ndarray, Dict[str, Any], Dict[str, Any]]:
        """Processes the input signal sample-by-sample and generate spikes

        Args:
            input_data (np.ndarray): batched input data recorded from IMU sensor. It should be in integer format. (BxTx3)
            record (bool, optional): If True, the intermediate results are recorded and returned. Defaults to False.

        Returns:
            Tuple[np.ndarray, Dict[str, Any], Dict[str, Any]]:
                output
                empty dictionary
                empty dictionary
        """

        # Shape check
        input_data, _ = self._auto_batch(input_data)
        input_data = np.array(input_data, dtype=np.int64).astype(object)
        return self.mod_IMUIF(input_data, record=record)

    @classmethod
    def from_config(cls, config: InputInterfaceConfig) -> IMUIFSim:
        ## BandPassFilter
        if not isinstance(config, InputInterfaceConfig):
            raise TypeError(
                f"config must be an instance of `samna.xyloImu.configuration.InputInterfaceConfig`. We got {type(config)}"
            )
        if config.enable != True:
            warn("IMUIF is not enabled in configuration!")

        # We could not use `config.delay_threshold` here because it does not affect the simulation
        return cls(
            shape=(3, 15),
            select_iaf_output=config.select_iaf_output,
            bypass_jsvd=config.bypass_jsvd,
            B_b_list=config.bpf_bb_values,
            B_wf_list=config.bpf_bwf_values,
            B_af_list=config.bpf_baf_values,
            a1_list=config.bpf_a1_values,
            a2_list=config.bpf_a2_values,
            scale_values=config.scale_values,
            iaf_threshold_values=config.iaf_threshold_values,
            num_avg_bitshift=config.estimator_k_setting,
            sampling_period=config.update_matrix_threshold,
        )

    @classmethod
    def from_specification(cls, *args, **kwargs) -> IMUIFSim:
        pass


if __name__ == "__main__":
    # config = InputInterfaceConfig()
    # print(config.update_matrix_threshold)

    IMUIFSim()
