"""
Low level DynapSE simulator.
Solves the characteristic equations to simulate the circuits.
Trainable parameters

renamed: dynapse1_neuron_synapse_jax.py -> adexplif_jax.py @ 211206
renamed: adexplif_jax.py -> dynapsim.py @ 220502

References:
[1] E. Chicca, F. Stefanini, C. Bartolozzi and G. Indiveri,
    "Neuromorphic Electronic Circuits for Building Autonomous Cognitive Systems,"
    in Proceedings of the IEEE, vol. 102, no. 9, pp. 1367-1388, Sept. 2014,
    doi: 10.1109/JPROC.2014.2313954.

[2] C. Bartolozzi and G. Indiveri, “Synaptic dynamics in analog vlsi,” Neural
    Comput., vol. 19, no. 10, p. 2581–2603, Oct. 2007. [Online]. Available:
    https://doi.org/10.1162/neco.2007.19.10.2581

[3] P. Livi and G. Indiveri, “A current-mode conductance-based silicon neuron for
    address-event neuromorphic systems,” in 2009 IEEE International Symposium on
    Circuits and Systems, May 2009, pp. 2898–2901

[4] Dynap-SE1 Neuromorphic Chip Simulator for NICE Workshop 2021
    https://code.ini.uzh.ch/yigit/NICE-workshop-2021

[5] Course: Neurormophic Engineering 1
    Tobi Delbruck, Shih-Chii Liu, Giacomo Indiveri
    https://tube.switch.ch/channels/88df64b6

[6] Course: 21FS INI508 Neuromorphic Intelligence
    Giacomo Indiveri
    https://tube.switch.ch/switchcast/uzh.ch/series/5ee1d666-25d2-4c4d-aeb9-4b754b880345?order=newest-first


Project Owner : Dylan Muir, SynSense AG
Author : Ugurcan Cakal
E-mail : ugurcan.cakal@gmail.com
13/07/2021
[] TODO : Optional mismatch
[] TODO : Check LIFjax for core.Tracer and all the other things
[] TODO : max spikes per dt
[] TODO : time and gain maybe as histogram
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import jax
from jax import random as rand
from jax import custom_gradient
from jax.lax import scan
from jax.tree_util import Partial

from jax import numpy as jnp
import numpy as np
from rockpool.devices.dynapse.config.board import DynapSimConfig
from rockpool.devices.dynapse.config.simcore import (
    DynapSimCurrents,
    DynapSimLayout,
    DynapSimTime,
)
from rockpool.devices.dynapse.config.weights import WeightParameters

from rockpool.nn.modules.jax.jax_module import JaxModule
from rockpool.parameters import Parameter, State, SimulationParameter

from rockpool.devices.dynapse.infrastructure.mismatch import MismatchDevice

DynapSEState = Tuple[
    jnp.DeviceArray,  # iahp
    jnp.DeviceArray,  # iampa
    jnp.DeviceArray,  # igaba
    jnp.DeviceArray,  # imem
    jnp.DeviceArray,  # inmda
    jnp.DeviceArray,  # ishunt
    jnp.DeviceArray,  # rng_key
    jnp.DeviceArray,  # spikes
    jnp.DeviceArray,  # timer_ref
    jnp.DeviceArray,  # vmem
]

DynapSERecord = Tuple[
    jnp.DeviceArray,  # iahp
    jnp.DeviceArray,  # iampa
    jnp.DeviceArray,  # igaba
    jnp.DeviceArray,  # imem
    jnp.DeviceArray,  # inmda
    jnp.DeviceArray,  # ishunt
    jnp.DeviceArray,  # spikes
    jnp.DeviceArray,  # vmem
]


Dynapse1Configuration = Any
Dynapse2Configuration = Any


@custom_gradient
def step_pwl(
    imem: jnp.DeviceArray, Ispkthr: jnp.DeviceArray, Ireset: jnp.DeviceArray
) -> Tuple[jnp.DeviceArray, Callable[[jnp.DeviceArray], jnp.DeviceArray]]:
    """
    step_pwl implements heaviside step function with piece-wise linear derivative to use as spike-generation surrogate

    :param imem: Input current to be compared for firing
    :type imem: jnp.DeviceArray
    :param Ispkthr: Spiking threshold current in Amperes
    :type Ispkthr: jnp.DeviceArray
    :param Ireset: Reset current after spike generation in Amperes
    :type Ireset: jnp.DeviceArray
    :return: spikes, grad_func
        spike: generated spike output values
        grad_func:gradient function
    :rtype: Tuple[jnp.DeviceArray, Callable[[jnp.DeviceArray], jnp.DeviceArray]]
    """

    spikes = jnp.clip(jnp.floor(imem - Ispkthr) + 1.0, 0.0)
    grad_func = lambda g: (g * (imem > Ireset) * (Ispkthr - Ireset), 0.0, 0.0)
    return spikes, grad_func


def poisson_weights_se2(
    shape: Tuple[int],
    Iw_0: float = 1e-7,
    Iw_1: float = 2e-7,
    Iw_2: float = 4e-7,
    Iw_3: float = 8e-7,
    fill_rate: Union[float, List[float]] = [0.25, 0.2, 0.04, 0.06],
    n_bits: int = 4,
) -> np.ndarray:

    mask = DynapSimConfig.poisson_mask(shape, fill_rate, n_bits)
    weight_param = WeightParameters(
        Iw_0=Iw_0, Iw_1=Iw_1, Iw_2=Iw_2, Iw_3=Iw_3, mux=mask
    )
    weights = weight_param.weights
    return weights


class DynapSim(JaxModule):
    """
    DynapSim solves dynamical chip equations for the DPI neuron and synapse models.
    Receives configuration as bias currents and solves membrane and synapse dynamics using ``jax`` backend.
    One block has
        - 4 synapses receiving spikes from the other circuits,
        - 1 recurrent synapse for spike frequency adaptation,
        - 1 membrane evaluating the state and deciding fire or not

    For all the synapses, the ``DPI Synapse`` update equations below are solved in parallel.

    :DPI Synapse:

    .. math ::

        I_{syn}(t_1) = \\begin{cases} I_{syn}(t_0) \\cdot exp \\left( \\dfrac{-dt}{\\tau} \\right) &\\text{in any case} \\\\ \\\\ I_{syn}(t_1) + \\dfrac{I_{th} I_{w}}{I_{\\tau}} \\cdot \\left( 1 - exp \\left( \\dfrac{-t_{pulse}}{\\tau} \\right) \\right) &\\text{if a spike arrives} \\end{cases}

    Where

    .. math ::

        \\tau = \\dfrac{C U_{T}}{\\kappa I_{\\tau}}

    For the membrane update, the forward Euler solution below is applied.

    :Membrane:

    .. math ::

        dI_{mem} = \dfrac{I_{mem}}{\tau \left( I_{mem} + I_{th} \right) } \cdot \left( I_{mem_{\infty}} + f(I_{mem}) - I_{mem} \left( 1 + \dfrac{I_{ahp}}{I_{\tau}} \right) \right) \cdot dt

        I_{mem}(t_1) = I_{mem}(t_0) + dI_{mem}

    Where

    .. math ::

        I_{mem_{\\infty}} = \\dfrac{I_{th}}{I_{\\tau}} \\left( I_{in} - I_{ahp} - I_{\\tau}\\right)

        f(I_{mem}) = \\dfrac{I_{a}}{I_{\\tau}} \\left(I_{mem} + I_{th} \\right )

        I_{a} = \\dfrac{I_{a_{gain}}}{1+ exp\\left(-\\dfrac{I_{mem}+I_{a_{th}}}{I_{a_{norm}}}\\right)}

    :On spiking:

    When the membrane potential for neuron :math:`j`, :math:`I_{mem, j}` exceeds the threshold current :math:`I_{spkthr}`, then the neuron emits a spike.

    .. math ::

        I_{mem, j} > I_{spkthr} \\rightarrow S_{j} = 1

        I_{mem, j} = I_{reset}

    :Attributes:

    :attr biases: name list of all the low level biases
    :type biases: List[str]

    :Parameters:

    :param shape: Either a single dimension ``N``, which defines a feed-forward layer of DynapSE AdExpIF neurons, or two dimensions ``(N, N)``, which defines a recurrent layer of DynapSE AdExpIF neurons.
    :type shape: Optional[Tuple[int]], optional
    :param Idc: Constant DC current injected to membrane in Amperes with shape (Nrec,), defaults to None
    :type Idc: Optional[np.ndarray], optinoal
    :param If_nmda: NMDA gate soft cut-off current setting the NMDA gating voltage in Amperes with shape (Nrec,), defaults to None
    :type If_nmda: Optional[np.ndarray], optinoal
    :param Igain_ahp: gain bias current of the spike frequency adaptation block in Amperes with shape (Nrec,), defaults to None
    :type Igain_ahp: Optional[np.ndarray], optinoal
    :param Igain_ampa: gain bias current of excitatory AMPA synapse in Amperes with shape (Nrec,), defaults to None
    :type Igain_ampa: Optional[np.ndarray], optinoal
    :param Igain_gaba: gain bias current of inhibitory GABA synapse in Amperes with shape (Nrec,), defaults to None
    :type Igain_gaba: Optional[np.ndarray], optinoal
    :param Igain_nmda: gain bias current of excitatory NMDA synapse in Amperes with shape (Nrec,), defaults to None
    :type Igain_nmda: Optional[np.ndarray], optinoal
    :param Igain_shunt: gain bias current of the inhibitory SHUNT synapse in Amperes with shape (Nrec,), defaults to None
    :type Igain_shunt: Optional[np.ndarray], optinoal
    :param Igain_mem: gain bias current for neuron membrane in Amperes with shape (Nrec,), defaults to None
    :type Igain_mem: Optional[np.ndarray], optinoal
    :param Ipulse_ahp: bias current setting the pulse width for spike frequency adaptation block `t_pulse_ahp` in Amperes with shape (Nrec,), defaults to None
    :type Ipulse_ahp: Optional[np.ndarray], optinoal
    :param Ipulse: bias current setting the pulse width for neuron membrane `t_pulse` in Amperes with shape (Nrec,), defaults to None
    :type Ipulse: Optional[np.ndarray], optinoal
    :param Iref: bias current setting the refractory period `t_ref` in Amperes with shape (Nrec,), defaults to None
    :type Iref: Optional[np.ndarray], optinoal
    :param Ispkthr: spiking threshold current, neuron spikes if :math:`Imem > Ispkthr` in Amperes with shape (Nrec,), defaults to None
    :type Ispkthr: Optional[np.ndarray], optinoal
    :param Itau_ahp: Spike frequency adaptation leakage current setting the time constant `tau_ahp` in Amperes with shape (Nrec,), defaults to None
    :type Itau_ahp: Optional[np.ndarray], optinoal
    :param Itau_ampa: AMPA synapse leakage current setting the time constant `tau_ampa` in Amperes with shape (Nrec,), defaults to None
    :type Itau_ampa: Optional[np.ndarray], optinoal
    :param Itau_gaba: GABA synapse leakage current setting the time constant `tau_gaba` in Amperes with shape (Nrec,), defaults to None
    :type Itau_gaba: Optional[np.ndarray], optinoal
    :param Itau_nmda: NMDA synapse leakage current setting the time constant `tau_nmda` in Amperes with shape (Nrec,), defaults to None
    :type Itau_nmda: Optional[np.ndarray], optinoal
    :param Itau_shunt: SHUNT synapse leakage current setting the time constant `tau_shunt` in Amperes with shape (Nrec,), defaults to None
    :type Itau_shunt: Optional[np.ndarray], optinoal
    :param Itau_mem: Neuron membrane leakage current setting the time constant `tau_mem` in Amperes with shape (Nrec,), defaults to None
    :type Itau_mem: Optional[np.ndarray], optinoal
    :param Iw_ahp: spike frequency adaptation weight current of the neurons of the core in Amperes with shape (Nrec,), defaults to None
    :type Iw_ahp: Optional[np.ndarray], optinoal
    :param C_ahp: AHP synapse capacitance in Farads with shape (Nrec,), defaults to None
    :type C_ahp: float, optional
    :param C_ampa: AMPA synapse capacitance in Farads with shape (Nrec,), defaults to None
    :type C_ampa: float, optional
    :param C_gaba: GABA synapse capacitance in Farads with shape (Nrec,), defaults to None
    :type C_gaba: float, optional
    :param C_nmda: NMDA synapse capacitance in Farads with shape (Nrec,), defaults to None
    :type C_nmda: float, optional
    :param C_pulse_ahp: spike frequency adaptation circuit pulse-width creation sub-circuit capacitance in Farads with shape (Nrec,), defaults to None
    :type C_pulse_ahp: float, optional
    :param C_pulse: pulse-width creation sub-circuit capacitance in Farads with shape (Nrec,), defaults to None
    :type C_pulse: float, optional
    :param C_ref: refractory period sub-circuit capacitance in Farads with shape (Nrec,), defaults to None
    :type C_ref: float, optional
    :param C_shunt: SHUNT synapse capacitance in Farads with shape (Nrec,), defaults to None
    :type C_shunt: float, optional
    :param C_mem: neuron membrane capacitance in Farads with shape (Nrec,), defaults to None
    :type C_mem: float, optional
    :param Io: Dark current in Amperes that flows through the transistors even at the idle state with shape (Nrec,), defaults to None
    :type Io: float, optional
    :param kappa_n: Subthreshold slope factor (n-type transistor) with shape (Nrec,), defaults to None
    :type kappa_n: float, optional
    :param kappa_p: Subthreshold slope factor (p-type transistor) with shape (Nrec,), defaults to None
    :type kappa_p: float, optional
    :param Ut: Thermal voltage in Volts with shape (Nrec,), defaults to None
    :type Ut: float, optional
    :param Vth: The cut-off Vgs potential of the transistors in Volts (not type specific) with shape (Nrec,), defaults to None
    :type Vth: float, optional
    :param w_rec: If the module is initialised in recurrent mode, one can provide a concrete initialisation for the recurrent weights, which must be a square matrix with shape ``(Nrec, Nrec, 4)``. The last 4 holds a weight matrix for 4 different synapse types. If the model is not initialised in recurrent mode, then you may not provide ``w_rec``, defaults tp None
    :type w_rec: Optional[np.ndarray], optional
    :param has_rec: When ``True`` the module provides a trainable recurrent weight matrix. ``False``, module is feed-forward, defaults to True
    :type has_rec: bool, optional
    :param weight_init_func: The initialisation function to use when generating weights, gets the shape and returns the initial weights, defatuls to None (poisson_DynapSE)
    :type weight_init_func: Optional[Callable[[Tuple], np.ndarray]], optional
    :param dt: The time step for the forward-Euler ODE solver, defaults to 1e-3
    :type dt: float, optional
    :param rng_key: The Jax RNG seed to use on initialisation. By default, a new seed is generated, defaults to None
    :type rng_key: Optional[Any], optional
    :param spiking_input: Whether this module receives spiking input, defaults to True
    :type spiking_input: bool, optional
    :param spiking_output: Whether this module produces spiking output, defaults to True
    :type spiking_output: bool, optional

    :Instance Variables:

    :ivar iahp: Spike frequency adaptation current states of the neurons in Amperes with shape (Nrec,)
    :type iahp: jnp.DeviceArray
    :ivar iampa: Fast excitatory AMPA synapse current states of the neurons in Amperes with shape (Nrec,)
    :type iampa: jnp.DeviceArray
    :ivar igaba: Slow inhibitory adaptation current states of the neurons in Amperes with shape (Nrec,)
    :type igaba: jnp.DeviceArray
    :ivar imem: Membrane current states of the neurons in Amperes with shape (Nrec,)
    :type imem: jnp.DeviceArray
    :ivar inmda: Slow excitatory synapse current states of the neurons in Amperes with shape (Nrec,)
    :type inmda: jnp.DeviceArray
    :ivar ishunt: Fast inhibitory shunting synapse current states of the neurons in Amperes with shape (Nrec,)
    :type ishunt: jnp.DeviceArray
    :ivar spikes: Logical spiking raster for each neuron at the last simulation time-step with shape (Nrec,)
    :type spikes: jnp.DeviceArray
    :ivar timer_ref: timer to keep the time from the spike generation until the refractory period ends
    :type timer_ref: jnp.DeviceArray
    :ivar vmem: Membrane potential states of the neurons in Volts with shape (Nrec,)
    :type vmem: jnp.DeviceArray
    :ivar md: The mismatch device to fluctuate the states, parameters and the simulation parameters
    :type md: MismatchDevice
    """

    __doc__ += "\nJaxModule" + JaxModule.__doc__

    def __init__(
        self,
        shape: Optional[Tuple[int]] = None,
        Idc: Optional[np.ndarray] = None,
        If_nmda: Optional[np.ndarray] = None,
        Igain_ahp: Optional[np.ndarray] = None,
        Igain_ampa: Optional[np.ndarray] = None,
        Igain_gaba: Optional[np.ndarray] = None,
        Igain_nmda: Optional[np.ndarray] = None,
        Igain_shunt: Optional[np.ndarray] = None,
        Igain_mem: Optional[np.ndarray] = None,
        Ipulse_ahp: Optional[np.ndarray] = None,
        Ipulse: Optional[np.ndarray] = None,
        Iref: Optional[np.ndarray] = None,
        Ispkthr: Optional[np.ndarray] = None,
        Itau_ahp: Optional[np.ndarray] = None,
        Itau_ampa: Optional[np.ndarray] = None,
        Itau_gaba: Optional[np.ndarray] = None,
        Itau_nmda: Optional[np.ndarray] = None,
        Itau_shunt: Optional[np.ndarray] = None,
        Itau_mem: Optional[np.ndarray] = None,
        Iw_ahp: Optional[np.ndarray] = None,
        C_ahp: Optional[np.ndarray] = None,
        C_ampa: Optional[np.ndarray] = None,
        C_gaba: Optional[np.ndarray] = None,
        C_nmda: Optional[np.ndarray] = None,
        C_pulse_ahp: Optional[np.ndarray] = None,
        C_pulse: Optional[np.ndarray] = None,
        C_ref: Optional[np.ndarray] = None,
        C_shunt: Optional[np.ndarray] = None,
        C_mem: Optional[np.ndarray] = None,
        Io: Optional[np.ndarray] = None,
        kappa_n: Optional[np.ndarray] = None,
        kappa_p: Optional[np.ndarray] = None,
        Ut: Optional[np.ndarray] = None,
        Vth: Optional[np.ndarray] = None,
        w_rec: Optional[jnp.DeviceArray] = None,
        has_rec: bool = True,
        weight_init_func: Optional[Callable[[Tuple], np.ndarray]] = None,
        dt: float = 1e-3,
        rng_key: Optional[Any] = None,
        spiking_input: bool = False,
        spiking_output: bool = True,
        *args,
        **kwargs,
    ) -> None:
        """
        __init__ Initialize ``DynapSim`` module. Parameters are explained in the class docstring.
        """
        self.__shape_check(shape)

        super(DynapSim, self).__init__(
            shape=shape,
            spiking_input=spiking_input,
            spiking_output=spiking_output,
            *args,
            **kwargs,
        )

        # - Seed RNG
        if rng_key is None:
            rng_key = rand.PRNGKey(np.random.randint(0, 2 ** 63))

        ### --- States --- ####
        __state = lambda init_func: State(
            init_func=init_func,
            shape=(self.size_out,),
            permit_reshape=False,
            cast_fn=jnp.array,
        )

        __Io_state = lambda _: __state(lambda s: jnp.full(tuple(reversed(s)), Io).T)
        __zero_state = lambda _: __state(jnp.zeros)

        ## Data
        self.iahp = __Io_state(None)
        self.iampa = __Io_state(None)
        self.igaba = __Io_state(None)
        self.imem = __Io_state(None)
        self.inmda = __Io_state(None)
        self.ishunt = __Io_state(None)
        self.spikes = __zero_state(None)
        self.timer_ref = __zero_state(None)
        self.vmem = __zero_state(None)

        ### --- Parameters --- ###
        if isinstance(has_rec, jax.core.Tracer) or has_rec:
            self.w_rec = Parameter(
                data=w_rec,
                family="weights",
                init_func=weight_init_func,
                shape=(self.size_out, self.size_in // 4, 4),
                permit_reshape=False,
                cast_fn=jnp.array,
            )
        else:
            if w_rec is not None:
                raise ValueError(
                    "If ``has_rec`` is False, then `w_rec` may not be provided as an argument or initialized by the module."
                )
            self.w_rec = jnp.zeros((self.size_out, self.size_in // 4, 4))

        ## Bias Currents
        __parameter = lambda _param: Parameter(
            data=_param,
            family="bias",
            shape=(self.size_out,),
            permit_reshape=False,
            cast_fn=jnp.array,
        )

        self.Idc = __parameter(Idc)
        self.If_nmda = __parameter(If_nmda)
        self.Igain_ahp = __parameter(Igain_ahp)
        self.Igain_ampa = __parameter(Igain_ampa)
        self.Igain_gaba = __parameter(Igain_gaba)
        self.Igain_nmda = __parameter(Igain_nmda)
        self.Igain_shunt = __parameter(Igain_shunt)
        self.Igain_mem = __parameter(Igain_mem)
        self.Ipulse_ahp = __parameter(Ipulse_ahp)
        self.Ipulse = __parameter(Ipulse)
        self.Iref = __parameter(Iref)
        self.Ispkthr = __parameter(Ispkthr)
        self.Itau_ahp = __parameter(Itau_ahp)
        self.Itau_ampa = __parameter(Itau_ampa)
        self.Itau_gaba = __parameter(Itau_gaba)
        self.Itau_nmda = __parameter(Itau_nmda)
        self.Itau_shunt = __parameter(Itau_shunt)
        self.Itau_mem = __parameter(Itau_mem)
        self.Iw_ahp = __parameter(Iw_ahp)

        # --- Simulation Parameters --- #
        __simparam = lambda _param: SimulationParameter(
            data=_param,
            shape=(self.size_out,),
            permit_reshape=False,
            cast_fn=jnp.array,
        )

        self.C_ahp = __simparam(C_ahp)
        self.C_ampa = __simparam(C_ampa)
        self.C_gaba = __simparam(C_gaba)
        self.C_nmda = __simparam(C_nmda)
        self.C_pulse_ahp = __simparam(C_pulse_ahp)
        self.C_pulse = __simparam(C_pulse)
        self.C_ref = __simparam(C_ref)
        self.C_shunt = __simparam(C_shunt)
        self.C_mem = __simparam(C_mem)
        self.Io = __simparam(Io)
        self.kappa_n = __simparam(kappa_n)
        self.kappa_p = __simparam(kappa_p)
        self.Ut = __simparam(Ut)
        self.Vth = __simparam(Vth)

        self.md = MismatchDevice(
            rng_key, **self.state(), **self.parameters(), **self.simulation_parameters()
        )

        # Escape from mismatch
        self.rng_key = State(rng_key, init_func=lambda _: rng_key)
        self.dt = SimulationParameter(dt, shape=())

        # Performance : Use device arrays in calculations
        self.__zero = jnp.array(0.0)
        self.__one = jnp.array(1.0)
        self.__two = jnp.array(2.0)

        # - Define additional arguments required during initialisation
        self._init_args = {
            "has_rec": has_rec,
            "weight_init_func": Partial(weight_init_func),
        }

    @classmethod
    def from_specification(
        cls,
        shape: Optional[Tuple[int]],
        has_rec: bool = True,
        w_rec_mask: np.ndarray = None,
        Idc: float = None,
        If_nmda: float = None,
        r_gain_ahp: float = 4,  # 100
        r_gain_ampa: float = 4,  # 100
        r_gain_gaba: float = 4,  # 100
        r_gain_nmda: float = 4,  # 100
        r_gain_shunt: float = 4,  # 100
        r_gain_mem: float = 2,  # 4
        t_pulse_ahp: float = 1e-6,
        t_pulse: float = 10e-6,
        t_ref: float = 2e-3,
        Ispkthr: float = 1e-6,
        tau_ahp: float = 50e-3,
        tau_ampa: float = 10e-3,
        tau_gaba: float = 100e-3,
        tau_nmda: float = 100e-3,
        tau_shunt: float = 10e-3,
        tau_mem: float = 20e-3,
        Iw_0: float = 1e-6,
        Iw_1: float = 2e-6,
        Iw_2: float = 4e-6,
        Iw_3: float = 8e-6,
        Iw_ahp: float = 1e-6,
        C_ahp: float = 40e-12,
        C_ampa: float = 24.5e-12,
        C_gaba: float = 25e-12,
        C_nmda: float = 25e-12,
        C_pulse_ahp: float = 0.5e-12,
        C_pulse: float = 0.5e-12,
        C_ref: float = 1.5e-12,
        C_shunt: float = 24.5e-12,
        C_mem: float = 3e-12,
        Io: float = 5e-13,
        kappa_n: float = 0.75,
        kappa_p: float = 0.66,
        Ut: float = 25e-3,
        Vth: float = 7e-1,
        weight_init_func: Optional[Callable[[Tuple], np.ndarray]] = None,
        dt: float = 1e-3,
        rng_key: Optional[Any] = None,
        spiking_input: bool = False,
        spiking_output: bool = True,
    ) -> DynapSim:

        if weight_init_func is None:
            weight_init_func = lambda s: poisson_weights_se2(
                s, Iw_0=Iw_0, Iw_1=Iw_1, Iw_2=Iw_2, Iw_3=Iw_3
            )

        simconfig = DynapSimConfig.from_specification(
            shape=shape[-1],
            w_rec_mask=w_rec_mask,
            Idc=Idc,
            If_nmda=If_nmda,
            r_gain_ahp=r_gain_ahp,
            r_gain_ampa=r_gain_ampa,
            r_gain_gaba=r_gain_gaba,
            r_gain_nmda=r_gain_nmda,
            r_gain_shunt=r_gain_shunt,
            r_gain_mem=r_gain_mem,
            t_pulse_ahp=t_pulse_ahp,
            t_pulse=t_pulse,
            t_ref=t_ref,
            Ispkthr=Ispkthr,
            tau_ahp=tau_ahp,
            tau_ampa=tau_ampa,
            tau_gaba=tau_gaba,
            tau_nmda=tau_nmda,
            tau_shunt=tau_shunt,
            tau_mem=tau_mem,
            Iw_0=Iw_0,
            Iw_1=Iw_1,
            Iw_2=Iw_2,
            Iw_3=Iw_3,
            Iw_ahp=Iw_ahp,
            C_ahp=C_ahp,
            C_ampa=C_ampa,
            C_gaba=C_gaba,
            C_nmda=C_nmda,
            C_pulse_ahp=C_pulse_ahp,
            C_pulse=C_pulse,
            C_ref=C_ref,
            C_shunt=C_shunt,
            C_mem=C_mem,
            Io=Io,
            kappa_n=kappa_n,
            kappa_p=kappa_p,
            Ut=Ut,
            Vth=Vth,
        )
        _mod = cls.from_DynapSimConfig(
            shape=shape,
            simconfig=simconfig,
            has_rec=has_rec,
            weight_init_func=weight_init_func,
            dt=dt,
            rng_key=rng_key,
            spiking_input=spiking_input,
            spiking_output=spiking_output,
        )
        return _mod

    @classmethod
    def from_DynapSimConfig(
        cls,
        shape: Optional[Tuple[int]],
        simconfig: DynapSimConfig,
        has_rec: bool = True,
        weight_init_func: Optional[Callable[[Tuple], np.ndarray]] = None,
        dt: float = 1e-3,
        rng_key: Optional[Any] = None,
        spiking_input: bool = False,
        spiking_output: bool = True,
        **kwargs,
    ) -> DynapSim:

        if weight_init_func is None:
            weight_init_func = lambda _: simconfig.w_rec

        __constructor = dict.fromkeys(DynapSimLayout.__annotations__.keys())
        __constructor.update(dict.fromkeys(DynapSimCurrents.__annotations__.keys()))
        __constructor.update(dict.fromkeys(["w_rec"]))

        for key in ["Iw_0", "Iw_1", "Iw_2", "Iw_3"]:
            __constructor.pop(key, None)
        for key in __constructor:
            __constructor[key] = simconfig.__getattribute__(key)

        _mod = cls(
            shape=shape,
            has_rec=has_rec,
            weight_init_func=weight_init_func,
            dt=dt,
            rng_key=rng_key,
            spiking_input=spiking_input,
            spiking_output=spiking_output,
            **__constructor,
            **kwargs,
        )
        return _mod

    @classmethod
    def from_Dynapse1Configuration(cls, config: Dynapse1Configuration) -> DynapSim:
        # Parameters
        # Weights
        None

    @classmethod
    def from_Dynapse2Configuration(cls, config: Dynapse2Configuration) -> DynapSim:
        None

    def __shape_check(self, shape: Tuple[int]) -> None:
        """
        _shape_check Controls the shape of module and complains if not appropriate.

        :param shape: Either a single dimension ``N``, which defines a feed-forward layer of DynapSE AdExpIF neurons, or two dimensions ``(N, N)``, which defines a recurrent layer of DynapSE AdExpIF neurons.
        :type shape: Tuple[int]
        :raises ValueError: ``shape`` should be defined (N*4,N,)!
        :raises ValueError: The simulation configuration object size and number of device neruons does not match!
        :raises ValueError: `shape[0]` should be `shape[1]`*4 in the recurrent mode
        """
        # Check the parameters and initialize to default if necessary
        if shape is None or len(shape) != 2:
            raise ValueError(f"shape should be defined (N*4,N,)! shape={shape}")

        # Check the network size and the recurrent weight vector accordingly
        syn_size_check = lambda s: s == (s // 4) * 4  # 4 synapse per neuron for sure

        # Check if input dimension meets the 4 synapse per neuron criteria
        if not syn_size_check(shape[0]):
            raise ValueError(
                f"Input dimension ({shape[0]},..) should have been multiples of 4! (Go for {shape[0]//4}, {(shape[0]+4)//4}, or {shape[0]*4}) \n"
                f"Each neuron holds 4 synaptic state, which means 4 input gates per neuron!\n"
                f"i.e. ({(shape[0]//4)*4},..) means {shape[0]//4} neurons with 4 synapses\n"
                f"i.e. ({((shape[0]+4)//4)*4},..) means {(shape[0]+4)//4} neurons with 4 synapses\n"
                f"i.e. ({shape[0]*4},..) means {shape[0]} neurons with 4 synapses\n"
            )

        # Check if output dimension meets the 4 synapse per neuron criteria
        if shape[1] != shape[0] // 4:
            raise ValueError("`shape[0]` should be `shape[1]`*4")

    def evolve(
        self, input_data: jnp.DeviceArray, record: bool = True
    ) -> Tuple[jnp.DeviceArray, Dict[str, jnp.DeviceArray], Dict[str, jnp.DeviceArray]]:
        """
        evolve implements raw rockpool JAX evolution function for a DynapSim module.
        The function solves the dynamical equations introduced at the ``DynapSim`` module definition

        :param input_data: Input array of shape ``(T, Nrec, 4)`` to evolve over. Represents number of spikes at that timebin for different synaptic gates
        :type input_data: jnp.DeviceArray
        :param record: record the each timestep of evolution or not, defaults to False
        :type record: bool, optional
        :return: spikes_ts, states, record_dict
            :spikes_ts: is an array with shape ``(T, Nrec)`` containing the output data(spike raster) produced by the module.
            :states: is a dictionary containing the updated module state following evolution.
            :record_dict: is a dictionary containing the recorded state variables during the evolution at each time step, if the ``record`` argument is ``True`` else empty dictionary {}
        :rtype: Tuple[jnp.DeviceArray, Dict[str, jnp.DeviceArray], Dict[str, jnp.DeviceArray]]
        """

        kappa = (self.md.kappa_n + self.md.kappa_p) / 2

        # --- Time constant computation utils --- #
        __pw = lambda ipw, C: (self.md.Vth * C) / ipw
        __tau = lambda itau, C: ((self.md.Ut / kappa) * C.T).T / itau

        tau_ahp = lambda itau: __tau(itau, self.md.C_ahp)
        tau_mem = lambda itau: __tau(itau, self.md.C_mem)
        tau_syn = lambda itau: __tau(itau, self.__syn_stack(self.md, "C"))

        # --- Stateless Parameters --- #
        t_ref = __pw(self.md.Iref, self.md.C_ref)
        t_pulse = __pw(self.md.Ipulse, self.md.C_pulse)
        t_pulse_ahp = __pw(self.md.Ipulse_ahp, self.md.C_pulse_ahp)

        ## --- Synapse Stack --- ## Nrec, 4
        Itau_syn_clip = jnp.clip(self.__syn_stack(self.md, "Itau").T, self.md.Io).T
        Igain_syn_clip = jnp.clip(self.__syn_stack(self.md, "Igain").T, self.md.Io).T

        ## --- Spike frequency adaptation --- ## Nrec
        Itau_ahp_clip = jnp.clip(self.md.Itau_ahp, self.md.Io)
        Igain_ahp_clip = jnp.clip(self.md.Igain_ahp, self.md.Io)

        ## -- Membrane -- ## Nrec
        Itau_mem_clip = jnp.clip(self.md.Itau_mem, self.md.Io)
        Igain_mem_clip = jnp.clip(self.md.Igain_mem, self.md.Io)

        # Both (T, Nrecx4), and (T, Nrec, 4) shaped inputs are accepted
        input_data = jnp.reshape(input_data, (input_data.shape[0], -1, 4))

        def forward(
            state: DynapSEState, Iw_input: jnp.DeviceArray
        ) -> Tuple[DynapSEState, DynapSERecord]:
            """
            forward implements single time-step neuron and synapse dynamics

            :param state: (iahp, iampa, igaba, imem, inmda, ishunt, rng_key, spikes, timer_ref, vmem)
                iahp: Spike frequency adaptation currents of each neuron [Nrec]
                iampa: AMPA synapse currents of each neuron [Nrec]
                igaba: GABA synapse currents of each neuron [Nrec]
                imem: Membrane currents of each neuron [Nrec]
                inmda: NMDA synapse currents of each neuron [Nrec]
                ishunt: SHUNT synapse currents of each neuron [Nrec]
                rng_key: The Jax RNG seed to be used for mismatch simulation
                spikes: Logical spike raster for each neuron [Nrec]
                timer_ref: Refractory timer of each neruon [Nrec]
                vmem: Membrane voltages of each neuron [Nrec]
            :type state: DynapSEState
            :param Iw_input: external weighted current matrix generated via input spikes [Nrec, 4]
            :type Iw_input: jnp.DeviceArray
            :return: state, record
                state: Updated state at end of the forward steps
                record: Updated record instance to including spikes, igaba, ishunt, inmda, iampa, iahp, imem, and vmem states
            :rtype: Tuple[DynapSEState, DynapSERecord]
            """
            # [] TODO : Would you allow currents to go below Io or not?!!!!

            (
                iahp,
                iampa,
                igaba,
                imem,
                inmda,
                ishunt,
                rng_key,
                spikes,
                timer_ref,
                vmem,
            ) = state

            isyn = jnp.stack([iampa, igaba, inmda, ishunt]).T
            # ---------------------------------- #
            # --- Forward step: DPI SYNAPSES --- #
            # ---------------------------------- #

            ## Real time weight is 0 if no spike, w_rec if spike event occurs
            Iws_internal = jnp.dot(self.md.w_rec.T, spikes).T
            Iws = Iws_internal + Iw_input

            # isyn_inf is the current that a synapse current would reach with a sufficiently long pulse
            isyn_inf = ((Igain_syn_clip / Itau_syn_clip) * Iws) - Igain_syn_clip
            isyn_inf = jnp.clip(isyn_inf, self.__zero)

            # synaptic time constant is practically much more longer than expected when isyn << Igain
            tau_syn_prime = tau_syn(Itau_syn_clip) * (1 + (Igain_syn_clip / isyn))

            ## Exponential charge, discharge positive feedback factor arrays
            f_charge = self.__one - jnp.exp(-t_pulse / tau_syn_prime.T).T  # Nrecx4
            f_discharge = jnp.exp(-self.dt / tau_syn_prime)  # Nrecx4

            ## DISCHARGE in any case
            isyn = f_discharge * isyn

            ## CHARGE if spike occurs -- UNDERSAMPLED -- dt >> t_pulse
            isyn += f_charge * isyn_inf
            isyn = jnp.clip(isyn.T, self.md.Io).T  # Nrecx4

            # ---------------------------------- #
            # ---------------------------------- #
            # ---------------------------------- #

            # ------------------------------------------------------ #
            # --- Forward step: AHP : Spike Frequency Adaptation --- #
            # ------------------------------------------------------ #

            Iws_ahp = self.md.Iw_ahp * spikes  # 0 if no spike, Iw_ahp if spike
            iahp_inf = ((Igain_ahp_clip / Itau_ahp_clip) * Iws_ahp) - Igain_ahp_clip

            tau_ahp_prime = tau_ahp(Itau_ahp_clip) * (
                self.__one + (Igain_ahp_clip / iahp)
            )

            # Calculate charge and discharge factors
            f_charge_ahp = self.__one - jnp.exp(-t_pulse_ahp / tau_ahp_prime)  # Nrec
            f_discharge_ahp = jnp.exp(-self.dt / tau_ahp_prime)  # Nrec

            ## DISCHARGE in any case
            iahp = f_discharge_ahp * iahp

            ## CHARGE if spike occurs -- UNDERSAMPLED -- dt >> t_pulse
            iahp += f_charge_ahp * iahp_inf
            iahp = jnp.clip(iahp, self.md.Io)  # Nrec

            # ------------------------------------------------------ #
            # ------------------------------------------------------ #
            # ------------------------------------------------------ #

            # ------------------------------ #
            # --- Forward step: MEMBRANE --- #
            # ------------------------------ #
            _kappa_2 = jnp.power(kappa, self.__two)
            _kappa_prime = _kappa_2 / (kappa + self.__one)
            f_feedback = jnp.exp(_kappa_prime * (vmem / self.md.Ut))  # 4xNrec

            ## Decouple synaptic currents and calculate membrane input
            (iampa, igaba, inmda, ishunt) = isyn.T

            # inmda = 0 if vmem < Vth_nmda else inmda
            I_nmda_dp = inmda / (self.__one + self.md.If_nmda / imem)

            # Iin = 0 if the neuron is in the refractory period
            Iin = I_nmda_dp + iampa - igaba + self.md.Idc
            Iin *= jnp.logical_not(timer_ref.astype(bool)).astype(jnp.float32)
            Iin = jnp.clip(Iin, self.md.Io)

            # ishunt (shunting) contributes to the membrane leak instead of subtracting from Iin
            Ileak = Itau_mem_clip + ishunt
            tau_mem_prime = tau_mem(Ileak) * (self.__one + (Igain_mem_clip / imem))

            ## Steady state current
            imem_inf = (Igain_mem_clip / Itau_mem_clip) * (Iin - iahp - Ileak)

            ## Positive feedback
            Ifb = self.md.Io * f_feedback
            f_imem = ((Ifb) / (Ileak)) * (imem + Igain_mem_clip)

            ## Forward Euler Update
            del_imem = (self.__one / tau_mem_prime) * (
                imem_inf + f_imem - (imem * (self.__one + (iahp / Ileak)))
            )
            imem = imem + del_imem * self.dt
            imem = jnp.clip(imem, self.md.Io)

            ## Membrane Potential
            vmem = (self.md.Ut / kappa) * jnp.log(imem / self.md.Io)

            # ------------------------------ #
            # ------------------------------ #
            # ------------------------------ #

            # ------------------------------ #
            # --- Spike Generation Logic --- #
            # ------------------------------ #

            ## Detect next spikes (with custom gradient)
            spikes = step_pwl(imem, self.md.Ispkthr, self.md.Io)

            ## Reset imem depending on spiking activity
            imem = (self.__one - spikes) * imem + spikes * self.md.Io

            ## Set the refractrory timer
            timer_ref -= self.dt
            timer_ref = jnp.clip(timer_ref, self.__zero)
            timer_ref = (self.__one - spikes) * timer_ref + spikes * t_ref

            # ------------------------------ #
            # ------------------------------ #
            # ------------------------------ #

            # igaba, ishunt, inmda, iampa = isyn

            # IMPORTANT : SHOULD BE IN THE SAME ORDER WITH THE self.state()
            state = (
                iahp,
                iampa,
                igaba,
                imem,
                inmda,
                ishunt,
                rng_key,
                spikes,
                timer_ref,
                vmem,
            )
            record_ts = (iahp, iampa, igaba, imem, inmda, ishunt, spikes, vmem)
            return state, record_ts

        # --- Evolve over spiking inputs --- #
        initial_state = (
            self.md.iahp,
            self.md.iampa,
            self.md.igaba,
            self.md.imem,
            self.md.inmda,
            self.md.ishunt,
            self.rng_key,
            self.spikes,
            self.timer_ref,
            self.vmem,
        )
        state, record_ts = scan(
            forward,
            initial_state,
            input_data,
        )

        states = dict(zip(self.state().keys(), state))

        record_dict = {}

        if record:
            rkeys = [
                "iahp",
                "iampa",
                "igaba",
                "imem",
                "inmda",
                "ishunt",
                "spikes",
                "vmem",
            ]
            record_dict = dict(zip(rkeys, record_ts))

        return record_ts[6], states, record_dict

    def export_Dynapse1Configuration(self) -> Dynapse1Configuration:
        None

    def export_Dynapse2Configuration(self) -> Dynapse2Configuration:
        None

    @staticmethod
    def __syn_stack(obj: object, name: str) -> jnp.DeviceArray:
        """
        __syn_stack fetches attributes from the synaptic gate subcircuits in [GABA, SHUNT, NMDA, AMPA] order and create a property array covering all the neurons allocated

        :param obj: the object to fectch the currents parameters
        :type obj: object
        :param name: the base name of the parameter
        :type name: str
        :return: an array full of the values of the target attributes of all 4 synapses (`size`, 4)
        :rtype: jnp.DeviceArray
        """
        return jnp.stack(
            [
                obj.__getattribute__(f"{name}_ampa"),
                obj.__getattribute__(f"{name}_gaba"),
                obj.__getattribute__(f"{name}_nmda"),
                obj.__getattribute__(f"{name}_shunt"),
            ]
        ).T
