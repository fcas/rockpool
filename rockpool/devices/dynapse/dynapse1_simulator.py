"""
Dynap-SE1 specific low level bias currents

Project Owner : Dylan Muir, SynSense AG
Author : Ugurcan Cakal
E-mail : ugurcan.cakal@gmail.com
20/09/2021
"""
from __future__ import annotations
import json

from rockpool.devices.dynapse.dynapse1_neuron_synapse_jax import (
    DynapSE1NeuronSynapseJax,
)

from rockpool.devices.dynapse.dynapse1_simconfig import (
    DynapSE1SimCore,
    DynapSE1SimConfig,
)

from rockpool.devices.dynapse.router import Router, NeuronConnection

from rockpool.parameters import SimulationParameter

from typing import (
    Optional,
    Dict,
    Union,
    List,
    Any,
)

from rockpool.typehints import (
    FloatVector,
)

from rockpool.devices.dynapse.utils import (
    get_Dynapse1Parameter,
)


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


class DynapSE1Jax(DynapSE1NeuronSynapseJax):
    """
    DynapSE1Jax is an extension to DynapSE1NeuronSynapseJax module with device specific deployment utilities.
    The parameters and pipeline are explained in the superclass `DynapSE1NeuronSynapseJax` doctring

    :Instance Variables:

    :ivar f_t_ref: An array of the factor of conversion from refractory period in seconds to refractory period bias current in Amperes
    :type f_t_ref: JP_ndarray
    :ivar f_t_pulse: An array of the factor of conversion from pulse width in seconds to pulse width bias current in Amperes
    :type f_t_pulse: JP_ndarray
    """

    __doc__ += DynapSE1NeuronSynapseJax.__doc__

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
        sim_config: Optional[DynapSE1SimCore] = None,
        w_in: Optional[FloatVector] = None,
        w_rec: Optional[FloatVector] = None,
        dt: float = 1e-3,
        rng_key: Optional[Any] = None,
        spiking_input: bool = True,
        spiking_output: bool = True,
        *args,
        **kwargs
    ) -> None:
        """
        __init__ Initialize ``DynapSE1Jax`` module. Parameters are explained in the superclass docstring.
        """

        if sim_config is None:
            sim_config = DynapSE1SimCore(shape[-1])

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
            **kwargs
        )

        self.f_t_ref = SimulationParameter(sim_config.f_t_ref)
        self.f_t_pulse = SimulationParameter(sim_config.f_t_pulse)

    def samna_param_group(self, chipId: int, coreId: int) -> Dynapse1ParameterGroup:
        """
        samna_param_group creates a samna Dynapse1ParameterGroup group object and configure the bias
        parameters by creating a dictionary. It does not check if the values are legal or not.

        :param chipId: the chip ID to declare in the paramter group
        :type chipId: int
        :param coreId: the core ID to declare in the parameter group
        :type coreId: int
        :return: samna config object to set a parameter group within one core
        :rtype: Dynapse1ParameterGroup
        """
        pg_json = json.dumps(self._param_group(chipId, coreId))
        pg_samna = Dynapse1ParameterGroup()
        pg_samna.from_json(pg_json)
        return pg_samna

    def _param_group(
        self, chipId, coreId
    ) -> Dict[
        str,
        Dict[str, Union[int, List[Dict[str, Union[str, Dict[str, Union[str, int]]]]]]],
    ]:
        """
        _param_group creates a samna type dictionary to configure the parameter group

        :param chipId: the chip ID to declare in the paramter group
        :type chipId: int
        :param coreId: the core ID to declare in the parameter group
        :type coreId: int
        :return: a dictonary of bias currents, and their coarse/fine values
        :rtype: Dict[str, Dict[str, Union[int, List[Dict[str, Union[str, Dict[str, Union[str, int]]]]]]]]
        """

        def param_dict(param: Dynapse1Parameter) -> Dict[str, Union[str, int]]:
            serial = {
                "paramName": param.param_name,
                "coarseValue": param.coarse_value,
                "fineValue": param.fine_value,
                "type": param.type,
            }
            return serial

        paramMap = [
            {"key": bias, "value": param_dict(self.__getattribute__(bias))}
            for bias in self.biases
        ]

        group = {
            "value0": {
                "paramMap": paramMap,
                "chipId": chipId,
                "coreId": coreId,
            }
        }

        return group

    @classmethod
    def from_config(
        cls,
        config: Dynapse1Configuration,
        virtual_connections: Optional[List[NeuronConnection]] = None,
        w_in: Optional[FloatVector] = None,
        default_bias: bool = True,
        *args,
        **kwargs
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
        :param default_bias: use default bias values or get the bias parameters from the netgen.config, defaults to True
        :type default_bias: bool
        :return: `DynapSE1Jax` simulator object
        :rtype: DynapSE1Jax
        """
        _w_in, w_rec, idx_map = Router.get_weight_from_config(
            config, virtual_connections, return_maps=True, decode_UID=True
        )
        w_in = _w_in if w_in is None else w_in

        shape = w_in.shape[0:2]
        if not default_bias:
            simconfig = DynapSE1SimConfig.from_config(config, idx_map["w_rec"])

        else:
            simconfig = DynapSE1SimConfig.from_config(None, idx_map["w_rec"])
        mod = cls(shape, simconfig, w_in, w_rec, *args, **kwargs)
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

    ## --- LOW LEVEL BIAS CURRENTS (SAMNA) -- ##
    @property
    def IF_AHTAU_N(self):
        """
        IF_AHTAU_N is the bias current controlling the AHP circuit time constant. Itau_ahp
        """
        param = get_Dynapse1Parameter(
            bias=self.Itau_syn[self.SYN["AHP"]].mean(), name="IF_AHTAU_N"
        )
        return param

    @property
    def IF_AHTHR_N(self):
        param = get_Dynapse1Parameter(
            bias=self.Ith_syn[self.SYN["AHP"]].mean(), name="IF_AHTHR_N"
        )
        return param

    @property
    def IF_AHW_P(self):
        param = get_Dynapse1Parameter(
            bias=self.Iw[self.SYN["AHP"]].mean(), name="IF_AHW_P"
        )
        return param

    @property
    def IF_BUF_P(self):
        """
        IF_BUF_P Vm readout, use samna defaults.
        """
        return Dynapse1Parameter("IF_BUF_P", 4, 80)

    @property
    def IF_CASC_N(self):
        """
        IF_CASC_N for AHP regularization, not so important, use samna defaults.
        """
        param = get_Dynapse1Parameter(bias=self.Io.mean(), name="IF_CASC_N")
        return param

    @property
    def IF_DC_P(self):
        param = get_Dynapse1Parameter(bias=self.Idc.mean(), name="IF_DC_P")
        return param

    @property
    def IF_NMDA_N(self):
        param = get_Dynapse1Parameter(bias=self.If_nmda.mean(), name="IF_NMDA_N")
        return param

    @property
    def IF_RFR_N(self):
        """
        # 4, 120 in Chenxi
        # 0, 20 by Ugurcan
        """
        I_ref = self.f_t_ref / self.t_ref
        param = get_Dynapse1Parameter(bias=I_ref.mean(), name="IF_RFR_N")
        return param

    @property
    def IF_TAU1_N(self):
        param = get_Dynapse1Parameter(bias=self.Itau_mem.mean(), name="IF_TAU1_N")
        return param

    @property
    def IF_TAU2_N(self):
        """
        IF_TAU2_N Second refractory period. Generally max current. For deactivation of certain neruons.
        """
        return Dynapse1Parameter("IF_TAU2_N", 7, 255)

    @property
    def IF_THR_N(self):
        param = get_Dynapse1Parameter(bias=self.Ith_mem.mean(), name="IF_THR_N")
        return param

    @property
    def NPDPIE_TAU_F_P(self):
        # FAST_EXC, AMPA
        param = get_Dynapse1Parameter(
            bias=self.Itau_syn[self.SYN["AMPA"]].mean(), name="NPDPIE_TAU_F_P"
        )
        return param

    @property
    def NPDPIE_TAU_S_P(self):
        # SLOW_EXC, NMDA
        param = get_Dynapse1Parameter(
            bias=self.Itau_syn[self.SYN["NMDA"]].mean(), name="NPDPIE_TAU_S_P"
        )
        return param

    @property
    def NPDPIE_THR_F_P(self):
        # FAST_EXC, AMPA
        param = get_Dynapse1Parameter(
            bias=self.Ith_syn[self.SYN["AMPA"]].mean(), name="NPDPIE_THR_F_P"
        )
        return param

    @property
    def NPDPIE_THR_S_P(self):
        # SLOW_EXC, NMDA
        param = get_Dynapse1Parameter(
            bias=self.Ith_syn[self.SYN["NMDA"]].mean(), name="NPDPIE_THR_S_P"
        )
        return param

    @property
    def NPDPII_TAU_F_P(self):
        # FAST_INH, GABA_B, shunting current, a mixture of subtractive and divisive
        param = get_Dynapse1Parameter(
            bias=self.Itau_syn[self.SYN["GABA_B"]].mean(), name="NPDPII_TAU_F_P"
        )
        return param

    @property
    def NPDPII_TAU_S_P(self):
        # SLOW_INH, GABA_A, subtractive
        param = get_Dynapse1Parameter(
            bias=self.Itau_syn[self.SYN["GABA_A"]].mean(), name="NPDPII_TAU_S_P"
        )
        return param

    @property
    def NPDPII_THR_F_P(self):
        # FAST_INH, GABA_B, shunting current, a mixture of subtractive and divisive
        param = get_Dynapse1Parameter(
            bias=self.Ith_syn[self.SYN["GABA_B"]].mean(), name="NPDPII_THR_F_P"
        )
        return param

    @property
    def NPDPII_THR_S_P(self):
        # SLOW_INH, GABA_A, subtractive
        param = get_Dynapse1Parameter(
            bias=self.Ith_syn[self.SYN["GABA_A"]].mean(), name="NPDPII_THR_S_P"
        )
        return param

    @property
    def PS_WEIGHT_EXC_F_N(self):
        # FAST_EXC, AMPA
        param = get_Dynapse1Parameter(
            bias=self.Iw[self.SYN["AMPA"]].mean(), name="PS_WEIGHT_EXC_F_N"
        )
        return param

    @property
    def PS_WEIGHT_EXC_S_N(self):
        # SLOW_EXC, NMDA
        param = get_Dynapse1Parameter(
            bias=self.Iw[self.SYN["NMDA"]].mean(), name="PS_WEIGHT_EXC_S_N"
        )
        return param

    @property
    def PS_WEIGHT_INH_F_N(self):
        # FAST_INH, GABA_B, shunting current, a mixture of subtractive and divisive
        param = get_Dynapse1Parameter(
            bias=self.Iw[self.SYN["GABA_B"]].mean(), name="PS_WEIGHT_INH_F_N"
        )
        return param

    @property
    def PS_WEIGHT_INH_S_N(self):
        # SLOW_INH, GABA_A, subtractive
        param = get_Dynapse1Parameter(
            bias=self.Iw[self.SYN["GABA_A"]].mean(), name="PS_WEIGHT_INH_S_N"
        )
        return param

    @property
    def PULSE_PWLK_P(self):
        """
        # 4, 160 by default
        # 3, 56 for 10u by Ugurcan
        """
        I_pulse = self.f_t_pulse / self.t_pulse
        param = get_Dynapse1Parameter(bias=I_pulse.mean(), name="PULSE_PWLK_P")
        return param

    @property
    def R2R_P(self):
        # Use samna defaults
        return Dynapse1Parameter("R2R_P", 3, 85)
