"""
Dynap-SE Simulation core to configure DynapSim simulation modules

renamed : dynapse1_simconfig.py -> simconfig.py @ 211208
split_from : simconfig.py -> layout.py @ 220114
split_from : simconfig.py -> circuits.py @ 220114
merged from : layout.py -> simcore.py @ 220505
merged from : circuits.py -> simcore.py @ 220505

Project Owner : Dylan Muir, SynSense AG
Author : Ugurcan Cakal
E-mail : ugurcan.cakal@gmail.com
03/05/2022

[] TODO : Biasgen type
[] TODO : add C_pulse_ahp
[] TODO : Add r_spkthr to gain
[] TODO :     
    :param neuron_idx_map: the neuron index map used in the case that the matrix indexes of the neurons and the device indexes are different.
    :type neuron_idx_map: Dict[np.uint8, np.uint16]
    :param core_key: the chip_id and core_id tuple uniquely defining the core, defaults to None
    :type core_key: Optional[Tuple[np.uint8]], optional

[] TODO : Implement samna aliases
    Dynapse1Configuration = Any
    Dynapse1Core = Any
    Dynapse2Configuration = Any
    Dynapse2Core = Any
[] TODO : add from_bias methods to samna aliases
"""

from __future__ import annotations
import logging

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from dataclasses import dataclass, replace, field

from rockpool.devices.dynapse.infrastructure.biasgen import (
    BiasGen,
    BiasGenSE1,
    BiasGenSE2,
)
from rockpool.devices.dynapse.lookup import param_name
from rockpool.devices.dynapse.samna_alias.dynapse1 import Dynapse1Parameter
from rockpool.devices.dynapse.samna_alias.dynapse2 import Dynapse2Parameter

Dynapse1Configuration = Any
Dynapse1Core = Any
Dynapse2Configuration = Any
Dynapse2Core = Any


@dataclass
class DynapSimLayout:
    """
    DynapSimLayout contains the constant values used in simulation that are related to the exact silicon layout of a Dynap-SE chips.

    :param C_ahp: AHP synapse capacitance in Farads, defaults to 40e-12
    :type C_ahp: float, optional
    :param C_ampa: AMPA synapse capacitance in Farads, defaults to 24.5e-12
    :type C_ampa: float, optional
    :param C_gaba: GABA synapse capacitance in Farads, defaults to 25e-12
    :type C_gaba: float, optional
    :param C_nmda: NMDA synapse capacitance in Farads, defaults to 25e-12
    :type C_nmda: float, optional
    :param C_pulse_ahp: spike frequency adaptation circuit pulse-width creation sub-circuit capacitance in Farads, defaults to 0.5e-12
    :type C_pulse_ahp: float, optional
    :param C_pulse: pulse-width creation sub-circuit capacitance in Farads, defaults to 0.5e-12
    :type C_pulse: float, optional
    :param C_ref: refractory period sub-circuit capacitance in Farads, defaults to 1.5e-12
    :type C_ref: float, optional
    :param C_shunt: SHUNT synapse capacitance in Farads, defaults to 24.5e-12
    :type C_shunt: float, optional
    :param C_soma: neuron soma capacitance in Farads, defaults to 3e-12
    :type C_soma: float, optional
    :param Io: Dark current in Amperes that flows through the transistors even at the idle state, defaults to 5e-13
    :type Io: float, optional
    :param kappa_n: Subthreshold slope factor (n-type transistor), defaults to 0.75
    :type kappa_n: float, optional
    :param kappa_p: Subthreshold slope factor (p-type transistor), defaults to 0.66
    :type kappa_p: float, optional
    :param Ut: Thermal voltage in Volts, defaults to 25e-3
    :type Ut: float, optional
    :param Vth: The cut-off Vgs potential of the transistors in Volts (not type specific), defaults to 7e-1
    :type Vth: float, optional
    """

    C_ahp: Optional[float] = 40e-12
    C_ampa: Optional[float] = 24.5e-12
    C_gaba: Optional[float] = 25e-12
    C_nmda: Optional[float] = 25e-12
    C_pulse_ahp: Optional[float] = 0.5e-12
    C_pulse: Optional[float] = 0.5e-12
    C_ref: Optional[float] = 1.5e-12
    C_shunt: Optional[float] = 24.5e-12
    C_soma: Optional[float] = 3e-12
    Io: Optional[float] = 5e-13
    kappa_n: Optional[float] = 0.75
    kappa_p: Optional[float] = 0.66
    Ut: Optional[float] = 25e-3
    Vth: Optional[float] = 7e-1


@dataclass
class DynapSimCore:
    """
    DynapSE1SimCore stores the simulation currents and manages the conversion from configuration objects
    It also provides easy update mechanisms using coarse&fine values, high-level parameter representations and etc.

    :param layout: constant values that are related to the exact silicon layout of a chip, defaults to None
    :type layout: Optional[DynapSimLayout], optional
    :param size: the number of neurons allocated in the simulation core, defaults to None
    :type size: Optional[int], optional
    :param Idc: Constant DC current injected to membrane in Amperes
    :type Idc: float
    :param If_nmda: NMDA gate soft cut-off current setting the NMDA gating voltage in Amperes
    :type If_nmda: float
    :param Igain_ahp: gain bias current of the spike frequency adaptation block in Amperes
    :type Igain_ahp: float
    :param Igain_ampa: gain bias current of excitatory AMPA synapse in Amperes
    :type Igain_ampa: float
    :param Igain_gaba: gain bias current of inhibitory GABA synapse in Amperes
    :type Igain_gaba: float
    :param Igain_nmda: gain bias current of excitatory NMDA synapse in Amperes
    :type Igain_nmda: float
    :param Igain_shunt: gain bias current of the inhibitory SHUNT synapse in Amperes
    :type Igain_shunt: float
    :param Igain_soma: gain bias current for neuron membrane in Amperes
    :type Igain_soma: float
    :param Ipulse_ahp: bias current setting the pulse width for spike frequency adaptation block `t_pulse_ahp` in Amperes
    :type Ipulse_ahp: float
    :param Ipulse: bias current setting the pulse width for neuron soma `t_pulse` in Amperes
    :type Ipulse: float
    :param Iref: bias current setting the refractory period `t_ref` in Amperes
    :type Iref: float
    :param Ispkthr: spiking threshold current, neuron spikes if :math:`Imem > Ispkthr` in Amperes
    :type Ispkthr: float
    :param Itau_ahp: Spike frequency adaptation leakage current setting the time constant `tau_ahp` in Amperes
    :type Itau_ahp: float
    :param Itau_ampa: AMPA synapse leakage current setting the time constant `tau_ampa` in Amperes
    :type Itau_ampa: float
    :param Itau_gaba: GABA synapse leakage current setting the time constant `tau_gaba` in Amperes
    :type Itau_gaba: float
    :param Itau_nmda: NMDA synapse leakage current setting the time constant `tau_nmda` in Amperes
    :type Itau_nmda: float
    :param Itau_shunt: SHUNT synapse leakage current setting the time constant `tau_shunt` in Amperes
    :type Itau_shunt: float
    :param Itau_soma: Neuron soma leakage current setting the time constant `tau_soma` in Amperes
    :type Itau_soma: float
    :param Iw_0: weight bit 0 current of the neurons of the core in Amperes
    :type Iw_0: float
    :param Iw_1: weight bit 1 current of the neurons of the core in Amperes
    :type Iw_1: float
    :param Iw_2: weight bit 2 current of the neurons of the core in Amperes
    :type Iw_2: float
    :param Iw_3: weight bit 3 current of the neurons of the core in Amperes
    :type Iw_3: float
    :param Iw_ahp: spike frequency adaptation weight current of the neurons of the core in Amperes
    :type Iw_ahp: float
    """

    layout: Optional[DynapSimLayout] = field(default=None, repr=False)
    size: Optional[int] = None
    Idc: Optional[float] = None
    If_nmda: Optional[float] = None
    Igain_ahp: Optional[float] = None
    Igain_ampa: Optional[float] = None
    Igain_gaba: Optional[float] = None
    Igain_nmda: Optional[float] = None
    Igain_shunt: Optional[float] = None
    Igain_soma: Optional[float] = None
    Ipulse_ahp: Optional[float] = None
    Ipulse: Optional[float] = None
    Iref: Optional[float] = None
    Ispkthr: Optional[float] = None
    Itau_ahp: Optional[float] = None
    Itau_ampa: Optional[float] = None
    Itau_gaba: Optional[float] = None
    Itau_nmda: Optional[float] = None
    Itau_shunt: Optional[float] = None
    Itau_soma: Optional[float] = None
    Iw_0: Optional[float] = None
    Iw_1: Optional[float] = None
    Iw_2: Optional[float] = None
    Iw_3: Optional[float] = None
    Iw_ahp: Optional[float] = None

    def __post_init__(self) -> None:
        if self.layout is None:
            self.layout = DynapSimLayout()

    @classmethod
    def from_specificaiton(
        cls,
        size: int,
        layout: Optional[DynapSimLayout] = None,
        Idc: float = None,
        If_nmda: float = None,
        r_gain_ahp: float = 100,
        r_gain_ampa: float = 100,
        r_gain_gaba: float = 100,
        r_gain_nmda: float = 100,
        r_gain_shunt: float = 100,
        r_gain_soma: float = 4,
        t_pulse_ahp: float = 1e-6,
        t_pulse: float = 10e-6,
        t_ref: float = 2e-2,
        Ispkthr: float = 1e-6,
        tau_ahp: float = 50e-3,
        tau_ampa: float = 10e-3,
        tau_gaba: float = 100e-3,
        tau_nmda: float = 100e-3,
        tau_shunt: float = 10e-3,
        tau_soma: float = 20e-3,
        Iw_0: float = 1e-6,
        Iw_1: float = 2e-6,
        Iw_2: float = 4e-6,
        Iw_3: float = 8e-6,
        Iw_ahp: float = 1e-6,
    ) -> DynapSimCore:
        """
        from_specificaiton is a class factory method helping DynapSimCore object construction
        using higher level representaitons of the currents like gain ratio or time constant whenever applicable.

        :param size: the number of neurons allocated in the simulation core
        :type size: int
        :param layout: constant values that are related to the exact silicon layout of a chip, defaults to None
        :type layout: Optional[DynapSimLayout], optional
        :param Idc: Constant DC current injected to membrane in Amperes, defaults to None
        :type Idc: float, optional
        :param If_nmda: NMDA gate soft cut-off current setting the NMDA gating voltage in Amperes, defaults to None
        :type If_nmda: float, optional
        :param r_gain_ahp: spike frequency adaptation block gain ratio :math:`Igain_ahp/Itau_ahp`, defaults to 100
        :type r_gain_ahp: float, optional
        :param r_gain_ampa: excitatory AMPA synpse gain ratio :math:`Igain_ampa/Itau_ampa`, defaults to 100
        :type r_gain_ampa: float, optional
        :param r_gain_gaba: inhibitory GABA synpse gain ratio :math:`Igain_gaba/Itau_gaba `, defaults to 100
        :type r_gain_gaba: float, optional
        :param r_gain_nmda: excitatory NMDA synpse gain ratio :math:`Igain_nmda/Itau_nmda`, defaults to 100
        :type r_gain_nmda: float, optional
        :param r_gain_shunt: inhibitory SHUNT synpse gain ratio :math:`Igain_shunt/Itau_shunt`, defaults to 100
        :type r_gain_shunt: float, optional
        :param r_gain_soma: neuron soma gain ratio :math:`Igain_soma/Itau_soma`, defaults to 2
        :type r_gain_soma: float, optional
        :param t_pulse_ahp: the spike pulse width for spike frequency adaptation circuit in seconds, defaults to 1e-6
        :type t_pulse_ahp: float, optional
        :param t_pulse: the spike pulse width for neuron soma in seconds, defaults to 10e-6
        :type t_pulse: float, optional
        :param t_ref: refractory period of the neurons in seconds, defaults to 2e-2
        :type t_ref: float, optional
        :param Ispkthr: spiking threshold current, neuron spikes if :math:`Imem > Ispkthr` in Amperes, defaults to 1e-6
        :type Ispkthr: float, optional
        :param tau_ahp: Spike frequency leakage time constant in seconds, defaults to 50e-3
        :type tau_ahp: float, optional
        :param tau_ampa: AMPA synapse leakage time constant in seconds, defaults to 10e-3
        :type tau_ampa: float, optional
        :param tau_gaba: GABA synapse leakage time constant in seconds, defaults to 100e-3
        :type tau_gaba: float, optional
        :param tau_nmda: NMDA synapse leakage time constant in seconds, defaults to 100e-3
        :type tau_nmda: float, optional
        :param tau_shunt:SHUNT synapse leakage time constant in seconds, defaults to 10e-3
        :type tau_shunt: float, optional
        :param tau_soma: Neuron soma leakage time constant in seconds, defaults to 20e-3
        :type tau_soma: float, optional
        :param Iw_0: weight bit 0 current of the neurons of the core in Amperes, defaults to 1e-6
        :type Iw_0: float
        :param Iw_1: weight bit 1 current of the neurons of the core in Amperes, defaults to 2e-6
        :type Iw_1: float
        :param Iw_2: weight bit 2 current of the neurons of the core in Amperes, defaults to 4e-6
        :type Iw_2: float
        :param Iw_3: weight bit 3 current of the neurons of the core in Amperes, defaults to 8e-6
        :type Iw_3: float
        :param Iw_ahp: spike frequency adaptation weight current of the neurons of the core in Amperes, defaults to 1e-6
        :type Iw_ahp: float
        :return: DynapSimCore object
        :rtype: DynapSimCore
        """

        # Depended default parameter initialization
        layout = DynapSimLayout() if layout is None else layout
        Idc = layout.Io if Idc is None else Idc
        If_nmda = layout.Io if If_nmda is None else If_nmda

        # Construct the core with compulsory low level current parameters
        _core = cls(
            size=size,
            layout=layout,
            Idc=Idc,
            If_nmda=If_nmda,
            Ispkthr=Ispkthr,
            Iw_0=Iw_0,
            Iw_1=Iw_1,
            Iw_2=Iw_2,
            Iw_3=Iw_3,
            Iw_ahp=Iw_ahp,
        )

        # Set the Itau currents
        _time = DynapSimCoreTime(
            t_pulse_ahp,
            t_pulse,
            t_ref,
            tau_ahp,
            tau_ampa,
            tau_gaba,
            tau_nmda,
            tau_shunt,
            tau_soma,
        )
        _core = _time.update_DynapSimCore(_core)

        # Set Igain currents depending on the ratio between related Itau currents
        _gain = DynapSimCoreGain(
            r_gain_ahp,
            r_gain_ampa,
            r_gain_gaba,
            r_gain_nmda,
            r_gain_shunt,
            r_gain_soma,
        )
        _core = _gain.update_DynapSimCore(_core)

        return _core

    @classmethod
    def __from_samna(
        cls,
        biasgen: BiasGen,
        param_getter: Callable[[str], Union[Dynapse1Parameter, Dynapse2Parameter]],
        param_map: Dict[str, str],
    ) -> DynapSimCore:
        """
        __from_samna is a class factory method which uses samna configuration objects to extract the simulation currents

        :param biasgen: the bias generator to convert the device parameters with coarse and fine values to bias currents
        :type biasgen: BiasGen
        :param param_getter: a function wich returns a samna parameter object given a name
        :type param_getter: Callable[[str], Union[Dynapse1Parameter, Dynapse2Parameter]]
        :param param_map: the dictionary of simulated currents and their respective device configaration parameter names like {"Idc": "SOIF_DC_P"}
        :type param_map: Dict[str, str]
        :return: a dynapse core simulation object whose parameters are imported from a samna configuration object
        :rtype: DynapSimCore
        """
        _current = lambda name: biasgen.param_to_bias(name, param_getter(name))
        _dict = {sim: _current(param) for sim, param in param_map.items()}
        _mod = cls(size=None, **_dict)
        return _mod

    @classmethod
    def from_Dynapse1Core(cls, core: Dynapse1Core) -> DynapSimCore:
        """
        from_Dynapse1Core is a class factory method which uses a samna Dynapse1Core object to extract the simualation current parameters

        :param core: a samna Dynapse1Core configuration object used to configure the core properties
        :type core: Dynapse1Core
        :return: a dynapse core simulation object whose parameters are imported from a samna configuration object
        :rtype: DynapSimCore
        """
        _mod = cls.__from_samna(
            biasgen=BiasGenSE1(),
            param_getter=lambda name: core.parameter_group.param_map[name],
            param_map=param_name.se1,
        )

        return _mod

    @classmethod
    def from_Dynapse2Core(cls, core: Dynapse2Core) -> DynapSimCore:
        """
        from_Dynapse2Core is a class factory method which uses a samna Dynapse2Core object to extract the simualation current parameters

        :param core: a samna Dynapse2Core configuration object used to configure the core properties
        :type core: Dynapse2Core
        :return: a dynapse core simulation object whose parameters are imported from a samna configuration object
        :rtype: DynapSimCore
        """
        _mod = cls.__from_samna(
            biasgen=BiasGenSE2(),
            param_getter=lambda name: core.parameters[name],
            param_map=param_name.se2,
        )
        return _mod

    def update(self, attr: str, value: Any) -> DynapSimCore:
        """
        update_current updates an attribute and returns a new object, does not change the original object.

        :param attr: any attribute that belongs to DynapSimCore object
        :type attr: str
        :param value: the new value to set
        :type value: Any
        :return: updated DynapSimCore object
        :rtype: DynapSimCore
        """
        if attr in list(self.__dict__.keys()):
            _updated = replace(self)
            _updated.__setattr__(attr, value)
            self.compare(self, _updated)

        return _updated

    def __update_high_level(
        self,
        obj: DynapSimCoreHigh,
        attr_getter: Callable[[str], Any],
        attr: str,
        value: Any,
    ) -> DynapSimCore:
        """
        __update_high_level updates high level representations of the current values like time constants and gain ratios.
        The current values are updated accordingly without changing the original object.

        :param obj: the high level object that stores the projections of the current values
        :type obj: DynapSimCoreHigh
        :param attr_getter: a function to get the high level attribute from the high level object
        :type attr_getter: Callable[[str], Any]
        :param attr: any attribute that belongs to any DynapSimCoreHigh object
        :type attr: str
        :param value: the new value to set
        :type value: Any
        :return: updated DynapSimCore object
        :rtype: DynapSimCore
        """
        if attr in list(obj.__dict__.keys()):
            obj.__setattr__(attr, value)
            _updated = obj.update_DynapSimCore(self)
            logging.info(
                f" {attr} value changed from {attr_getter(attr)} to {obj.__getattribute__(attr)}"
            )
            self.compare(self, _updated)

        return _updated

    def update_time_constant(self, attr: str, value: Any) -> DynapSimCore:
        """
        update_time_constant updates currents setting time constant attributes that have a representation in `DynapSimCoreTime()` class instances

        :param attr: any attribute that belongs to any DynapSimCoreTime object
        :type attr: str
        :param value: the new value to set
        :type value: Any
        :return: updated DynapSimCore object
        :rtype: DynapSimCore
        """
        return self.__update_high_level(
            obj=DynapSimCoreTime(),
            attr_getter=lambda name: self.time.__getattribute__(name),
            attr=attr,
            value=value,
        )

    def update_gain_ratio(self, attr: str, value: Any) -> DynapSimCore:
        """
        update_gain_ratio updates currents setting gain ratio (Igain/Itau) attributes that have a representation in `DynapSimCoreGain()` class instances

        :param attr: any attribute that belongs to any DynapSimCoreGain object
        :type attr: str
        :param value: the new value to set
        :type value: Any
        :return: updated DynapSimCore object
        :rtype: DynapSimCore
        """
        return self.__update_high_level(
            obj=DynapSimCoreGain(),
            attr_getter=lambda name: self.gain.__getattribute__(name),
            attr=attr,
            value=value,
        )

    @staticmethod
    def compare(core1: DynapSimCore, core2: DynapSimCore) -> Dict[str, Tuple[Any]]:
        """
        compare compares two DynapSimCore objects detects the different values set

        :param core1: the first core object
        :type core1: DynapSimCore
        :param core2: the second core object to compare against the first one
        :type core2: DynapSimCore
        :return: a dictionary of changed values
        :rtype: Dict[str, Tuple[Any]]
        """

        changed = {}
        for key in core1.__dict__:
            val1 = core1.__getattribute__(key)
            val2 = core2.__getattribute__(key)
            if val1 != val2:
                changed[key] = (val1, val2)
                logging.info(f" {key} value changed from {val1} to {val2}")

        return changed

    @property
    def time(self) -> DynapSimCoreTime:
        """
        time creates the high level time constants set by currents
        Ipulse_ahp, Ipulse, Iref, Itau_ahp, Itau_ampa, Itau_gaba, Itau_nmda, Itau_shunt, Itau_soma
        """
        return DynapSimCoreTime.from_DynapSimCore(self)

    @property
    def gain(self) -> DynapSimCoreGain:
        """
        gain creates the high level gain ratios set by currents
        Igain_ahp, Igain_ampa, Igain_gaba, Igain_nmda, Igain_shunt, Igain_soma
        """
        return DynapSimCoreGain.from_DynapSimCore(self)


@dataclass
class DynapSimCoreHigh:
    """
    DynapSimCoreHigh is an abstract class to be used as a boiler-plate for high-level projection classes
    """

    @classmethod
    def from_DynapSimCore(cls, core: DynapSimCore) -> DynapSimCoreHigh:
        NotImplementedError("Abstract method not implemented!")

    def update_DynapSimCore(self, core: DynapSimCore) -> DynapSimCore:
        NotImplementedError("Abstract method not implemented!")


@dataclass
class DynapSimCoreTime(DynapSimCoreHigh):
    """
    DynapSimCoreTime stores the high-level projections of the currents setting time consant values

    :param t_pulse_ahp: the spike pulse width for spike frequency adaptation circuit in seconds
    :type t_pulse_ahp: float, optional
    :param t_pulse: the spike pulse width for neuron soma in seconds
    :type t_pulse: float, optional
    :param t_ref: refractory period of the neurons in seconds
    :type t_ref: float, optional
    :param tau_ahp: Spike frequency leakage time constant in seconds
    :type tau_ahp: float, optional
    :param tau_ampa: AMPA synapse leakage time constant in seconds
    :type tau_ampa: float, optional
    :param tau_gaba: GABA synapse leakage time constant in seconds
    :type tau_gaba: float, optional
    :param tau_nmda: NMDA synapse leakage time constant in seconds
    :type tau_nmda: float, optional
    :param tau_shunt:SHUNT synapse leakage time constant in seconds
    :type tau_shunt: float, optional
    :param tau_soma: Neuron soma leakage time constant in seconds
    :type tau_soma: float, optional
    """

    t_pulse_ahp: Optional[float] = None
    t_pulse: Optional[float] = None
    t_ref: Optional[float] = None
    tau_ahp: Optional[float] = None
    tau_ampa: Optional[float] = None
    tau_gaba: Optional[float] = None
    tau_nmda: Optional[float] = None
    tau_shunt: Optional[float] = None
    tau_soma: Optional[float] = None

    @classmethod
    def from_DynapSimCore(cls, core: DynapSimCore) -> DynapSimCoreTime:
        """
        from_DynapSimCore is a class factory method using DynapSimCore object

        :param core: the `DynapSimCore` object contatining the current values setting the time constants
        :type core: DynapSimCore
        :return: a `DynapSimCoreTime` object, that stores the time constants set by a `DynapSimCore`
        :rtype: DynapSimCoreTime
        """

        def _tau(name: str) -> float:
            """
            _tau converts a current value to a tau parameter

            :param name: the name of the subcircuit
            :type name: str
            :return: time constant in seconds
            :rtype: float
            """
            return cls.tau_converter(
                tau=core.__getattribute__(f"Itau_{name}"),
                Ut=core.layout.Ut,
                kappa=(core.layout.kappa_n + core.layout.kappa_p) / 2,
                C=core.layout.__getattribute__(f"C_{name}"),
            )

        def _pw(name: str) -> float:
            """
            _pw converts a current value to a pulse width parameter

            :param name: the name of the subcircuit
            :type name: str
            :return: pulse width in seconds
            :rtype: float
            """
            return cls.pw_converter(
                pw=core.__getattribute__(f"I{name}"),
                Vth=core.layout.Vth,
                C=core.layout.__getattribute__(f"C_{name}"),
            )

        # Construct the object
        _mod = cls(
            t_pulse_ahp=_pw("pulse_ahp"),
            t_pulse=_pw("pulse"),
            t_ref=_pw("ref"),
            tau_ahp=_tau("ahp"),
            tau_ampa=_tau("ampa"),
            tau_gaba=_tau("gaba"),
            tau_nmda=_tau("nmda"),
            tau_shunt=_tau("shunt"),
            tau_soma=_tau("soma"),
        )
        return _mod

    def update_DynapSimCore(self, core: DynapSimCore) -> DynapSimCore:
        """
        update_DynapSimCore updates a `DynapSimCore` object using the defined attirbutes in `DynapSimCoreTime` object
        It does not change the original core object and returns an updated copy

        :param core: a `DynapSimCore` object to be updated
        :type core: DynapSimCore
        :raises ValueError: Layout should be defined for update
        :return: an updated copy of DynapSimCore object
        :rtype: DynapSimCore
        """
        if core.layout is None:
            raise ValueError("Layout should be defined for update!")

        _core = replace(core)

        def _tau(name: str) -> float:
            """
            _tau converts a time constant to a representative current

            :param name: the name of the subcircuit of interest
            :type name: str
            :return: the current in Amperes setting the time constant
            :rtype: float
            """
            tau = self.__getattribute__(f"tau_{name}")
            if tau is None:
                __value = _core.__getattribute__(f"Itau_{name}")
            else:
                __value = self.tau_converter(
                    tau=tau,
                    Ut=_core.layout.Ut,
                    kappa=(_core.layout.kappa_n + _core.layout.kappa_p) / 2,
                    C=_core.layout.__getattribute__(f"C_{name}"),
                )

            return __value

        def _pw(name: str) -> float:
            """
            _pw converts a pulse width to a representative current

            :param name: the name of the subcircuit of interest
            :type name: str
            :return: the current in Amperes setting the pulse width
            :rtype: float
            """
            pw = self.__getattribute__(f"t_{name}")
            if pw is None:
                __value = _core.__getattribute__(f"I{name}")
            else:
                __value = self.pw_converter(
                    pw=pw,
                    Vth=_core.layout.Vth,
                    C=_core.layout.__getattribute__(f"C_{name}"),
                )

            return __value

        # Update
        for time in ["pulse_ahp", "pulse", "ref"]:
            _core.__setattr__(f"I{time}", _pw(time))

        for syn in ["ahp", "ampa", "gaba", "nmda", "shunt", "soma"]:
            _core.__setattr__(f"Itau_{syn}", _tau(syn))

        return _core

    @staticmethod
    def tau_converter(tau: float, Ut: float, kappa: float, C: float) -> float:
        """
        tau_converter converts a time constant to a current value or a current value to a time constant using the conversion above:

        .. math ::

            \\tau = \\dfrac{C U_{T}}{\\kappa I_{\\tau}}

        :param tau: a time constant or a current setting the time constant
        :type tau: float
        :param Ut: Thermal voltage in Volts
        :type Ut: float, optional
        :param kappa: Subthreshold slope factor of the responsible transistor
        :type kappa: float
        :param C: the capacitance value of the subcircuit
        :type C: float
        :return: a time constant or a current setting the time constant. If a time constant provided as input, the current is returned and vice versa
        :rtype: float
        """
        if tau is None or tau <= 0.0:
            return None
        _tau = ((Ut / kappa) * C) / tau
        return _tau

    @staticmethod
    def pw_converter(pw: float, Vth: float, C: float) -> float:
        """
        pw_converter converts a pulse width to a current value or a current value to a pulse width using the conversion above:

        .. math ::

            pw = \\dfrac{C V_{th}}{\\kappa I_{pw}}

        :param pw: a pulse width or a current setting the pulse width
        :type pw: float
        :param Vth: The cut-off Vgs potential of the respective transistor in Volts
        :type Vth: float
        :param C: the capacitance value of the subcircuit
        :type C: float
        :return: a pulse width or a current setting the pulse width. If a pulse width provided as input, the current is returned and vice versa
        :rtype: float
        """
        if pw is None or pw <= 0.0:
            return None
        _pw = (Vth * C) / pw
        return _pw


@dataclass
class DynapSimCoreGain(DynapSimCoreHigh):
    """
    DynapSimCoreGain stores the ratio between gain and tau current values

    :param r_gain_ahp: spike frequency adaptation block gain ratio :math:`Igain_ahp/Itau_ahp`, defaults to 100
    :type r_gain_ahp: float, optional
    :param r_gain_ampa: excitatory AMPA synpse gain ratio :math:`Igain_ampa/Itau_ampa`, defaults to 100
    :type r_gain_ampa: float, optional
    :param r_gain_gaba: inhibitory GABA synpse gain ratio :math:`Igain_gaba/Itau_gaba `, defaults to 100
    :type r_gain_gaba: float, optional
    :param r_gain_nmda: excitatory NMDA synpse gain ratio :math:`Igain_nmda/Itau_nmda`, defaults to 100
    :type r_gain_nmda: float, optional
    :param r_gain_shunt: inhibitory SHUNT synpse gain ratio :math:`Igain_shunt/Itau_shunt`, defaults to 100
    :type r_gain_shunt: float, optional
    :param r_gain_soma: neuron soma gain ratio :math:`Igain_soma/Itau_soma`, defaults to 2
    :type r_gain_soma: float, optional
    """

    r_gain_ahp: Optional[float] = None
    r_gain_ampa: Optional[float] = None
    r_gain_gaba: Optional[float] = None
    r_gain_nmda: Optional[float] = None
    r_gain_shunt: Optional[float] = None
    r_gain_soma: Optional[float] = None

    @classmethod
    def from_DynapSimCore(cls, core: DynapSimCore) -> DynapSimCoreGain:
        """
        from_DynapSimCore is a class factory method using DynapSimCore object

        :param core: the `DynapSimCore` object contatining the current values setting the gain ratios
        :type core: DynapSimCore
        :return: a `DynapSimCoreGain` object, that stores the gain ratios set by a `DynapSimCore`
        :rtype: DynapSimCoreGain
        """
        _r_gain = lambda name: cls.ratio_gain(
            Igain=core.__getattribute__(f"Igain_{name}"),
            Itau=core.__getattribute__(f"Itau_{name}"),
        )

        # Construct the object
        _mod = cls(
            r_gain_ahp=_r_gain("ahp"),
            r_gain_ampa=_r_gain("ampa"),
            r_gain_gaba=_r_gain("gaba"),
            r_gain_nmda=_r_gain("nmda"),
            r_gain_shunt=_r_gain("shunt"),
            r_gain_soma=_r_gain("soma"),
        )
        return _mod

    def update_DynapSimCore(self, core: DynapSimCore) -> DynapSimCore:
        """
        update_DynapSimCore updates a `DynapSimCore` object using the defined attirbutes in `DynapSimCoreGain` object
        It does not change the original core object and returns an updated copy

        :param core: a `DynapSimCore` object to be updated
        :type core: DynapSimCore
        :return: an updated copy of DynapSimCore object
        :rtype: DynapSimCore
        """
        _I_gain = lambda name: self.gain_current(
            Igain=_core.__getattribute__(f"Igain_{name}"),
            r_gain=self.__getattribute__(f"r_gain_{name}"),
            Itau=_core.__getattribute__(f"Itau_{name}"),
        )
        _core = replace(core)

        for syn in ["ahp", "ampa", "gaba", "nmda", "shunt", "soma"]:
            _core.__setattr__(f"Igain_{syn}", _I_gain(syn))

        return _core

    @staticmethod
    def ratio_gain(Igain: Optional[float], Itau: Optional[float]) -> float:
        """
        ratio_gain checks the parameters and divide Igain by Itau

        :param Igain: any gain bias current in Amperes
        :type Igain: Optional[float]
        :param Itau: any leakage current in Amperes
        :type Itau: Optional[float]
        :return: the ratio between the currents if the currents are properly set
        :rtype: float
        """
        if Itau is not None and Itau > 0 and Igain is not None and Igain > 0:
            return Igain / Itau
        else:
            return None

    @staticmethod
    def gain_current(
        Igain: Optional[float], r_gain: Optional[float], Itau: Optional[float]
    ) -> float:
        """
        gain_current checks the ratio and Itau to deduce Igain out of them

        :param Igain: any gain bias current in Amperes
        :type Igain: Optional[float]
        :param r_gain: the ratio between Igain and Itau
        :type r_gain: Optional[float]
        :param Itau: any leakage current in Amperes
        :type Itau: Optional[float]
        :return: the gain bias current Igain in Amperes obtained from r_gain and Itau
        :rtype: float
        """
        if r_gain is None:
            return Igain
        elif Itau is not None:
            return Itau * r_gain
        else:
            return Igain


if __name__ == "__main__":
    import os

    logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))
    sim_config = DynapSimCore.from_specificaiton(10)
    print(sim_config)
    print(sim_config.time)
    print(sim_config.gain)
    updated = sim_config.update_gain_ratio("r_gain_soma", 10)
