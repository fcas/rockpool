"""
Dynap-SE1 specific low level bias currents

Project Owner : Dylan Muir, SynSense AG
Author : Ugurcan Cakal
E-mail : ugurcan.cakal@gmail.com
20/09/2021
"""
from __future__ import annotations
import json

from rockpool.devices.dynapse.adexplif_jax import (
    DynapSEAdExpLIFJax,
)

from rockpool.devices.dynapse.dynapse1_simconfig import (
    DynapSE1SimBoard,
    NeuronKey,
)

from rockpool.devices.dynapse.router import Router, NeuronConnection
from rockpool.devices.dynapse.biasgen import BiasGen

from rockpool.parameters import SimulationParameter

from typing import (
    Optional,
    Dict,
    Union,
    List,
    Any,
    Tuple,
)

import logging
import jax.numpy as np
from rockpool.typehints import FloatVector


_SAMNA_AVAILABLE = True

try:
    from samna.dynapse1 import (
        Dynapse1Configuration,
        Dynapse1ParameterGroup,
        Dynapse1Parameter,
    )
except ModuleNotFoundError as e:
    Dynapse1Configuration = Any
    Dynapse1ParameterGroup = Any
    Dynapse1Parameter = Any
    print(
        e,
        "\DynapSE1Jax module can only be used for simulation purposes."
        "Deployment utilities depends on samna!",
    )
    _SAMNA_AVAILABLE = False

_NETGEN_AVAILABLE = True

try:
    from netgen import (
        NetworkGenerator,
    )
except ModuleNotFoundError as e:
    NetworkGenerator = Any
    print(
        e,
        "\nSimulator object factory from the NetworkGenerator object is not possible!",
    )
    _NETGEN_AVAILABLE = False


class DynapSE1Jax(DynapSEAdExpLIFJax):
    """
    DynapSE1Jax is an extension to DynapSEAdExpLIFJax module with device specific deployment utilities.
    The parameters and pipeline are explained in the superclass `DynapSEAdExpLIFJax` doctring

    :Parameters:
    :param idx_map_dict: a dictionary of dictionaries (2 seperate dictionary for `w_in` and `w_rec`) of the mapping between matrix indexes of the neurons and their global unique neuron keys. if index map is in proper format, a core dictionary can be inferred without an error
    :type idx_map_dict: Dict[str, Dict[int, NeuronKey]]

    :Instance Variables:

    :ivar f_t_ref: An array of the factor of conversion from refractory period in seconds to refractory period bias current in Amperes
    :type f_t_ref: JP_ndarray
    :ivar f_t_pulse: An array of the factor of conversion from pulse width in seconds to pulse width bias current in Amperes
    :type f_t_pulse: JP_ndarray
    :ivar core_dict: a dictionary from core keys (chipID, coreID) to an index map of neruons (neuron index : local neuronID) that the core allocates.
    :type core_dict: Dict[Tuple[int], Dict[int, int]]

    idx_map = {
        0: (1, 0, 20),
        1: (1, 0, 36),
        2: (1, 0, 60),
        3: (2, 3, 107),
        4: (2, 3, 110),
        5: (3, 1, 152)
    }

    core_dict = {
        (1, 0): {0: 20, 1: 36, 2: 60},
        (2, 3): {3: 107, 4: 110},
        (3, 1): {5: 152}
    }
    """

    __doc__ += DynapSEAdExpLIFJax.__doc__

    biases = [
        "IF_AHTAU_N",
        "IF_AHTHR_N",
        "IF_AHW_P",
        "IF_BUF_P",
        "IF_CASC_N",
        "IF_DC_P",
        "IF_NMDA_N",
        "IF_RFR_N",
        "IF_TAU1_N",
        "IF_TAU2_N",
        "IF_THR_N",
        "NPDPIE_TAU_F_P",
        "NPDPIE_TAU_S_P",
        "NPDPIE_THR_F_P",
        "NPDPIE_THR_S_P",
        "NPDPII_TAU_F_P",
        "NPDPII_TAU_S_P",
        "NPDPII_THR_F_P",
        "NPDPII_THR_S_P",
        "PS_WEIGHT_EXC_F_N",
        "PS_WEIGHT_EXC_S_N",
        "PS_WEIGHT_INH_F_N",
        "PS_WEIGHT_INH_S_N",
        "PULSE_PWLK_P",
        "R2R_P",
    ]

    def __init__(
        self,
        shape: tuple = None,
        idx_map_dict: Optional[Dict[str, Dict[int, NeuronKey]]] = None,
        sim_config: Optional[DynapSE1SimBoard] = None,
        w_in: Optional[FloatVector] = None,
        w_rec: Optional[FloatVector] = None,
        dt: float = 1e-3,
        rng_key: Optional[Any] = None,
        spiking_input: bool = True,
        spiking_output: bool = True,
        *args,
        **kwargs,
    ) -> None:
        """
        __init__ Initialize ``DynapSE1Jax`` module. Parameters are explained in the superclass docstring.
        """

        if sim_config is None:
            # Get a simulation board from an index map with default bias parameters
            if idx_map_dict is not None:
                sim_config = DynapSE1SimBoard.from_config(None, idx_map_dict["w_rec"])
            else:
                sim_config = DynapSE1SimBoard(shape[-1])

        if idx_map_dict is None:
            idx_map_dict = {}
            idx_map_dict["w_in"] = {}
            idx_map_dict["w_rec"] = sim_config.idx_map

        super().__init__(
            shape,
            sim_config,
            w_in,
            w_rec,
            dt,
            rng_key,
            spiking_input,
            spiking_output,
            *args,
            **kwargs,
        )

        self.f_t_ref = SimulationParameter(sim_config.f_t_ref)
        self.f_t_pulse = SimulationParameter(sim_config.f_t_pulse)

        # Check if index map is in proper format, if so, a core dictionary can be inferred without an error.
        DynapSE1SimBoard.check_neuron_id_order(list(idx_map_dict["w_rec"].keys()))
        self.core_dict = DynapSE1SimBoard.idx_map_to_core_dict(idx_map_dict["w_rec"])
        self.idx_map_dict = idx_map_dict

    def samna_param_group(
        self, chipID: np.uint8, coreID: np.uint8
    ) -> Dynapse1ParameterGroup:
        """
        samna_param_group creates a samna Dynapse1ParameterGroup group object and configure the bias
        parameters by creating a dictionary. It does not check if the values are legal or not.

        :param chipID: Unique chip ID to of the parameter group
        :type chipID: np.uint8
        :param coreID: Non-unique core ID to of the parameter group
        :type coreID: np.uint8
        :return: samna config object to set a parameter group within one core
        :rtype: Dynapse1ParameterGroup
        """
        pg_json = json.dumps(self._param_group(chipID, coreID))
        pg_samna = Dynapse1ParameterGroup()
        pg_samna.from_json(pg_json)
        return pg_samna

    def _param_group(
        self, chipID: np.uint8, coreID: np.uint8
    ) -> Dict[
        str,
        Dict[str, Union[int, List[Dict[str, Union[str, Dict[str, Union[str, int]]]]]]],
    ]:
        """
        _param_group creates a samna type dictionary to configure the parameter group

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: a dictonary of bias currents, and their coarse/fine values
        :rtype: Dict[str, Dict[str, Union[int, List[Dict[str, Union[str, Dict[str, Union[str, int]]]]]]]]
        """

        bias_getter = lambda bias: getattr(self, bias)(chipID, coreID)

        def param_dict(param: Dynapse1Parameter) -> Dict[str, Union[str, int]]:
            serial = {
                "paramName": param.param_name,
                "coarseValue": param.coarse_value,
                "fineValue": param.fine_value,
                "type": param.type,
            }
            return serial

        param_map = [
            {"key": bias, "value": param_dict(bias_getter(bias))}
            for bias in self.biases
        ]

        group = {
            "value0": {
                "paramMap": param_map,
                "chipId": chipID,
                "coreId": coreID,
            }
        }

        return group

    @classmethod
    def from_config(
        cls,
        config: Dynapse1Configuration,
        virtual_connections: Optional[List[NeuronConnection]] = None,
        w_in: Optional[FloatVector] = None,
        idx_map_in: Optional[Dict[int, NeuronKey]] = None,
        sim_config: Optional[DynapSE1SimBoard] = None,
        default_bias: bool = True,
        *args,
        **kwargs,
    ) -> DynapSE1Jax:
        """
        from_config is a class factory method depending on a samna device configuration object. Using this,
        the virtual connections or input weights `w_in` should be provided explicitly. The reason is that
        the config object does not have the FPGA -> device connections information

        :param config: samna Dynapse1 configuration object used to configure a network on the chip
        :type config: Dynapse1Configuration
        :param virtual_connections: A list of tuples of universal neuron IDs defining the input connections from the FPGA to device neurons, defaults to None
            e.g : [(50,1044),(50,1045)]
        :type virtual_connections: Optional[List[NeuronConnection]], optional
        :param w_in: input weight matrix (3D, NinxNrecx4), defaults to None
        :type w_in: Optional[FloatVector], optional
        :param idx_map_in: a dictionary of the mapping between matrix indexes of the FPGA-to-device input connections and their global unique neuron keys. Define when virtual connections is not defined but w_in is provided explicitly, defaults to None
        :type idx_map_in: Optional[Dict[int, NeuronKey]]
        :param sim_config: Dynap-SE1 bias currents and simulation configuration parameters, it can be provided explicitly, or created using default settings, or can be extracted from the config bias currents. defaults to None
        :type sim_config: Optional[DynapSE1SimBoard], optional
        :param default_bias: use default bias values or get the bias parameters from the netgen.config, defaults to True
        :type default_bias: bool
        :return: `DynapSE1Jax` simulator object
        :rtype: DynapSE1Jax
        """
        _w_in, w_rec, idx_map_dict = Router.get_weight_from_config(
            config, virtual_connections, return_maps=True
        )

        if w_in is not None:
            idx_map_dict["w_in"] = idx_map_in

        w_in = _w_in if w_in is None else w_in

        shape = w_in.shape[0:2]

        if sim_config is None:
            if not default_bias:
                sim_config = DynapSE1SimBoard.from_config(config, idx_map_dict["w_rec"])

            else:
                sim_config = DynapSE1SimBoard.from_config(None, idx_map_dict["w_rec"])
        mod = cls(shape, idx_map_dict, sim_config, w_in, w_rec, *args, **kwargs)
        return mod

    @classmethod
    def from_netgen(cls, netgen: NetworkGenerator, *args, **kwargs) -> DynapSE1Jax:
        """
        from_netgen is a class factory which makes it easier to get a `DynapSE1Jax` object using the `NetworkGenerator` object
        The reason that it became easier to construct a simulator object than `from_config` is that netgen object has also the
        implicit input connections information and a samna config object. Therefore the `from_netgen()` method
        extracts the virtual connections and device configuration object from the netgen object and calls `.from_config()` method

        :param netgen: network generator object defined in samna/ctxctl_contrib/netgen
        :type netgen: NetworkGenerator
        :return: `DynapSE1Jax` simulator object
        :rtype: DynapSE1Jax
        """
        connections = Router.get_virtual_connections(netgen.network)
        config = netgen.make_dynapse1_configuration()
        mod = cls.from_config(config, connections, *args, **kwargs)
        return mod

    def get_bias(
        self,
        chipID: np.uint8,
        coreID: np.uint8,
        attribute: str,
        syn_type: Optional[str] = None,
    ) -> float:
        """
        get_bias obtains a bias current from the simulation currents to convert this
        into device bias with coarse and fine values

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :param attribute: the name of the simulation attribute which corresponds to the desired bias
        :type attribute: str
        :param syn_type: the synase type of the attribute if the corresponding current is a synaptic current rather than membrane, defaults to None
        :type syn_type: Optional[str], optional
        :raises IndexError: Chip:{chipID},Core:{coreID} is not used! Please look at the core dictionary!
        :raises AttributeError: Bias: {attribute} is a synaptic current. Please define the syn_type!"
        :return: the bias current of a subset of neruons obtained from the core dictionary
        :rtype: float
        """
        I_bias = None
        if (chipID, coreID) not in self.core_dict:
            raise IndexError(
                f"Chip:{chipID},Core:{coreID} is not used! Please look at the core dictionary! {list(self.core_dict.keys())}"
            )
        else:
            # Obtain the neuron indices from the core dictionary
            idx = np.array(list(self.core_dict[(chipID, coreID)].keys()))
            I_base = self.__getattribute__(attribute)
            if syn_type is None:
                if len(I_base.shape) == 2:
                    raise AttributeError(
                        f"Bias: {attribute} is a synaptic current. Please define the syn_type!"
                    )
                I_bias = float(I_base[idx].mean())
            else:
                if len(I_base.shape) == 1:
                    logging.warning(
                        f"Bias: {attribute} is a a membrane current. Defined syn_type:{syn_type} has no effect!"
                    )
                    I_bias = float(I_base[idx].mean())
                else:
                    I_bias = float(I_base[self.SYN[syn_type], idx].mean())

        return I_bias

    @staticmethod
    def get_Dynapse1Parameter(bias: float, name: str) -> Dynapse1Parameter:
        """
        get_Dynapse1Parameter constructs a samna DynapSE1Parameter object given the bias current desired

        :param bias: bias current desired. It will be expressed by a coarse fine tuple which will generate the closest possible bias current.
        :type bias: float
        :param name: the name of the bias parameter
        :type name: str
        :return: samna DynapSE1Parameter object
        :rtype: Dynapse1Parameter
        """
        coarse, fine = BiasGen.bias_to_coarse_fine(bias)
        param = Dynapse1Parameter(name, coarse, fine)
        return param

    def bias_parameter(
        self,
        chipID: np.uint8,
        coreID: np.uint8,
        sim_name: str,
        dev_name: str,
        syn_type: Optional[str] = None,
    ) -> Dynapse1Parameter:
        """
        bias_parameter wraps the bias current inference from the simulation currents and DynapSE1Parameter construction

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :param sim_name: the name of the simulation attribute which corresponds to the desired bias
        :type sim_name: str
        :param dev_name: the name of the bias parameter
        :type dev_name: str
        :param syn_type: the synase type of the attribute if the corresponding current is a synaptic current rather than membrane, defaults to None
        :type syn_type: Optional[str], optional
        :return: samna DynapSE1Parameter object
        :rtype: Dynapse1Parameter
        """
        I_bias = self.get_bias(chipID, coreID, sim_name, syn_type)
        param = DynapSE1Jax.get_Dynapse1Parameter(bias=I_bias, name=dev_name)
        return param

    @property
    def Iref(self) -> FloatVector:
        """
        Iref is the device bias current (specific to neurons, not the core) setting the refractory period.
        """
        return self.f_t_ref / self.t_ref

    @property
    def Ipulse(self) -> FloatVector:
        """
        Ipulse is the device bias current (specific to neurons, not the core) setting the spike triggered pulse width period.
        """
        return self.f_t_pulse / self.t_pulse

    ## --- LOW LEVEL BIAS CURRENTS (SAMNA) -- ##
    def IF_AHTAU_N(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        IF_AHTAU_N controls the spike frequency adaptation(AHP) circuit time constant, reciprocal to `Itau_syn[AHP]`
        The depended time constant can be calculated by using the formula :math:`\\tau = \\dfrac{U_T}{I_{\\tau} \\cdot \\kappa \\cdot C}`,

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Itau_syn", "IF_AHTAU_N", "AHP")

    def IF_AHTHR_N(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        IF_AHTHR_N controls the spike frequency adaptation(AHP) circuit gain current, reciprocal to `Ith_syn[AHP]`
        It scales the steady state output current of the DPI circuit, :math:`I_{syn_{\\infty}} = \dfrac{I_{th}}{I_{\\tau}} \\cdot I_{w}`

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Ith_syn", "IF_AHTHR_N", "AHP")

    def IF_AHW_P(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        IF_AHW_P controls the spike frequency adaptation(AHP) circuit base weight current, reciprocal to `Iw[AHP]`

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Iw", "IF_AHW_P", "AHP")

    def IF_BUF_P(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        IF_BUF_P has an effect on the membrane potential `Vm` readout, does not have a huge effect on simulation, use samna defaults.
        !NON-PARAMETRIC! chipID and coreID has no effect for now but it might be changed, (keep them for the sake of convenience)

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return Dynapse1Parameter("IF_BUF_P", 4, 80)

    def IF_CASC_N(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        IF_CASC_N for spike frequency current (AHP) regularization, does not have a huge effect on simulation, use samna defaults.
        !NON-PARAMETRIC! chipID and coreID has no effect for now but it might be changed, (keep them for the sake of convenience)

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return Dynapse1Parameter("IF_CASC_N", 0, 0)

    def IF_DC_P(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        IF_DC_P controls the DC current added to the sum of the synaptic input currents of the membrane, reciprocal to `Idc`

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Idc", "IF_DC_P")

    def IF_NMDA_N(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        IF_NMDA_N controls the NMDA NMDA gate current in Amperes setting the NMDA gating voltage, reciprocal to `If_nmda`
        If :math:`V_{mem} > V_{nmda}` : The :math:`I_{syn_{NMDA}}` current is added to the synaptic input currents of the membrane, else it cannot

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "If_nmda", "IF_NMDA_N")

    def IF_RFR_N(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        IF_RFR_N controls the refractory periof of the neruons. In the refractory period the synaptic input current of the membrane is the dark current. reciprocal to `Iref`
        The depended time constant can be calculated by using the formula :math:`\\t_{ref} = \\dfrac{U_T}{I_{\\ref} \\cdot \\kappa \\cdot C}`,

        # 4, 120 in Chenxi's master thesis
        # 4, 3 by default in samna
        # 0, 30 for 10 ms in rockpool

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Iref", "IF_RFR_N")

    def IF_TAU1_N(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        IF_TAU1_N controls the membrane circuit time constant, reciprocal to `Itau_mem`
        The depended time constant can be calculated by using the formula :math:`\\tau = \\dfrac{U_T}{I_{\\tau} \\cdot \\kappa \\cdot C}`

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Itau_mem", "IF_TAU1_N")

    def IF_TAU2_N(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        IF_TAU2_N controls the membrane circuit time constant, reciprocal to `Itau2_mem`. Generally max current, used for deactivation of certain neruons.
        The depended time constant can be calculated by using the formula :math:`\\tau = \\dfrac{U_T}{I_{\\tau} \\cdot \\kappa \\cdot C}`

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Itau2_mem", "IF_TAU2_N")

    def IF_THR_N(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        IF_THR_N controls the membrane circuit gain current, reciprocal to `Ith_mem`
        It scales the steady state output current of the DPI circuit, :math:`I_{syn_{\\infty}} = \dfrac{I_{th}}{I_{\\tau}} \\cdot I_{w}`

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Ith_mem", "IF_THR_N")

    def NPDPIE_TAU_F_P(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        NPDPIE_TAU_F_P controls the FAST_EXC, AMPA circuit time constant, reciprocal to `Itau_syn[AMPA]`
        The depended time constant can be calculated by using the formula :math:`\\tau = \\dfrac{U_T}{I_{\\tau} \\cdot \\kappa \\cdot C}`,

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Itau_syn", "NPDPIE_TAU_F_P", "AMPA")

    def NPDPIE_TAU_S_P(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        NPDPIE_TAU_S_P controls the SLOW_EXC, NMDA circuit time constant, reciprocal to `Itau_syn[NMDA]`
        The depended time constant can be calculated by using the formula :math:`\\tau = \\dfrac{U_T}{I_{\\tau} \\cdot \\kappa \\cdot C}`,

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Itau_syn", "NPDPIE_TAU_S_P", "NMDA")

    def NPDPIE_THR_F_P(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        NPDPIE_THR_F_P controls the FAST_EXC, AMPA circuit gain current, reciprocal to `Ith_syn[AMPA]`
        It scales the steady state output current of the DPI circuit, :math:`I_{syn_{\\infty}} = \dfrac{I_{th}}{I_{\\tau}} \\cdot I_{w}`

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Ith_syn", "NPDPIE_THR_F_P", "AMPA")

    def NPDPIE_THR_S_P(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        NPDPIE_THR_S_P controls the SLOW_EXC, NMDA circuit gain current, reciprocal to `Ith_syn[NMDA]`
        It scales the steady state output current of the DPI circuit, :math:`I_{syn_{\\infty}} = \dfrac{I_{th}}{I_{\\tau}} \\cdot I_{w}`

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Ith_syn", "NPDPIE_THR_S_P", "NMDA")

    def NPDPII_TAU_F_P(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        NPDPII_TAU_F_P controls the FAST_INH, GABA_A, circuit time constant, reciprocal to `Itau_syn[GABA_A]`
        The depended time constant can be calculated by using the formula :math:`\\tau = \\dfrac{U_T}{I_{\\tau} \\cdot \\kappa \\cdot C}`,
        Shunting current: a mixture of subtractive and divisive

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(
            chipID, coreID, "Itau_syn", "NPDPII_TAU_F_P", "GABA_A"
        )

    def NPDPII_TAU_S_P(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        NPDPII_TAU_S_P controls the SLOW_INH, GABA_B circuit time constant, reciprocal to `Itau_syn[GABA_B]`
        The depended time constant can be calculated by using the formula :math:`\\tau = \\dfrac{U_T}{I_{\\tau} \\cdot \\kappa \\cdot C}`,

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(
            chipID, coreID, "Itau_syn", "NPDPII_TAU_S_P", "GABA_B"
        )

    def NPDPII_THR_F_P(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        NPDPII_THR_F_P controls FAST_INH, GABA_A, circuit gain current, reciprocal to `Ith_syn[GABA_A]`
        It scales the steady state output current of the DPI circuit, :math:`I_{syn_{\\infty}} = \dfrac{I_{th}}{I_{\\tau}} \\cdot I_{w}`
        Shunting current: a mixture of subtractive and divisive

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(
            chipID, coreID, "Ith_syn", "NPDPII_THR_F_P", "GABA_A"
        )

    def NPDPII_THR_S_P(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        NPDPII_THR_S_P controls the SLOW_INH, GABA_B circuit gain current, reciprocal to `Ith_syn[GABA_B]`
        It scales the steady state output current of the DPI circuit, :math:`I_{syn_{\\infty}} = \dfrac{I_{th}}{I_{\\tau}} \\cdot I_{w}`

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(
            chipID, coreID, "Ith_syn", "NPDPII_THR_S_P", "GABA_B"
        )

    def PS_WEIGHT_EXC_F_N(
        self, chipID: np.uint8, coreID: np.uint8
    ) -> Dynapse1Parameter:
        """
        PS_WEIGHT_EXC_F_N controls the FAST_EXC, AMPA circuit base weight current, reciprocal to `Iw[AMPA]`

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Iw", "PS_WEIGHT_EXC_F_N", "AMPA")

    def PS_WEIGHT_EXC_S_N(
        self, chipID: np.uint8, coreID: np.uint8
    ) -> Dynapse1Parameter:
        """
        PS_WEIGHT_EXC_S_N controls the SLOW_EXC, NMDA circuit base weight current, reciprocal to `Iw[NMDA]`

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Iw", "PS_WEIGHT_EXC_S_N", "NMDA")

    def PS_WEIGHT_INH_F_N(
        self, chipID: np.uint8, coreID: np.uint8
    ) -> Dynapse1Parameter:
        """
        PS_WEIGHT_INH_F_N controls the FAST_INH, GABA_A circuit base weight current, reciprocal to `Iw[GABA_A]`
        Shunting current: a mixture of subtractive and divisive

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Iw", "PS_WEIGHT_INH_F_N", "GABA_A")

    def PS_WEIGHT_INH_S_N(
        self, chipID: np.uint8, coreID: np.uint8
    ) -> Dynapse1Parameter:
        """
        PS_WEIGHT_INH_S_N controls the SLOW_INH, GABA_B circuit base weight current, reciprocal to `Iw[GABA_B]`

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Iw", "PS_WEIGHT_INH_S_N", "GABA_B")

    def PULSE_PWLK_P(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        PULSE_PWLK_P controls the the width of the pulse in seconds produced by virtue of a spikeö reciprocal to `Ipulse`
        The depended time constant can be calculated by using the formula :math:`\\t_{pulse} = \\dfrac{U_T}{I_{\\pulse} \\cdot \\kappa \\cdot C}`,

        # 4, 160 by default in samna
        # 4, 106 in Chenxi's master thesis
        # 3, 70 for 10us in rockpool

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return self.bias_parameter(chipID, coreID, "Ipulse", "PULSE_PWLK_P")

    def R2R_P(self, chipID: np.uint8, coreID: np.uint8) -> Dynapse1Parameter:
        """
        R2R_P maybe something related to digital to analog converter(unsure), does not have a huge effect on simulation, use samna defaults.
        !NON-PARAMETRIC! chipID and coreID has no effect for now but it might be changed, (keep them for the sake of convenience)

        :param chipID: Unique chip ID
        :type chipID: np.uint8
        :param coreID: Non-unique core ID
        :type coreID: np.uint8
        :return: samna bias parameter object involving a coarse and fine value
        :rtype: Dynapse1Parameter
        """
        return Dynapse1Parameter("R2R_P", 3, 85)